"""Versioned continuation with bounded recovery and discrepancy diagnostics.

prepare/local/report are offline. run is the user-terminal API entry point.
Direct-review approvals from earlier samples are never reused for new samples.
"""
from video_extraction._layout import source_path, code_hashes_match
import argparse
import copy
from video_extraction.shared import file_lock as fcntl
import html
import json
from pathlib import Path
import cv2
import numpy as np
from PIL import Image

from video_extraction.shared.common import read, save, jsonl, digest_file, signature, now
from video_extraction.shared.gemini import Gemini, Blocked
from video_extraction.ink.runner.ink_continue import safe_task, select_batch, local_batch, context_bindings, CONTEXT_PROMPT, check_plan as check_previous
from video_extraction.ink.runner.ink_pipeline import ROOT, VISUAL, LINKS, stage_call, merge_repair, transform_ocr, transform_visual
from video_extraction.ink.correction.ink_recheck import core_box
from video_extraction.ink.correction.ink_recovery import source_audit, evaluate, needs_wider, widen_to_source, required_ids, RECOVERY_VISUAL_PROMPT, hashes as recovery_hashes, admin_ids
from video_extraction.ink.correction.ink_discrepancy import discrepancy_report, refresh_relations, pixel_probe

OUTPUT=ROOT/'outputs/ink-continuation-v2'


def hashes():
    return {**recovery_hashes(), **{n:digest_file(source_path(n)) for n in
            ('ink_continue.py','ink_discrepancy.py','ink_continue_v2.py')}}


def aligned_package(package, view):
    """Move OCR and scanned coverage exactly when recovery moves to full frame."""
    p=copy.deepcopy(package); old=p['view']
    if old['crop_in_source']!=view['crop_in_source']:
        p['ocr']=transform_ocr(package['ocr'],old,view)
        if 'alternative_words' in package['ocr']:
            p['ocr']['alternative_words']=transform_ocr({'words':package['ocr']['alternative_words']},old,view)['words']
        p['ocr_coverage']=transform_visual({'items':[{'box':p['ocr_coverage'],'arrow_points':[]}]},old,view)['items'][0]['box']
    p['view']=copy.deepcopy(view)
    return p


def diagnostics_with_pixels(package, result):
    """Locate shape candidates by source components, never by estimated text width.

    Multiple plausible locations stay ambiguous. These measurements do not waive
    an OCR conflict or associate a particular character with a component as fact.
    """
    diagnostics=discrepancy_report(package,result)
    source=package['task']['evidence']['selected_frame']
    with Image.open(source) as im: rgb=np.asarray(im.convert('RGB')).astype(np.int16)
    height,width=rgb.shape[:2]; items={i['id']:i for i in result['candidate']['items']}
    for iid,row in diagnostics.items():
        diffs=row.get('differences',[])
        kinds=set()
        for d in diffs:
            if d['category']!='punctuation_shape_confusion':continue
            kinds.update({':':'colon','()':'parentheses_pair','_':'underscore'}[s]
                         for s in (d['observed'],d['ocr']) if s in (':','()','_'))
        if not kinds:continue
        box=transform_visual({'items':[items[iid]]},package['view'],{'crop_in_source':[0,0,1,1]})['items'][0]['box']
        x,y,r,b=[int(round(box[k]*s/1000)) for k,s in zip(('left','top','right','bottom'),(width,height,width,height))]
        if not (0<=x<r<=width and 0<=y<b<=height):
            row['pixel_probe_state']='invalid_source_box';continue
        crop=rgb[y:b,x:r];h=b-y
        mask=((crop.max(2)<185)&((crop.max(2)-crop.min(2))<80)).astype('uint8')
        _,_,stats,_=cv2.connectedComponentsWithStats(mask,8)
        parts=sorted([s for s in stats[1:] if s[4]>=2],key=lambda s:(s[0],s[1]))
        candidates=[];attempts=0
        def propose(kind, components):
            nonlocal attempts
            if attempts>=48:return
            attempts+=1
            left=min(s[0] for s in components)+x; top=min(s[1] for s in components)+y
            right=max(s[0]+s[2] for s in components)+x; bottom=max(s[1]+s[3] for s in components)+y
            roi=[max(x,int(left)-1),max(y,int(top)-1),min(r,int(right)+1),min(b,int(bottom)+1)]
            probe=pixel_probe(source,roi,kind)
            if probe['state']=='shape_support_only':candidates.append(probe)
        for i,s in enumerate(parts):
            if len(candidates)>=12 or attempts>=48:break
            if 'underscore' in kinds and s[2]>=3*s[3] and s[1]>=h*.5:propose('underscore',[s])
            for t in parts[i+1:]:
                if len(candidates)>=12 or attempts>=48:break
                if 'colon' in kinds and max(s[2],s[3],t[2],t[3])<=max(3,h*.3):
                    if abs((s[0]+s[2]/2)-(t[0]+t[2]/2))<=1 and abs(s[1]-t[1])>=2:
                        propose('colon',[s,t])
                if 'parentheses_pair' in kinds and min(s[3],t[3])>=h*.5:
                    if 0<t[0]-(s[0]+s[2])<h*.6 and max(s[2],t[2])<h*.6:
                        propose('parentheses_pair',[s,t])
        row.update(pixel_candidates=candidates,pixel_probe_state='source_review_required',
                   character_to_pixel_alignment='not_confirmed',automatic_release=False)
    return diagnostics


