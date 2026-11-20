"""Resume an isolated, real-API validation of the two-layer extractor."""
from video_extraction._layout import source_path
import argparse
from video_extraction.shared import file_lock as fcntl
import html
import json
from pathlib import Path
import shutil
import time

from video_extraction.shared.common import digest_file, now, read, save
from video_extraction.shared.errors import guidance
from video_extraction.shared.gemini import Gemini, Blocked
from video_extraction.video.vision_benchmark import DEFAULT_OUT, ROOT, validate_frozen
from video_extraction.video.vision_layers import process_frame_layers, VERSION

DEFAULT_FRAMES=[4,5,6,16,21,22,29,30,31,32]
DEFAULT_OUTPUT=ROOT/'outputs/vision-layer-validation'


def prepare(source,out,numbers,text_budget,visual_budget):
    manifest=read(source/'manifest.json');validate_frozen(source,manifest)
    selected=[f'frame-{n:05}' for n in numbers]
    if len(set(selected))!=len(selected) or not set(selected)<=set(manifest['selected_ids']):
        raise ValueError('invalid_validation_frame_selection')
    frames=read(source/'inputs/frames.json')
    config={'version':VERSION,'source':str(source),'selected_ids':selected,'model':manifest['model'],
            'text_budget':text_budget,'visual_budget':visual_budget,
            'implementation_sha256':digest_file(source_path('vision_layers.py')),
            'frame_sha256':{fid:manifest['frame_sha256'][fid] for fid in selected},
            'speech_sha256':manifest['speech_sha256'],
            'previous_result_sha256':{fid:digest_file(source/'optimized/vision'/fid/'result.json') for fid in selected}}
    path=out/'validation-config.json'
    if path.exists() and read(path)!=config:raise ValueError('validation_config_changed_use_new_output')
    if not path.exists() and any(out.glob('vision/*/result.json')):raise ValueError('output_contains_unbound_results')
    save(path,config)
    for f in frames:
        if f['id'] not in selected:continue
        dst=out/f['path'];dst.parent.mkdir(parents=True,exist_ok=True)
        if not dst.exists():shutil.copy2(source/'inputs'/f['path'],dst)
        if digest_file(dst)!=config['frame_sha256'][f['id']]:raise ValueError('copied_frame_changed')
    speech=[json.loads(s) for s in (source/'inputs/speech_segments.jsonl').read_text().splitlines()]
    return config,frames,speech


def render(source,out,config,state):
    e=html.escape;rows=[];summaries=[]
    references=read(source/'reference.json')['checks']
    for fid in config['selected_ids']:
        previous=read(source/'optimized/vision'/fid/'result.json')
        path=out/'vision'/fid/'result.json';r=read(path) if path.exists() else None
        checks=[]
        if r:
            for ref in references:
                if ref['frame_id']==fid:
                    expected=''.join(ref['expected'].split())
                    checks.append({'expected':ref['expected'],'present':expected in ''.join(r['text'].split())})
            if fid=='frame-00029':
                # Check the cell in a table, not a Dictionary heading elsewhere.
                present=any('딕셔너리(Dictionary)' in ''.join(b['text'].split()) for b in r['final_blocks'] if b['kind']=='table')
                checks.append({'expected':'비교 표 셀: 딕셔너리(Dictionary)','present':present})
        summary={'frame_id':fid,'completed':bool(r),'old_holds':len(previous['holds']),
                 'new_holds':len(r['holds']) if r else None,'visual_count':len(r['visuals']) if r else None,
                 'deferred_count':len(r['deferred_regions']) if r else None,'checks':checks}
        summaries.append(summary)
        visual_html=''.join(f'<li><b>{e(v["kind"])} · {e(v["id"])}</b><p>{e(v["description"])}</p>'
            f'<p>필기 글자: {e(v["literal_text"]) or "없음"} · 연결 본문: {e(", ".join(v["related_block_ids"])) or "없음"}</p>'
            f'<p>불확실성: {e(", ".join(v["uncertainties"])) or "모델이 표시하지 않음"}</p></li>' for v in r['visuals']) if r else ''
        rows.append(f'<details><summary>{fid} · {e(r["status"] if r else "대기")} · 그림/필기 {len(r["visuals"]) if r else 0}개</summary>'
                    f'<img src="frames/{fid}.png" alt="원본 {fid}" loading="lazy"><div class="cols"><div><h3>수정 전 본문</h3><pre>{e(previous["text"])}</pre></div>'
                    f'<div><h3>수정 후 본문</h3><pre>{e(r["text"] if r else "미실행")}</pre><h3>별도 그림·필기</h3><ul>{visual_html}</ul></div></div>'
                    f'<h3>참조 검사</h3><pre>{e(json.dumps(checks,ensure_ascii=False,indent=2))}</pre>'
                    f'<details><summary>보류와 미처리 영역</summary><pre>{e(json.dumps({"holds":r["holds"],"deferred":r["deferred_regions"]},ensure_ascii=False,indent=2)) if r else ""}</pre></details></details>')
    report={'created_at':now(),'state':state,'frames':summaries,'config':config,
            'note':'Real API results only. Completion and snippet checks do not establish full visual accuracy.'}
    save(out/'comparison.json',report)
    page=f'''<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>그림·필기 분리 재검증</title>
<style>body{{font:16px/1.7 system-ui;max-width:1200px;margin:35px auto;padding:20px;color:#203040;background:#f5f8fa}}details,.notice{{background:white;border:1px solid #ccd5dc;padding:18px;margin:16px 0}}summary{{cursor:pointer;font-weight:bold}}img{{max-width:100%}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:#eef2f5;padding:14px;font-size:13px}}.cols{{display:grid;grid-template-columns:1fr 1fr;gap:20px}}@media(max-width:700px){{.cols{{grid-template-columns:1fr}}}}</style>
<h1>그림·필기 분리 재검증</h1><div class="notice"><b>상태: {e(state['state'])} · 완료 {sum(s['completed'] for s in summaries)}/{len(summaries)}</b><p>{e(state.get('reason',''))}</p>
<p>본문과 시각 정보를 분리하고, 같은 타깃의 여러 지적을 병합합니다. 본문·그림 검토 상한은 각각 {config['text_budget']}개 / {config['visual_budget']}개입니다. 미처리 영역은 개별 보류로 남습니다.</p>
<p>그림 설명은 AI 해석이며 원문 글자 전사가 아닙니다. 이전 32개 결과와 별도 폴더에 저장합니다. 완료는 정확도 인증이 아닙니다.</p><a href="comparison.json">실행·참조 검사 기록</a></div>{''.join(rows)}</html>'''
    (out/'그림필기_재검증.html').write_text(page,encoding='utf-8')
    return report


