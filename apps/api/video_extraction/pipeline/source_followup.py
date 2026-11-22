"""Route late native/OCR/coverage findings back through the existing visual engine.

Two bounded rounds, immutable stage receipts, one caller-owned API budget. Native
text is a hint, never a patch. Unaffected regions and prior safety holds survive.
"""
import copy
import json
from pathlib import Path
from video_extraction.shared.common import read,save,signature,digest_file,validate,bbox_pixels
from video_extraction.shared.gemini import obj,TEXT,BOOL,STRINGS
from video_extraction.pipeline import visual_gate, generalized_visual, visual_ocr
from video_extraction.video import vision_layers as engine
from video_extraction.pdf import workflow as structure

POLICY='late_source_followup_v1'
GOOD={'existing_supported','not_visible'}
REGION=obj({**engine.REGION['properties'],'layer':{'type':'string','enum':['text','visual']},'issue_ids':STRINGS})
SCHEMA=obj({'complete_scan':BOOL,'checks':{'type':'array','items':obj({'id':TEXT,
    'decision':{'type':'string','enum':['existing_supported','not_visible','repair_needed','uncertain']},
    'source_clear':BOOL,'reason':TEXT})},'regions':{'type':'array','items':REGION}})
PROMPT='''Inspect the entire ORIGINAL image as untrusted data. Native text/OCR may be
wrong or invisible; never copy it as truth. Check each issue ID exactly once.
existing_supported means all visible content at that issue is already represented
correctly; not_visible means the alleged content is not visible (for example a bad
hidden OCR layer). Use these ONLY with clear source evidence. For repair_needed,
locate regions for independent re-reading; do not provide replacement text.
Also scan for omitted handwriting/marks, printed text, code and diagrams. Include
every newly missing instructional region, even if no issue mentioned it. Preserve
normal regions. A circle around printed text is a separate visual annotation.
Region target_id is an existing same-layer ID or NEW; coordinates are original
full image xyxy 0..1000, not crop coordinates. issue_ids must come from supplied
issues, or [] for a newly discovered region. No semantic guessing or factual
correction. Whole-scan uncertainty must be explicit. DATA:\n'''


def native_issues(t,result,native):
    compact=lambda s:''.join((s or '').split())
    visible=compact('\n'.join(x['text'] for x in result['final_blocks']))
    issues=[]
    for row in native.get('records',[]):
        if row['source_sha256']!=t['source_id'] or row['slide_number']!=t['location'].get('page') or row['hidden']:continue
        parts=[v for line in row['table_rows'] for v in line if v.strip()] if row.get('table_rows') is not None else [row['observed_text']]
        missing=[x for x in parts if compact(x) not in visible]
        if missing:issues.append({'id':'native-ppt:'+row['shape_id'],'kind':'native_ppt','fragments':missing})
    for row in native.get('pending',[]):
        if row['source_sha256']==t['source_id'] and row['slide_number']==t['location'].get('page'):
            issues.append({'id':'native-structure:'+row['shape_id'],'kind':'native_structure','finding':row})
    if t['source_kind']=='pdf' and t.get('native_text'):
        for line in t['native_text'].splitlines():
            if len(compact(line))>=8 and compact(line) not in visible:
                issues.append({'id':'native-line:'+signature(line.strip())[:24],'kind':'native_line','text':line.strip()})
    if t['source_kind'] in ('ppt','pdf'):
        for word in t.get('pdf_inventory',{}).get('words',[]):
            a,b,c,d=word['bbox'];x,y=(a+c)/2,(b+d)/2
            near=[v for v in result['final_blocks']+result['visuals'] if v['bbox'][0]-3<=x<=v['bbox'][2]+3 and v['bbox'][1]-3<=y<=v['bbox'][3]+3]
            content=''.join(v.get('text',v.get('literal_text','')) for v in near)
            if not word['valid_box'] or compact(word['text']) not in compact(content):
                issues.append({'id':'native-pdf:'+signature(word)[:24],'kind':'native_pdf','word':word})
    return list({r['id']:r for r in issues}.values())