def execute(data, output, plan, client):
    task=data['task']; p=copy.deepcopy(data); view=p['view']
    media=list(dict.fromkeys([Path(view['path']),Path(task['current_image'])]))
    visual=stage_call(task,output,plan,client,'continuation_v2_visual',media,
        RECOVERY_VISUAL_PROMPT+json.dumps(dict(core_box=core_box(task,view),
            instruction='Image 1 coordinates only. Image 2 is the same full source frame. '
            'Read complete words/operators, not clipped fragments. Check nearby matching symbols '
            'before calling a mark a letter. Do not guess exact symbol or meaning from lecture context. '
            'Keep uncertainties. Pure emphasis has no observed direction.'),ensure_ascii=False),VISUAL)
    segments=[s for s in task.get('asr_context',[]) if task['audio_interval'][0]<=s['start_seconds']<s['end_seconds']<=task['audio_interval'][1]]
    active=required_ids(p,visual)
    if segments and active:
        context=stage_call(task,output,plan,client,'continuation_v2_asr_context',[Path(view['path'])],
            CONTEXT_PROMPT+json.dumps(dict(inventory=visual,segments=segments,audio_interval=task['audio_interval']),ensure_ascii=False),LINKS)
        context=context_bindings(context,segments,visual,task['audio_interval'])
    else: context={'bindings':[],'concepts':[],'word_candidates':[],'notes':['No complete ASR segment supplied.']}
    p.update(base=copy.deepcopy(visual),candidate=visual,audio_context=context)
    # Even an empty extraction gets an independent scan for missing core content.
    first,trace=source_audit(p,visual,output,plan,client,'continuation_v2_source_audit')
    initial=evaluate(p,visual,first)
    initial_diagnostics=diagnostics_with_pixels(p,initial)
    requested={d['id'] for d in initial['decisions'] if d['status']=='held'}-set(initial['unresolved_audit_ids'])
    if initial['missing_core'] or not first['complete']: requested.add('__scope__')
    value=visual; final=first; traces=[trace]
    if requested:
        if needs_wider(initial) and view['crop_in_source']!=[0,0,1,1]:
            p=widen_to_source(p);view=p['view'];value=p['candidate']
        # Recalculate diagnostics in the new coordinates; pixel locations are not inferred from string length.
        diagnostic_result={**initial,'candidate':value,'final_view':view}
        diagnostics=diagnostics_with_pixels(p,diagnostic_result)
        media=list(dict.fromkeys([Path(view['path']),Path(task['current_image'])]))
        patch=stage_call(task,output,plan,client,'continuation_v2_targeted_repair',media,
            RECOVERY_VISUAL_PROMPT+json.dumps(dict(candidate=value,repair_only_ids=sorted(requested),
                administrator_ids=sorted(admin_ids(value)),core_box=core_box(task,view),
                findings=[d for d in initial['decisions'] if d['id'] in requested],
                discrepancy_diagnostics=diagnostics,
                instruction='Repair only requested IDs, preserve unaffected IDs, no deletion. '
                'Read source pixels at mismatching punctuation; OCR is not truth. Do not blindly replace '
                'O with (), dot with colon, or space with underscore. Pixel/neighbor suggestions are '
                'not approvals. Preserve ambiguity, cancellation, meaningful arrows and code case/numbers. '
                'Use full words and complete geometry inside image 1.'),ensure_ascii=False),VISUAL)
        value=merge_repair(value,patch,requested)
        final,trace=source_audit(p,value,output,plan,client,'continuation_v2_final_audit');traces.append(trace)
    result=evaluate(p,value,final)
    refresh_relations(result)
    result.update(task_id=task['id'],plan_signature=signature(plan),candidate_signature=signature(value),
        initial_extraction=visual,initial_audit=first,audio_context=context,audit_recovery=traces,
        repair_used=bool(requested),repair_requested_ids=sorted(requested),
        initial_discrepancy_diagnostics=initial_diagnostics,
        discrepancy_diagnostics=diagnostics_with_pixels(p,result),
        verification_run='continuation_v2_source_checked',extraction_created=True,
        direct_review_receipts_reused=False)
    # Inspectable package for any later direct review, already in final coordinates.
    p['candidate']=value
    save(output/'prepared'/(task['id']+'.json'),p)
    return result


