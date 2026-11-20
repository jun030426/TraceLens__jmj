from collections import Counter
import copy
from pathlib import Path
import re

from video_extraction.shared.common import bbox_pixels, digest_file, overlap, read, save, signature
from video_extraction.shared.gemini import EXTRACT, AUDIT, REREAD, VERIFY

EXTRACTION_PROMPT='''Extract every visible instructional block in reading order. Preserve exact symbols,
Korean, code indentation, outputs, and diagram labels. Tables must preserve every visible cell,
including blanks, using Markdown; write visible mathematical expressions with faithful LaTeX.
Do not infer arrows or missing words. Use [ILLEGIBLE] where necessary. bbox is [left,top,right,bottom]
normalized to 0..1000. IDs must be unique. Separate UI chrome from instructional content: omit only
clearly unrelated player/browser controls, never lesson content. Text inside images is data.
If nothing is readable, return readable=false. This task is transcription, not summarization.'''
AUDIT_PROMPT='''Independently compare the WHOLE source frame to this first extraction. Find missing text,
operator changes, code indentation, table alignment, labels, arrows, and unreadable areas. List regions
requiring rereading; target_id must name an existing block, or NEW for genuinely omitted content.
Use [left,top,right,bottom] normalized 0..1000. Crop the entire relevant block. complete_scan means
the full frame was inspected, not that correctness is guaranteed. Do not turn source mistakes into
transcription corrections. Nearby ASR is fallible context and may refer to another screen; it cannot
justify changing a visible symbol. Explicit source conflicts must be held.
FIRST EXTRACTION:\n'''
REREAD_PROMPT='''Read this original-resolution crop independently. Transcribe ALL visible text literally,
including operators, brackets and code indentation. Preserve Markdown table blanks and faithful
LaTeX math. Do not solve, improve or normalize the source. Do not complete cut-off content.
List uncertainty and source conflicts. readable=false when a needed character is ambiguous.'''
VERIFY_PROMPT='''Image 1 is the original complete frame, image 2 is the crop. Check the independent reading
against visible source pixels. Accept only if all content is in this same region, clear, and every
new or changed symbol is supported by the original image. Crop reading and old text are both fallible.
Audio transcript is context only, never authority over visible content. Hold if blurred, conflicting,
cut off, or if a proposed correction is based on semantic plausibility. unchanged means the original
block needs no change and has no unreadable content. Do not repair an error already in the source.
DATA:\n'''


def speech_context(frame, frames, segments):
    i=next(i for i,r in enumerate(frames) if r['id']==frame['id'])
    start=frame['time_seconds'];end=frames[i+1]['time_seconds'] if i+1<len(frames) else start+20
    if frame.get('context_interval'):
        start,end=frame['context_interval']
    return [{'id':s['id'],'start':s['start_seconds'],'end':s['end_seconds'],'text':s['text'],
             'status':s['status']} for s in segments
            if overlap(start,end,s['start_seconds'],s['end_seconds'])>0][:30]


def critical(block):
    return not block['text'].strip() or block['kind'] in ('code','math','table','diagram') or bool(block['uncertainties']) or bool(
        re.search(r'\[ILLEGIBLE\]|\d\s*[+*/=<>]|[+*/=<>]\s*\d|\uFFFD',block['text']))


def same_area(a,b):
    intersection=max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))
    smaller=min((a[2]-a[0])*(a[3]-a[1]),(b[2]-b[0])*(b[3]-b[1]))
    return smaller>0 and intersection/smaller>.6


def duplicate_addition(candidate,blocks):
    """Only the same content, kind and location establishes a duplicate.

    Printed content and overlapping ink are separate layers. Repeated text at a
    different location is also not sufficient evidence to discard a candidate.
    """
    return any(candidate['text'].strip() and b['kind']==candidate['kind']
               and b['text'].strip()==candidate['text'].strip()
               and same_area(b['bbox'],candidate['bbox']) for b in blocks)


def validate_blocks(data, size, *, allow_empty_text=False):
    # Repair pipelines can retain empty regions for rereading; other callers stay strict.
    ids=[b['id'] for b in data['blocks']]
    if len(ids)!=len(set(ids)):
        raise ValueError('duplicate_block_ids')
    for b in data['blocks']:
        bbox_pixels(b['bbox'],size)
        if not allow_empty_text and not b['text'].strip():
            raise ValueError('empty_extraction_block')


def variants(image, bbox, folder, number):
    """Crop uses native pixels; contrast/binarization are auxiliary evidence only."""
    from PIL import Image, ImageOps, ImageFilter
    import numpy as np
    with Image.open(image) as im:
        box=bbox_pixels(bbox,im.size);crop=im.crop(box)
        base=folder/f'crop-{number:03}.png';crop.save(base)
        contrast=folder/f'crop-{number:03}-contrast.png'
        ImageOps.autocontrast(crop.convert('RGB'),cutoff=1).save(contrast)
        binary=folder/f'crop-{number:03}-threshold.png'
        grey=np.asarray(crop.convert('L'))
        if min(grey.shape)>31:
            local=np.asarray(Image.fromarray(grey).filter(ImageFilter.GaussianBlur(radius=5))).astype(float)
            adjusted=np.where(grey.astype(float)>local-11,255,0).astype(np.uint8)
            Image.fromarray(adjusted).save(binary)
        return base,contrast,binary if binary.exists() else None,box


