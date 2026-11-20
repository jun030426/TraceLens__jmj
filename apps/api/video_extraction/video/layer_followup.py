"""Continue only frozen deferred regions and narrowly inspect ambiguous code symbols.

prepare/report are offline. Only run constructs an API client. Source results are
immutable; per-batch receipts and API cache make interrupted runs resumable.
"""
from video_extraction._layout import source_path
import argparse
import copy
from video_extraction.shared import file_lock as fcntl
import html
import json
from pathlib import Path
import re
import shutil
import time

from video_extraction.shared.common import digest_file, now, read, save, signature
from video_extraction.shared.gemini import Gemini, Blocked, BOOL, TEXT, STRINGS, obj
from video_extraction.shared.errors import guidance
from video_extraction.video.vision import variants
from video_extraction.video.vision_optimized import chunks, unpack_batch
from video_extraction.video.vision_layers import batch_call, batch_schema, visual_problems, VISUAL_FIELDS
from video_extraction.video.layer_validation import ROOT, DEFAULT_OUTPUT

OUTPUT=ROOT/'outputs/vision-layer-followup'
FOCUS_FRAMES={'frame-00030','frame-00031','frame-00032'}
# Visually located in these three original 1280x720 frames on 2026-10-19.
# Never reuse these coordinates for an uninspected image just because its ID matches.
FOCUS_IMAGE_HASHES={
 'frame-00030':'27362ad01b7cb29bdb2cde5e1bacc35b1ef8812349b0846dbaed36640ebfa497',
 'frame-00031':'25738bf9a850351e190d36db303e55ef1ad0e8afec60e2371c893b7b78cba656',
 'frame-00032':'a5a0a7227057c75f86f354c1d0e48bb2dcb77210821d43fea39f6907614240db',
}
FOCUS_BOXES={'index':[603,397,765,561], 'code_separator':[601,776,732,819],
             'output_separator':[372,687,456,729]}
PATTERNS={
 'index':re.compile(r'(?m)^\s*name\s*=\s*student\[([0o])\][ \t]*$'),
 'code_separator':re.compile(r'(?m)^[ \t]*print\(["\'](-+)["\']\)[ \t]*$'),
 'output_separator':re.compile(r'(?m)^[ \t]*(-{2,})[ \t]*$'),
}
LABELS={'index':'name = student[...]의 인덱스 0 또는 o',
        'code_separator':'코드 print문 안의 구분선', 'output_separator':'출력 상자의 구분선'}
READING=obj({'value':TEXT,'clear':BOOL,'uncertainties':STRINGS,'evidence':TEXT})
CONFIRM=obj({'value_confirmed':BOOL,'boundary_clear':BOOL,'glyphs_clear':BOOL,'reason':TEXT})
FOCUS_PROMPT='''Inspect ORIGINAL source pixels, not what correct Python should say. Image 1 is
the full frame; other images are native crops. For index, return ONLY the literal index character
inside name = student[...], either 0 or o. Compare its shape with total = 0 and other glyphs in THIS
frame; never infer from Python semantics. For code_separator, return ONLY the exact hyphen string
inside the print string literal. For output_separator, return ONLY the exact hyphen string printed
in the output box. Count each glyph; these two separators may differ. Do not copy another frame's
reading or use a conventional divider length. If blur, antialiasing, touching strokes or cropping
prevents certainty, clear=false and explain uncertainty; do not guess. Return every region_id once.
Do not transcribe unrelated lines. DATA:\n'''
CONFIRM_PROMPT='''Independently check each proposed symbol/string against the ORIGINAL frame and
native crop. All hyphens must be individually supported with both endpoints visible; verify exact
count, not approximate length. Distinguish 0 from o by glyph shapes within this frame, not Python
logic. If there is any ambiguity set glyphs_clear=false. Do not treat two agreeing model readings
as pixel evidence. A source mistake must remain unchanged. Return every region_id once. DATA:\n'''


def focus_targets(result):
    targets=[]
    for kind,pattern in PATTERNS.items():
        matches=[]
        for b in result['final_blocks']:
            if (kind=='output_separator')==(b['kind']=='code'):continue
            for m in pattern.finditer(b['text']):
                matches.append({'region_id':kind,'target_id':b['id'],'bbox':b['bbox'],
                                'label':LABELS[kind],'old_value':m.group(1),'span':list(m.span(1))})
        if len(matches)!=1:raise ValueError('ambiguous_focus_anchor:'+result['frame_id']+':'+kind)
        targets+=matches
    return targets