def prepare(source, reviewed, output, batch_size=8):
    source=source.resolve();reviewed=reviewed.resolve();output=output.resolve()
    if output.exists(): raise ValueError('output_exists_choose_new_folder')
    if not 1<=batch_size<=32: raise ValueError('invalid_batch_size')
    old=check_previous(source); manifest=read(reviewed/'manifest.json')
    for path,expected in manifest['input_hashes'].items():
        if digest_file(path)!=expected: raise ValueError('changed_review_input:'+path)
    if not code_hashes_match(manifest['code_sha256'], digest_file(source_path('ink_discrepancy.py'))):
        raise ValueError('changed_direct_review_code')
    inputs={str(source/'plan.json'):digest_file(source/'plan.json'),str(reviewed/'manifest.json'):digest_file(reviewed/'manifest.json')}
    latest={}; processed=[]; tasks=[]
    for task in old['tasks']:
        result_path=source/'results'/(task['id']+'.json')
        if not result_path.exists():
            t=safe_task(task);tasks.append(t);inputs[t['current_image']]=digest_file(t['current_image']);continue
        r=read(result_path)
        if r['plan_signature']!=signature(old):raise ValueError('stale_previous_result')
        inputs[str(result_path)]=digest_file(result_path);processed.append(task['id']);latest[task['id']]=r
        replacement=reviewed/'results'/(task['id']+'.json')
        if replacement.exists():
            r=read(replacement)
            if r.get('result_version')=='direct_source_review_v1':
                if r.get('candidate_signature')!=signature(r['candidate']):raise ValueError('changed_review_candidate')
            else:
                # Unmodified inherited recovery rows predate candidate signatures
                # on local replay; their exact source receipt hash is authoritative.
                inherited=str(Path(manifest['source'])/'results'/(task['id']+'.json'))
                if digest_file(replacement)!=manifest['input_hashes'].get(inherited):
                    raise ValueError('changed_inherited_review_result')
            inputs[str(replacement)]=digest_file(replacement);latest[task['id']]=r
    admin_path=reviewed/'administrator-review.jsonl';inputs[str(admin_path)]=digest_file(admin_path)
    admin=[json.loads(l) for l in admin_path.read_text().splitlines()]
    pending=[]
    for tid,r in latest.items():
        pending += [dict(task_id=tid,**d) for d in r.get('decisions',[]) if d['status'] in ('held','symbol_observed_meaning_unresolved')]
        pending += [dict(task_id=tid,status='missing_core',**m) for m in r.get('missing_core',[])]
        if not r.get('active_coverage_complete') and not any(x['task_id']==tid for x in pending):
            pending.append(dict(task_id=tid,status='coverage_review_required'))
    output.mkdir(parents=True)
    plan=dict(version=2,created_at=now(),source=str(source),reviewed_source=str(reviewed),
        source_sha256=old['source_sha256'],model=old['model'],tasks=tasks,batch_size=batch_size,
        excluded_processed_ids=processed,earlier_excluded_ids=old.get('skipped_completed_ids',[]),
        inherited_pending=pending,inherited_administrator_queue=admin,input_hashes=inputs,code_hashes=hashes(),
        max_logical_calls_per_task=7,scope='Previously detected unprocessed ink only; no new audio or whole-video detection.',
        direct_review_approvals_for_new_data=False)
    save(output/'plan.json',plan);select_batch(output,plan)
    return report(output)


def check_plan(output):
    p=read(output/'plan.json')
    if not code_hashes_match(p['code_hashes'], hashes()): raise ValueError('code_changed_prepare_new_output')
    for path,expected in p['input_hashes'].items():
        if digest_file(path)!=expected: raise ValueError('changed_input:'+path)
    return p


