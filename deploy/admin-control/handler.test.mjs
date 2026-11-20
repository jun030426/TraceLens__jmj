import { test } from 'node:test';
import assert from 'node:assert/strict';
import { generateKeyPair, exportJWK, createLocalJWKSet, SignJWT } from 'jose';
import { createHandler } from './handler.mjs';

const { publicKey, privateKey } = await generateKeyPair('RS256');
const jwk = await exportJWK(publicKey);
jwk.kid = 'test';
const issuer = 'https://oidc.vercel.com/test-team';
const audience = 'https://vercel.com/test-team';
const subject = 'owner:test-team:project:lerny:environment:production';
const instanceId = 'i-0123456789abcdef0';
const accountId = '123456789012';
const calls = [];
const client = { send: async (command) => {
  calls.push(command);
  return { Reservations: [{ OwnerId: accountId, Instances: [{ InstanceId: instanceId, State: { Name: 'running' }, InstanceType: 't3.small' }] }], $metadata: { requestId: 'request-1' } };
} };
const handle = createHandler({ instanceId, accountId, region: 'ap-southeast-2', issuer, audience, subject,
  keys: createLocalJWKSet({ keys: [jwk] }), client });
const token = (claims = {}) => new SignJWT({ iss: issuer, aud: audience, sub: subject,
  iat: Math.floor(Date.now() / 1000), exp: Math.floor(Date.now() / 1000) + 60, ...claims })
  .setProtectedHeader({ alg: 'RS256', kid: 'test' }).sign(privateKey);
const request = (jwt, body = { action: 'describe' }) => ({ requestContext: { http: { method: 'POST' } },
  headers: { authorization: `Bearer ${jwt}` }, body: JSON.stringify(body) });

test('valid production identity can only control the configured instance', async () => {
  const jwt = await token();
  for (const action of ['describe', 'start', 'stop']) assert.equal((await handle(request(jwt, { action }))).statusCode, 200);
  assert.deepEqual(calls.map(x => x.input.InstanceIds), [[instanceId], [instanceId], [instanceId]]);
  assert.equal(calls.at(-1).input.Force, false);
});
test('signature, expiry, issuer, audience and production subject are required before AWS', async () => {
  const before = calls.length;
  for (const claims of [{ exp: 1 }, { iss: 'https://attacker.test' }, { aud: 'wrong' }, { sub: subject.replace('production', 'preview') }]) {
    assert.equal((await handle(request(await token(claims)))).statusCode, 401);
  }
  const jwt = await token();
  assert.equal((await handle(request(jwt.slice(0, -10) + 'tampered'))).statusCode, 401);
  assert.equal((await handle(request(''))).statusCode, 401);
  assert.equal(calls.length, before);
});
test('caller cannot select another instance, arbitrary operation or malformed request', async () => {
  const before = calls.length;
  const jwt = await token();
  for (const body of [{ action: 'terminate' }, { action: 'stop', instanceId: 'another' }, null]) {
    assert.equal((await handle(request(jwt, body))).statusCode, 400);
  }
  assert.equal((await handle({ ...request(jwt), isBase64Encoded: true })).statusCode, 400);
  assert.equal((await handle({ ...request(jwt), requestContext: { http: { method: 'GET' } } })).statusCode, 405);
  assert.equal(calls.length, before);
});