def prepare(source,out):
    source=Path(source).resolve();out=Path(out).resolve()
    if source==out or source in out.parents or out in source.parents:
        raise ValueError('followup_output_must_be_separate')
    original=read(source/'validation-config.json')
    if read(source/'run-state.json')['state']!='complete':raise ValueError('source_validation_not_complete')
    inputs=[source/'validation-config.json'];tasks=[];visual_count=0;focus_count=0
    for fid in original['selected_ids']:
        result_path=source/'vision'/fid/'result.json';image=source/'frames'/f'{fid}.png'
        r=read(result_path);inputs += [result_path,image]
        if digest_file(image)!=original['frame_sha256'][fid]:raise ValueError('source_frame_changed:'+fid)
        ids=[g['region_id'] for g in r['deferred_regions']]
        if len(ids)!=len(set(ids)):raise ValueError('duplicate_deferred_ids')
        for g in r['deferred_regions']:
            if g['layer']!='visual' or g['target_id']=='NEW':raise ValueError('unsupported_deferred_target')
            if sum(v['id']==g['target_id'] for v in r['visuals'])!=1:raise ValueError('missing_deferred_visual')
            matched=[h for h in r['holds'] if h['reason']=='region_budget' and h.get('layer')=='visual'
                     and h.get('region',{}).get('region_id')==g['region_id'] and h.get('target_id')==g['target_id']]
            if len(matched)!=1:raise ValueError('deferred_hold_mismatch')
        for n,batch in enumerate(chunks(r['deferred_regions'],3),1):
            tasks.append({'id':f'{fid}-visual-{n:02}','frame_id':fid,'kind':'visual','regions':batch})
            visual_count+=len(batch)
        if fid in FOCUS_FRAMES:
            targets=focus_targets(r);focus_count+=len(targets)
            if digest_file(image)!=FOCUS_IMAGE_HASHES[fid]:raise ValueError('focus_image_needs_reinspection:'+fid)
            for target in targets:
                target['bbox']=FOCUS_BOXES[target['region_id']]
                target['crop_basis']='visually_located_in_hash_bound_original_frame'
            tasks.append({'id':f'{fid}-symbols','frame_id':fid,'kind':'symbols','regions':targets})
    if set(original['selected_ids']) & FOCUS_FRAMES != FOCUS_FRAMES:raise ValueError('missing_focus_frames')
    dependencies=['layer_followup.py','vision_layers.py','vision_optimized.py','vision.py','gemini.py','common.py']
    config={'version':1,'source':str(source),'model':original['model'],'selected_ids':original['selected_ids'],
            'source_hashes':{str(p.relative_to(source)):digest_file(p) for p in inputs},
            'code_hashes':{f:digest_file(source_path(f)) for f in dependencies},
            'visual_targets':visual_count,'symbol_targets':focus_count,'tasks':tasks}
    path=out/'plan.json'
    if path.exists() and read(path)!=config:raise ValueError('followup_inputs_changed_use_another_output')
    if not path.exists() and any(out.glob('receipts/*.json')):raise ValueError('unbound_receipts')
    out.mkdir(parents=True,exist_ok=True)
    for fid in config['selected_ids']:
        dest=out/'frames'/f'{fid}.png';dest.parent.mkdir(exist_ok=True)
        if not dest.exists():shutil.copy2(source/'frames'/f'{fid}.png',dest)
        if digest_file(dest)!=config['source_hashes'][f'frames/{fid}.png']:raise ValueError('copied_frame_changed')
    save(path,config);return config


def prepared_regions(task,out):
    image=out/'frames'/f'{task["frame_id"]}.png';folder=out/'evidence'/task['id'];folder.mkdir(parents=True,exist_ok=True)
    rows=[]
    for n,g in enumerate(task['regions'],1):
        native,_,_,_=variants(image,g['bbox'],folder,n)
        rows.append({**copy.deepcopy(g),'native':native})
    return image,rows


def passes(v):
    return v['decision'] in ('accept','unchanged') and all(v[k] is True for k in
            ('source_clear','all_changes_visible','same_region')) and v['source_conflict'] is False


