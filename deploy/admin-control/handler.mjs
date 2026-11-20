import { EC2Client, DescribeInstancesCommand, StartInstancesCommand, StopInstancesCommand } from '@aws-sdk/client-ec2';
import { createRemoteJWKSet, jwtVerify } from 'jose';

// Values are deployment configuration, never accepted from a caller or JWT.
export function createHandler({ instanceId, accountId, region, issuer, audience, subject, keys, client }) {
  if (!/^i-[a-f0-9]{8,17}$/.test(instanceId) || !/^\d{12}$/.test(accountId)
      || !issuer?.startsWith('https://oidc.vercel.com/') || !audience || !subject || !region) {
    throw new Error('INVALID_CONFIGURATION');
  }
  const reply = (statusCode, value) => ({ statusCode,
    headers: { 'content-type': 'application/json', 'cache-control': 'no-store' }, body: JSON.stringify(value) });
  return async (event) => {
    if (event.requestContext?.http?.method !== 'POST') return reply(405, { error: 'METHOD_NOT_ALLOWED' });
    const authorization = event.headers?.authorization;
    if (typeof authorization !== 'string' || !authorization.startsWith('Bearer ') || authorization.length > 16384) {
      return reply(401, { error: 'UNAUTHORIZED' });
    }
    try {
      await jwtVerify(authorization.slice(7), keys, {
        issuer, audience, subject, algorithms: ['RS256'], requiredClaims: ['iat', 'exp', 'sub'], clockTolerance: 5,
      });
    } catch { return reply(401, { error: 'UNAUTHORIZED' }); }
    let action;
    try {
      if (event.isBase64Encoded || typeof event.body !== 'string' || event.body.length > 128) throw new Error();
      const body = JSON.parse(event.body);
      if (!body || Object.keys(body).length !== 1 || !['describe', 'start', 'stop'].includes(body.action)) throw new Error();
      action = body.action;
    } catch { return reply(400, { error: 'INVALID_ACTION' }); }
    try {
      const command = action === 'describe' ? new DescribeInstancesCommand({ InstanceIds: [instanceId] })
        : action === 'start' ? new StartInstancesCommand({ InstanceIds: [instanceId] })
          : new StopInstancesCommand({ InstanceIds: [instanceId], Force: false });
      const result = await client.send(command, { abortSignal: AbortSignal.timeout(8000) });
      if (action === 'describe') {
        const reservation = result.Reservations?.[0];
        const item = reservation?.Instances?.[0];
        if (reservation?.OwnerId !== accountId || item?.InstanceId !== instanceId) throw new Error('TARGET_MISMATCH');
        return reply(200, { instance_id: item.InstanceId, state: item.State.Name, type: item.InstanceType, region });
      }
      return reply(200, { request_id: result.$metadata.requestId });
    } catch {
      // No raw error/event logging: credentials and tokens must never reach CloudWatch.
      return reply(502, { error: 'SERVER_CONTROL_UNAVAILABLE' });
    }
  };
}

let liveHandler;
export async function handler(event) {
  if (!liveHandler) {
    const issuer = process.env.VERCEL_ISSUER;
    liveHandler = createHandler({ instanceId: process.env.INSTANCE_ID, accountId: process.env.ACCOUNT_ID,
      region: process.env.AWS_REGION, issuer, audience: process.env.VERCEL_AUDIENCE, subject: process.env.VERCEL_SUBJECT,
      keys: createRemoteJWKSet(new URL(`${issuer}/.well-known/jwks`), { timeoutDuration: 3000 }),
      client: new EC2Client({ region: process.env.AWS_REGION, maxAttempts: 1 }),
    });
  }
  return liveHandler(event);
}
