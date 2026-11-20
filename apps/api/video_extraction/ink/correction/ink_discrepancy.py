"""Offline, source-bound discrepancy resolution; no API or blind OCR rewriting.

Pixel probes are supporting measurements, not OCR ground truth. A release requires
an explicit direct-review receipt for exactly this source/result/candidate.
"""
import argparse
import copy
import difflib
import html
import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from video_extraction.shared.common import digest_file, read, save, jsonl, signature, now
from video_extraction.ink.runner.ink_pipeline import inspect_visual
from video_extraction.ink.correction.ink_recheck import ROOT, ocr_words
from video_extraction.ink.correction.ink_recovery import check_plan as check_recovery

ACCEPTED = {'model_source_checked', 'usable_with_warning', 'source_review_checked'}


def character_differences(observed, ocr):
    """Offsets refer to unchanged strings; case, numbers and spaces are preserved."""
    differences = []
    for op, a, b, c, d in difflib.SequenceMatcher(None, observed, ocr, autojunk=False).get_opcodes():
        if op == 'equal': continue
        x, y = observed[a:b], ocr[c:d]
        if (x, y) in {(':','.'),('.',':'),('()','O'),('()','0'),('O','()'),('0','()'),('_',' '),(' ','_')}:
            category = 'punctuation_shape_confusion'
        elif not x.strip() and not y.strip(): category = 'spacing'
        else: category = 'lexical_numeric_or_other'
        differences.append(dict(observed_span=[a,b], ocr_span=[c,d], observed=x, ocr=y, category=category))
    return differences


def runs(projection):
    out=[]
    for i, v in enumerate(projection):
        if v and (not out or out[-1][1] != i): out.append([i,i+1])
        elif v: out[-1][1]=i+1
    return out


