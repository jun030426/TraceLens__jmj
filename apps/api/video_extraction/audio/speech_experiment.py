"""Reproducible, offline, non-destructive speech-correction experiment.

Run with the existing ASR environment: python -m video_extraction.audio.speech_experiment.
The original video worker and its outputs are never written to.
"""
from video_extraction._layout import PROJECT_ROOT, source_path, code_hashes_match
import argparse
from collections import Counter
import html
import json
from pathlib import Path
import random
import re
import time
import wave

from video_extraction.shared.common import digest_file, read, save, signature, jsonl
from video_extraction.audio.speech_rules import VERSION, apply, propose, token_time

ROOT=PROJECT_ROOT
DEFAULT_JOB=ROOT/'outputs/video-extraction/f2bbd01de9a3e78d-f9a29e713f86'
DEFAULT_OUT=ROOT/'outputs/speech-context-test'/f'run-v{VERSION}'
GROUPS=[
    (3,'객체 튜플 리스트 딕셔너리 집합 자료형 자료구조','파이썬 데이터 구조 값 순서 자료 저장'),
    (3,'합집합 교집합 차집합 연산','집합 데이터 공통 메소드 메서드'),
    (2,'인덱스 메소드 메서드 정렬 탐색 배열 반환','리스트 데이터 순서 함수 값 자료'),
    (2,'대괄호 중괄호 소괄호','리스트 튜플 집합 딕셔너리 가로 괄호'),
    (2,'학생 과목 수강 성적','학생 과목 수강 학교 점수 과제'),
    (2,'가변 불변 무결성','튜플 리스트 자료형 변경 수정 데이터'),
    (1,'파이썬 스택 참조','객체 데이터 자료 구조 리스트'),
]


def lexicon(job):
    sources=[]
    native=ROOT/'outputs/extraction-compare/native/slides.jsonl'
    for n,line in enumerate(native.read_text().splitlines(),1):
        sources.append((str(native.relative_to(ROOT))+f'#line={n}',line))
    # Snapshot only currently completed results. Screen text is a hint, not audio truth.
    for path in sorted((job/'vision').glob('*/result.json')):
        d=read(path)
        sources.append((str(path.relative_to(ROOT)),d.get('text','')))
    entries=[]
    for importance,terms,anchors in GROUPS:
        for term in terms.split():
            refs=[p for p,t in sources if term in t]
            if refs:entries.append({'term':term,'importance':importance,'anchors':anchors.split(),
                'source_refs':refs[:3],'source_kind':'course_text_hint_not_audio_reference'})
    return entries


def neighboring(segments,s):
    # Exclude the target so its suspect wording cannot supply its own context vote.
    return ' '.join(x['text'] for x in segments if x['id']!=s['id']
        and x['end_seconds']>s['start_seconds']-25 and x['start_seconds']<s['end_seconds']+25)