def report(output):
    plan=read(output/'plan.json');results=[];records=[];pending=copy.deepcopy(plan['inherited_pending'])
    admin={a['id']:a for a in plan['inherited_administrator_queue']};cards=[]
    for task in plan['tasks']:
        path=output/'results'/(task['id']+'.json')
        if not path.exists():continue
        r=read(path)
        if r['plan_signature']!=signature(plan):raise ValueError('stale_result')
        results.append(r);records+=r.get('records',[])
        for a in r.get('administrator_queue',[]):admin[a['id']]=a
        pending += [dict(task_id=task['id'],**d) for d in r.get('decisions',[]) if d['status']=='held']
        pending += [dict(task_id=task['id'],status='missing_core',**m) for m in r.get('missing_core',[])]
        if not r.get('active_coverage_complete'):pending.append(dict(task_id=task['id'],status='review_required'))
        cards.append('<article><h2>'+html.escape(task['id'])+'</h2><pre>'+html.escape(json.dumps({k:r.get(k) for k in
            ('status','changes','decisions','discrepancy_diagnostics','audit_recovery')},ensure_ascii=False,indent=2))+'</pre></article>')
    summary=dict(catalogue_at_start=len(plan['tasks']),processed=len(results),not_processed=len(plan['tasks'])-len(results),
        active_complete=sum(r.get('active_coverage_complete',False) for r in results),
        usable_records=len(records),new_held_items=sum(d['status']=='held' for r in results for d in r.get('decisions',[])),
        inherited_pending=len(plan['inherited_pending']),administrator_entries=len(admin),batch_size=plan['batch_size'],accuracy=None)
    save(output/'summary.json',summary);jsonl(output/'records.jsonl',records);jsonl(output/'pending.jsonl',pending)
    jsonl(output/'administrator-review.jsonl',list(admin.values()))
    (output/'미처리필기_개선검증.html').write_text('<!doctype html><meta charset="utf-8"><title>개선 로직 이어 검증</title>'
        '<style>body{font-family:system-ui;max-width:1100px;margin:30px auto}pre{white-space:pre-wrap}</style>'
        '<h1>개선 로직으로 미처리 필기 이어 검증</h1><p>새 항목에는 이전 직접 검토 승인을 재사용하지 않습니다. '
        '기존 관리자 검토와 기호 의미 미확정은 별도로 유지합니다.</p><pre>'+html.escape(json.dumps(summary,ensure_ascii=False,indent=2))+
        '</pre>'+''.join(cards),encoding='utf-8')
    return summary


def run(output,env_file,python,models,max_calls=60,delay=15,local_only=False):
    if max_calls<1 or delay<15:raise ValueError('invalid_limits')
    with (output/'.run.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);plan=check_plan(output);batch=select_batch(output,plan)
        if not batch['ids']:return report(output)
        data=local_batch(output,plan,batch,python,models)
        if local_only:return dict(local_prepared=len(data['tasks']),batch_ids=batch['ids'],api_requests=0)
        client=None
        try:
            for tid in batch['ids']:
                dest=output/'results'/(tid+'.json')
                if dest.exists():continue # select_batch validated all result signatures.
                if client is None:client=Gemini(output/'api-cache',plan['model'],env_file,max_calls=max_calls,delay=delay)
                try:result=execute(data['tasks'][tid],output,plan,client)
                except Blocked as exc:
                    if str(exc)!='invalid_model_response':raise
                    result=dict(task_id=tid,plan_signature=signature(plan),status='review_required',
                                error=str(exc),active_coverage_complete=False,records=[],decisions=[],changes=[])
                save(dest,result)
                print(json.dumps(dict(task=tid,state=result['status'],requests=client.stats['requests']),ensure_ascii=False),flush=True)
        finally:
            state=dict(at=now(),batch_ids=batch['ids'],api_stats=client.stats if client else {'requests':0},summary=report(output))
            save(output/'run-state.json',state);save(output/'runs'/(now().replace(':','-')+'.json'),state)
    return report(output)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('mode',choices=['prepare','local','run','report'])
    p.add_argument('--source',type=Path,default=ROOT/'outputs/ink-continuation-v1')
    p.add_argument('--reviewed',type=Path,default=ROOT/'outputs/ink-source-review-v1')
    p.add_argument('--output',type=Path,default=OUTPUT);p.add_argument('--batch-size',type=int,default=8)
    p.add_argument('--env-file',type=Path,default=ROOT/'.env');p.add_argument('--max-api-calls',type=int,default=60)
    p.add_argument('--delay',type=float,default=15)
    p.add_argument('--ocr-python',type=Path,default=ROOT/'work/extraction-compare/env/bin/python')
    p.add_argument('--ocr-models',type=Path,default=ROOT/'work/extraction-compare/paddlex/official_models')
    a=p.parse_args();out=a.output.resolve()
    if a.mode=='prepare':result=prepare(a.source,a.reviewed,out,a.batch_size)
    elif a.mode in ('local','run'):result=run(out,a.env_file,a.ocr_python,a.ocr_models,a.max_api_calls,a.delay,a.mode=='local')
    else:check_plan(out);result=report(out)
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
