"""Conservative visual reuse plus bounded multi-region rereading.

All non-identical frames still receive a complete extraction AND whole-frame audit.
Similarity never deletes a frame. Only already-verified, pixel-stable, same-text
blocks may skip another critical-content reread, and an audit flag overrides reuse.
"""
from collections import Counter
import copy
import json
import unicodedata
from pathlib import Path

from video_extraction.shared.common import bbox_pixels, digest_file, read, save, signature
from video_extraction.shared.gemini import EXTRACT, AUDIT, REREAD, VERIFY, TEXT, obj
from video_extraction.video.vision import EXTRACTION_PROMPT, AUDIT_PROMPT, REREAD_PROMPT, VERIFY_PROMPT, speech_context, critical, duplicate_addition, validate_blocks, variants

VERSION=2
READ_BATCH=obj({'items':{'type':'array','maxItems':3,'items':obj({'region_id':TEXT,'reading':REREAD})}})
VERIFY_BATCH=obj({'items':{'type':'array','maxItems':3,'items':obj({'region_id':TEXT,'verification':VERIFY})}})


def pixels(path):
    import numpy as np
    from PIL import Image
    return np.asarray(Image.open(path).convert('RGB')).copy()


def compare_pixels(a,b):
    import numpy as np
    if a.shape!=b.shape:return {'same_scene':False,'exact':False,'changed_fraction':1,'max_delta':255}
    d=np.max(np.abs(a.astype('int16')-b.astype('int16')),axis=2)
    fraction=float(np.mean(d>24))
    return {'same_scene':fraction<=.015,'exact':bool(np.max(d)==0),
            'changed_fraction':fraction,'max_delta':int(np.max(d))}


def text_key(block):
    # Do not collapse whitespace: indentation and blank table cells are content.
    return unicodedata.normalize('NFC',block['text'])


