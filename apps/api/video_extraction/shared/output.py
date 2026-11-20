from video_extraction._layout import source_path
import html
from pathlib import Path
from video_extraction.shared.common import jsonl, overlap, save


def align(frames, speech, duration, vision):
    """References preserve full source text; overlap is temporal, not semantic equivalence."""
    units=[]
    for i,frame in enumerate(frames):
        start=0.0 if i==0 else frame['time_seconds']
        end=frames[i+1]['time_seconds'] if i+1<len(frames) else duration
        linked=[s for s in speech if overlap(start,end,s['start_seconds'],s['end_seconds'])>0]
        v=vision.get(frame['id'])
        units.append({'id':f'unit-{i+1:05}','start_seconds':start,'end_seconds':end,
            'frame_id':frame['id'],'frame_time_seconds':frame['time_seconds'],'frame_path':frame['path'],
            'screen_text':v['text'] if v else '', 'screen_status':v['status'] if v else 'pending',
            'speech_segment_ids':[s['id'] for s in linked],
            'speech_text':' '.join(s['text'] for s in linked),
            'alignment':'approximate temporal overlap; not PPT matching or semantic confirmation',
            'screen_eligible':bool(v and v['status'] in ('auto_checked','auto_repaired')),
            'speech_review_ids':[s['id'] for s in linked if s['review_reasons']]})
    return units


def timestamp(seconds):
    ms=round(seconds*1000);h,ms=divmod(ms,3600000);m,ms=divmod(ms,60000);s,ms=divmod(ms,1000)
    return f'{h:02}:{m:02}:{s:02},{ms:03}'


def export(out, state, frames, speech, vision):
    out=Path(out);duration=state['metadata']['duration_seconds'];source=state['source_sha256']
    units=align(frames,speech,duration,vision)
    jsonl(out/'aligned_units.jsonl',units)
    jsonl(out/'speech_segments.jsonl',speech)
    (out/'transcript.srt').write_text('\n\n'.join(f'{i}\n{timestamp(s["start_seconds"])} --> {timestamp(s["end_seconds"])}\n{s["text"]}' for i,s in enumerate(speech,1)),encoding='utf-8')
    (out/'transcript.txt').write_text('\n'.join(f'[{s["start_seconds"]:.2f}–{s["end_seconds"]:.2f}] {s["text"]}' for s in speech),encoding='utf-8')
    candidates=[];review=[]
    for s in speech:
        if s['review_reasons']:
            review.append({'source_type':'speech','id':s['id'],'start_seconds':s['start_seconds'],
                           'end_seconds':s['end_seconds'],'reasons':s['review_reasons'],'text':s['text']})
        else:
            candidates.append({'id':source[:16]+':'+s['id'],'source_sha256':source,'source_type':'speech',
              'start_seconds':s['start_seconds'],'end_seconds':s['end_seconds'],'text':s['text'],
              'quality':s.get('status','machine_transcribed_no_heuristic_flags'),'approved':False})
    for u in units:
        if u['screen_eligible']:
            if u['screen_text'].strip():
                candidates.append({'id':source[:16]+':'+u['frame_id'],'source_sha256':source,
                  'source_type':'screen','frame_id':u['frame_id'],'frame_time_seconds':u['frame_time_seconds'],
                  'start_seconds':u['start_seconds'],'end_seconds':u['end_seconds'],
                  'text':u['screen_text'],'quality':u['screen_status'],'approved':False})
        else:
            v=vision.get(u['frame_id'])
            review.append({'source_type':'screen','id':u['frame_id'],'frame_path':u['frame_path'],
                           'frame_time_seconds':u['frame_time_seconds'],
                           'reasons':v['holds'] if v else ['vision_pending'],'text':u['screen_text']})
    jsonl(out/'rag_candidates.jsonl',candidates)
    save(out/'review_queue.json',review)
    summary={'state':state['state'],'duration_seconds':duration,'frames':len(frames),'speech_segments':len(speech),
             'vision_completed':len(vision),'vision_pending':len(frames)-len(vision),
             'changed_blocks':sum(v['changed_blocks'] for v in vision.values()),
             'screen_review':sum(v['status']=='needs_review' for v in vision.values()),
             'speech_review':sum(bool(s['review_reasons']) for s in speech),'candidate_records':len(candidates),
             'speech_auto_changed':sum(s.get('original_text',s['text'])!=s['text'] for s in speech),
             'publication':'not embedded or published; approved=false for all candidates',
             'accuracy':'not independently evaluated; no percentage claimed'}
    save(out/'summary.json',summary)
    e=html.escape
    cards=[]
    for u in units:
        cards.append(f'<details><summary>{e(u["frame_id"])} · {u["start_seconds"]:.1f}–{u["end_seconds"]:.1f}s · {e(u["screen_status"])}</summary>'
          f'<img loading="lazy" src="{e(u["frame_path"])}" alt="강의 원본 프레임">'
          f'<h3>화면 추출</h3><pre>{e(u["screen_text"] or "Gemini 처리 대기")}</pre>'
          f'<h3>동시간대 음성 전사</h3><pre>{e(u["speech_text"])}</pre>'
          '<p>시간이 겹친다는 사실만으로 두 내용이 동일하거나 서로를 정정한다고 판단하지 않습니다.</p></details>')
    page='''<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>영상 데이터 추출 결과</title><style>body{font-family:system-ui;max-width:1050px;margin:35px auto;padding:20px;color:#183047;background:#f1f5f9;line-height:1.7}header,details,.box{background:white;border:1px solid #d3dee8;border-radius:12px;padding:20px;margin:15px 0}h1{font-size:28px}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:14px;background:#f5f7f9;padding:15px}img{max-width:100%;height:auto}summary{cursor:pointer;font-weight:700}a{color:#0a6c65}.warn{color:#965900}</style>'''
    page+=f'<header><h1>영상 데이터 추출 결과</h1><p>{e(Path(state["source_path"]).name)}</p><strong>상태: {e(state["state"])}</strong><p class="warn">{e(state.get("blocked_reason",""))}</p></header>'
    if state.get('next_action'):
        page+=f'<div class="box"><strong>다음 조치</strong><p>{e(state["next_action"])}</p><pre>{e(str(state.get("blocked_detail",{})))}</pre></div>'
    page+=f'<div class="box"><p>영상 {duration/60:.2f}분 · 프레임 {len(frames)}장 · 음성 {len(speech)}구간 · 화면 처리 {len(vision)}/{len(frames)}장</p><p>자동 변경 {summary["changed_blocks"]}블록 · 화면 보류 {summary["screen_review"]}장 · 음성 검토 {summary["speech_review"]}구간</p><p>원본과 최초 추출은 보존합니다. 자동 검사 통과는 정답률 100%를 뜻하지 않습니다. 추출 후보를 벡터 DB에 게시하지 않았습니다.</p><a href="transcript.txt">전사 TXT</a> · <a href="transcript.srt">자막 SRT</a> · <a href="aligned_units.jsonl">시간대 연결 데이터</a> · <a href="review_queue.json">검토 대기 목록</a> · <a href="rag_candidates.jsonl">RAG 후보 데이터</a> · <a href="state.json">실행 상태</a></div>'
    page+=''.join(cards)+'</html>'
    (out/'결과.html').write_text(page,encoding='utf-8')
    return summary