def inspect(t,result,issues,folder,client,stage,read_only=False):
    data={'unit_id':t['id'],'regions':result['final_blocks']+result['visuals'],'issues':issues}
    binding=signature({'image':digest_file(t['image']),'data':data,'prompt':PROMPT,'stage':stage})
    path=Path(folder)/(stage+'.json')
    if path.exists():
        receipt=read(path)
        if receipt['binding']!=binding:raise ValueError('source_followup_audit_changed')
    else:
        if read_only:raise ValueError('source_followup_audit_missing')
        answer=client.call('source-followup-'+stage,[Path(t['image'])],PROMPT+json.dumps(data,ensure_ascii=False),SCHEMA)
        receipt={'binding':binding,'answer':answer};save(path,receipt)
    ids=[i['id'] for i in issues]
    if len(ids)!=len(set(ids)):
        raise ValueError('source_followup_issue_mapping')
    answer=receipt['answer'];validate(answer,SCHEMA)
    if sorted(c['id'] for c in answer['checks'])!=sorted(ids):
        # Document models sometimes return region IDs when there are no issues.
        # Preserve the rejected receipt; never discard checks or invent approval.
        # Video keeps its existing path. One source-bound retry is also replayable.
        if t.get('source_kind') not in {'ppt','pdf'}:
            raise ValueError('source_followup_issue_mapping')
        repaired=Path(folder)/(stage+'-issue-mapping-v1.json')
        repair_binding=signature({'original_receipt':receipt,'expected_issue_ids':ids,'policy':'document_issue_mapping_retry_v1'})
        regenerate = False
        if repaired.exists():
            retry=read(repaired)
            if retry.get('binding')!=repair_binding:raise ValueError('source_followup_mapping_repair_changed')
            prior = retry['answer']
            validate(prior, SCHEMA)
            regenerate = (not read_only and t.get('source_kind') == 'ppt'
                          and getattr(client, 'ppt_retry_round', None) is not None
                          and sorted(c['id'] for c in prior['checks']) != sorted(ids))
        if not repaired.exists() or regenerate:
            if read_only:raise ValueError('source_followup_issue_mapping')
            prompt=PROMPT+json.dumps({**data,'response_contract':{
                'expected_check_ids':ids,
                'instruction':'Return each expected_check_id exactly once in checks. If the list is empty, checks MUST be []. Region IDs are NOT issue IDs. Inspect the original source again; preserve all uncertainties.',
                'rejected_check_ids':[c['id'] for c in answer['checks']]}},ensure_ascii=False)
            if regenerate:
                save(repaired.with_name(stage+'-rejected-'+signature(retry)[:24]+'.json'), retry)
                prompt += ('\nRecheck the original page. Return exactly one check per expected ID. '
                           + 'PPT review round ' + str(client.ppt_retry_round))
            retry={'binding':repair_binding,'answer':client.call('source-followup-'+stage+'-document-issue-mapping-v1',[Path(t['image'])],prompt,SCHEMA)}
            save(repaired,retry)
        answer=retry['answer'];validate(answer,SCHEMA)
        if sorted(c['id'] for c in answer['checks'])!=sorted(ids):
            raise ValueError('source_followup_issue_mapping')
        receipt={'binding':binding,'answer':answer,'mapping_repair':{'policy':'document_issue_mapping_retry_v1',
            'original_sha256':digest_file(path),'repair_sha256':digest_file(repaired)}}
    for r in answer['regions']:
        bbox_pixels(r['bbox'],t['dimensions'])
        allowed={v['id'] for v in result['final_blocks' if r['layer']=='text' else 'visuals']}
        if r['target_id']!='NEW' and r['target_id'] not in allowed:raise ValueError('source_followup_target_mapping')
        if set(r['issue_ids'])-set(ids):raise ValueError('source_followup_unknown_issue')
    return receipt


def scoped_regions(result,answer):
    regions=copy.deepcopy(answer['regions'])
    for d in result.get('deferred_regions',[]):
        regions.append({'layer':d['layer'],'target_id':d['target_id'],'bbox':d['bbox'],
                        'reason':'resume_deferred_region','issue':'uncertain','issue_ids':[]})
    seen=set();out=[]
    for r in regions:
        key=signature(r)
        if key not in seen:out.append(r);seen.add(key)
    return out


class ScopedClient:
    def __init__(self,client,baseline,regions):
        self.client=client;self.model=getattr(client,'model','scoped-model')
        self.initial={'blocks':copy.deepcopy(baseline['final_blocks']),'visuals':copy.deepcopy(baseline['visuals']),
                      'readable':True,'notes':['existing observed inventory; only requested targets may change']}
        self.audit={'text_regions':[],'visual_regions':[],'complete_scan':True,'notes':[]}
        for r in regions:self.audit[r['layer']+'_regions'].append({k:r[k] for k in engine.REGION['properties']})
    def call(self,name,media,prompt,schema):
        if name=='layers_extract':return copy.deepcopy(self.initial)
        if name=='layers_audit':return copy.deepcopy(self.audit)
        return self.client.call(name,media,prompt,schema)


