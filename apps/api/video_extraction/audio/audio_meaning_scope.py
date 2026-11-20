"""Release exact original matches and recheck a separately bounded restoration body.

No old artifacts are overwritten. prepare/reclassify are offline; only run uses API.
"""
import argparse
import copy
import html
import json
import re
from pathlib import Path
from video_extraction.audio import audio_meaning_review as prior
from video_extraction.audio.audio_meaning_review import base, read, save, jsonl, signature, digest_file, now, canonical, lock, Budget, Gemini, Blocked, api_key

ROOT=prior.ROOT
OUT=ROOT/'outputs/audio-meaning-review-v2'
BODY=ROOT/'outputs/audio-meaning-body-v2'
EXPRESSIONS=ROOT/'outputs/audio-meaning-expressions-v3'
ARCHIVED_SCOPE_CODE='9a9cd0c7b4d4f6b8f4126a266f914d6bda4e243bf9c1eecb025595b7b9857714'
EXPRESSION_POLICY='korean_restoration_variants_v1'


def expression_projection(text, expected):
    """Comparison only: complete Korean words, never arbitrary substrings/code.

    Preserve each raw reading. Render just the two authorized pairs in the
    candidate's spelling; no deletions, paraphrases or fuzzy similarity threshold.
    """
    if re.search(r'''[A-Za-z0-9_`'"=<>+*/\\\[\]{}]''',text+expected):return text
    for a,b,suffix in [('이런','요런',''),('메서드','메소드','(?:를|는|가|의|로|에|도|만|와|과|에서|으로)?')]:
        def pattern(word):return r'(?<![가-힣A-Za-z0-9_])'+word+r'(?='+suffix+r'(?:\s|[.,!?]|$))'
        has_a=bool(re.search(pattern(a),expected));has_b=bool(re.search(pattern(b),expected))
        if has_a != has_b:
            text=re.sub(pattern(b if has_a else a),a if has_a else b,text)
    return text


def comparison_evidence(t,b,r):
    """Return a labeled comparison view, not replacement acoustic evidence."""
    if t.get('expression_policy')!=EXPRESSION_POLICY or t['mode']!='restore' or t['before'] or t.get('candidate',{}).get('finding',{}).get('action')!='insert':
        return b,r
    # Raw span/ownership problems cannot be hidden by normalization.
    if base.scope_reasons(t,b,'text') or base.scope_reasons(t,r,'literal_text'):return b,r
    left,right=copy.deepcopy(b),copy.deepcopy(r)
    left['text']=expression_projection(left['text'],t['after'])
    right['literal_text']=expression_projection(right['literal_text'],t['after'])
    for value in (left,right):
        for span in value['target_spans']:
            span['text']=expression_projection(span['text'],t['after'])
    # Addition evidence is deliberately NOT normalized: the proposal must already
    # have explicit supporting addition spans in the reviewer response.
    return left,right


def gate(t,b,r):
    g=prior.gate(t,b,r)
    if t.get('expression_policy')==EXPRESSION_POLICY and t['mode']=='restore':
        left,right=comparison_evidence(t,b,r)
        compared=base.decision(t,left,right)
        g={**compared,'comparison_policy':EXPRESSION_POLICY,
           'raw_differences':g.get('differences',{}),'raw_readings_preserved':True,
           'representation_difference_accepted':compared['passed'] and not g['passed']}
    if t['mode']=='impact_review' and g['passed']:
        # No semantic projection for release: two scoped literal readings must match
        # the existing text, allowing whitespace/punctuation only.
        exact=all(base.text_difference(t['before'],v) in ('exact','format_only')
                  for v in (b['text'],r['literal_text']))
        if exact:g={**g,'status':'original_confirmed','verbatim_verified':False}
    return g