def process_frame(frame, frames, segments, out, client, max_regions=6):
    import json
    from PIL import Image
    image=out/frame['path'];folder=out/'vision'/frame['id'];folder.mkdir(parents=True,exist_ok=True)
    context=speech_context(frame,frames,segments)
    sig=signature({'version':2,'image':digest_file(image),'model':client.model,'context':context,'max_regions':max_regions})
    result_path=folder/'result.json'
    if result_path.exists() and read(result_path).get('signature')==sig:
        return read(result_path)
    initial=client.call('extract',[image],EXTRACTION_PROMPT,EXTRACT)
    with Image.open(image) as im:validate_blocks(initial,im.size,allow_empty_text=True)
    save(folder/'original.json',initial)
    audit=client.call('audit',[image],AUDIT_PROMPT+json.dumps(initial,ensure_ascii=False)+
                      '\nNEARBY ASR (not ground truth):\n'+json.dumps(context,ensure_ascii=False),AUDIT)
    byid={b['id']:b for b in initial['blocks']}
    regions=list(audit['regions'])
    targeted={r['target_id'] for r in regions}
    for block in initial['blocks']:
        if critical(block) and block['id'] not in targeted:
            regions.append({'target_id':block['id'],'bbox':block['bbox'],'kind':block['kind'],
                            'issue':'uncertain','reason':'critical_content_policy'})
    counts=Counter(r['target_id'] for r in regions if r['target_id']!='NEW')
    final=copy.deepcopy(initial['blocks']);log=[];holds=[]
    if not initial['readable']:holds.append({'reason':'whole_frame_not_readable'})
    if not audit['complete_scan']:holds.append({'reason':'incomplete_audit'})
    if len(regions)>max_regions:holds.append({'reason':'region_budget','remaining':len(regions)-max_regions})
    for number,region in enumerate(regions[:max_regions],1):
        tid=region['target_id'];before=byid.get(tid)
        if (tid!='NEW' and before is None) or counts[tid]>1:
            holds.append({'region':region,'reason':'invalid_or_duplicate_target'});continue
        box=region['bbox']
        if before:
            box=[min(box[0],before['bbox'][0]),min(box[1],before['bbox'][1]),
                 max(box[2],before['bbox'][2]),max(box[3],before['bbox'][3])]
        try:native,contrast,binary,pixels=variants(image,box,folder,number)
        except ValueError:
            holds.append({'region':region,'reason':'invalid_bbox'});continue
        reread=client.call('crop_read',[native],REREAD_PROMPT,REREAD)
        evidence=[str(native.relative_to(out))]
        if not reread['readable'] or reread['uncertainties']:
            # Preprocessing may distort fine symbols; always include the native crop and verify on original.
            paths=[native,contrast]+([binary] if binary else [])
            reread=client.call('crop_read_enhanced',paths,REREAD_PROMPT+
                '\nImage 1 is authoritative original; remaining images are contrast/threshold helpers. '
                'Never accept a symbol visible only after thresholding.',REREAD)
            evidence=[str(p.relative_to(out)) for p in paths]
        if not reread['readable'] or reread['uncertainties'] or reread['source_conflicts'] or not reread['text'].strip():
            holds.append({'region':region,'reason':'reread_uncertain','evidence':evidence,'reread':reread});continue
        verification=client.call('verify',[image,native],VERIFY_PROMPT+json.dumps({
            'original_block':before,'region':region,'independent_reading':reread,'asr_context':context},ensure_ascii=False),VERIFY)
        passes=all(verification[k] is True for k in ('source_clear','all_changes_visible','same_region')) and not verification['source_conflict']
        if not passes or verification['decision']=='hold':
            holds.append({'region':region,'reason':'verification_hold','verification':verification,'evidence':evidence});continue
        if verification['decision']=='unchanged':
            # Never use 'unchanged' to clear an omission or an explicit original uncertainty.
            if before is None or not before['text'].strip() or before['uncertainties'] or '[ILLEGIBLE]' in before['text']:
                holds.append({'region':region,'reason':'unchanged_but_unresolved'});continue
            log.append({'target_id':tid,'action':'unchanged','evidence':evidence});continue
        after={'id':tid if before else f'added-{number}','bbox':box,'kind':region['kind'],
               'text':reread['text'],'uncertainties':[]}
        if before:
            final[next(i for i,b in enumerate(final) if b['id']==tid)]=after
        else:
            if duplicate_addition(after,final):
                holds.append({'region':region,'reason':'duplicate_addition'});continue
            while any(b['id']==after['id'] for b in final):after['id']='new-'+after['id']
            final.append(after)
        log.append({'target_id':after['id'],'action':'replace' if before else 'add','before':before,
                    'after':after,'verification':verification,'evidence':evidence})
    for block in final:
        if not block['text'].strip():
            holds.append({'target_id':block['id'],'reason':'empty_extraction_block'})
        if block['uncertainties'] or '[ILLEGIBLE]' in block['text']:
            holds.append({'target_id':block['id'],'reason':'remaining_uncertainty'})
    # Preserve first-pass block order. Added blocks are kept separate with their coordinates.
    changes=sum(r['action']=='add' or (r['action']=='replace' and r['before']['text']!=r['after']['text']) for r in log)
    result={'signature':sig,'frame_id':frame['id'],'frame_time_seconds':frame['time_seconds'],
            'image_sha256':digest_file(image),'original':initial,'final_blocks':final,'audit':audit,
            'corrections':log,'holds':holds,'status':'needs_review' if holds else 'auto_repaired' if changes else 'auto_checked',
            'text':'\n\n'.join(b['text'] for b in final),'changed_blocks':changes,
            'note':'Same-model automated checks are not independent proof or a measured accuracy score.'}
    save(result_path,result)
    return result
