"""Frozen-input comparison. Offline replay is never reported as new model inference.

local: replay existing successful API cache read-only and calculate a call plan.
run:   execute optimized extraction with an independent cache; resume on interruption.
report: render recorded results. No source job or RAG export is modified.
"""
from video_extraction._layout import PROJECT_ROOT
import argparse
from collections import Counter
import copy
import difflib
from video_extraction.shared import file_lock as fcntl
import html
import json
from pathlib import Path
import re
import shutil
import time
import unicodedata

from video_extraction.shared.common import digest_file, now, read, save, signature, validate
from video_extraction.shared.errors import guidance
from video_extraction.shared.gemini import Blocked, Gemini, SYSTEM
from video_extraction.video.vision import process_frame
from video_extraction.video.vision_optimized import process_frame_optimized, pixels, compare_pixels, reuse_blocks, regions_for, chunks

ROOT=PROJECT_ROOT
DEFAULT_JOB=ROOT/'outputs/video-extraction/f2bbd01de9a3e78d-f9a29e713f86'
DEFAULT_OUT=ROOT/'outputs/vision-optimization'


class CacheOnly:
    """Never calls the network and never writes the source API cache."""
    def __init__(self,cache,model):self.cache=cache;self.model=model;self.trace=[]
    def call(self,stage,images,prompt,schema):
        sig=signature({'version':2,'model':self.model,'system':SYSTEM,'stage':stage,
                       'images':[digest_file(p) for p in images],'prompt':prompt,'schema':schema})
        path=self.cache/(sig+'.json')
        if not path.exists():raise RuntimeError('baseline_cache_missing:'+stage+':'+sig)
        cached=read(path)
        if cached['signature']!=sig:raise ValueError('cache_signature_mismatch')
        parsed=validate(cached['parsed'],schema)
        crop=next((re.search(r'crop-(\d+)',p.name).group(1) for p in images if re.search(r'crop-(\d+)',p.name)),None)
        self.trace.append({'stage':stage,'signature':sig,'seconds':cached['seconds'],
                           'crop_number':int(crop) if crop else None,'parsed':parsed})
        return copy.deepcopy(parsed)


def link_inputs(src,dest,frames):
    for f in frames:
        target=dest/f['path'];target.parent.mkdir(parents=True,exist_ok=True)
        if not target.exists():shutil.copy2(src/f['path'],target)
        elif digest_file(target)!=digest_file(src/f['path']):raise ValueError('copied_input_changed:'+f['id'])


def validate_frozen(out,manifest):
    if digest_file(out/'inputs/speech_segments.jsonl')!=manifest['speech_sha256']:
        raise ValueError('frozen_speech_changed')
    if signature(read(out/'baseline/results.json'))!=manifest['baseline_sha256']:
        raise ValueError('frozen_baseline_changed')
    for f in read(out/'inputs/frames.json'):
        if digest_file(out/'inputs'/f['path'])!=manifest['frame_sha256'][f['id']]:
            raise ValueError('frozen_frame_changed:'+f['id'])


def freeze(job,out):
    path=out/'manifest.json'
    if path.exists():return read(path)
    state=read(job/'state.json');frames=read(job/'frames.json')
    selected=[f['id'] for f in frames if (job/'vision'/f['id']/'result.json').exists()]
    if not selected:raise ValueError('no_completed_baseline_frames')
    link_inputs(job,out/'inputs',frames)
    save(out/'inputs/frames.json',frames)
    shutil.copy2(job/'speech_segments.jsonl',out/'inputs/speech_segments.jsonl')
    baseline={fid:read(job/'vision'/fid/'result.json') for fid in selected}
    save(out/'baseline/results.json',baseline)
    manifest={'created_at':now(),'source_job':str(job.resolve()),'model':state['config']['gemini_model'],
       'max_regions':state['config']['max_regions'],'frames':len(frames),'selected_ids':selected,
       'source_sha256':state['source_sha256'],'speech_sha256':digest_file(job/'speech_segments.jsonl'),
       'frame_sha256':{f['id']:digest_file(job/f['path']) for f in frames},
       'baseline_sha256':signature(baseline),'original_last_run':state['runs'][-1],
       'note':'Snapshot includes completed baseline frames only; unfinished frame calls excluded from paired comparison.'}
    save(path,manifest);return manifest