def review_visuals(task,out,base,client):
    image,batch=prepared_regions(task,out);blocks=base['final_blocks']
    byid={v['id']:v for v in base['visuals']}
    for i in batch:i['before']=copy.deepcopy(byid[i['target_id']])
    try:readings=batch_call(client,'followup_visual_read',image,batch,'visual',blocks)
    except ValueError:return [{'region_id':i['region_id'],'target_id':i['target_id'],'status':'needs_review','reason':'invalid_read_mapping'} for i in batch]
    outcomes={};ready=[]
    for i in batch:
        r=readings[i['region_id']];i['reading']=r;problems=visual_problems(r,blocks)
        item={'region_id':i['region_id'],'target_id':i['target_id'],'reading':r,
              'evidence':str(i['native'].relative_to(out))}
        outcomes[i['region_id']]=item
        if not r['readable'] or r['uncertainties'] or r['source_conflicts'] or problems:
            item.update(status='needs_review',reason='reread_uncertain',problems=problems)
        else:ready.append(i)
    if ready:
        try:verified=batch_call(client,'followup_visual_verify',image,ready,'visual',blocks,True)
        except ValueError:
            for i in ready:outcomes[i['region_id']].update(status='needs_review',reason='invalid_verify_mapping')
        else:
            for i in ready:
                v=verified[i['region_id']];item=outcomes[i['region_id']];item['verification']=v
                if not passes(v):item.update(status='needs_review',reason='verification_hold');continue
                after=copy.deepcopy(i['before'])
                if v['decision']=='accept':
                    after.update(kind=i['reading']['kind'],**{k:i['reading'][k] for k in VISUAL_FIELDS})
                if visual_problems(after,blocks):item.update(status='needs_review',reason='unresolved_visual');continue
                item.update(status='verified',after=after)
    return [outcomes[i['region_id']] for i in batch]


def review_symbols(task,out,base,client):
    image,batch=prepared_regions(task,out)
    # Blind reads receive no previous transcription, old value, other frame or other read.
    targets=[{'region_id':i['region_id'],'label':i['label'],'bbox':i['bbox'],'crop_image':n}
             for n,i in enumerate(batch,2)]
    images=[image]+[i['native'] for i in batch];expected=[i['region_id'] for i in batch]
    reads=[]
    try:
        for stage in ('a','b'):
            raw=client.call('followup_symbol_read_'+stage,images,FOCUS_PROMPT+json.dumps({'targets':targets},ensure_ascii=False),batch_schema('reading',READING))
            reads.append(unpack_batch(raw,expected,'reading'))
    except ValueError:return [{'region_id':i['region_id'],'target_id':i['target_id'],'status':'needs_review','reason':'invalid_symbol_mapping'} for i in batch]
    outcomes=[];ready=[]
    for i in batch:
        a,b=[r[i['region_id']] for r in reads];value=a['value']
        valid=value in ('0','o') if i['region_id']=='index' else bool(re.fullmatch('-{1,120}',value))
        item={k:copy.deepcopy(i[k]) for k in ('region_id','target_id','old_value','span','label')}
        item.update(readings=[a,b],evidence=str(i['native'].relative_to(out)))
        outcomes.append(item)
        if not valid or value!=b['value'] or not all(r['clear'] and not r['uncertainties'] for r in (a,b)):
            item.update(status='needs_review',reason='symbol_unclear_or_disagrees')
        else:item['value']=value;ready.append(item)
    if ready:
        # Keep image numbering unchanged even if only a subset is ready.
        data=[{**targets[expected.index(i['region_id'])],'value':i['value']} for i in ready]
        try:
            raw=client.call('followup_symbol_verify',images,CONFIRM_PROMPT+json.dumps({'targets':data},ensure_ascii=False),batch_schema('verification',CONFIRM))
            verified=unpack_batch(raw,[i['region_id'] for i in ready],'verification')
        except ValueError:
            for i in ready:i.update(status='needs_review',reason='invalid_symbol_verify_mapping')
        else:
            for i in ready:
                v=verified[i['region_id']];i['verification']=v
                if all(v[k] is True for k in ('value_confirmed','boundary_clear','glyphs_clear')):
                    i.update(status='verified',hyphen_count=len(i['value']) if i['region_id']!='index' else None)
                else:i.update(status='needs_review',reason='symbol_verification_hold')
    return outcomes