def pixel_probe(path, roi, kind):
    """Native source pixels only. ROI must be supplied, not guessed from text width."""
    with Image.open(path) as im:
        w,h=im.size
        if len(roi)!=4 or not all(isinstance(v,int) for v in roi): raise ValueError('invalid_roi')
        x,y,r,b=roi
        if not 0<=x<r<=w or not 0<=y<b<=h: raise ValueError('roi_outside_source')
        rgb=np.asarray(im.convert('RGB'))[y:b,x:r].astype(np.int16)
    dark=(rgb.max(2)<185)&((rgb.max(2)-rgb.min(2))<80)
    colored=(rgb[:,:,0]>rgb[:,:,1]+45)&(rgb[:,:,0]>rgb[:,:,2]+35)
    rows=runs(dark.sum(1)); cols=runs(dark.sum(0)); hh,ww=dark.shape
    support=False
    if kind=='colon':
        support=(len(rows)==2 and len(cols)==1 and max(t-s for s,t in rows)<=max(3,hh*.35)
                 and rows[1][0]-rows[0][1]>=2 and cols[0][1]-cols[0][0]<=ww*.6)
    elif kind=='parentheses_pair':
        support=(len(cols)==2 and cols[1][0]>cols[0][1]
                 and all(np.count_nonzero(dark[:,a:b].sum(1))>=hh*.65 for a,b in cols))
    elif kind=='underscore':
        support=any(row.sum()>=ww*.65 for row in dark[hh//2:])
    else: raise ValueError('unsupported_probe')
    return dict(kind=kind, source_roi=roi, source_sha256=digest_file(path),
                dark_pixels=int(dark.sum()), colored_pixels=int(colored.sum()),
                row_runs=rows, column_runs=cols,
                state='shape_support_only' if support else 'insufficient_pixel_evidence',
                automatic_release=False, text_rewritten=False)


def symbol_context(path, item_box, view):
    """Suggest paired ink structure; never decide '[' vs a letter or infer meaning."""
    with Image.open(path) as im: rgb=np.asarray(im.convert('RGB')).astype(np.int16)
    h,w=rgb.shape[:2]; a,b,c,d=view['crop_in_source']
    left=(a+item_box['left']/1000*(c-a))*w; top=(b+item_box['top']/1000*(d-b))*h
    right=(a+item_box['right']/1000*(c-a))*w; bottom=(b+item_box['bottom']/1000*(d-b))*h
    iw,ih=right-left,bottom-top
    rect=[max(0,int(left-iw*.5)),max(0,int(top-ih*.5)),min(w,int(right+iw*3)),min(h,int(bottom+ih*4))]
    x,y,r,t=rect; crop=rgb[y:t,x:r]
    ink=((crop[:,:,0]>crop[:,:,1]+45)&(crop[:,:,0]>crop[:,:,2]+35)).astype('uint8')
    _,_,stats,_=cv2.connectedComponentsWithStats(ink,8)
    components=[dict(box=[int(s[0]+x),int(s[1]+y),int(s[0]+s[2]+x),int(s[1]+s[3]+y)],area=int(s[4]))
                for s in stats[1:] if s[4]>=4]
    aligned=[]
    for comp in components:
        q=comp['box']; cy=(q[1]+q[3])/2
        if q[0]>right and abs(cy-(top+bottom)/2)<=ih and .4*ih<=q[3]-q[1]<=2.5*ih:
            aligned.append(comp)
    return dict(context_roi=rect, components=components, aligned_right_components=aligned,
                suggestion='paired_symbol_candidate' if aligned else 'unresolved_symbol',
                exact_symbol=None, meaning=None, automatic_reclassification=False)


def discrepancy_report(package, result):
    if package['view']['crop_in_source']!=result['final_view']['crop_in_source']:
        raise ValueError('ocr_coordinate_alignment_required')
    items={x['id']:x for x in result['candidate']['items']}; diagnostics={}
    for decision in result['decisions']:
        iid=decision['id']
        if decision['status']!='held' or iid not in items: continue
        item=items[iid]; row={}
        if 'ocr_text_conflict' in decision['reasons']:
            words,partial=ocr_words(package['ocr'].get('words',[]),item,result['final_view'])
            text=' '.join(w['text'] for w in words)
            row.update(observed=item['text'], ocr=text, differences=character_differences(item['text'],text),
                       partial_ocr_coverage=partial, next_step='localized_source_review',
                       automatic_release=False)
        if 'unclear_item' in decision['reasons']:
            row['symbol_context']=symbol_context(package['task']['evidence']['selected_frame'],item['box'],result['final_view'])
        diagnostics[iid]=row
    return diagnostics


def refresh_relations(result):
    """Own judgement survives a held target; only usability waits on dependencies."""
    by_id={d['id']:d for d in result['decisions']}
    checks={c['id']:c for c in result['final_audit']['checks']}
    for link in result['candidate']['links']:
        d=by_id[link['id']]; c=checks.get(link['id'],{})
        own=[r for r in d['reasons'] if r!='dependency_unresolved']
        supported=all(c.get(k)=='supported' for k in ('content','geometry','meaning'))
        d['relation_validation']=dict(own_status='checked' if supported and not own else 'unresolved',
                                     target_status='unresolved')
        refs=link['from_ids']+link['to_ids']
        targets=bool(link['from_ids'] and link['to_ids']) and all(by_id.get(i,{}).get('status') in ACCEPTED for i in refs)
        if targets: d['relation_validation']['target_status']='checked'
        # Only previously dependency-blocked relations may be released here.
        if d['status']=='held' and d['reasons']==['dependency_unresolved'] and targets and supported:
            d.update(status='usable_with_warning' if d['warnings'] else 'source_review_checked',reasons=[])
            d['resolution']='dependency_rechecked_after_source_review'


def apply_review(package, previous, receipt):
    """A narrow, version-bound exception; no blanket punctuation whitelist."""
    if signature(previous)!=receipt['result_signature']: raise ValueError('review_result_changed')
    source=package['task']['evidence']['selected_frame']
    if digest_file(source)!=receipt['source_sha256']: raise ValueError('review_source_changed')
    if receipt.get('approval')!='user_authorized_direct_source_review': raise ValueError('review_not_approved')
    result=copy.deepcopy(previous); values={x['id']:x for x in result['candidate']['items']}
    decisions={d['id']:d for d in result['decisions']}; checks={c['id']:c for c in result['final_audit']['checks']}
    result['source_review']=copy.deepcopy(receipt); result['review_changes']=[]
    result['discrepancy_diagnostics']=discrepancy_report(package,previous)
    for entry in receipt['entries']:
        iid=entry['id']; item=values[iid]; d=decisions[iid]; before=copy.deepcopy(item)
        if signature(item)!=entry['item_signature']: raise ValueError('review_item_changed')
        if d['status']!='held': raise ValueError('review_requires_held_item')
        if entry['action']=='release_ocr_false_positive':
            if set(d['reasons'])!={'ocr_text_conflict'}: raise ValueError('additional_unresolved_reason')
            if not all(checks.get(iid,{}).get(k)=='supported' for k in ('content','geometry','meaning')):
                raise ValueError('source_audit_not_supported')
            if item['text']!=entry['observed_text']: raise ValueError('review_text_changed')
            # Require explicit direct observation; probes do not create approval.
            if not entry.get('direct_observation'): raise ValueError('missing_direct_observation')
            d.update(status='usable_with_warning',reasons=[])
            d['warnings'].append('ocr_false_positive_source_reviewed')
        elif entry['action']=='bracket_shape_meaning_unresolved':
            if d['reasons']!=['unclear_item'] or item.get('arrow_points') or item.get('cancelled'):
                raise ValueError('unsafe_symbol_reclassification')
            item.update(kind='bracket',text='',uncertainties=[])
            d.update(status='symbol_observed_meaning_unresolved',reasons=[],unprocessed=['symbol_meaning_unresolved'],
                     warnings=['exact_symbol_and_meaning_unresolved'],representation='observed_bracket_shape')
        else: raise ValueError('unsupported_review_action')
        d['resolution']=entry['action']
        old_effective=next((x for x in previous['effective_inventory']['items'] if x['id']==iid),None)
        result['review_changes'].append(dict(id=iid,before=before,after=copy.deepcopy(item),
            previous_effective=copy.deepcopy(old_effective),before_status='held',after_status=d['status'],
            action=entry['action'],reason=entry['direct_observation']))
    refresh_relations(result)
    newly={d['id'] for d in result['decisions'] if d['status']!='held' and
           next(x for x in previous['decisions'] if x['id']==d['id'])['status']=='held'}
    for link in result['candidate']['links']:
        if link['id'] in newly:
            result['review_changes'].append(dict(id=link['id'],before=copy.deepcopy(link),after=copy.deepcopy(link),
                before_status='held',after_status=decisions[link['id']]['status'],
                action='dependency_rechecked_after_source_review',reason='Own source audit supported; all targets now usable.'))
    rows,flags=inspect_visual(result['candidate'],package['task'],result['final_view'],{'state':'unavailable','words':[]})
    # Old OCR-unavailable flags are not evidence against explicitly source-reviewed items.
    for iid in newly:
        fatal=[v for v in flags.get(iid,[]) if v not in ('ocr_unavailable','dependency_unresolved')]
        if fatal: raise ValueError('new_structure_error:'+iid+':'+str(fatal))
    for row in rows:
        iid=row['local_id']
        if iid not in newly: continue
        d=decisions[iid]; row.update(judgment=d['status'],approved_for_rag=False,content_verified=False,
            representation=d.get('representation','literal_observation'),
            verification=dict(method='assistant_direct_source_review',gold_approved=False,receipt_signature=signature(receipt)),
            policy_findings=dict(blocking=[],warnings=d['warnings'],unprocessed=d['unprocessed']),
            selected_frame=source,selected_frame_seconds=package['task']['evidence'].get('selected_frame_seconds'),
            usable_for_semantic_assertion=d['status'] in ACCEPTED)
        if d['status']=='symbol_observed_meaning_unresolved':
            row.update(observed_shape='bracket_like',exact_symbol=None,meaning=None,
                       original_observation=next(x for x in previous['candidate']['items'] if x['id']==iid))
        row['issues']=[i for i in row['issues'] if i['code']!='geometry_evidence_pending']
        result['records']=[r for r in result['records'] if r['local_id']!=iid]+[row]
    for group in ('items','links'):
        for item in result['candidate'][group]:
            if item['id'] not in newly: continue
            result['effective_inventory'][group]=[x for x in result['effective_inventory'][group] if x['id']!=item['id']]+[copy.deepcopy(item)]
    result['active_coverage_complete']=not any(d['status'] in ('held','symbol_observed_meaning_unresolved') for d in result['decisions']) and not result['missing_core']
    result['visual_review_complete']=not any(d['status']=='held' for d in result['decisions']) and not result['missing_core']
    result['all_review_resolved']=result['active_coverage_complete'] and not result['administrator_queue']
    result['effective_inventory']['complete']=result['all_review_resolved']
    result['status']=('source_review_checked' if result['all_review_resolved'] else
                      'symbol_meaning_unresolved' if any(d['status']=='symbol_observed_meaning_unresolved' for d in result['decisions'])
                      else 'partially_checked')
    result['candidate_signature']=signature(result['candidate'])
    result['source_plan_signature']=previous['plan_signature']
    result['result_version']='direct_source_review_v1'
    result['semantic_pending_ids']=[d['id'] for d in result['decisions'] if d['status']=='symbol_observed_meaning_unresolved']
    result['api_requests']=0
    return result


def build(source, receipts, output):
    """New result version; source results and original images stay unchanged."""
    if output.exists(): raise ValueError('output_exists')
    source=source.resolve(); plan=check_recovery(source); reviews=read(receipts)
    input_hashes={str(receipts.resolve()):digest_file(receipts),str(source/'plan.json'):digest_file(source/'plan.json')}
    results=[]; changes=[]; records=[]; pending=[]; diagnostics={}; released=0; reviewed=0
    allowed={t['id'] for t in plan['tasks']}
    if not set(reviews)<=allowed: raise ValueError('unknown_review_task')
    for task in plan['tasks']:
        path=source/'results'/(task['id']+'.json'); r=read(path)
        if r['plan_signature']!=signature(plan): raise ValueError('stale_source_result')
        input_hashes[str(path)]=digest_file(path)
        if any(d['status']=='held' for d in r['decisions']):
            package=read(task['package']); input_hashes[task['package']]=digest_file(task['package'])
            diagnostics[task['id']]=discrepancy_report(package,r)
        if task['id'] in reviews:
            package=read(task['package']); input_hashes[task['package']]=digest_file(task['package'])
            old_held={d['id'] for d in r['decisions'] if d['status']=='held'}
            r=apply_review(package,r,reviews[task['id']]); diagnostics[task['id']]=r['discrepancy_diagnostics']
            released+=sum(d['id'] in old_held and d['status'] in ACCEPTED for d in r['decisions'])
            reviewed+=sum(d['id'] in old_held and d['status']!='held' for d in r['decisions'])
            for probe in reviews[task['id']].get('probes',[]):
                diagnostics[task['id']].setdefault('pixel_probes',[]).append(pixel_probe(package['task']['evidence']['selected_frame'],probe['roi'],probe['kind']))
            input_hashes[package['task']['evidence']['selected_frame']]=reviews[task['id']]['source_sha256']
        results.append(r); records+=r['records']; changes+=r.get('review_changes',[])
        pending += [dict(task_id=task['id'],**d) for d in r['decisions'] if d['status'] in ('held','symbol_observed_meaning_unresolved')]
    administrators=[json.loads(l) for l in (source/'administrator-review.jsonl').read_text().splitlines()]
    input_hashes[str(source/'administrator-review.jsonl')]=digest_file(source/'administrator-review.jsonl')
    summary=dict(reviewed_items=reviewed,released_false_positive_items=released,
                 symbol_meaning_unresolved=sum(d['status']=='symbol_observed_meaning_unresolved' for d in pending),
                 held_items=sum(d['status']=='held' for d in pending),api_requests=0,
                 administrator_entries=len(administrators),
                 active_complete_regions=sum(r['active_coverage_complete'] for r in results),accuracy=None)
    for r in results: save(output/'results'/(r['task_id']+'.json'),r)
    save(output/'manifest.json',dict(created_at=now(),source=str(source),input_hashes=input_hashes,
         code_sha256=digest_file(__file__),review_scope='source-bound direct review, not general ground truth'))
    save(output/'summary.json',summary);save(output/'diagnostics.json',diagnostics)
    jsonl(output/'records.jsonl',records);jsonl(output/'review-changes.jsonl',changes);jsonl(output/'pending.jsonl',pending)
    jsonl(output/'administrator-review.jsonl',administrators)
    (output/'원본대조_반영결과.html').write_text('<!doctype html><meta charset="utf-8"><title>원본 대조 반영</title>'
        '<style>body{font-family:system-ui;max-width:1000px;margin:40px auto}pre{white-space:pre-wrap}</style>'
        '<h1>원본 직접 대조 반영</h1><p>확인된 오탐 4개 해제. 화면 7은 괄호형 기호로 보존하며 정확한 기호·의미는 미확정입니다. API 0회.</p><pre>'+
        html.escape(json.dumps(dict(summary=summary,changes=changes,pending=pending),ensure_ascii=False,indent=2))+'</pre>',encoding='utf-8')
    return summary


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',type=Path,default=ROOT/'outputs/ink-recovery-v1')
    p.add_argument('--receipts',type=Path,required=True)
    p.add_argument('--output',type=Path,default=ROOT/'outputs/ink-source-review-v1')
    a=p.parse_args();print(json.dumps(build(a.source,a.receipts,a.output),ensure_ascii=False))
