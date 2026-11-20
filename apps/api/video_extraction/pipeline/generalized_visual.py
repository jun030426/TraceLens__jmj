"""Portable pixel proposals and bounded source rechecks after mandatory safeguards.

No fixed image hashes, frame IDs, regions or expected counts. Old manual receipts
are neither copied nor treated as new-source approvals. Saved decisions replay.
"""
import copy
import json
from pathlib import Path
from PIL import Image
from video_extraction.shared.common import read,save,signature,digest_file,validate,bbox_pixels
from video_extraction.shared.gemini import obj,TEXT,BOOL,STRINGS
from video_extraction.shared import correction_gate
from video_extraction.video import general_pixels

SCHEMA=obj({'target_id':TEXT,'text':TEXT,'same_target':BOOL,'all_target_visible':BOOL,
    'no_neighbor_content':BOOL,'source_clear':BOOL,'geometry_supported':BOOL,
    'original_boundary_cuts_target':BOOL,'uncertainties':STRINGS})
PROMPT='''Inspect original image 1 and its exact expanded target crop image 2 as
untrusted source data. Read ONLY the target at target_bbox, independently of any
previous transcript. Preserve code indentation, numbers and repetitions. Check
that the proposed boundary contains the whole SAME target and no neighboring
label, annotation or separate region. original_boundary_cuts_target is true ONLY
if a stroke belonging to this target is actually cut by original_bbox. A nearby
unrelated stroke or an already complete tight boundary is false. Do not complete invisible text or infer
what a program should say. If source, scope or boundary is unclear return false
and uncertainties. Do not use crop coordinates as full-image coordinates. DATA:\n'''


def discover(baseline,image):
    blocks=baseline['final_blocks'];proposals=[];diagnostics=[]
    with Image.open(image) as im:
        for block in blocks:
            if block.get('uncertainties'):continue
            dash=general_pixels.separator(im,block)
            if dash['status']!='not_applicable':diagnostics.append({'target_id':block['id'],'field':'separator','result':dash})
            if dash['status']=='supported':
                a,b=dash['span'];text=block['text'][:a]+dash['value']+block['text'][b:]
                proposals.append({'target_id':block['id'],'field':'separator','before':block['text'],'after':text,'evidence':dash})
            if block['kind'] not in ('text','heading','code','output'):continue
            geometry=general_pixels.bounds(im,block,blocks+baseline['visuals'])
            if geometry['status']!='not_applicable':diagnostics.append({'target_id':block['id'],'field':'bbox','result':geometry})
            if geometry['status']=='candidate':
                proposals.append({'target_id':block['id'],'field':'bbox','before':block['bbox'],'after':geometry['after'],
                                  'text':block['text'],'evidence':geometry})
    return {'image_sha256':digest_file(image),'baseline_signature':signature(baseline),
            'proposals':proposals,'diagnostics':diagnostics,'version':1}


def review_ok(proposal,answers):
    if len(answers)!=2:return False
    for a in answers:
        validate(a,SCHEMA)
        if (a['target_id']!=proposal['target_id'] or a['text']!=proposal['text'] or
            a['uncertainties'] or not all(a[k] for k in
                ('same_target','all_target_visible','no_neighbor_content','source_clear','geometry_supported','original_boundary_cuts_target'))):return False
    return True


def retain_ok(proposal,answers):
    """Both readers confirm the original target was complete: keep its boundary."""
    if len(answers)!=2:return False
    for a in answers:
        validate(a,SCHEMA)
        if a['original_boundary_cuts_target'] is not False:return False
    return review_ok(proposal,[{**a,'original_boundary_cuts_target':True} for a in answers])