def baseline_replay(out,manifest,frames,segments):
    trace_path=out/'baseline/trace.json'
    if trace_path.exists():return read(trace_path)
    work=out/'baseline/replay';link_inputs(out/'inputs',work,frames)
    client=CacheOnly(Path(manifest['source_job'])/'api-cache',manifest['model'])
    baseline=read(out/'baseline/results.json');traces={};started=time.monotonic()
    for f in frames:
        if f['id'] not in baseline:continue
        # This dedicated replay folder is disposable derived data; source results are untouched.
        result_path=work/'vision'/f['id']/'result.json'
        if result_path.exists():result_path.unlink()
        begin=len(client.trace)
        r=process_frame(f,frames,segments,work,client,manifest['max_regions'])
        if r['text']!=baseline[f['id']]['text'] or r['holds']!=baseline[f['id']]['holds']:
            raise ValueError('baseline_replay_changed:'+f['id'])
        traces[f['id']]=client.trace[begin:]
    value={'frames':traces,'local_replay_seconds':time.monotonic()-started,
           'note':'seconds inside each API record are historic response time; local_replay_seconds is NOT inference time.'}
    save(trace_path,value);return value


def region_key(item):return signature(item['region'])


def plan_frame(result,prior,a,b,trace,max_regions):
    scene=compare_pixels(a,b) if a is not None else None
    if scene and scene['exact']:
        return {'scene':scene,'reuse':[],'old_calls':len(trace),'planned_calls':0,'max_successful_calls':0,'exact_reuse':True}
    reused=reuse_blocks(result['original'],result['audit'],prior,a,b) if prior else []
    regions,holds=regions_for(result['original'],result['audit'],reused,max_regions)
    old_regions,_=regions_for(result['original'],result['audit'],[],max_regions)
    old_numbers={region_key(i):i['number'] for i in old_regions}
    calls=2;unknown=0
    for batch in chunks(regions,3):
        calls+=1;weak=False;ready=False
        for item in batch:
            number=old_numbers.get(region_key(item))
            rows=[r for r in trace if r['crop_number']==number] if number is not None else []
            if not rows:
                unknown+=1;weak=True;ready=True
            else:
                weak=weak or any(r['stage']=='crop_read_enhanced' for r in rows)
                ready=ready or any(r['stage']=='verify' for r in rows)
        calls+=int(weak)+int(ready)
    return {'scene':scene,'reuse':reused,'old_calls':len(trace),'planned_calls':calls,
            'max_successful_calls':2+3*len(chunks(regions,3)),
            'regions':len(regions),'newly_in_budget_regions':unknown,'budget_holds':holds,
            'note':'Call plan assumes old model decisions; batching can change those decisions and retry counts.'}


def compact(text):return re.sub(r'\s+','',unicodedata.normalize('NFC',text))


def reference_checks(out,baseline,optimized):
    p=out/'reference.json'
    if not p.exists():return {'available':False}
    reference=read(p);checks=[]
    for row in reference['checks']:
        fid=row['frame_id'];expected=compact(row['expected'])
        old=expected in compact(baseline[fid]['text'])
        new=expected in compact(optimized[fid]['text']) if fid in optimized else None
        checks.append({**row,'baseline_present':old,'optimized_present':new,
                       'regression':old and new is False})
    done=[r for r in checks if r['optimized_present'] is not None]
    return {'available':True,'total':len(checks),'baseline_present':sum(r['baseline_present'] for r in checks),
            'evaluated_new':len(done),'optimized_present':sum(r['optimized_present'] for r in done) if done else None,
            'regressions':sum(r['regression'] for r in done) if done else None,'checks':checks,
            'note':'Limited visible snippet presence checks, not whole-frame accuracy. Extra false text and diagram relationships require review.'}