def verify(out,archived=False):
    # prior verifies the source PCM, input hashes and all primary/context bindings.
    p=prior.verify(out)
    expected=ARCHIVED_SCOPE_CODE if archived else digest_file(__file__)
    if p.get('scope_code_hash')!=expected:raise ValueError('scope_code_changed_choose_new_output')
    if archived and any(t.get('expression_policy') for t in p['tasks']):raise ValueError('unexpected_archived_policy')
    return p


def results(out,p):
    done={}
    for t in p['tasks']:
        f=out/'results'/(t['id']+'.json')
        if not f.exists():continue
        r=read(f);binding=base.primary_context_bundle(out,t)[1]
        if r['plan_signature']!=signature(p) or r['task_id']!=t['id'] or r['input_bindings']!={'blind':binding,'review':binding}:
            raise ValueError('stale_or_wrong_audio_result')
        if r['gate']!=gate(t,r['blind'],r['review']):raise ValueError('gate_changed')
        done[t['id']]=r
    return done


def body_candidate(t,r):
    """Propose, never approve, a common suffix with a source-timed start.

    Only short connective-prefix uncertainty can be isolated automatically. Content,
    numbers, negation, technical terms or repetition disagreements cannot be cropped away.
    """
    if t['mode']!='restore' or t['before'] or r['gate']['passed']:raise ValueError('not_failed_gap')
    b,review=r['blind'],r['review']
    left,right=b['text'].split(),review['literal_text'].split()
    n=0
    while n<min(len(left),len(right)) and left[-n-1]==right[-n-1]:n+=1
    # Keep the entire connective with its disputed prefix, not a dangling '하는'.
    if n and left[-n]=='하는':n-=1
    if n<5:raise ValueError('insufficient_common_body')
    prefixes=[' '.join(x[:-n]) for x in (left,right)]
    if any(x not in ('이라고 하는','느라고 하는','라고 하는','이라고','라고') for x in prefixes):
        raise ValueError('substantive_prefix_cannot_be_ignored')
    text=' '.join(left[-n:]);spans=b['target_spans'];start=None
    for i,span in enumerate(spans):
        if canonical(' '.join(s['text'] for s in spans[i:]))==canonical(text):
            start=span['start_seconds'];break
    if start is None or not 0<start<t['interval'][1]-t['interval'][0]:raise ValueError('body_start_evidence_missing')
    return text,[round(t['interval'][0]+start,6),t['interval'][1]]


