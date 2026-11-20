"""Offline, source-bound listening references and ASR scoring; no API imports.

Scores only reviewer-approved, fully audible segments. Never treats a model
prediction, an unreviewed draft, or file integrity as a reference transcript.
"""
from video_extraction._layout import PROJECT_ROOT
import argparse
import datetime
import hashlib
import html
import json
import random
import re
import unicodedata
import wave
from pathlib import Path

ROOT = PROJECT_ROOT
DEFAULT_INPUT = ROOT/'outputs/usable-accuracy-full-20261030/population-after-repair.jsonl'
DEFAULT_OUTPUT = ROOT/'outputs/audio-accuracy-289-v1'
POLICY = 'nfc-punctuation-space-v1'


def read(p):
    return json.loads(Path(p).read_text(encoding='utf-8'))


def save(p, value):
    Path(p).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def digest(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def normalized(text):
    """Preserve lexical spelling, case, numbers and symbols; ignore punctuation.

    Korean WER uses whitespace-separated eojeol, not a morphological tokenizer.
    Technical-term normalization and guessed word substitution are not applied.
    """
    text = unicodedata.normalize('NFC', text)
    # Decimal points and numeric signs carry meaning, unlike sentence punctuation.
    def numeric_mark(i, c):
        after = i+1 < len(text) and text[i+1].isdigit()
        return after and ((c == '.' and i > 0 and text[i-1].isdigit()) or c == '-')
    text = ''.join(' ' if unicodedata.category(c)[0] in ('P', 'Z', 'C') and not numeric_mark(i,c) else c for i,c in enumerate(text))
    return ' '.join(text.split())


def edits(reference, hypothesis):
    # Each cell: distance, substitutions, deletions, insertions. Deterministic ties.
    prev = [(j, 0, 0, j) for j in range(len(hypothesis)+1)]
    for i, token in enumerate(reference, 1):
        cur = [(i, 0, i, 0)]
        for j, other in enumerate(hypothesis, 1):
            if token == other:
                cur.append(prev[j-1]); continue
            n,s,d,a = prev[j-1]; sub = (n+1,s+1,d,a)
            n,s,d,a = prev[j]; delete = (n+1,s,d+1,a)
            n,s,d,a = cur[-1]; insert = (n+1,s,d,a+1)
            cur.append(min((sub,delete,insert), key=lambda x:x[0]))
        prev = cur
    n,s,d,i = prev[-1]
    return {'errors':n, 'substitutions':s, 'deletions':d, 'insertions':i, 'reference_units':len(reference)}


def compare(ref, hyp):
    r,h = normalized(ref),normalized(hyp)
    return {'cer':edits(r.replace(' ',''),h.replace(' ','')),
            'wer':edits(r.split(),h.split()), 'normalized_exact':r == h}


def clip(source, dest, start, end):
    with wave.open(str(source),'rb') as w:
        rate = w.getframerate(); lo = round(start*rate); hi = round(end*rate)
        if not 0 <= lo < hi <= w.getnframes(): raise ValueError('invalid_clip_bounds')
        w.setpos(lo); data = w.readframes(hi-lo)
        if len(data) != (hi-lo)*w.getnchannels()*w.getsampwidth(): raise ValueError('short_clip')
        with wave.open(str(dest),'wb') as out:
            out.setparams(w.getparams()); out.writeframes(data)
    return {'start_seconds':lo/rate,'end_seconds':hi/rate,'duration_seconds':(hi-lo)/rate,'sha256':digest(dest)}


def prepare(population=DEFAULT_INPUT, output=DEFAULT_OUTPUT, seed=20261030):
    population,output = Path(population).resolve(),Path(output).resolve()
    if output.exists():
        manifest = read(output/'manifest.json')
        if manifest['input_sha256'] != digest(population): raise ValueError('population_changed_choose_new_output')
        verify_package(output)
        return manifest
    records = [r for r in map(json.loads,population.read_text().splitlines()) if r['modality']=='audio']
    if not records or len({r['id'] for r in records}) != len(records): raise ValueError('invalid_population')
    records.sort(key=lambda r:(r['start_seconds'],r['id']))
    output.mkdir(parents=True); (output/'clips').mkdir()
    sources = {}; clips = []
    order=list(range(len(records)));random.Random(seed).shuffle(order)
    priority={idx:rank+1 for rank,idx in enumerate(order)}
    for i,r in enumerate(records):
        source=Path(r['source_audio']).resolve()
        if str(source) not in sources:
            with wave.open(str(source),'rb') as w:
                sources[str(source)]={'sha256':digest(source),'duration_seconds':w.getnframes()/w.getframerate(),'sample_rate':w.getframerate()}
        start,end=r['start_seconds'],r['end_seconds'];duration=sources[str(source)]['duration_seconds']
        short=f'A{i+1:03}';exact=f'clips/{short}.wav';context=f'clips/{short}-context.wav'
        meta=clip(source,output/exact,start,end)
        context_meta=clip(source,output/context,max(0,start-2),min(duration,end+2))
        clips.append({'id':r['id'],'label':short,'priority':priority[i],'pilot':priority[i]<=30,
                      'source_audio':str(source),'source_sha256':sources[str(source)]['sha256'],
                      'start_seconds':start,'end_seconds':end,'clip':exact,'clip_meta':meta,
                      'context_clip':context,'context_meta':context_meta,
                      'context_target_start':meta['start_seconds']-context_meta['start_seconds'],
                      'context_target_end':meta['end_seconds']-context_meta['start_seconds']})
    save(output/'predictions.frozen.json',records)  # Not embedded in blind review UI.
    save(output/'clips.json',clips)
    manifest={'version':1,'created_at':now(),'input':str(population),'input_sha256':digest(population),
              'population_count':len(records),'seed':seed,'pilot_count':min(30,len(records)),
              'audio_seconds_sum':sum(c['clip_meta']['duration_seconds'] for c in clips),
              'sources':sources,'policy':POLICY,'api_calls':0,'accuracy':None,
              'purpose':'selected_development_audio_census_not_independent_holdout',
              'files':{'predictions.frozen.json':digest(output/'predictions.frozen.json'),'clips.json':digest(output/'clips.json')}}
    save(output/'manifest.json',manifest)
    blank={'version':1,'manifest_sha256':digest(output/'manifest.json'),'reviewer':'','records':[
        {'id':r['id'],'status':'pending','reference_text':'','no_speech':False,'listened':False,'reviewed_at':None,'notes':''} for r in records]}
    save(output/'references.blank.json',blank)
    payload={'manifest_sha256':blank['manifest_sha256'],'clips':sorted(clips,key=lambda x:x['priority']),'blank':blank}
    template=(ROOT/'video_extraction/audio/audio_accuracy_review.html').read_text()
    (output/'음성_원음대조.html').write_text(template.replace('__PAYLOAD__',json.dumps(payload,ensure_ascii=False).replace('<','\\u003c')),encoding='utf-8')
    return manifest


def verify_package(output):
    output=Path(output);m=read(output/'manifest.json')
    for name,h in m['files'].items():
        if digest(output/name)!=h: raise ValueError('frozen_file_changed:'+name)
    for source,meta in m['sources'].items():
        if digest(source)!=meta['sha256']: raise ValueError('source_audio_changed')
    for c in read(output/'clips.json'):
        for name,meta in [('clip','clip_meta'),('context_clip','context_meta')]:
            if digest(output/c[name])!=c[meta]['sha256']: raise ValueError('audio_clip_changed:'+c['id'])
    return m


def evaluate(predictions, submission):
    """Pure scoring function: validates reference assertions before any scoring."""
    expected={r['id']:r for r in predictions};seen=set();approved=[];excluded=[]
    for r in submission.get('records',[]):
        rid=r.get('id')
        if rid not in expected or rid in seen: raise ValueError('unknown_or_duplicate_reference_id')
        seen.add(rid);status=r.get('status')
        if status not in ('pending','draft','approved','ambiguous','boundary'): raise ValueError('invalid_reference_status')
        if status!='approved':
            excluded.append({'id':rid,'status':status});continue
        if not submission.get('reviewer','').strip() or r.get('listened') is not True or not r.get('reviewed_at'):
            raise ValueError('approval_requires_named_listener_and_timestamp')
        text=r.get('reference_text')
        if not isinstance(text,str) or type(r.get('no_speech')) is not bool: raise ValueError('invalid_reference_text')
        if r['no_speech']:
            if text.strip():raise ValueError('no_speech_reference_must_be_empty')
        elif not normalized(text) or any(x in text for x in ('[불명료]','[판독불가]','⟦','⟧')):
            raise ValueError('ambiguous_or_empty_reference_cannot_be_approved')
        p=expected[rid];before=p.get('original_text');current=p['observed_text']
        approved.append({'id':rid,'reviewer':r.get('reviewer',submission['reviewer']),'reviewed_at':r['reviewed_at'],'reference_text':text,'current_text':current,'before_text':before,
                         'no_speech':r['no_speech'],'current':compare(text,current),
                         'before':compare(text,before) if isinstance(before,str) else None})
    excluded.extend({'id':rid,'status':'not_submitted'} for rid in expected if rid not in seen)
    def aggregate(rows,key):
        total={metric:{k:sum(r[key][metric][k] for r in rows) for k in ('errors','substitutions','deletions','insertions','reference_units')} for metric in ('cer','wer')}
        for m in total.values():m['error_rate_pct']=100*m['errors']/m['reference_units'] if m['reference_units'] else None
        return total
    paired=[r for r in approved if r['before'] is not None]
    return {'population_count':len(expected),'scored_segments':len(approved),'excluded_segments':len(excluded),
            'coverage_pct':100*len(approved)/len(expected) if expected else 0,
            'evaluation_complete':len(approved)==len(expected),
            'current_metrics':aggregate(approved,'current'),
            'normalized_exact_segments':sum(r['current']['normalized_exact'] for r in approved),
            'normalized_exact_segment_rate_pct':100*sum(r['current']['normalized_exact'] for r in approved)/len(approved) if approved else None,
            'paired_before_after':{'segments':len(paired),'before':aggregate(paired,'before'),'after':aggregate(paired,'current'),
                'improved_by_character_errors':sum(r['current']['cer']['errors']<r['before']['cer']['errors'] for r in paired),
                'worsened_by_character_errors':sum(r['current']['cer']['errors']>r['before']['cer']['errors'] for r in paired),
                'unchanged_by_character_errors':sum(r['current']['cer']['errors']==r['before']['cer']['errors'] for r in paired)},
            'no_speech_segments':sum(r['no_speech'] for r in approved),
            'no_speech_with_false_transcription':sum(r['no_speech'] and bool(normalized(r['current_text'])) for r in approved),
            'results':approved,'excluded':excluded}


def score(output, references):
    output=Path(output).resolve();references=Path(references).resolve();m=verify_package(output);sub=read(references)
    if sub.get('version')!=1 or sub.get('manifest_sha256')!=digest(output/'manifest.json'):raise ValueError('reference_population_mismatch')
    result=evaluate(read(output/'predictions.frozen.json'),sub)
    result.update(created_at=now(),api_calls=0,policy=POLICY,reviewer=sub.get('reviewer'),reference_sha256=digest(references),
                  manifest_sha256=digest(output/'manifest.json'),review_level='single_listener_approved_not_independently_adjudicated',
                  caveats=['CER/WER는 오류율이며 낮을수록 좋음. 삽입 오류 때문에 100%를 넘을 수 있음.',
                           '미승인·불명료·경계 잘림은 채점에서 제외하고 건수·비율을 별도 표시함.',
                           '부분 검토의 점수는 검토된 구간에만 해당하며 전체 289개 정확도가 아님.',
                           '구두점과 공백 형식은 정규화. 발음·기술 용어·숫자를 문맥으로 바꾸지 않음.',
                           '문자 오류율은 공백 제외, 어절 오류율은 공백 구분. 한국어 형태소 단위가 아님.',
                           '같은 원음으로 수정 전후 비교. 기존 모델 검증 판정을 정답으로 재사용하지 않음.',
                           '이미 사용한 개발 강의의 선별 데이터이며 새 강의 일반화 성능은 아님.'])
    dest=output/'scores'/result['reference_sha256'][:16];dest.mkdir(parents=True,exist_ok=True)
    save(dest/'references.submitted.json',sub);save(dest/'score.json',result)
    e=html.escape
    def pct(v):return '미측정' if v is None else f'{v:.2f}%'
    page='<meta charset="utf-8"><title>음성 정확도 평가</title><style>body{font:17px/1.65 system-ui;max-width:1000px;margin:40px auto;padding:20px}pre{white-space:pre-wrap}details{border:1px solid #ccd;padding:15px;margin:10px 0}</style><h1>음성 정확도 평가</h1>'
    page+=f'<p>승인·채점 {result["scored_segments"]}/{result["population_count"]}개 · 제외/미완료 {result["excluded_segments"]}개</p>'
    page+='<p><b>'+('전체 항목 청취 승인 완료' if result['evaluation_complete'] else '부분 평가: 전체 정확도로 해석하지 마세요.')+'</b></p>'
    page+=f'<p>문자 오류율(CER): {pct(result["current_metrics"]["cer"]["error_rate_pct"])} · 어절 오류율(WER): {pct(result["current_metrics"]["wer"]["error_rate_pct"])} · 구간 전체 일치율: {pct(result["normalized_exact_segment_rate_pct"])}</p>'
    pair=result['paired_before_after'];page+=f'<p>같은 정답으로 수정 전후 비교 {pair["segments"]}개: 문자 오류 감소 {pair["improved_by_character_errors"]}개 / 증가 {pair["worsened_by_character_errors"]}개 / 동일 {pair["unchanged_by_character_errors"]}개</p>'
    page+='<p>수정 전 CER '+pct(pair['before']['cer']['error_rate_pct'])+' → 수정 후 CER '+pct(pair['after']['cer']['error_rate_pct'])+'</p><ul>'+''.join('<li>'+e(x)+'</li>' for x in result['caveats'])+'</ul>'
    for r in result['results']:
        page+=f'<details><summary>{e(r["id"])} · 문자 오류 {r["current"]["cer"]["errors"]}</summary><h3>원음 청취 정답</h3><pre>{e(r["reference_text"])}</pre><h3>현재 전사</h3><pre>{e(r["current_text"])}</pre><h3>수정 전</h3><pre>{e(r["before_text"] or "원본 전사 없음")}</pre></details>'
    (dest/'음성_정확도결과.html').write_text(page,encoding='utf-8')
    return {'report':str(dest/'음성_정확도결과.html'),'scored':result['scored_segments'],'total':result['population_count'],'cer':result['current_metrics']['cer']['error_rate_pct'],'wer':result['current_metrics']['wer']['error_rate_pct'],'api_calls':0}


def main():
    ap=argparse.ArgumentParser(description=__doc__);sub=ap.add_subparsers(dest='mode',required=True)
    p=sub.add_parser('prepare');p.add_argument('--population',type=Path,default=DEFAULT_INPUT);p.add_argument('--output',type=Path,default=DEFAULT_OUTPUT)
    p=sub.add_parser('score');p.add_argument('--output',type=Path,default=DEFAULT_OUTPUT);p.add_argument('--references',type=Path,required=True)
    a=ap.parse_args();print(json.dumps(prepare(a.population,a.output) if a.mode=='prepare' else score(a.output,a.references),ensure_ascii=False,indent=2))
if __name__=='__main__':main()