def local(out,manifest):
    started=time.monotonic();frames=read(out/'inputs/frames.json')
    segments=[json.loads(s) for s in (out/'inputs/speech_segments.jsonl').read_text().splitlines()]
    baseline=read(out/'baseline/results.json')
    trace=baseline_replay(out,manifest,frames,segments)
    rows={};prior=None;previous_pixels=None;exact=0;near=0
    for f in frames:
        b=pixels(out/'inputs'/f['path'])
        if previous_pixels is not None:
            comparison=compare_pixels(previous_pixels,b);exact+=comparison['exact'];near+=comparison['same_scene']
        if f['id'] in baseline:
            rows[f['id']]=plan_frame(baseline[f['id']],prior,previous_pixels,b,
                                    trace['frames'][f['id']],manifest['max_regions'])
            prior=baseline[f['id']]
        else:prior=None
        previous_pixels=b
    calls=[c for cs in trace['frames'].values() for c in cs]
    old_count=len(calls);new_count=sum(r['planned_calls'] for r in rows.values())
    # Same configured request-start gap; excludes parsing, disk I/O, failures and pauses.
    paced=sum(max(15,c['seconds']) for c in calls[:-1])+calls[-1]['seconds']
    report={'created_at':now(),'frames_preserved':len(frames),'completed_baseline_frames':len(rows),
       'all_frame_exact_adjacent_pairs':exact,'all_frame_near_adjacent_pairs':near,
       'same_scene_is_not_skipped':True,'reuse_candidates':sum(len(r['reuse']) for r in rows.values()),
       'old_successful_calls':old_count,'old_stages':dict(Counter(c['stage'] for c in calls)),
       'old_recorded_response_seconds':sum(c['seconds'] for c in calls),
       'old_paced_schedule_seconds':paced,'planned_calls':new_count,
       'max_successful_calls_if_all_batches_need_enhancement':sum(r['max_successful_calls'] for r in rows.values()),
       'planned_call_reduction_percent':100*(1-new_count/old_count),
       'new_minimum_start_gap_seconds':max(0,new_count-1)*15,
       'local_analysis_seconds':time.monotonic()-started,'frames':rows,
       'new_inference_time_seconds':None,'new_accuracy':None,
       'note':'The new call count is a plan from cached old decisions, not measured new API performance. No total speedup or accuracy claim.'}
    save(out/'local-comparison.json',report);render(out);return report