def receipt_path(out,task):return out/'receipts'/(task['id']+'.json')


def execute_task(task,out,config,client):
    path=receipt_path(out,task);sig=signature({'plan':config,'task':task['id']})
    if path.exists():
        receipt=read(path)
        if receipt.get('signature')!=sig:raise ValueError('receipt_signature_mismatch')
        return receipt
    base=read(Path(config['source'])/'vision'/task['frame_id']/'result.json')
    outcomes=(review_visuals if task['kind']=='visual' else review_symbols)(task,out,base,client)
    if [i['region_id'] for i in outcomes]!=[i['region_id'] for i in task['regions']]:raise ValueError('incomplete_outcomes')
    receipt={'signature':sig,'task_id':task['id'],'kind':task['kind'],'frame_id':task['frame_id'],
             'outcomes':outcomes,'completed_at':now()}
    save(path,receipt);return receipt


def merge_frame(base,receipts,tasks):
    r=copy.deepcopy(base);r['parent_signature']=r.pop('signature');r['followup']={'visual_checks':[],'symbol_checks':[]}
    r['followup']['corrections']=[]
    replacements={};checked=set();verified=set();symbol_results=[]
    for receipt in receipts:
        for row in receipt['outcomes']:
            if receipt['kind']=='visual':
                r['followup']['visual_checks'].append(row);key=(row['region_id'],row['target_id']);checked.add(key)
                if row['status']=='verified':
                    verified.add(key);replacements[row['target_id']]=row['after']
                    before=next(v for v in base['visuals'] if v['id']==row['target_id'])
                    if before!=row['after']:
                        r['followup']['corrections'].append({'layer':'visual','target_id':row['target_id'],
                            'before':before,'after':row['after'],'evidence':row.get('evidence')})
                else:r['holds'].append({'layer':'visual','target_id':row['target_id'],'region_id':row['region_id'],'reason':'followup_'+row['reason']})
            else:symbol_results.append(row)
    # Retire only matching budget holds; failed checks acquire explicit unresolved holds above.
    r['holds']=[h for h in r['holds'] if not (h['reason']=='region_budget' and h.get('layer')=='visual' and
        (h.get('region',{}).get('region_id'),h.get('target_id')) in checked)]
    r['deferred_regions']=[g for g in r['deferred_regions'] if (g['region_id'],g['target_id']) not in checked]
    r['visuals']=[replacements.get(v['id'],v) for v in r['visuals']]
    # Apply only verified character spans, in reverse order, preserving all other bytes.
    for b in r['final_blocks']:
        rows=[i for i in symbol_results if i['target_id']==b['id'] and i['status']=='verified']
        for item in sorted(rows,key=lambda x:x['span'][0],reverse=True):
            start,end=item['span']
            if b['text'][start:end]!=item['old_value']:raise ValueError('symbol_anchor_changed')
            b['text']=b['text'][:start]+item['value']+b['text'][end:]
            if item['old_value']!=item['value']:
                r['followup']['corrections'].append({'layer':'text','target_id':b['id'],
                    'region_id':item['region_id'],'before':item['old_value'],'after':item['value'],
                    'original_span':item['span'],'evidence':item.get('evidence')})
    r['followup']['symbol_checks']=symbol_results
    completed_symbols={i['region_id'] for i in symbol_results}
    for task in tasks:
        if task['kind']=='symbols':
            for target in task['regions']:
                if target['region_id'] not in completed_symbols:
                    r['holds'].append({'layer':'text','target_id':target['target_id'],'reason':'symbol_check_pending','region_id':target['region_id']})
    for item in symbol_results:
        if item['status']!='verified':r['holds'].append({'layer':'text','target_id':item['target_id'],'region_id':item['region_id'],'reason':item['reason']})
    # Existing non-budget holds remain: a narrow symbol check does not certify the whole block.
    r['text']='\n\n'.join(b['text'] for b in r['final_blocks'])
    r['status']='needs_review' if r['holds'] else 'auto_repaired' if r['followup']['corrections'] else 'auto_checked'
    r['followup']['changed_items']=len(r['followup']['corrections'])
    r['followup']['visual_verified']=len(verified);r['followup']['visual_reviewed']=len(checked)
    r['signature']=signature({'parent':r['parent_signature'],'receipts':receipts,'tasks':tasks})
    return r