def main():
    ap=argparse.ArgumentParser();ap.add_argument('mode',choices=['run','report'])
    ap.add_argument('--source',type=Path,default=DEFAULT_OUT);ap.add_argument('--output',type=Path,default=DEFAULT_OUTPUT)
    ap.add_argument('--frames',type=int,nargs='+',default=DEFAULT_FRAMES)
    ap.add_argument('--text-budget',type=int,default=8);ap.add_argument('--visual-budget',type=int,default=8)
    ap.add_argument('--max-api-calls',type=int,default=200);ap.add_argument('--delay',type=float,default=15)
    ap.add_argument('--env-file',type=Path,default=ROOT/'.env');args=ap.parse_args()
    if not 0<=args.text_budget<=40 or not 0<=args.visual_budget<=60 or args.delay<0 or args.max_api_calls<0:
        raise ValueError('invalid_processing_limits')
    source=args.source.resolve();out=args.output.resolve()
    if source==out or source in out.parents:raise ValueError('validation_output_must_be_separate_from_source')
    out.mkdir(parents=True,exist_ok=True)
    with (out/'.validation.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:print('재검증 작업이 이미 실행 중입니다.');return 2
        config,frames,speech=prepare(source,out,args.frames,args.text_budget,args.visual_budget)
        state_path=out/'run-state.json';state=read(state_path) if state_path.exists() else {'runs':[],'state':'not_started'}
        if args.mode=='report':render(source,out,config,state);return 0
        client=Gemini(out/'api-cache',config['model'],args.env_file,args.max_api_calls,args.delay)
        started=time.monotonic();record={'started_at':now()};state.update(state='running',reason='',completed=0)
        save(state_path,state);code=0
        try:
            for frame in frames:
                if frame['id'] not in config['selected_ids']:continue
                process_frame_layers(frame,frames,speech,out,client,args.text_budget,args.visual_budget)
                state['completed']+=1;save(state_path,state)
                print(json.dumps({'frame':frame['id'],'completed':state['completed'],'total':len(config['selected_ids']),
                                  'requests':client.stats['requests'],'cache_hits':client.stats['cache_hits']}),flush=True)
            state.update(state='complete',reason='')
        except Blocked as exc:
            state.update(state='blocked',reason=str(exc),detail=exc.detail);code=2
            print(guidance(str(exc)),flush=True)
        except KeyboardInterrupt:
            state.update(state='interrupted',reason='resume_same_command');code=130
        except Exception as exc:
            state.update(state='failed',reason=f'{type(exc).__name__}: {str(exc)[:300]}');code=1
            raise
        finally:
            record.update(ended_at=now(),seconds=time.monotonic()-started,api=client.stats,state=state['state'])
            state['runs'].append(record);save(state_path,state);render(source,out,config,state)
        print(json.dumps({'state':state['state'],'report':str(out/'그림필기_재검증.html')},ensure_ascii=False),flush=True)
        return code


if __name__=='__main__':raise SystemExit(main())