def prepare(job,out):
    path=out/'manifest.json'
    if path.exists():
        d=read(path)
        if d['baseline_sha256']!=digest_file(job/'asr.json'):raise ValueError('Baseline changed; choose a new output folder.')
        if d['audio_sha256']!=digest_file(job/'audio-normalized.wav'):raise ValueError('Audio changed; choose a new output folder.')
        if not code_hashes_match(d['rules_sha256'], digest_file(source_path('speech_rules.py'))):raise ValueError('Rules changed; use a new output folder.')
        return d
    segments=read(job/'asr.json')['segments'];terms=lexicon(job)
    all_rows=[]
    for s in segments:
        context=neighboring(segments,s)
        all_rows.append({'segment':s,'context':context,'proposals':propose(s['text'],context,terms)})
    suspicious=[x for x in all_rows if x['proposals']]
    # Freeze selection before re-decoding. Cover terms then higher-ranked candidates.
    ranked=sorted(suspicious,key=lambda r:(-max(p['rank_score'] for p in r['proposals']),r['segment']['start_seconds']))
    selected=[];seen=set()
    def add(row,group):
        s=row['segment']
        if any(abs(s['start_seconds']-x['segment']['start_seconds'])<12 for x in selected):return False
        selected.append({**row,'group':group});return True
    for row in ranked:
        term=max(row['proposals'],key=lambda p:p['rank_score'])['term']
        if term not in seen and add(row,'suspected'):seen.add(term)
        if len(selected)>=12:break
    for row in ranked:
        if len(selected)>=16:break
        add(row,'suspected')
    controls=[x for x in all_rows if not x['proposals'] and not x['segment']['review_reasons']
              and 3<=x['segment']['end_seconds']-x['segment']['start_seconds']<=12]
    random.Random(20261019).shuffle(controls)
    count=0
    for row in controls:
        if add(row,'control'):count+=1
        if count==8:break
    selected.sort(key=lambda x:x['segment']['start_seconds'])
    d={'version':VERSION,'job':str(job),'baseline_sha256':digest_file(job/'asr.json'),
       'audio_sha256':digest_file(job/'audio-normalized.wav'),
       'rules_sha256':digest_file(source_path('speech_rules.py')),
       'experiment_sha256':digest_file(Path(__file__)),'model':'turbo',
       'lexicon':terms,'total_segments':len(segments),'flagged_segments':len(suspicious),
       'flagged_tokens':sum(len(x['proposals']) for x in suspicious),'selection_seed':20261019,
       'selection_policy':'16 suspicious (term coverage then rank), 8 deterministic random unflagged controls; >=12s spacing',
       'selected':selected,'all_proposals':all_rows,
       'evaluation':'No independently listened gold transcript. Counts are candidates/evidence, not accuracy.',
       'conditions':'Same original baseline and normalized audio. Same clip/context margin, model, decoder settings for both new arms.'}
    save(out/'baseline.json',{'segments':segments});save(path,d)
    return d


def clip_audio(source,destination,left,right):
    with wave.open(str(source)) as src:
        if src.getnchannels()!=1 or src.getsampwidth()!=2 or src.getframerate()!=16000:raise ValueError('Expected PCM16 mono 16kHz')
        src.setpos(round(left*src.getframerate()))
        with wave.open(str(destination),'wb') as dst:
            dst.setparams(src.getparams());dst.writeframes(src.readframes(round((right-left)*src.getframerate())))


def decode(model,path,left,segment,prompt,hotwords):
    import numpy as np
    started=time.monotonic()
    # Use PCM directly: the existing PyAV build lacks decode_audio's metadata_errors option.
    with wave.open(str(path)) as wav:
        audio=np.frombuffer(wav.readframes(wav.getnframes()),dtype=np.int16).astype(np.float32)/32768
    segments,_=model.transcribe(audio,language='ko',beam_size=5,vad_filter=True,
        condition_on_previous_text=False,word_timestamps=True,
        initial_prompt=prompt or None,hotwords=hotwords or None)
    words=[];texts=[]
    for s in segments:
        texts.append(s.text.strip())
        for w in s.words or []:
            words.append({'word':w.word,'start_seconds':left+w.start,'end_seconds':left+w.end,'probability':w.probability})
    owned=[w for w in words if segment['start_seconds'] <= (w['start_seconds']+w['end_seconds'])/2 < segment['end_seconds']]
    return {'text':''.join(w['word'] for w in owned).strip(),'full_clip_text':' '.join(texts),
            'words':owned,'all_words':words,'seconds':time.monotonic()-started}