def render(out,config,state):
    e=html.escape;cards=[];processed=verified=0;symbols=[];all_holds=0;pending=0;coordinate_reviews=[]
    pixel_review=read(out/'pixel-review.json') if (out/'pixel-review.json').exists() else None
    symbol_review=read(out/'symbol-review.json') if (out/'symbol-review.json').exists() else None
    bbox_review=read(out/'bbox-review.json') if (out/'bbox-review.json').exists() else None
    for fid in config['selected_ids']:
        base=read(Path(config['source'])/'vision'/fid/'result.json')
        tasks=[t for t in config['tasks'] if t['frame_id']==fid]
        receipts=[]
        for task in tasks:
            p=receipt_path(out,task)
            if p.exists():
                record=read(p)
                if record.get('signature')!=signature({'plan':config,'task':task['id']}):raise ValueError('receipt_signature_mismatch')
                receipts.append(record)
        r=merge_frame(base,receipts,tasks)
        if pixel_review:
            from video_extraction.video.separator_pixels import apply_review
            r=apply_review(r,pixel_review,config,out)
        if symbol_review:
            from video_extraction.video.symbol_review import apply_review
            r=apply_review(r,symbol_review,config,out)
        if bbox_review:
            from video_extraction.video.bbox_review import apply_review
            r=apply_review(r,bbox_review,config,out)
        coordinate_reviews.extend(r['followup'].get('coordinate_reviews',[]))
        save(out/'vision'/fid/'result.json',r)
        processed+=r['followup']['visual_reviewed'];verified+=r['followup']['visual_verified']
        all_holds+=len(r['holds']);pending+=len(r['deferred_regions'])
        symbols.extend({'frame_id':fid,**i} for i in r['followup']['symbol_checks'])
        detail=e(json.dumps(r['followup'],ensure_ascii=False,indent=2))
        cards.append(f'<details><summary>{fid} · {e(r["status"])} · 미처리 {len(r["deferred_regions"])} · 보류 {len(r["holds"])}</summary>'
            f'<img src="frames/{fid}.png" alt="원본 {fid}"><h3>추가 검토 기록</h3><pre>{detail}</pre>'
            f'<h3>보류 사항</h3><pre>{e(json.dumps(r["holds"],ensure_ascii=False,indent=2))}</pre>'
            f'<h3>병합된 본문</h3><pre>{e(r["text"])}</pre></details>')
    report={'state':state,'visual_reviewed':processed,'visual_verified':verified,'visual_total':config['visual_targets'],
            'visual_pending':pending,'symbol_reviewed':len(symbols),'symbol_total':config['symbol_targets'],
            'symbols':symbols,'remaining_hold_records':all_holds,
            'coordinate_reviews':coordinate_reviews,
            'pixel_verified':sum(s.get('method')=='native_pixel_dash_runs_v1' and s['status']=='verified' for s in symbols),
            'note':'Pending is unprocessed, needs_review is processed but unresolved. Same-model agreement is not independent ground truth.'}
    save(out/'summary.json',report)
    symbol_rows=''.join(f'<tr><td>{s["frame_id"]}</td><td>{e(s.get("label",s["region_id"]))}</td><td>{e(s.get("old_value",""))}</td>'
        f'<td>{e(s.get("value","미확정"))}</td><td>{e(s.get("context_candidate",{}).get("value","—"))}</td>'
        f'<td>{s.get("hyphen_count") or "—"}</td><td>{e(s["status"])}</td></tr>' for s in symbols)
    page=f'''<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>미검증 후속 검토</title>
<style>body{{max-width:1100px;margin:40px auto;padding:20px;font:16px/1.7 system-ui;color:#203040;background:#f4f7fa}}details,header{{padding:18px;background:white;border:1px solid #ccd6df;margin:16px 0}}summary{{cursor:pointer}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;font-size:13px}}img{{max-width:100%}}td,th{{border:1px solid #ccd6df;padding:8px}}table{{border-collapse:collapse;width:100%}}</style>
<header><h1>미검증 54개·코드 기호 후속 검토</h1><b>{e(state['state'])}</b><p>{e(state.get('reason',''))}</p>
<p>그림·필기 처리 {processed}/{config['visual_targets']} · 검증 통과 {verified} · 미처리 {pending}<br>기호 검사 처리 {len(symbols)}/{config['symbol_targets']} · 남은 보류 기록 {all_holds}</p>
<p>원래 결과와 API 판독 기록은 보존합니다. 구분선의 픽셀 검토 기록이 있으면 원본의 선 조각을 여러 밝기 기준으로 센 결과를 우선 적용합니다. 픽셀 검토 통과: {report['pixel_verified']}곳. 계산이 불안정하면 보류합니다. 0/o 판독은 픽셀 개수 검사의 대상이 아니며, 기호 일부의 통과로 기존 코드 전체 보류를 해제하지 않습니다. API 판독 일치는 정답을 보장하지 않습니다.</p></header>
<h2>기호별 결과</h2><p>문맥상 보정 후보는 원본 판독 확정값이 아니며 본문에 자동 적용하지 않습니다. 0/o가 보류된 본문에는 이전 전사 문자가 남아 있으므로 해당 문자를 확정값으로 사용하지 마세요.</p><table><tr><th>화면</th><th>대상</th><th>이전 값</th><th>판독 결과</th><th>문맥상 보정 후보 (미적용)</th><th>하이픈 수</th><th>상태</th></tr>{symbol_rows}</table>
<p><a href="summary.json">요약 JSON</a> · <a href="plan.json">실행 대상</a></p>{''.join(cards)}</html>'''
    (out/'미검증_후속검토.html').write_text(page,encoding='utf-8');return report