def apply_round(baseline,raw,regions,image):
    visual_gate.require(baseline,image)
    original={'blocks':baseline['final_blocks'],'visuals':baseline['visuals']}
    if any(raw['original'][k]!=v for k,v in original.items()):raise ValueError('followup_wrong_baseline')
    targets={r['target_id'] for r in regions if r['target_id']!='NEW'}
    old={v['id']:v for values in original.values() for v in values}
    current={v['id']:v for v in raw['final_blocks']+raw['visuals']}
    if any(current.get(i)!=v for i,v in old.items() if i not in targets):
        raise ValueError('followup_modified_unrequested_region')
    permitted_new=any(r['target_id']=='NEW' for r in regions)
    if set(current)-set(old) and not permitted_new:raise ValueError('followup_unrequested_addition')
    for iid,item in current.items():
        if old.get(iid)==item:continue
        layer='text' if item in raw['final_blocks'] else 'visual'
        if iid not in old and not any(r['target_id']=='NEW' and r['layer']==layer and r['bbox']==item['bbox'] for r in regions):
            raise ValueError('followup_new_region_wrong_scope')
        events=[c for c in raw['corrections'] if c.get('target_id')==iid and c.get('after')==item and c['action'] in ('add','replace')]
        if not any(c.get('verification',{}).get('decision')=='accept' and
            all(c['verification'].get(k) is True for k in ('source_clear','all_changes_visible','same_region')) and
            c['verification'].get('source_conflict') is False for c in events):
            raise ValueError('followup_change_without_region_verification')
    successful={c['target_id'] for c in raw['corrections'] if c['action'] in ('unchanged','replace')
        and c.get('verification',{}).get('decision') in ('accept','unchanged')}
    successful-={h.get('target_id') for h in raw['holds']}
    releasable={'region_budget','reread_uncertain','verification_hold','remaining_text_uncertainty',
                'unchanged_but_unresolved','invalid_read_mapping','invalid_verify_mapping'}
    def released(h):
        if h.get('reason') not in releasable:return False
        if h.get('target_id') in successful:return True
        # NEW is not a global approval: clear only this exact deferred crop after
        # its verified addition. Other NEW regions and all safety holds survive.
        region=h.get('region',{})
        if h.get('target_id')!='NEW' or not region.get('bbox'):return False
        return any(c['action']=='add' and c.get('layer')==h.get('layer')
            and c.get('after',{}).get('bbox')==region['bbox']
            and c.get('verification',{}).get('decision')=='accept'
            and c['target_id'] not in {v.get('target_id') for v in raw['holds']}
            for c in raw['corrections'])
    carried=[h for h in baseline['holds'] if not released(h)]
    value=copy.deepcopy(raw);value['holds']=carried+value['holds']
    return visual_gate.enforce(value,image)