def build_bundle(snapshot,tasks,done):
    snap=copy.deepcopy(snapshot);resolved=[];boundaries=[]
    fresh=any(t['mode']=='normal_control' and done[t['id']]['gate']['passed'] for t in tasks)
    # A partial body is a new source-bound candidate. Only its successful NEW reading
    # can replace the old whole-gap hypothesis; the excluded prefix remains a queue item.
    for t in tasks:
        if not t.get('parent_gap'):continue
        parent=t['parent_gap'];passed=done[t['id']]['gate']['passed'] and fresh
        boundaries.append({'task_id':t['id'],'interval':[parent[0],t['interval'][0]],
            'status':'held_boundary','original_gap':parent,'body_restored':False,
            'reason':'Uncertain connective prefix; never inferred from context',
            'readings':t['prefix_readings'],'eligible_for_chunking':False})
        if not passed:continue
        keep=[]
        for c in snap['parent_snapshot']['held']:
            f=c['finding']
            if f['kind']=='missing_utterance' and f['action']=='insert' and not f['target_id'] and parent[0]<=f['start']<f['end']<=parent[1]:
                resolved.append(c)
            else:keep.append(c)
        snap['parent_snapshot']['held']=keep
    comparison_done=copy.deepcopy(done)
    comparisons=[]
    for t in tasks:
        raw=done[t['id']]
        if raw['gate']!=gate(t,raw['blind'],raw['review']):raise ValueError('gate_evidence_mismatch')
        if t.get('expression_policy')!=EXPRESSION_POLICY:continue
        b,r=comparison_evidence(t,raw['blind'],raw['review'])
        comparison_done[t['id']].update(blind=b,review=r,gate=base.decision(t,b,r))
        comparisons.append({'task_id':t['id'],'policy':EXPRESSION_POLICY,
            'raw_blind':raw['blind']['text'],'raw_review':raw['review']['literal_text'],
            'comparison_blind':b['text'],'comparison_review':r['literal_text'],
            'proposed_text_preserved':t['after'],'gate':raw['gate']})
    bundle=prior.build_bundle(snap,tasks,comparison_done)
    # Release only the resolved task's own hold, never unrelated coverage/content flags.
    released=[]
    for t in tasks:
        if done[t['id']]['gate'].get('status')!='original_confirmed' or not fresh:continue
        if any(base.task_conflict(t,o) for o in tasks if o['id']!=t['id']):continue
        rec=next((r for r in bundle['excluded'] if r['id']==t['target_id']),None)
        if rec is None:continue
        own=t.get('candidate',{}).get('finding')
        conflicts=[f for f in bundle['held_findings'] if base.affected(
            {'id':t['target_id'],'start_seconds':t['interval'][0],'end_seconds':t['interval'][1]},f)]
        if any(not own or f!=own for f in conflicts):continue
        allowed={'unresolved_coverage_finding','existing_text_control_needs_review','low_impact_error_administrator_review'}
        if set(rec['selection_reasons'])-allowed:continue
        rec.update(eligible_for_chunking=True,judgment='original_source_reconfirmed',
                   reasons=[],selection_reasons=[],verification='two_scoped_literal_readings_match_original',gold_approved=False)
        rec.pop('impact_review',None)
        # Remove hold-specific false flags rather than assert downstream deployment.
        for k in ('approved_for_rag','eligible_for_generation'):rec.pop(k,None)
        released.append({'task_id':t['id'],'record_id':rec['id'],'text':rec['observed_text'],
                         'reason':'Two source-bound readings match the unchanged original'})
    ids={x['record_id'] for x in released}
    bundle['administrator_holds']=[x for x in bundle['administrator_holds'] if x['record_id'] not in ids]
    records=bundle['selected']+bundle['excluded']
    bundle['selected']=[r for r in records if r['eligible_for_chunking']]
    bundle['excluded']=[r for r in records if not r['eligible_for_chunking']]
    source_hash=snap['parent_snapshot']['source_plan']['source_sha256']
    bundle['combined']=[r for r in snap['parent_snapshot']['previous_usable'] if not(r['modality']=='audio' and r['source_sha256']==source_hash)]+bundle['selected']
    for b in boundaries:
        b['body_restored']=any(t['id']==b['task_id'] and bundle['application_decisions'].get(t['id'],{}).get('apply') for t in tasks)
    # Record the supersession only if the new body actually applied.
    if resolved and not any(b['body_restored'] for b in boundaries):raise ValueError('gap_split_not_applied')
    bundle.update(released_originals=released,boundary_holds=boundaries,expression_comparisons=comparisons)
    bundle['resolved_gap_hypotheses']+=resolved
    return bundle


