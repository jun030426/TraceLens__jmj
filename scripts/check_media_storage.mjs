// Explicit deployment verification only. Tokens remain inside the Vercel build.
import { randomUUID, createHash } from 'node:crypto';

if (process.env.LERNY_MEDIA_VERIFY === '1') {
  const endpoint=process.env.LERNY_MEDIA_STORAGE_URL;
  const token=process.env.VERCEL_OIDC_TOKEN;
  if (!/^https:\/\/[a-z0-9]+\.lambda-url\.ap-southeast-2\.on\.aws\/?$/.test(endpoint||'') || !token) throw new Error('MEDIA_VERIFICATION_CONFIGURATION_REQUIRED');
  const call=async body=>{
    const response=await fetch(endpoint,{method:'POST',headers:{authorization:`Bearer ${token}`,'content-type':'application/json'},body:JSON.stringify(body),signal:AbortSignal.timeout(245000)});
    if(!response.ok)throw new Error(`MEDIA_VERIFICATION_${body.action}_${response.status}`);
    return response.json();
  };
  const total=1024**3;const id=randomUUID();let upload;
  const box=(kind,data)=>{const h=Buffer.alloc(8);h.writeUInt32BE(data.length+8);h.write(kind,4);return Buffer.concat([h,data]);};
  const prefix=Buffer.concat([box('ftyp',Buffer.from('isom0000isommp42')),box('moov',Buffer.from('synthetic upload verification'))]);
  const header=Buffer.alloc(8);header.writeUInt32BE(total-prefix.length);header.write('mdat',4);
  const beginning=Buffer.concat([prefix,header]);const hash=createHash('sha256');
  try {
    const anonymous=await fetch(endpoint,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({action:'begin',id,size:1})});
    if(anonymous.status!==401)throw new Error('MEDIA_ANONYMOUS_ACCESS');
    upload=(await call({action:'begin',id,size:total})).upload_id;
    let state=await call({action:'parts',id,size:total,upload_id:upload});
    const expectedParts=state.parts.length;
    for (let i=0;i<expectedParts;i++) {
      const part=state.parts[0];const bytes=Buffer.alloc(part.size);
      if(part.offset===0)beginning.copy(bytes);
      hash.update(bytes);
      const response=await fetch(part.url,{method:'PUT',body:bytes,headers:{'content-length':String(bytes.length)},signal:AbortSignal.timeout(120000)});
      if(!response.ok)throw new Error(`MEDIA_PART_${response.status}`);
      if(i===0) {
        state=await call({action:'parts',id,size:total,upload_id:upload});
        if(state.uploaded_bytes!==part.size || state.parts.some(p=>p.number===part.number))throw new Error('MEDIA_RESUME_FAILED');
      } else state.parts.shift();
      if((i+1)%32===0)console.log(`Media verification: ${i+1}/${expectedParts} parts transferred`);
    }
    const result=await call({action:'complete',id,size:total,upload_id:upload});
    if(result.size!==total || result.sha256!==hash.digest('hex'))throw new Error('MEDIA_HASH_MISMATCH');
    const repeated=await call({action:'complete',id,size:total,upload_id:upload});
    if(repeated.sha256!==result.sha256)throw new Error('MEDIA_COMPLETION_RETRY_FAILED');
    const download=await call({action:'download',id,filename:'synthetic.mp4'});
    const read=await fetch(download.url,{headers:{range:`bytes=0-${beginning.length-1}`}});
    if(read.status!==206 || !Buffer.from(await read.arrayBuffer()).equals(beginning))throw new Error('MEDIA_DOWNLOAD_FAILED');
    console.log('Media verification passed: 1 GiB actual S3 multipart upload, resume, Lambda validation, exact SHA-256, repeated completion and private download; no model calls or database fixtures');
  } finally {
    if(upload) { await call({action:'discard',id,upload_id:upload});console.log('Media verification objects removed'); }
  }
}