def render(out):
    manifest=read(out/'manifest.json');plan=read(out/'local-comparison.json')
    baseline=read(out/'baseline/results.json');optimized={}
    for fid in manifest['selected_ids']:
        p=out/'optimized/vision'/fid/'result.json'
        if p.exists():optimized[fid]=read(p)
    state=read(out/'run-state.json') if (out/'run-state.json').exists() else {'state':'not_started','reason':'fresh_api_test_pending'}
    refs=reference_checks(out,baseline,optimized)
    validation=read(out/'validation.json') if (out/'validation.json').exists() else {}
    new_present=refs.get('optimized_present') if refs.get('evaluated_new') else '미측정'
    new_regressions=refs.get('regressions') if refs.get('evaluated_new') else '미측정'
    comparison={'created_at':now(),'state':state,'local':plan,'reference_checks':refs,
       'new_completed_frames':len(optimized),'paired_frames':[],'human_accuracy_review':'pending'}
    details=[]
    for fid in manifest['selected_ids']:
        old=baseline[fid];new=optimized.get(fid);p=plan['frames'][fid]
        pair={'frame_id':fid,'baseline_holds':len(old['holds']),'baseline_changes':old['changed_blocks'],
              'optimized_holds':len(new['holds']) if new else None,
              'optimized_changes':new['changed_blocks'] if new else None,
              'text_equal':new['text']==old['text'] if new else None}
        comparison['paired_frames'].append(pair)
        diff='\n'.join(difflib.unified_diff(old['text'].splitlines(),new['text'].splitlines(),fromfile='기존',tofile='개선',lineterm='')) if new else '새 Gemini 실행 대기'
        details.append(f'<details><summary>{fid} · {old["frame_time_seconds"]:g}초 · 기존 {p["old_calls"]}회 / 계획 {p["planned_calls"]}회 · 검토 재사용 후보 {len(p["reuse"])}개</summary>'
           f'<img loading="lazy" src="inputs/frames/{fid}.png" alt="원본 {fid}"><div class="cols"><div><h3>기존 추출</h3><pre>{html.escape(old["text"])}</pre></div>'
           f'<div><h3>개선 추출</h3><pre>{html.escape(new["text"] if new else "아직 실행하지 않았습니다.")}</pre></div></div><h3>내용 차이 — 정답 판정 아님</h3><pre>{html.escape(diff)}</pre></details>')
    save(out/'comparison.json',comparison)
    final_comparable=state.get('state')=='complete' and len(optimized)==len(baseline)
    actual=f'{state.get("active_elapsed_seconds",0)/60:.1f}분 (실행 누적, 중단 대기 제외)' if final_comparable else '아직 측정 완료 안 됨'
    e=html.escape
    page=f'''<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>화면 추출 최적화 비교</title>
<style>body{{max-width:1150px;margin:40px auto;padding:0 22px;font:16px/1.7 -apple-system,BlinkMacSystemFont,sans-serif;color:#192b3a;background:#f7f9fb}}h1{{font-size:31px}}table{{border-collapse:collapse;width:100%;background:white}}td,th{{border:1px solid #d8e0e6;padding:12px;text-align:left}}.notice{{padding:18px;background:#fff0cf;border-left:5px solid #c17d00}}details{{margin:18px 0;background:white;border:1px solid #d8e0e6;padding:16px}}summary{{cursor:pointer;font-weight:600}}img{{max-width:100%;height:auto}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:#eef2f5;padding:15px;font-size:13px}}.cols{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}@media(max-width:700px){{.cols{{grid-template-columns:1fr}}}}</style>
<h1>화면 추출 최적화 비교</h1><p>같은 원본 · 같은 모델 · 같은 화면당 검토 상한 6개 · 요청 시작 간격 15초. 기존 결과는 보존합니다.</p>
<p class="notice"><b>현재 상태: {e(state['state'])} — 개선 결과 {len(optimized)}/{len(baseline)}개.</b><br>로컬 분석과 새 Gemini 실행을 구분합니다. 새 API 실험이 끝나기 전에는 처리시간 감소나 오류가 늘지 않았다고 결론 내릴 수 없습니다.<br>{e(state.get('reason',''))}</p>
<table><tr><th>항목</th><th>기존 기록 / 로컬 확인</th><th>개선안</th></tr>
<tr><td>원본 화면·시간대</td><td>{plan['frames_preserved']}개 보존</td><td>동일하게 모두 보존</td></tr>
<tr><td>전체 115장 중 인접한 완전 동일 화면</td><td>{plan['all_frame_exact_adjacent_pairs']}쌍</td><td>이 표본에서 통째 건너뛰기로 얻는 이득은 제한적</td></tr>
<tr><td>비교 표본</td><td>완료된 {len(baseline)}개 화면</td><td>동일 화면 {len(optimized)}개 실행 완료</td></tr>
<tr><td>정상 응답 호출</td><td>{plan['old_successful_calls']}회 (기존 캐시 재현)</td><td>{plan['planned_calls']}회 계획 ({plan['planned_call_reduction_percent']:.1f}% 감소 예상)</td></tr>
<tr><td>검토 결과 재사용 후보</td><td>이전 화면의 개별 검증 이력 사용</td><td>{plan['reuse_candidates']}개 영역 · 새 추출·전체 대조가 모두 통과해야 적용</td></tr>
<tr><td>새 방식 실제 처리시간</td><td>기존 전체 실행은 약 {manifest['original_last_run']['elapsed_seconds']/60:.1f}분: 미완료 화면 호출·기타 작업 포함</td><td>{actual}</td></tr>
<tr><td>오류·누락 증가 여부</td><td>기존 결과도 정답 데이터가 아님</td><td>실측·원본 대조 전 결론 보류</td></tr></table>
<p>계획 호출 수는 기존 응답의 판독 가능 여부를 다시 사용해 계산했습니다. 묶음 요청은 응답 내용·길이·재시도 수가 달라질 수 있습니다. 응답 시간까지 그 비율로 줄어든다는 의미는 아닙니다. 현재 계획의 영역 수를 유지하면서 모든 묶음에서 추가 보정이 필요하면 정상 호출은 {plan['max_successful_calls_if_all_batches_need_enhancement']}회입니다. 새 추출에서 영역 수 자체가 늘면 이 값보다 많아질 수 있으며 재시도도 별도입니다.</p>
<h2>적용한 규칙</h2><ol><li>화면이 픽셀 단위로 동일할 때만 전체 검토 결과 재사용. 미해결 보류도 그대로 유지.</li><li>다른 화면은 전체 추출과 전체 대조 유지. 유사도만으로 삭제하지 않음.</li><li>같은 글자·영역·종류이며 이전에 검증되고, 원본 픽셀 차이가 매우 작고, 새 대조에서 지적되지 않은 영역만 반복 정밀 검토 생략.</li><li>의심 영역 최대 3개를 한 요청으로 읽고 별도 요청으로 검증. 각 영역 ID가 빠지거나 섞이면 자동 수정하지 않고 보류.</li><li>요청 결과 캐시와 화면별 진행 상태 저장. 중단된 경우 성공한 요청부터 재사용.</li></ol>
<h2>품질 비교 범위</h2><p>원본을 직접 보고 미리 지정한 문구·코드 {refs.get('total',0)}곳 중 기존 결과 포함 {refs.get('baseline_present',0)}곳. 개선 결과 평가 {refs.get('evaluated_new',0)}곳, 포함: {new_present}, 기존에 있던 문구가 사라진 항목: {new_regressions}. 이것은 제한된 문구 포함 검사이며 전체 OCR 정확도나 도표 구조의 정확도가 아닙니다. 허위 추가 내용과 나머지 영역도 아래 원본과 비교해야 합니다.</p>
<p>로컬 검사: 단위 테스트 {validation.get('unit_tests_passed','미기록')}개 통과. 실제 화면에 작은 픽셀·빨간 획·십자 표시를 인위적으로 추가한 {len(validation.get('real_frame_synthetic_mutations',[]))}개 사례에서 해당 영역의 재사용이 차단됐습니다. 원본 화면·음성·기존 추출 파일의 변경 여부는 <a href="validation.json">검증 기록</a>에 남겼습니다. 이 검사는 재사용 규칙 검사이며 새 Gemini 판독 정확도 측정이 아닙니다.</p>
<p>새 실행: 프로젝트의 <b>화면최적화_비교실행.command</b>를 일반 Mac 터미널에서 실행합니다. 기존 장시간 추출과 동시에 실행하면 계정 호출 제한을 공유하므로 하나씩 실행합니다. 이 실험은 기존 RAG 데이터나 기존 추출 결과를 변경하지 않습니다.</p>
<h2>화면별 원본·결과</h2>{''.join(details)}</html>'''
    (out/'화면최적화_비교결과.html').write_text(page,encoding='utf-8')
    return comparison