def main():
    ap=argparse.ArgumentParser();ap.add_argument('mode',choices=['prepare','run','report'])
    ap.add_argument('--source',type=Path,default=DEFAULT_OUTPUT);ap.add_argument('--output',type=Path,default=OUTPUT)
    ap.add_argument('--env-file',type=Path,default=ROOT/'.env');ap.add_argument('--delay',type=float,default=15)
    ap.add_argument('--max-api-calls',type=int,default=100);args=ap.parse_args()
    if args.delay<0 or args.max_api_calls<0:raise ValueError('invalid_limits')
    out=args.output.resolve()
    # Validate placement before making lock directories.
    src=args.source.resolve()
    if src==out or src in out.parents or out in src.parents:raise ValueError('output_must_be_separate')
    out.mkdir(parents=True,exist_ok=True)
    with (out/'.followup.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:print('후속 검토가 이미 실행 중입니다.');return 2
        if args.mode=='report' and (out/'plan.json').exists():
            from video_extraction.video.separator_pixels import load_frozen_plan
            config=load_frozen_plan(out)
        else:config=prepare(src,out)
        state_path=out/'run-state.json'
        state=read(state_path) if state_path.exists() else {'state':'prepared','runs':[]}
        if args.mode!='run':
            save(state_path,state);report=render(out,config,state)
            print(json.dumps({k:report[k] for k in ('visual_total','symbol_total','visual_reviewed','symbol_reviewed')},ensure_ascii=False));return 0
        client=Gemini(out/'api-cache',config['model'],args.env_file,args.max_api_calls,args.delay)
        started=time.monotonic();record={'started_at':now()};state.update(state='running',reason='');code=0
        save(state_path,state)
        try:
            for task in config['tasks']:
                cached=receipt_path(out,task).exists();execute_task(task,out,config,client)
                report=render(out,config,state)
                print(json.dumps({'task':task['id'],'reused':cached,'visual_reviewed':report['visual_reviewed'],
                    'visual_total':config['visual_targets'],'symbol_reviewed':report['symbol_reviewed'],
                    'symbol_total':config['symbol_targets'],'requests':client.stats['requests']},ensure_ascii=False),flush=True)
            state['state']='complete_with_review' if report['remaining_hold_records'] else 'complete'
        except Blocked as exc:
            state.update(state='blocked',reason=str(exc),detail=exc.detail);code=2;print(guidance(str(exc)),flush=True)
        except KeyboardInterrupt:state.update(state='interrupted',reason='resume_same_command');code=130
        except Exception as exc:
            state.update(state='failed',reason=f'{type(exc).__name__}: {str(exc)[:300]}');code=1;raise
        finally:
            record.update(ended_at=now(),seconds=time.monotonic()-started,api=client.stats,state=state['state'])
            state['runs'].append(record);save(state_path,state);render(out,config,state)
        print(json.dumps({'state':state['state'],'report':str(out/'미검증_후속검토.html')},ensure_ascii=False),flush=True);return code


if __name__=='__main__':raise SystemExit(main())