def run(job,out,manifest):
    from faster_whisper import WhisperModel
    start=time.monotonic()
    model=WhisperModel('turbo',device='cpu',compute_type='int8',cpu_threads=4,
        local_files_only=True,download_root=str(ROOT/'work/extraction-compare/models'))
    witness_model=WhisperModel('small',device='cpu',compute_type='int8',cpu_threads=4,
        local_files_only=True,download_root=str(Path.home() / 'Documents/Codex/2026-10-13/new-chat/work/models'))
    load_seconds=time.monotonic()-start
    raw=job/'audio-normalized.wav'
    with wave.open(str(raw)) as wav:duration=wav.getnframes()/wav.getframerate()
    offset=read(job/'state.json')['metadata']['audio_offset_seconds']
    # This experiment uses zero-offset source. Refuse silently misaligned sources.
    if abs(offset)>.001:raise ValueError('Nonzero media offset requires explicit conversion')
    for n,row in enumerate(manifest['selected']):
        s=row['segment'];folder=out/'samples'/s['id'];folder.mkdir(parents=True,exist_ok=True)
        left=max(0,s['start_seconds']-2);right=min(duration,s['end_seconds']+2)
        clip=folder/'audio.wav'
        if not clip.exists():clip_audio(raw,clip,left,right)
        # Context is neighboring transcript; glossary is weighted in proposal ranking.
        # hotwords itself has no per-word numeric weight in faster-whisper.
        ordered=sorted(manifest['lexicon'],key=lambda t:(-t['importance'],t['term']))
        hotwords=', '.join(t['term'] for t in ordered)
        prompt='자료구조 강의 전사. 앞뒤 발언 참고: '+row['context'][:380]
        arms={}
        for arm in (('plain','hinted','witness') if n%2==0 else ('hinted','plain','witness')):
            p=folder/(arm+'.json')
            params={'manifest':signature(manifest),'clip_sha256':digest_file(clip),'arm':arm,
                    'prompt':prompt if arm=='hinted' else '', 'hotwords':hotwords if arm=='hinted' else ''}
            sig=signature(params)
            if p.exists() and read(p).get('signature')==sig:arms[arm]=read(p)['result']
            else:
                result=decode(witness_model if arm=='witness' else model,clip,left,s,params['prompt'],params['hotwords'])
                save(p,{'signature':sig,'parameters':params,'result':result});arms[arm]=result
            print(f'{n+1}/{len(manifest["selected"])} {s["id"]} {arm}: {arms[arm]["seconds"]:.2f}s',flush=True)
        final,accepted,held=apply(s,row['proposals'],arms['plain'],arms['hinted'],arms['witness'])
        save(folder/'result.json',{'id':s['id'],'group':row['group'],'start_seconds':s['start_seconds'],
            'end_seconds':s['end_seconds'],'original':s['text'],'plain':arms['plain'],'hinted':arms['hinted'],'witness':arms['witness'],
            'corrected_candidate':final,'accepted':accepted,'held':held,'proposals':row['proposals'],
            'clip':str(clip.relative_to(out)),'clip_left_seconds':left,
            'status':'machine_supported_not_independently_verified','approved':False})
    save(out/'runtime.json',{'model_load_seconds':load_seconds,'run_wall_seconds':time.monotonic()-start,
        'note':'Cached runs retain original per-decode timing. Not isolated from other computer activity.'})