def run(out,manifest,args):
    frames=read(out/'inputs/frames.json');segments=[json.loads(s) for s in (out/'inputs/speech_segments.jsonl').read_text().splitlines()]
    work=out/'optimized';link_inputs(out/'inputs',work,frames)
    client=Gemini(work/'api-cache',manifest['model'],args.env_file,max_calls=args.max_api_calls,delay=args.delay)
    state_path=out/'run-state.json'
    state=read(state_path) if state_path.exists() else {'runs':[],'per_frame':{},'active_elapsed_seconds':0}
    config={'delay':args.delay,'batch_size':3,'max_regions':manifest['max_regions'],'version':1,'model':manifest['model']}
    if state.get('config') not in (None,config):raise ValueError('benchmark_config_changed_use_another_output_folder')
    state.update(state='running',reason='',config=config)
    prior=None;prior_image=None;done=0;started=time.monotonic();run_record={'started_at':now()}
    try:
        for f in frames:
            if f['id'] not in manifest['selected_ids']:continue
            before=copy.deepcopy(client.stats);tick=time.monotonic()
            result=process_frame_optimized(f,frames,segments,work,client,prior,prior_image,
                                           manifest['max_regions'],3)
            counts={k:client.stats[k]-before[k] for k in ('requests','successes','cache_hits')}
            if f['id'] not in state['per_frame'] or counts['requests'] or counts['cache_hits']:
                state['per_frame'][f['id']]={'seconds_this_completion_attempt':time.monotonic()-tick,**counts,
                                            'holds':len(result['holds']),'reuse':len(result.get('reuse',[]))}
            prior=result;prior_image=work/f['path'];done+=1
            state['completed']=done;save(state_path,state)
            print(json.dumps({'stage':'optimized_vision','done':done,'total':len(manifest['selected_ids']),**counts}),flush=True)
        state.update(state='complete',reason='');return_code=0
    except Blocked as exc:
        state.update(state='blocked',reason=str(exc),detail=exc.detail);return_code=2
        print(guidance(str(exc)),flush=True)
    except KeyboardInterrupt:
        state.update(state='interrupted',reason='resume_with_same_command');return_code=130
    except Exception as exc:
        state.update(state='failed',reason=type(exc).__name__);return_code=1
        raise
    finally:
        elapsed=time.monotonic()-started;state['active_elapsed_seconds']+=elapsed
        run_record.update(ended_at=now(),elapsed_seconds=elapsed,api=client.stats,state=state['state'])
        state['runs'].append(run_record);save(state_path,state);render(out)
    print(json.dumps({'state':state['state'],'completed':done,'total':len(manifest['selected_ids']),
                      'report':str(out/'화면최적화_비교결과.html')},ensure_ascii=False),flush=True)
    return return_code


def main():
    ap=argparse.ArgumentParser();ap.add_argument('mode',choices=['local','run','report'])
    ap.add_argument('--job',type=Path,default=DEFAULT_JOB);ap.add_argument('--output',type=Path,default=DEFAULT_OUT)
    ap.add_argument('--env-file',type=Path,default=ROOT/'.env');ap.add_argument('--max-api-calls',type=int,default=300)
    ap.add_argument('--delay',type=float,default=15)
    args=ap.parse_args();out=args.output.resolve();out.mkdir(parents=True,exist_ok=True)
    with (out/'.benchmark.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:print('비교 작업이 이미 실행 중입니다.');return 2
        manifest=freeze(args.job,out)
        validate_frozen(out,manifest)
        if args.mode=='report':render(out);return 0
        if not (out/'local-comparison.json').exists() or args.mode=='local':
            data=local(out,manifest)
            print(json.dumps({k:v for k,v in data.items() if k!='frames'},ensure_ascii=False),flush=True)
        if args.mode=='run':return run(out,manifest,args)
    return 0


if __name__=='__main__':raise SystemExit(main())