def publish(out,p,done):
    bundle=build_bundle(read(out/'snapshot.json'),p['tasks'],done)
    revision=signature({'plan':signature(p),'results':done})[:24];folder=out/'revisions'/revision
    data={'full-transcript.corrected.jsonl':bundle['rows'],'audio-records.jsonl':bundle['selected']+bundle['excluded'],
          'usable-audio.jsonl':bundle['selected'],'review-required-audio.jsonl':bundle['excluded'],
          'usable-records.jsonl':bundle['combined'],'new-restorations.jsonl':bundle['new_restorations'],
          'administrator-review.jsonl':bundle['administrator_holds'],'released-originals.jsonl':bundle['released_originals'],
          'expression-comparisons.jsonl':bundle['expression_comparisons'],
          'boundary-review.jsonl':bundle['boundary_holds'],'superseded-gap-findings.jsonl':bundle['resolved_gap_hypotheses']}
    mp=folder/'manifest.json'
    if mp.exists():
        manifest=read(mp)
        for name,h in manifest['file_hashes'].items():
            if digest_file(folder/name)!=h:raise ValueError('published_revision_changed')
    else:
        folder.mkdir(parents=True,exist_ok=True)
        for name,rows in data.items():jsonl(folder/name,rows)
        manifest={'revision':revision,'plan_signature':signature(p),'previous_repairs_preserved':True,
                  'new_restorations':len(bundle['new_restorations']),'released_originals':len(bundle['released_originals']),
                  'administrator_holds':len(bundle['administrator_holds']),'boundary_holds':len(bundle['boundary_holds']),
                  'usable_audio':len(bundle['selected']),'review_required_audio':len(bundle['excluded']),
                  'usable_total':len(bundle['combined']),'accuracy_pct':None,
                  'file_hashes':{name:digest_file(folder/name) for name in data}}
        save(mp,manifest)
    save(out/'latest.json',{'revision':revision,'manifest':str(mp),'usable_records':str(folder/'usable-records.jsonl'),
                          'usable_audio':str(folder/'usable-audio.jsonl')})
    return manifest


def report(out,p):
    done=results(out,p)
    s={'tasks':len(p['tasks']),'completed':len(done),'remaining':len(p['tasks'])-len(done),
       'reused':sum('reused_from' in r for r in done.values()),
       'api_attempts':sum(len(read(f)['attempts']) for f in (out/'runs').glob('*.json'))}
    if (out/'latest.json').exists():s.update(read(read(out/'latest.json')['manifest']))
    save(out/'summary.json',s)
    page='<meta charset="utf-8"><title>음성 원문 확인·본문 복원</title><style>body{font:17px/1.7 system-ui;max-width:1000px;margin:30px auto}pre{white-space:pre-wrap}</style><h1>원문 일치 보류 해제 · 메소드 본문 복원</h1>'
    page+='<p>원문 일치는 수정 없이 해제합니다. 영향 낮은 실제 차이는 관리자 보류를 유지합니다. 본문 복원은 새 대상 원음 재검사 후 반영하며 앞부분은 별도 보류합니다. 모델 검증 결과이며 정답지 정확도는 아닙니다.</p><pre>'+html.escape(json.dumps({k:v for k,v in s.items() if k!='file_hashes'},ensure_ascii=False,indent=2))+'</pre>'
    if (out/'latest.json').exists():
        rev=read(out/'latest.json')['revision']
        for f in ('released-originals.jsonl','new-restorations.jsonl','administrator-review.jsonl','boundary-review.jsonl','usable-records.jsonl'):
            page+=f'<p><a href="revisions/{rev}/{f}">{f}</a></p>'
    for t in p['tasks']:
        r=done.get(t['id']);g=r['gate'] if r else {}
        label='미실행' if not r else '원문 일치 · 해제 판정' if g.get('status')=='original_confirmed' else '관리자 검토' if g.get('status')=='administrator_hold_low_impact' else '검사 통과' if g.get('passed') else '보류'
        page+=f'<details><summary>{t["interval"]} · {label}</summary><p>원문: {html.escape(t["before"])}</p><p>후보: {html.escape(t["after"])}</p><audio controls src="{Path(t["target_clip"]).as_uri()}"></audio><pre>'+html.escape(json.dumps(g,ensure_ascii=False,indent=2))+'</pre></details>'
    (out/'음성복원_범위분리검토.html').write_text(page,encoding='utf-8')
    return s