def render(out,manifest):
    rows=[read(out/'samples'/r['segment']['id']/'result.json') for r in manifest['selected']
          if (out/'samples'/r['segment']['id']/'result.json').exists()]
    accepted=[p for r in rows for p in r['accepted']];held=[p for r in rows for p in r['held']]
    def repeated(text):
        tokens=re.findall(r'[가-힣A-Za-z0-9_]+',text)
        return {tuple(tokens[i:i+n]) for n in range(1,5) for i in range(len(tokens)-2*n+1)
                if tokens[i:i+n]==tokens[i+n:i+2*n] and len(''.join(tokens[i:i+n]))>1}
    def repeats(r,arm):return sorted(repeated(r[arm]['text'])-repeated(r['original']))
    originals={r['segment']['id']:r['segment'] for r in manifest['selected']}
    def literal_hits(arm):
        count=0
        for r in rows:
            for p in r['proposals']:
                span=token_time(originals[r['id']],p)
                if not span:continue
                words=[w for w in r[arm]['all_words'] if span[0]-.45<=(w['start_seconds']+w['end_seconds'])/2<=span[1]+.45]
                candidates={''.join(re.findall('[가-힣]+',''.join(w['word'] for w in words[i:i+n])))
                            for i in range(len(words)) for n in range(1,4)}
                count+=p['after'] in candidates
        return count
    metrics={'sample_segments':len(rows),'suspected_samples':sum(r['group']=='suspected' for r in rows),
        'control_samples':sum(r['group']=='control' for r in rows),
        'candidate_tokens':sum(len(r['proposals']) for r in rows),
        'machine_supported_changes':len(accepted),'held_candidates':len(held),
        'changed_segments':sum(r['original']!=r['corrected_candidate'] for r in rows),
        'changed_control_segments':sum(r['group']=='control' and r['original']!=r['corrected_candidate'] for r in rows),
        'raw_hinted_changed_segments':sum(r['original']!=r['hinted']['text'] for r in rows),
        'raw_hinted_changed_controls':sum(r['group']=='control' and r['original']!=r['hinted']['text'] for r in rows),
        'new_repetition_flags':sum(bool(repeats(r,'hinted')) for r in rows),
        'plain_literal_candidate_hits':literal_hits('plain'),
        'hinted_literal_candidate_hits':literal_hits('hinted'),
        'plain_decode_seconds':sum(r['plain']['seconds'] for r in rows),
        'hinted_decode_seconds':sum(r['hinted']['seconds'] for r in rows),
        'witness_decode_seconds':sum(r['witness']['seconds'] for r in rows),
        'sample_audio_seconds':sum(r['end_seconds']-r['start_seconds']+4 for r in rows),
        'held_reasons':dict(Counter(p['reason'] for p in held)),
        'verified_corrected_errors':None,'verified_harmful_changes':None,'cer':None,'wer':None,
        'limitation':'No human-audited audio reference. Turbo with/without hints plus small blind transcription can share errors. Unchanged controls do not prove zero harm.'}
    save(out/'metrics.json',metrics)
    if rows and 'broad_hinted' in rows[0]:
        metrics['broad_hinted_decode_seconds']=sum(r['broad_hinted']['seconds'] for r in rows)
        metrics['broad_new_repetition_flags']=sum(bool(repeats(r,'broad_hinted')) for r in rows)
        metrics['broad_raw_changed_controls']=sum(r['group']=='control' and r['original']!=r['broad_hinted']['text'] for r in rows)
        metrics['comparison_design']='Bounded follow-up on same development sample. Plain/small results reused. No independent holdout.'
        metrics['broad_same_gate_changes']=sum(len(r['broad_same_gate']['accepted']) for r in rows)
        metrics['broad_literal_candidate_hits']=literal_hits('broad_hinted')
        save(out/'metrics.json',metrics)
    selected={r['id']:r for r in rows};copies=[];queue=[]
    for original_row in manifest['all_proposals']:
        s=original_row['segment'];r=selected.get(s['id']);copy={**s,'approved':False}
        copy['original_text']=s['text'];copy['correction_status']='not_sampled'
        if r:
            copy['text']=r['corrected_candidate'];copy['correction_status']='machine_supported_candidate' if r['accepted'] else 'unchanged'
            copy['corrections']=r['accepted']
            if copy['text']!=s['text']:
                copy['original_words']=copy.pop('words',[]);copy['words']=[]
            if r['held']:queue.append({'id':s['id'],'start_seconds':s['start_seconds'],'status':'needs_audio_review','proposals':r['held']})
        elif original_row['proposals']:
            queue.append({'id':s['id'],'start_seconds':s['start_seconds'],'status':'not_sampled','proposals':original_row['proposals']})
        copies.append(copy)
    jsonl(out/'speech_corrected_candidates.jsonl',copies)
    save(out/'review_queue.json',queue)
    metrics['review_queue_segments']=len(queue);save(out/'metrics.json',metrics)
    esc=lambda x:html.escape(str(x))
    parts=['''<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>음성 문맥 보완 비교</title><style>body{max-width:1100px;margin:40px auto;padding:0 22px;font:16px/1.7 system-ui;color:#182738}h1{font-size:29px}h2{margin-top:36px}table{border-collapse:collapse;width:100%;font-size:14px}th,td{border:1px solid #d2dce5;padding:10px;text-align:left;vertical-align:top}th{background:#eef4f8}pre{white-space:pre-wrap;overflow-wrap:anywhere;padding:14px;background:#f1f5f8}details{margin:20px 0;padding:14px;border:1px solid #d5dce1}summary{cursor:pointer;font-weight:650}.note{padding:16px;background:#fff3ce}audio{width:100%}</style><body>
<h1>발음·문맥·핵심 용어 보완 실험</h1>
<p class="note"><b>실제 강의 음성으로 재전사한 결과입니다.</b> 정답 전사본이 없어 ‘자동 근거가 모인 수정 후보’와 ‘정확히 고친 오류’를 구분합니다. 아래 변경은 미승인 상태이며 기존 전사·RAG에는 반영하지 않았습니다.</p>''']
    parts.append(f'<p>전체 {manifest["total_segments"]}개 발언을 규칙 검사해 {manifest["flagged_segments"]}개에서 {manifest["flagged_tokens"]}개 후보를 찾았습니다. 새 모델 출력을 보기 전에 의심 구간 {metrics["suspected_samples"]}개와 비의심 비교 구간 {metrics["control_samples"]}개를 고정했습니다.</p>')
    parts.append('<table><tr><th>측정 항목</th><th>결과</th></tr>')
    for name,key in [('실제 재전사 구간','sample_segments'),('표본 내 교정 제안','candidate_tokens'),('무힌트·힌트·별도 모델 모두 지지한 변경','machine_supported_changes'),('반영 보류','held_candidates'),('최종 문구가 바뀐 발언','changed_segments'),('비의심 비교 구간의 최종 변경','changed_control_segments')]:
        parts.append(f'<tr><td>{name}</td><td>{metrics[key]}</td></tr>')
    parts.append('</table><p><b>확정 정정 수·잘못 수정한 수·오류율은 아직 측정하지 못했습니다.</b> turbo의 두 전사와 무힌트 small 모델이 함께 틀릴 수 있습니다. 비의심 구간은 정답으로 확정된 정상 구간이 아닙니다. 규칙이 제안하지 않은 구간은 최종 적용 대상에서 제외되므로 비교 구간 보존은 정확도의 증명이 아닙니다.</p>')
    if accepted:
        parts.append('<h2>자동 조건을 통과한 수정 후보</h2><table><tr><th>시각</th><th>기존</th><th>후보</th></tr>')
        for r in rows:
            for p in r['accepted']:
                parts.append(f'<tr><td>{r["start_seconds"]:.2f}초</td><td>{esc(p["before"])}</td><td>{esc(p["after"])}</td></tr>')
        parts.append('</table>')
    order_note='최초 무힌트·넓은 힌트 실험은 순서를 번갈아 실행했고, 제한한 힌트는 그 이후 실행했습니다.' if 'broad_source' in manifest else '두 방식의 순서를 번갈아 실행했습니다.'
    parts.append(f'<p>동일 길이의 음성 약 {metrics["sample_audio_seconds"]:.1f}초를 각 방식에 입력. 무힌트 {metrics["plain_decode_seconds"]:.1f}초, 문맥·용어 힌트 {metrics["hinted_decode_seconds"]:.1f}초. CPU int8, 4스레드, beam 5. {order_note} 최초 전체 전사와 클립 길이가 달라 무힌트 재전사도 별도로 비교합니다.</p>')
    if 'broad_hinted_decode_seconds' in metrics:
        parts.append(f'<h2>힌트 양을 줄인 추가 비교</h2><p>전체 용어 24개·앞뒤 문맥 최대 380자를 넣은 실험에서 반복이 발생해, 동일 개발 표본으로 용어 최대 8개·이전 발언 최대 100자 방식도 실행했습니다. 무힌트 turbo와 small 결과는 재사용했습니다. 새로운 미사용 평가 자료는 아닙니다.</p><table><tr><th>항목</th><th>넓은 힌트</th><th>제한한 힌트</th></tr><tr><td>추가된 연속 단어 반복 의심 구간</td><td>{metrics["broad_new_repetition_flags"]}</td><td>{metrics["new_repetition_flags"]}</td></tr><tr><td>비의심 비교 구간의 전사문 변화</td><td>{metrics["broad_raw_changed_controls"]}</td><td>{metrics["raw_hinted_changed_controls"]}</td></tr><tr><td>힌트 재전사 시간</td><td>{metrics["broad_hinted_decode_seconds"]:.1f}초</td><td>{metrics["hinted_decode_seconds"]:.1f}초</td></tr></table><p>변화에는 구두점·띄어쓰기·구간 경계 차이도 포함됩니다. 반복 감지는 오류 의심 신호이며 실제 오수정률이 아닙니다. 최종 후보는 아래 별도 적용 조건으로 제한했습니다.</p>')
        parts.append(f'<p>{metrics["candidate_tokens"]}개 수정 제안의 표기가 해당 시각에 나온 위치: 무힌트 <b>{metrics["plain_literal_candidate_hits"]}</b>, 넓은 힌트 <b>{metrics["broad_literal_candidate_hits"]}</b>, 제한한 힌트 <b>{metrics["hinted_literal_candidate_hits"]}</b>곳. 제안 표기와의 일치 수일 뿐 정답 기준 정확도가 아닙니다. 잘못 제안된 용어를 말했어도 이 지표는 올라갈 수 있으므로 자동 반영에는 별도 음성 검증을 적용합니다.</p>')
    parts.append(f'<p>별도 small 모델의 무힌트 검증에 {metrics["witness_decode_seconds"]:.1f}초를 추가했습니다. 이 모델도 정답 판정기는 아닙니다.</p>')
    parts.append('<h2>적용한 규칙</h2><p>한글 자모 거리와 단일 받침 연음으로 후보 생성 → 주변 ±25초 문맥과 강의 용어 중요도(1~3)로 순위 계산 → 같은 음성을 무힌트/힌트로 각각 재전사 → 별도 small 모델도 무힌트로 확인 → 해당 단어의 시각에서 세 전사가 조사까지 포함한 교정 표기를 지지할 때만 최소 글자 수정. 발음이 정확히 같은 연음 표기는 동등한 근거로 인정하고, 단순히 소리가 비슷한 정도로는 통과시키지 않습니다. 경쟁 후보·숫자·부정·연산자·시각 불명은 보류합니다.</p><p>용어 가중치는 자체 후보 점수에 적용합니다. Whisper hotwords는 힌트이며 숫자 가중치를 직접 받지 않습니다. 완전한 한국어 발음 변환·자유로운 문장 재작성은 구현 범위에 포함하지 않았습니다.</p>')
    for r in rows:
        edits='; '.join(p['before']+' → '+p['after'] for p in r['accepted']) or '적용된 변경 없음'
        parts.append(f'<details><summary>{r["start_seconds"]:.2f}–{r["end_seconds"]:.2f}초 · {esc(r["group"])} · {esc(edits)}</summary><audio controls preload="none" src="{esc(r["clip"])}"></audio>')
        columns=[('기존 전사','original'),('무힌트 재전사','plain')]
        if 'broad_hinted' in r:columns.append(('넓은 힌트 재전사 — 비교용','broad_hinted'))
        columns += [('문맥·용어 힌트 재전사','hinted'),('별도 small 무힌트 검증','witness'),('발음 규칙과 적용 조건까지 통과한 후보','corrected_candidate')]
        for title,key in columns:
            v=r[key]['text'] if isinstance(r[key],dict) else r[key]
            parts.append(f'<b>{title}</b><pre>{esc(v)}</pre>')
        if r['held']:parts.append('<p>보류: '+esc('; '.join(p['before']+' → '+p['after']+' ('+p['reason']+')' for p in r['held']))+'</p>')
        parts.append('</details>')
    parts.append('<p>manifest.json: 고정 표본·용어 출처·입력 해시 / metrics.json: 측정값 / samples/: 실제 음성·각 방식 전사·변경 이력 / speech_corrected_candidates.jsonl: 전체 전사의 별도 복사본에 검증 통과 후보만 반영(미승인) / review_queue.json: 추가 확인 대상. 기존 자료와 실행 중인 영상 작업은 변경하지 않았습니다.</p></body></html>')
    (out/'음성보완_비교결과.html').write_text(''.join(parts),encoding='utf-8')
    return metrics


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--job',type=Path,default=DEFAULT_JOB)
    parser.add_argument('--out',type=Path,default=DEFAULT_OUT);parser.add_argument('--prepare-only',action='store_true')
    parser.add_argument('--report-only',action='store_true');args=parser.parse_args()
    args.out.mkdir(parents=True,exist_ok=True);d=prepare(args.job,args.out)
    print(json.dumps({'flagged':d['flagged_segments'],'terms':len(d['lexicon']),'selected':len(d['selected'])}),flush=True)
    if args.prepare_only:return
    if not args.report_only:run(args.job,args.out,d)
    print(json.dumps(render(args.out,d),ensure_ascii=False,indent=2))


if __name__=='__main__':main()