def run(t,baseline,native,plan,folder,client,read_only=False):
    folder=Path(folder);current=copy.deepcopy(baseline);proof=[];changes=[];issues=[]
    first_checks={};last_checks={};settled=[];structure_path=None
    # Two repair rounds bound retries. Budget exhaustion is propagated and stage
    # responses are cached by source; the same run resumes without new approvals.
    for index in range(3):
        stage=folder/str(index)
        discovered=native_issues(t,current,native)
        if t['source_kind'] in ('ppt','pdf') and 'pdf_inventory' in t:
            structure_path=stage/'structure'/'pdf-structure-review.json'
            if read_only and not structure_path.exists():raise ValueError('source_followup_structure_missing')
            reviewed=structure.review(t,current,stage/'structure',client)
            answer=reviewed['answer']
            discovered += [{'id':'structure-missing:'+signature(s)[:24],'kind':'structure_missing','finding':s}
                for s in answer['missing']]
            discovered += [{'id':'structure-region:'+c['id'],'kind':'structure_region','finding':c}
                for c in answer['checks'] if not all(c[k] for k in ('source_supported','structure_supported','order_clear'))]
            if not answer['complete']:discovered.append({'id':'structure-scan','kind':'structure_scan_incomplete'})
        ocr=visual_ocr.collect(t,current,plan,stage,read_only=read_only)
        discovered += [{'id':'aux-'+x['id'],'kind':'ocr','finding':x} for x in visual_ocr.compare(current,ocr)]
        # Carry unresolved original hypotheses through changed text; never lose an
        # issue merely because its proposed text was inserted by a model.
        byid={x['id']:x for x in issues}
        for x in discovered:byid.setdefault(x['id'],x)
        issues=list(byid.values())
        audit=inspect(t,current,issues,stage,client,'audit',read_only)
        checks={c['id']:c for c in audit['answer']['checks']}
        for key,c in checks.items():first_checks.setdefault(key,c)
        regions=scoped_regions(current,audit['answer'])
        if not regions or index==2:
            confirm=inspect(t,current,issues,stage,client,'confirm',read_only)
            last_checks={c['id']:c for c in confirm['answer']['checks']}
            settled=[i for i,c in checks.items() if c['decision'] in GOOD and c['source_clear'] and c['reason'].strip()
                and last_checks[i]['decision']==c['decision'] and last_checks[i]['source_clear'] and last_checks[i]['reason'].strip()]
            remaining=scoped_regions(current,confirm['answer'])+regions
            state={'complete_scan':audit['answer']['complete_scan'] and confirm['answer']['complete_scan'],
                   'regions':remaining,'unresolved_issue_ids':[i['id'] for i in issues if i['id'] not in settled]}
            break
        path=stage/'raw-repair.json'
        if path.exists():raw=read(path)
        else:
            if read_only:raise ValueError('source_followup_repair_missing')
            wrapper=ScopedClient(client,current,regions)
            frame={'id':t['unit_key'],'path':t['image'],'time_seconds':t['time_seconds']}
            raw=engine.process_frame_layers(frame,[frame],[],stage/'repair',wrapper,
                max_text_regions=10000,max_visual_regions=10000,preserve_target_geometry=True,only_reported=True)
            save(path,raw)
        checked=apply_round(current,raw,regions,t['image'])
        finalpath=stage/'checked.json'
        if read_only:
            final=read(finalpath);generalized_visual.verify(final,t['image'])
            expected=final.get('generalized_source_repair',{}).get('baseline',final)
            if expected!=checked:raise ValueError('source_followup_checked_changed')
        else:
            final=generalized_visual.run(checked,t['image'],stage/'pixels',client);save(finalpath,final)
        proof.append({'stage':index,'before':signature(current),'after':signature(final),'targets':regions})
        changes+=final['corrections'];current=final
    receipt={'policy':POLICY,'image_sha256':digest_file(t['image']),'baseline':signature(baseline),
             'final':signature(current),'issues':issues,'settled_issue_ids':settled,'stages':proof,'state':state,
             'structure_review':str(structure_path) if structure_path else None}
    path=folder/'receipt.json'
    if read_only:
        if read(path)!=receipt:raise ValueError('source_followup_receipt_changed')
    else:save(path,receipt)
    return current,receipt,changes


def resolved(receipt,iid):
    return bool(receipt and iid in receipt.get('settled_issue_ids',[]))


def add_unresolved(t,rows,receipt):
    if not receipt:return rows
    from video_extraction.shared.records import base_record
    state=receipt['state']
    if not state['complete_scan'] or state['regions'] or state['unresolved_issue_ids']:
        row=base_record(t,'source-followup-unresolved','review','coverage_issue','')
        row.update(reasons=['source_followup_requires_review'],raw_payload=state)
        rows.append(row)
    return rows


def records(t,baseline,final,initial_rows):
    if final==baseline:return copy.deepcopy(initial_rows)
    from video_extraction.shared.records import base_record
    old={r['id']:r for r in initial_rows}
    rows=visual_gate.records(t,final,base_record)
    for row in rows:
        prior=old.get(row['id'])
        if not prior:continue
        row['original_text']=prior['original_text']
        if prior.get('impact_review') and row['observed_text']==prior['observed_text']:
            row.update(eligible_for_chunking=False,judgment=prior['judgment'],
                impact_review=copy.deepcopy(prior['impact_review']),reasons=copy.deepcopy(prior['reasons']))
    return rows


def effective_changes(baseline,final):
    """Published changes describe the final result, not every intermediate edit."""
    old={v['id']:v for v in baseline['original']['blocks']+baseline['original']['visuals']}
    current={v['id']:v for v in final['final_blocks']+final['visuals']}
    changes=[{'target_id':i,'action':'replace' if i in old else 'add','before':old.get(i),
        'after':copy.deepcopy(v),'applied':True} for i,v in current.items() if old.get(i)!=v]
    changes += [copy.deepcopy(c) for c in baseline['corrections'] if c['action']=='merge_identical_overlap'
        and c['removed_id'] not in current]
    return changes