def prepare(out=OUT,source=prior.OUT,split=False):
    out,source=Path(out).resolve(),Path(source).resolve()
    if out==source or out in source.parents or source in out.parents:raise ValueError('overlapping_output')
    with lock(out),lock(source):
        if (out/'plan.json').exists():return verify(out)
        old=(verify if split else prior.verify)(source)
        done=(results if split else prior.results)(source,old)
        if len(done)!=len(old['tasks']):raise ValueError('incomplete_source')
        latest=read(source/'latest.json');mp=Path(latest['manifest']);manifest=read(mp)
        if manifest['plan_signature']!=signature(old):raise ValueError('wrong_source_revision')
        for f,h in manifest['file_hashes'].items():
            if digest_file(mp.parent/f)!=h:raise ValueError('changed_source_revision')
        p=copy.deepcopy(old);p.update(created_at=now(),scope_code_hash=digest_file(__file__),reused_source=str(source),split_body=split)
        inputs=[source/'plan.json',source/'snapshot.json',source/'latest.json',mp]
        inputs += [mp.parent/f for f in manifest['file_hashes']]
        inputs += [source/'results'/(t['id']+'.json') for t in old['tasks']]
        p['inputs'].update({str(f):digest_file(f) for f in inputs})
        snap=read(source/'snapshot.json');save(out/'snapshot.json',snap)
        p['snapshot_sha256']=digest_file(out/'snapshot.json');pending=set()
        if split:
            for t in p['tasks']:
                if t['mode']!='restore' or done[t['id']]['gate']['passed']:continue
                text,interval=body_candidate(t,done[t['id']]);t['parent_gap']=t['interval'];t['interval']=interval;t['after']=text
                t['prefix_readings']=[done[t['id']]['blind']['text'],done[t['id']]['review']['literal_text']]
                f=copy.deepcopy(t['candidate']['finding']);f.update(start=interval[0],end=interval[1],after=text)
                window=next(w for w in snap['parent_snapshot']['source_plan']['windows'] if w['label']==t['owner'])
                c=base.core.check_finding(f,window,snap['base_rows'],text);c['batch_conflict']=False
                if not c['candidate']:raise ValueError('body_candidate_local_gate_failed:'+str(c['reasons']))
                t['candidate']=c
                clip=out/'clips'/(t['id']+'-body.wav');clip.parent.mkdir(exist_ok=True)
                t['target_clip']=str(clip);t['target_clip_meta']=base.clip(Path(p['source_audio']),clip,*interval)
                t['target_sample_check']=base.verify_slice(p['source_audio'],clip,t['target_clip_meta'],interval)
                pending.add(t['id'])
        p['nominal_api_calls']=2*len(pending);save(out/'plan.json',p)
        for t in p['tasks']:
            if t['id'] in pending:continue
            r=copy.deepcopy(done[t['id']]);r.update(plan_signature=signature(p),reused_from=str(source/'results'/(t['id']+'.json')),
                gate=gate(t,r['blind'],r['review']))
            save(out/'results'/(t['id']+'.json'),r)
        verify(out)
        if not pending:publish(out,p,results(out,p))
        report(out,p);return p


def recheck_expressions(out=EXPRESSIONS,source=BODY):
    """Offline re-evaluation of a pinned predecessor, with unchanged audio inputs."""
    out,source=Path(out).resolve(),Path(source).resolve()
    if out==source or out in source.parents or source in out.parents:raise ValueError('overlapping_output')
    with lock(out),lock(source):
        if (out/'plan.json').exists():
            p=verify(out);publish(out,p,results(out,p));return report(out,p)
        old=verify(source,archived=True);done=results(source,old)
        if len(done)!=len(old['tasks']):raise ValueError('incomplete_source')
        mp=Path(read(source/'latest.json')['manifest']);manifest=read(mp)
        if manifest['plan_signature']!=signature(old):raise ValueError('wrong_source_revision')
        for name,h in manifest['file_hashes'].items():
            if digest_file(mp.parent/name)!=h:raise ValueError('changed_source_revision')
        p=copy.deepcopy(old);p.update(created_at=now(),scope_code_hash=digest_file(__file__),
            reused_source=str(source),nominal_api_calls=0,expression_policy=EXPRESSION_POLICY)
        files=[source/'plan.json',source/'snapshot.json',source/'latest.json',mp]
        files += [mp.parent/name for name in manifest['file_hashes']]
        files += [source/'results'/(t['id']+'.json') for t in old['tasks']]
        p['inputs'].update({str(f):digest_file(f) for f in files})
        for t in p['tasks']:
            if t['mode']=='restore':t['expression_policy']=EXPRESSION_POLICY
        save(out/'snapshot.json',read(source/'snapshot.json'))
        p['snapshot_sha256']=digest_file(out/'snapshot.json');save(out/'plan.json',p)
        for t in p['tasks']:
            r=copy.deepcopy(done[t['id']]);r.update(plan_signature=signature(p),
                reused_from=str(source/'results'/(t['id']+'.json')),gate=gate(t,r['blind'],r['review']))
            save(out/'results'/(t['id']+'.json'),r)
        verify(out);publish(out,p,results(out,p));s=report(out,p)
        save(out/'run-state.json',{'stop_reason':'complete_offline_recheck','api_calls_this_run':0})
        return s