def box_iou(a,b):
    inter=max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))
    total=(a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-inter
    return inter/total if total else 0


def intersects(a,b):
    return min(a[2],b[2])>max(a[0],b[0]) and min(a[3],b[3])>max(a[1],b[1])


def verified_ids(result):
    ids=set()
    for row in result.get('corrections',[]):
        if row['action']=='unchanged':ids.add(row['target_id'])
        elif row['action'] in ('replace','add'):
            v=row.get('verification',{})
            if (v.get('decision')=='accept' and all(v.get(k) is True for k in
                ('source_clear','all_changes_visible','same_region')) and v.get('source_conflict') is False):
                ids.add(row['target_id'])
    for row in result.get('reuse',[]):ids.add(row['target_id'])
    # A surviving explicit issue prevents reusing the block's verification.
    for h in result.get('holds',[]):
        ids.discard(h.get('target_id',h.get('region',{}).get('target_id')))
    return ids


def reuse_blocks(current, audit, prior, a, b):
    """Pixel comparison is a candidate gate; fresh text + whole-frame audit are also required."""
    import numpy as np
    if prior is None or not compare_pixels(a,b)['same_scene'] or not audit['complete_scan']:return []
    candidates=[x for x in prior['final_blocks'] if x['id'] in verified_ids(prior)
                and x['text'].strip() and not x['uncertainties'] and '[ILLEGIBLE]' not in x['text']]
    reuse=[]
    for block in current['blocks']:
        if not block['text'].strip() or block['uncertainties'] or '[ILLEGIBLE]' in block['text']:continue
        # NEW omissions and differently named targets also override reuse spatially.
        if any(r['target_id']==block['id'] or intersects(r['bbox'],block['bbox']) for r in audit['regions']):continue
        for prev in candidates:
            if prev['kind']!=block['kind'] or text_key(prev)!=text_key(block) or box_iou(prev['bbox'],block['bbox'])<.85:continue
            union=[min(prev['bbox'][0],block['bbox'][0]),min(prev['bbox'][1],block['bbox'][1]),
                   max(prev['bbox'][2],block['bbox'][2]),max(prev['bbox'][3],block['bbox'][3])]
            x1,y1,x2,y2=bbox_pixels(union,(a.shape[1],a.shape[0]),pad=12)
            delta=int(np.max(np.abs(a[y1:y2,x1:x2].astype('int16')-b[y1:y2,x1:x2].astype('int16'))))
            # Very small compression-level changes only. Low-contrast residual risk
            # is why a fresh extraction and whole-frame audit remain mandatory.
            if delta<=8:
                reuse.append({'target_id':block['id'],'source_id':prev['id'],
                    'source_frame':prior['frame_id'],'max_pixel_delta':delta,
                    'basis':'same_text_verified_before_stable_pixels_fresh_whole_frame_audit'})
                break
    return reuse


def regions_for(initial,audit,reused,max_regions):
    regions=list(audit['regions']);targeted={r['target_id'] for r in regions};skip={r['target_id'] for r in reused}
    for block in initial['blocks']:
        if critical(block) and block['id'] not in targeted and block['id'] not in skip:
            regions.append({'target_id':block['id'],'bbox':block['bbox'],'kind':block['kind'],
                            'issue':'uncertain','reason':'critical_content_policy'})
    counts=Counter(r['target_id'] for r in regions if r['target_id']!='NEW')
    byid={b['id']:b for b in initial['blocks']};valid=[];holds=[]
    if len(regions)>max_regions:holds.append({'reason':'region_budget','remaining':len(regions)-max_regions})
    for number,region in enumerate(regions[:max_regions],1):
        tid=region['target_id'];before=byid.get(tid)
        if (tid!='NEW' and before is None) or counts[tid]>1:
            holds.append({'region':region,'reason':'invalid_or_duplicate_target'});continue
        box=list(region['bbox'])
        if before:box=[min(box[0],before['bbox'][0]),min(box[1],before['bbox'][1]),max(box[2],before['bbox'][2]),max(box[3],before['bbox'][3])]
        valid.append({'region_id':f'r{number}','number':number,'region':region,'before':before,'bbox':box})
    return valid,holds


def unpack_batch(response, expected, field):
    rows=response['items'];ids=[r['region_id'] for r in rows]
    if len(ids)!=len(set(ids)) or set(ids)!=set(expected):
        raise ValueError('batch_missing_duplicate_or_unexpected_region_id')
    return {r['region_id']:r[field] for r in rows}


def chunks(items,n):
    return [items[i:i+n] for i in range(0,len(items),n)]


def batched_read(client,items,enhanced=False):
    paths=[];mapping=[]
    for item in items:
        originals=[item['native']]
        if enhanced:originals += [item['contrast']]+([item['binary']] if item['binary'] else [])
        first=len(paths)+1;paths+=originals
        mapping.append({'region_id':item['region_id'],'original_image':first,
                        'helper_images':list(range(first+1,len(paths)+1))})
    prompt=REREAD_PROMPT+'\nReturn one independent reading per region_id; never merge regions. '
    prompt+='The FIRST image for each region is authoritative. Helpers cannot establish a missing symbol. '
    prompt+='Every listed region_id must appear exactly once. IMAGE MAP:\n'+json.dumps(mapping)
    data=client.call('optimized_read_enhanced' if enhanced else 'optimized_read',paths,prompt,READ_BATCH)
    return unpack_batch(data,[i['region_id'] for i in items],'reading')


def batched_verify(client,image,items,context):
    prompt=VERIFY_PROMPT.replace('image 2 is the crop.', 'each following image is a separate crop.')
    prompt+='\nImage 1 is the full frame. Each following image is a distinct region. '
    prompt+='Verify each region_id independently. Never use pixels from another region. Return all IDs exactly once.\n'
    data=[{'region_id':i['region_id'],'crop_image':n+2,'original_block':i['before'],
           'region':i['region'],'independent_reading':i['reading']} for n,i in enumerate(items)]
    response=client.call('optimized_verify',[image]+[i['native'] for i in items],
        prompt+json.dumps({'regions':data,'asr_context':context},ensure_ascii=False),VERIFY_BATCH)
    return unpack_batch(response,[i['region_id'] for i in items],'verification')


def process_frame_optimized(frame,frames,segments,out,client,prior=None,prior_image=None,max_regions=6,batch_size=3):
    from PIL import Image
    if not 1<=batch_size<=3:raise ValueError('batch_size must be 1..3')
    if prior is not None and prior_image is None:raise ValueError('prior_image required with prior result')
    image=out/frame['path'];folder=out/'vision'/frame['id'];folder.mkdir(parents=True,exist_ok=True)
    context=speech_context(frame,frames,segments);current_pixels=pixels(image)
    previous_pixels=pixels(prior_image) if prior_image else None
    scene=compare_pixels(previous_pixels,current_pixels) if previous_pixels is not None else None
    sig=signature({'version':VERSION,'image':digest_file(image),'model':client.model,'context':context,
        'prior':signature(prior) if prior else None,'max_regions':max_regions,'batch_size':batch_size})
    path=folder/'result.json'
    if path.exists() and read(path).get('signature')==sig:return read(path)
    if prior is not None and scene['exact']:
        # Preserve ALL uncertainty/holds; identical image does not resolve old errors.
        result={**copy.deepcopy(prior),'signature':sig,'frame_id':frame['id'],
                'frame_time_seconds':frame['time_seconds'],'image_sha256':digest_file(image),
                'reused_frame':prior['frame_id'],'changed_blocks':0,'new_changed_blocks':0,'scene':scene,
                'verification_context_frame':prior.get('verification_context_frame',prior['frame_id']),
                'optimization_version':VERSION,'batch_size':batch_size}
        save(path,result);return result
    initial=client.call('extract',[image],EXTRACTION_PROMPT,EXTRACT)
    with Image.open(image) as im:validate_blocks(initial,im.size,allow_empty_text=True)
    save(folder/'original.json',initial)
    audit=client.call('audit',[image],AUDIT_PROMPT+json.dumps(initial,ensure_ascii=False)+
        '\nNEARBY ASR (not ground truth):\n'+json.dumps(context,ensure_ascii=False),AUDIT)
    reused=reuse_blocks(initial,audit,prior,previous_pixels,current_pixels) if prior else []
    regions,holds=regions_for(initial,audit,reused,max_regions)
    if not initial['readable']:holds.append({'reason':'whole_frame_not_readable'})
    if not audit['complete_scan']:holds.append({'reason':'incomplete_audit'})
    prepared=[];final=copy.deepcopy(initial['blocks']);log=[]
    for item in regions:
        try:native,contrast,binary,_=variants(image,item['bbox'],folder,item['number'])
        except ValueError:
            holds.append({'region':item['region'],'reason':'invalid_bbox'});continue
        prepared.append({**item,'native':native,'contrast':contrast,'binary':binary})
    for batch in chunks(prepared,batch_size):
        try:readings=batched_read(client,batch)
        except ValueError:
            holds.extend({'region':i['region'],'reason':'invalid_batch_read_mapping'} for i in batch);continue
        for i in batch:i['reading']=readings[i['region_id']];i['evidence']=[str(i['native'].relative_to(out))]
        weak=[i for i in batch if not i['reading']['readable'] or i['reading']['uncertainties']]
        if weak:
            try:
                enhanced=batched_read(client,weak,True)
                for i in weak:
                    i['reading']=enhanced[i['region_id']]
                    i['evidence']=[str(p.relative_to(out)) for p in (i['native'],i['contrast'],i['binary']) if p]
            except ValueError:
                for i in weak:i['reading']={**i['reading'],'readable':False}
        ready=[]
        for i in batch:
            r=i['reading']
            if not r['readable'] or r['uncertainties'] or r['source_conflicts'] or not r['text'].strip():
                holds.append({'region':i['region'],'reason':'reread_uncertain','evidence':i['evidence'],'reread':r})
            else:ready.append(i)
        if not ready:continue
        try:verifications=batched_verify(client,image,ready,context)
        except ValueError:
            holds.extend({'region':i['region'],'reason':'invalid_batch_verify_mapping'} for i in ready);continue
        for i in ready:
            v=verifications[i['region_id']];before=i['before'];tid=i['region']['target_id']
            passes=all(v[k] is True for k in ('source_clear','all_changes_visible','same_region')) and not v['source_conflict']
            if not passes or v['decision']=='hold':
                holds.append({'region':i['region'],'reason':'verification_hold','verification':v,'evidence':i['evidence']});continue
            if v['decision']=='unchanged':
                if before is None or not before['text'].strip() or before['uncertainties'] or '[ILLEGIBLE]' in before['text']:
                    holds.append({'region':i['region'],'reason':'unchanged_but_unresolved'});continue
                log.append({'target_id':tid,'action':'unchanged','evidence':i['evidence']});continue
            after={'id':tid if before else f'added-{i["number"]}','bbox':i['bbox'],'kind':i['region']['kind'],
                   'text':i['reading']['text'],'uncertainties':[]}
            if before:final[next(n for n,b in enumerate(final) if b['id']==tid)]=after
            else:
                if duplicate_addition(after,final):
                    holds.append({'region':i['region'],'reason':'duplicate_addition'});continue
                while any(b['id']==after['id'] for b in final):after['id']='new-'+after['id']
                final.append(after)
            log.append({'target_id':after['id'],'action':'replace' if before else 'add','before':before,
                        'after':after,'verification':v,'evidence':i['evidence']})
    for block in final:
        if not block['text'].strip():holds.append({'target_id':block['id'],'reason':'empty_extraction_block'})
        if block['uncertainties'] or '[ILLEGIBLE]' in block['text']:holds.append({'target_id':block['id'],'reason':'remaining_uncertainty'})
    changes=sum(r['action']=='add' or (r['action']=='replace' and r['before']['text']!=r['after']['text']) for r in log)
    result={'signature':sig,'frame_id':frame['id'],'frame_time_seconds':frame['time_seconds'],
        'image_sha256':digest_file(image),'original':initial,'final_blocks':final,'audit':audit,'corrections':log,
        'holds':holds,'status':'needs_review' if holds else 'auto_repaired' if changes else 'auto_checked',
        'text':'\n\n'.join(b['text'] for b in final),'changed_blocks':changes,'reuse':reused,'scene':scene,
        'optimization_version':VERSION,'batch_size':batch_size,'note':'Automated candidate, not independent proof of accuracy.'}
    save(path,result);return result