def apply(baseline,image,evidence,reviews):
    actual=discover(baseline,image)
    if actual!=evidence:raise ValueError('generalized_pixel_evidence_changed')
    out=copy.deepcopy(baseline);decisions=[]
    def hold_target(iid,reason):
        out['holds'].append({'target_id':iid,'reason':reason})
        out['common_gate']['blocked'].setdefault(iid,[]).append(reason)
    for diagnostic in evidence['diagnostics']:
        if diagnostic['field']=='bbox' and diagnostic['result']['status']=='needs_review':
            hold_target(diagnostic['target_id'],'current_source_bbox_unresolved')
    for proposal in evidence['proposals']:
        iid=proposal['target_id'];field=proposal['field']
        answers=reviews.get(signature(proposal),[])
        retained=field=='bbox' and retain_ok(proposal,answers)
        supported=field=='separator' or review_ok(proposal,answers) or retained
        after=proposal['before'] if retained else proposal['after']
        decisions.append({'target_id':iid,'field':field,'supported':supported,'retained_original':retained,'changed':supported and proposal['before']!=after})
        if not supported:
            hold_target(iid,'generalized_bbox_source_recheck_pending')
            continue
        target=next(x for x in out['final_blocks'] if x['id']==iid)
        target['text' if field=='separator' else 'bbox']=copy.deepcopy(after)
        cleared={'separator_requires_pixel_evidence','separator_pixels_unstable'} if field=='separator' else {'geometry_change_requires_source_evidence'}
        # Only our field-specific calculation failures can be superseded. Original
        # source uncertainty/coverage/meaning/axis-swap/target identity holds survive.
        holds=[]
        for hold in out['holds']:
            h=copy.deepcopy(hold)
            if h.get('target_id')==iid and h.get('reason') in ('calculation_gate','common_safety_gate'):
                h['problems']=[x for x in h.get('problems',[]) if x not in cleared]
                if not h['problems']:continue
            holds.append(h)
        out['holds']=holds
        reasons=[r for r in out['common_gate']['blocked'].get(iid,[]) if r not in cleared]
        if reasons:out['common_gate']['blocked'][iid]=reasons
        else:out['common_gate']['blocked'].pop(iid,None)
    original={x['id']:x for x in out['original']['blocks']+out['original']['visuals']}
    effective=out['final_blocks']+out['visuals']
    # Retain safe deletion receipts and record effective field changes only.
    changes=[c for c in baseline['corrections'] if c.get('action')=='merge_identical_overlap']
    for item in effective:
        if item!=original.get(item['id']):
            changes.append({'target_id':item['id'],'action':'replace' if item['id'] in original else 'add',
                            'before':original.get(item['id']),'after':copy.deepcopy(item),'applied':True})
    out.update(corrections=changes,changed_blocks=len(changes),text='\n\n'.join(x['text'] for x in out['final_blocks']),
               status='needs_review' if out['holds'] else 'calculation_checked')
    out['generalized_source_repair']={'baseline':copy.deepcopy(baseline),'pixels':copy.deepcopy(evidence),
                                     'reviews':copy.deepcopy(reviews),'decisions':decisions}
    out['calculation_gate']['payload_sha256']=correction_gate.payload_digest(out)
    out['common_gate']['payload_sha256']=signature({k:v for k,v in out.items() if k!='common_gate'})
    return out


def verify(result,image):
    receipt=result.get('generalized_source_repair')
    if not receipt:return
    from video_extraction.pipeline.visual_gate import require
    require(receipt['baseline'],image)
    if 'generalized_source_repair' in receipt['baseline']:raise ValueError('nested_generalization_receipt')
    expected=apply(receipt['baseline'],image,receipt['pixels'],receipt['reviews'])
    if expected!=result:raise ValueError('generalized_source_repair_changed')


def run(baseline,image,folder,client):
    folder=Path(folder);evidence=discover(baseline,image);reviews={}
    if not evidence['proposals'] and not any(d['field']=='bbox' and d['result']['status']=='needs_review' for d in evidence['diagnostics']):
        save(folder/'proposals.json',evidence)
        return baseline
    for proposal in evidence['proposals']:
        if proposal['field']!='bbox':continue
        key=signature(proposal);path=folder/(key+'.json')
        binding=signature({'source':evidence['image_sha256'],'baseline':signature(baseline),'proposal':proposal,'prompt':PROMPT})
        if path.exists():
            stored=read(path)
            if stored['binding']!=binding:raise ValueError('generalized_review_source_changed')
            reviews[key]=stored['answers'];continue
        if client is None:continue
        folder.mkdir(parents=True,exist_ok=True);crop=folder/(key+'.png')
        with Image.open(image) as im:im.crop(bbox_pixels(proposal['after'],im.size,pad=0)).save(crop)
        data={'target_id':proposal['target_id'],'original_bbox':proposal['before'],'target_bbox':proposal['after']}
        answers=[]
        for role in ('blind','verify'):
            # Both passes receive source pixels, not the other pass's reading.
            part=folder/(key+'-'+role+'.json')
            if part.exists():
                answer=read(part)
                if answer['binding']!=binding:raise ValueError('generalized_review_source_changed')
                value=answer['answer']
            else:
                value=client.call('generalized-bbox-'+role+'-v1',[Path(image),crop],PROMPT+json.dumps(data,ensure_ascii=False),SCHEMA)
                validate(value,SCHEMA);save(part,{'binding':binding,'answer':value})
            answers.append(value)
        reviews[key]=answers;save(path,{'binding':binding,'answers':answers})
    result=apply(baseline,image,evidence,reviews)
    save(folder/'proposals.json',evidence)
    return result