def run(out,env_file,maximum=20,delay=15):
    with lock(out):
        p=verify(out);done=results(out,p);budget=Budget(out,maximum,delay);error=None
        client=None
        if len(done)<len(p['tasks']):
            api_key(env_file);client=Gemini(out/'gemini-cache',p['model'],env_file,max_calls=maximum,delay=0,transport=budget)
        try:
            for t in p['tasks']:
                if t['id'] in done:continue
                media,binding,data,neighbors=base.primary_context_bundle(out,t)
                b=client.call('audio-body-blind-v2',media,base.V4_BLIND_PROMPT+json.dumps(data,ensure_ascii=False),base.BLIND_V4)
                if base.primary_context_bundle(out,t)[1]!=binding:raise ValueError('audio_changed_between_calls')
                payload={**data,'current_text':t['before'],'neighboring_transcripts_text_only':neighbors,
                         'proposed_text':t['after'],'added_fragments':base.additions(t['before'],t['after'])}
                r=client.call('audio-body-recheck-v2',media,base.V4_REVIEW_PROMPT+json.dumps(payload,ensure_ascii=False),base.REVIEW_V4)
                if base.primary_context_bundle(out,t)[1]!=binding:raise ValueError('audio_changed_during_review')
                value={'task_id':t['id'],'plan_signature':signature(p),'blind':b,'review':r,'gate':gate(t,b,r),
                       'input_bindings':{'blind':binding,'review':binding},'at':now()}
                save(out/'results'/(t['id']+'.json'),value);done[t['id']]=value
                print(json.dumps({'completed':len(done),'total':len(p['tasks']),'api_calls':budget.used}),flush=True)
            publish(out,p,done)
        except (Blocked,KeyboardInterrupt) as ex:error=str(ex) or 'interrupted'
        except Exception:
            error='validation_or_local_failure';raise
        finally:save(out/'run-state.json',{'stop_reason':error or 'complete','api_calls_this_run':budget.used,'summary':report(out,p)})
        if error:raise Blocked(error)
        return report(out,p)


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('mode',choices=['reclassify','prepare-body','run','report','recheck-expressions'])
    ap.add_argument('--max-api-calls',type=int,default=20);ap.add_argument('--delay',type=float,default=15)
    a=ap.parse_args()
    try:
        if a.mode=='recheck-expressions':value=recheck_expressions()
        elif a.mode=='reclassify':prepare();value=report(OUT,verify(OUT))
        elif a.mode=='prepare-body':prepare(BODY,OUT,True);value=report(BODY,verify(BODY))
        elif a.mode=='run':value=run(BODY,ROOT/'.env',a.max_api_calls,a.delay)
        else:value=report(BODY,verify(BODY))
        print(json.dumps({k:v for k,v in value.items() if k!='file_hashes'},ensure_ascii=False,indent=2));return 0
    except (Blocked,ValueError,OSError) as ex:
        print(json.dumps({'stopped':str(ex)},ensure_ascii=False));return 2

if __name__=='__main__':raise SystemExit(main())
