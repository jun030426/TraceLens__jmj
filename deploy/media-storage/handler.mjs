import { createHash } from 'node:crypto';
import { S3Client, CreateMultipartUploadCommand, UploadPartCommand, CompleteMultipartUploadCommand, AbortMultipartUploadCommand, DeleteObjectsCommand, HeadObjectCommand, GetObjectCommand, PutObjectCommand, paginateListParts } from '@aws-sdk/client-s3';
import { getSignedUrl } from '@aws-sdk/s3-request-presigner';
import { createRemoteJWKSet, jwtVerify } from 'jose';
import { Mp4Inspector } from './mp4.mjs';

export const MAX_SIZE = 1024 * 1024 * 1024;
export const PART_SIZE = 8 * 1024 * 1024;
const missing = error => ['NoSuchKey', 'NotFound', 'NoSuchUpload'].includes(error?.name);

export function createOperations({ client, bucket, account, sign = getSignedUrl }) {
  const base = { Bucket: bucket, ExpectedBucketOwner: account };
  async function head(Key) {
    try { return await client.send(new HeadObjectCommand({ ...base, Key })); }
    catch (error) { if (missing(error)) return null; throw error; }
  }
  async function uploaded(Key, UploadId) {
    const parts = [];
    for await (const page of paginateListParts({ client, stopOnSameToken:true }, { ...base, Key, UploadId })) {
      parts.push(...(page.Parts || []));
      if (parts.length > Math.ceil(MAX_SIZE / PART_SIZE)) throw new Error('MEDIA_SIZE_MISMATCH');
      // S3 may include a string "0" next marker even on the final empty page.
      if (!page.IsTruncated) break;
    }
    return parts;
  }
  return async body => {
    if (!body || !/^[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}$/.test(body.id || '')) throw new Error('INVALID_INPUT');
    if (!['begin', 'parts', 'complete', 'download', 'discard'].includes(body.action)) throw new Error('INVALID_INPUT');
    const { action, id, size, upload_id: UploadId } = body;
    const keys = { begin: ['action','id','size'], parts: ['action','id','size','upload_id'], complete: ['action','id','size','upload_id'], download: ['action','id','filename'], discard: ['action','id','upload_id'] };
    if (Object.keys(body).some(k => !keys[action].includes(k))) throw new Error('INVALID_INPUT');
    if (!['download','discard'].includes(action) && (!Number.isSafeInteger(size) || size <= 0 || size > MAX_SIZE)) throw new Error('MEDIA_SIZE_MISMATCH');
    if (['parts','complete','discard'].includes(action) && (typeof UploadId !== 'string' || !UploadId.length || UploadId.length > 2048)) throw new Error('INVALID_INPUT');
    const Key = `media/${id}.mp4`;
    if (action === 'discard') {
      try { await client.send(new AbortMultipartUploadCommand({ ...base, Key, UploadId })); }
      catch (error) { if (!missing(error)) throw error; }
      const result = await client.send(new DeleteObjectsCommand({ ...base, Delete:{Objects:[{Key},{Key:`receipts/${id}.json`}],Quiet:true} }));
      if (result.Errors?.length) throw new Error('MEDIA_CLEANUP_FAILED');
      return { discarded:true };
    }
    if (action === 'download') {
      if (typeof body.filename !== 'string' || !body.filename.length || body.filename.length > 200 || /[\r\n]/.test(body.filename)) throw new Error('INVALID_INPUT');
      const url = await sign(client, new GetObjectCommand({ ...base, Key,
        ResponseContentDisposition: `attachment; filename*=UTF-8''${encodeURIComponent(body.filename).replace(/'/g,'%27')}` }), { expiresIn: 60 });
      return { url };
    }
    if (action === 'begin') {
      if (await head(Key)) throw new Error('INVALID_INPUT');
      const result = await client.send(new CreateMultipartUploadCommand({ ...base, Key,
        ContentType: 'video/mp4', ServerSideEncryption: 'AES256', Metadata: { size: String(size) } }));
      return { upload_id: result.UploadId };
    }
    let existing = await head(Key);
    if (existing && (existing.ContentLength !== size || existing.Metadata?.size !== String(size))) throw new Error('MEDIA_SIZE_MISMATCH');
    let parts = [];
    if (!existing) {
      try { parts = await uploaded(Key, UploadId); }
      catch (error) { if (missing(error)) throw new Error('MEDIA_UPLOAD_EXPIRED'); throw error; }
    }
    const count = Math.ceil(size / PART_SIZE);
    const expected = number => Math.min(PART_SIZE, size - (number - 1) * PART_SIZE);
    if (parts.some(p => p.PartNumber < 1 || p.PartNumber > count || p.Size !== expected(p.PartNumber))) throw new Error('MEDIA_SIZE_MISMATCH');
    if (action === 'parts') {
      if (existing) return { complete: true, parts: [] };
      const done = new Set(parts.map(p => p.PartNumber));
      const remaining = [];
      for (let number = 1; number <= count; number++) {
        if (done.has(number)) continue;
        const length = expected(number);
        const url = await sign(client, new UploadPartCommand({ ...base, Key, UploadId, PartNumber: number, ContentLength: length }),
          { expiresIn: 3600, signableHeaders: new Set(['content-length']) });
        remaining.push({ number, offset: (number - 1) * PART_SIZE, size: length, url });
      }
      return { complete: false, uploaded_bytes: parts.reduce((n,p) => n + p.Size, 0), parts: remaining };
    }
    if (!existing) {
      if (parts.length !== count) throw new Error('MEDIA_UPLOAD_INCOMPLETE');
      const ordered = parts.sort((a,b) => a.PartNumber - b.PartNumber);
      if (ordered.some((p,i) => p.PartNumber !== i + 1)) throw new Error('MEDIA_UPLOAD_INCOMPLETE');
      try {
        await client.send(new CompleteMultipartUploadCommand({ ...base, Key, UploadId,
          MultipartUpload: { Parts: ordered.map(p => ({ PartNumber: p.PartNumber, ETag: p.ETag })) } }));
      } catch (error) { if (!missing(error) || !await head(Key)) throw error; }
      existing = await head(Key);
      if (!existing || existing.ContentLength !== size || existing.Metadata?.size !== String(size)) throw new Error('MEDIA_SIZE_MISMATCH');
    }
    const receiptKey = `receipts/${id}.json`;
    try {
      const receipt = await client.send(new GetObjectCommand({ ...base, Key: receiptKey }));
      if (receipt.ContentLength > 2048) { receipt.Body.destroy(); throw new Error('INVALID_RECEIPT'); }
      const value = JSON.parse(await receipt.Body.transformToString());
      if (value.etag !== existing.ETag || value.size !== size || !/^[a-f0-9]{64}$/.test(value.sha256)) throw new Error('INVALID_RECEIPT');
      return { size, sha256: value.sha256 };
    } catch (error) { if (!missing(error)) throw error; }
    const object = await client.send(new GetObjectCommand({ ...base, Key, IfMatch: existing.ETag }));
    const hash = createHash('sha256'); const inspector = new Mp4Inspector(size);
    try { for await (const chunk of object.Body) { hash.update(chunk); inspector.write(chunk); } inspector.finish(); }
    finally { object.Body.destroy(); }
    const sha256 = hash.digest('hex');
    await client.send(new PutObjectCommand({ ...base, Key: receiptKey, ContentType: 'application/json',
      Body: JSON.stringify({ size, sha256, etag: existing.ETag }), ServerSideEncryption: 'AES256' }));
    return { size, sha256 };
  };
}

