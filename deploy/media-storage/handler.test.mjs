import test from 'node:test';
import assert from 'node:assert/strict';
import { Readable } from 'node:stream';
import { createHash } from 'node:crypto';
import { S3Client } from '@aws-sdk/client-s3';
import { generateKeyPair, SignJWT } from 'jose';
import { createHandler, createOperations, MAX_SIZE, PART_SIZE } from './handler.mjs';
import { Mp4Inspector } from './mp4.mjs';
const box = (kind, data) => { const h=Buffer.alloc(8);h.writeUInt32BE(data.length+8);h.write(kind,4);return Buffer.concat([h,data]); };
const movie = Buffer.concat([box('ftyp',Buffer.from('isom0000isommp42')),box('moov',Buffer.from('metadata')),box('mdat',Buffer.from('video'))]);
const id='12345678-1234-1234-1234-123456789abc';

test('MP4 inspection survives arbitrary stream boundaries and rejects truncated/renamed files',()=>{
  for (const width of [1,3,8,15,1024]) { const p=new Mp4Inspector(movie.length);for(let i=0;i<movie.length;i+=width)p.write(movie.subarray(i,i+width));p.finish(); }
  for (const value of [Buffer.from('not video'), movie.subarray(0,-1), Buffer.concat([box('ftyp',Buffer.from('xxxx0000')),box('moov',Buffer.from('m')),box('mdat',Buffer.from('v'))])]) {
    assert.throws(()=>{const p=new Mp4Inspector(value.length);p.write(value);p.finish();},/INVALID_MP4/);
  }
});
test('1 GiB container inspection uses bounded state',()=>{
  const prefix=movie.subarray(0,movie.length-13);const h=Buffer.alloc(8);h.writeUInt32BE(MAX_SIZE-prefix.length);h.write('mdat',4);
  const p=new Mp4Inspector(MAX_SIZE);p.write(prefix);p.write(h);
  let left=MAX_SIZE-prefix.length-8;const block=Buffer.alloc(1024*1024);
  while(left){const n=Math.min(left,block.length);p.write(block.subarray(0,n));left-=n;}
  p.finish();assert.ok(p.header.length+p.brands.length<=4096);
});
test('multipart recovery, immutable completion, digest caching, and input restrictions',async()=>{
  const client=new S3Client({region:'ap-southeast-2',credentials:{accessKeyId:'test',secretAccessKey:'test'}});
  let completed=false, receipt=null, reads=0, uploads=0;
  client.send=async command=>{
    const input=command.input;
    switch(command.constructor.name){
      case 'HeadObjectCommand': if(!completed)throw Object.assign(new Error(),{name:'NotFound'});return {ContentLength:movie.length,Metadata:{size:String(movie.length)},ETag:'immutable'};
      case 'CreateMultipartUploadCommand':uploads++;return {UploadId:'multipart'};
      case 'ListPartsCommand':return {Parts:[{PartNumber:1,Size:movie.length,ETag:'part'}],IsTruncated:false};
      case 'CompleteMultipartUploadCommand':completed=true;return {};
      case 'GetObjectCommand':if(input.Key.startsWith('receipts/')){if(!receipt)throw Object.assign(new Error(),{name:'NoSuchKey'});return {ContentLength:receipt.length,Body:{transformToString:async()=>receipt}};}reads++;return {Body:Readable.from([movie.subarray(0,5),movie.subarray(5)])};
      case 'PutObjectCommand':receipt=input.Body;return {};
      default:throw new Error('unexpected command');
    }
  };
  const ops=createOperations({client,bucket:'private-media',account:'123456789012',sign:async()=> 'signed'});
  const args={id,size:movie.length,upload_id:'multipart'};
  assert.equal((await ops({action:'begin',id,size:movie.length})).upload_id,'multipart');
  assert.deepEqual((await ops({action:'parts',...args})).parts,[]);
  const result=await ops({action:'complete',...args});assert.equal(result.sha256,createHash('sha256').update(movie).digest('hex'));
  assert.deepEqual(await ops({action:'complete',...args}),result);assert.equal(reads,1);assert.equal(uploads,1);
  assert.equal((await ops({action:'parts',...args})).complete,true);
  await assert.rejects(ops({action:'begin',id,size:MAX_SIZE+1}),/MEDIA_SIZE_MISMATCH/);
  await assert.rejects(ops({action:'download',id:'../../private',filename:'a.mp4'}),/INVALID_INPUT/);
  await assert.rejects(ops({action:'download',id,filename:'a.mp4',bucket:'other'}),/INVALID_INPUT/);
  await assert.rejects(ops({action:'download',id,filename:'evil\r\nheader'}),/INVALID_INPUT/);
});
test('part URLs bind exact lengths and only missing parts are returned',async()=>{
  const client=new S3Client({region:'ap-southeast-2',credentials:{accessKeyId:'test',secretAccessKey:'test'},requestChecksumCalculation:'WHEN_REQUIRED'});
  client.send=async c=>{if(c.constructor.name==='HeadObjectCommand')throw Object.assign(new Error(),{name:'NotFound'});return {Parts:[{PartNumber:1,Size:PART_SIZE,ETag:'done'}]};};
  const ops=createOperations({client,bucket:'private-media',account:'123456789012'});
  const result=await ops({action:'parts',id,size:PART_SIZE+9,upload_id:'multipart'});
  assert.equal(result.uploaded_bytes,PART_SIZE);assert.equal(result.parts.length,1);assert.equal(result.parts[0].size,9);
  assert.match(new URL(result.parts[0].url).searchParams.get('X-Amz-SignedHeaders'),/content-length/);
});
test('final empty S3 page with a zero marker cannot loop',async()=>{
  const client=new S3Client({region:'ap-southeast-2',credentials:{accessKeyId:'test',secretAccessKey:'test'}});let reads=0;
  client.send=async c=>{if(c.constructor.name==='HeadObjectCommand')throw Object.assign(new Error(),{name:'NotFound'});reads++;assert.ok(reads<3);return {Parts:[],NextPartNumberMarker:'0',IsTruncated:false};};
  const ops=createOperations({client,bucket:'private-media',account:'123456789012',sign:async()=> 'signed'});
  const result=await ops({action:'parts',id,size:MAX_SIZE,upload_id:'multipart'});
  assert.equal(reads,1);assert.equal(result.parts.length,128);
});
test('only the intended production Vercel JWT can call the bridge',async()=>{
  const {privateKey,publicKey}=await generateKeyPair('RS256');let calls=0;
  const issuer='https://oidc.vercel.com/team';const audience='https://vercel.com/team';const subject='production';
  const handler=createHandler({issuer,audience,subject,keys:publicKey,operations:async()=>{calls++;return {ok:true};}});
  const event={requestContext:{http:{method:'POST'}},headers:{},body:'{}'};
  assert.equal((await handler(event)).statusCode,401);
  async function token(sub,iss=issuer){return new SignJWT({}).setProtectedHeader({alg:'RS256'}).setIssuedAt().setExpirationTime('5m').setIssuer(iss).setAudience(audience).setSubject(sub).sign(privateKey);}
  for(const jwt of [await token('preview'),await token(subject,'https://attacker.example')])assert.equal((await handler({...event,headers:{authorization:'Bearer '+jwt}})).statusCode,401);
  assert.equal((await handler({...event,headers:{authorization:'Bearer '+await token(subject)}})).statusCode,200);assert.equal(calls,1);
});