export function createHandler({ issuer, audience, subject, keys, operations }) {
  const reply = (statusCode, body) => ({ statusCode, headers: { 'content-type':'application/json', 'cache-control':'no-store' }, body: JSON.stringify(body) });
  return async event => {
    if (event.requestContext?.http?.method !== 'POST') return reply(405,{error:'METHOD_NOT_ALLOWED'});
    const token = event.headers?.authorization;
    if (typeof token !== 'string' || !token.startsWith('Bearer ') || token.length > 16384) return reply(401,{error:'UNAUTHORIZED'});
    try { await jwtVerify(token.slice(7),keys,{issuer,audience,subject,algorithms:['RS256'],requiredClaims:['iat','exp','sub'],clockTolerance:5}); }
    catch { return reply(401,{error:'UNAUTHORIZED'}); }
    let body;
    try { if (event.isBase64Encoded || typeof event.body !== 'string' || event.body.length > 4096) throw new Error(); body=JSON.parse(event.body); }
    catch { return reply(400,{error:'INVALID_INPUT'}); }
    try { return reply(200,await operations(body)); }
    catch (error) {
      if (['INVALID_INPUT','INVALID_MP4','MEDIA_SIZE_MISMATCH','MEDIA_UPLOAD_EXPIRED','MEDIA_UPLOAD_INCOMPLETE'].includes(error.message)) return reply(422,{error:error.message});
      // Never log events, tokens, signed URLs or AWS responses.
      console.error('MEDIA_STORAGE_OPERATION_FAILED', /^[A-Za-z][A-Za-z0-9]{0,50}$/.test(error.name || '') ? error.name : 'Error', Number(error.$metadata?.httpStatusCode || 0));
      return reply(503,{error:'MEDIA_STORAGE_UNAVAILABLE'});
    }
  };
}
let live;
export async function handler(event) {
  if (!live) {
    const issuer = process.env.VERCEL_ISSUER;
    if (!/^https:\/\/oidc\.vercel\.com\/[a-z0-9-]+$/.test(issuer || '') || !/^\d{12}$/.test(process.env.ACCOUNT_ID || '')) throw new Error('INVALID_CONFIGURATION');
    live = createHandler({ issuer, audience:process.env.VERCEL_AUDIENCE, subject:process.env.VERCEL_SUBJECT,
      keys:createRemoteJWKSet(new URL(`${issuer}/.well-known/jwks`),{timeoutDuration:3000}),
      operations:createOperations({bucket:process.env.BUCKET,account:process.env.ACCOUNT_ID,
        client:new S3Client({region:process.env.AWS_REGION,maxAttempts:2,requestChecksumCalculation:'WHEN_REQUIRED',responseChecksumValidation:'WHEN_REQUIRED'})}) });
  }
  return live(event);
}
