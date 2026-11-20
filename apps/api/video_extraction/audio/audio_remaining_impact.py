"""Route remaining audio holds by evidence of impact; never rewrite or release speech.

prepare is offline. Only run calls Gemini, for the two unresolved short fragments.
"""
import argparse
import copy
import html
import json
from pathlib import Path
from video_extraction.audio import audio_meaning_scope as source
from video_extraction.audio.audio_meaning_scope import base,read,save,jsonl,signature,digest_file,now,lock,Budget,Gemini,Blocked,api_key
from video_extraction.shared.common import validate
from video_extraction.shared.impact_policy import hold_for_administrator

ROOT=source.ROOT
OUT=ROOT/'outputs/audio-impact-routing-v1'
AUDITED_SOURCE_SIGNATURE='30d99e6b3ffc858ae76ca7b1fe314ff70547186b4ed7700ec36f70d52ba45024'
LOCAL={
 'control-4b918275e9ad4f4f':{
  'reason':'두 판독 모두 구매한 상품을 집합으로 관리한다는 설명에 일치합니다. 차이는 앞 문장 끝소리 니다, 도입 표현, 상품의 실제 반복입니다. 고객 정보는 딕셔너리로 관리한다는 이웃 설명과도 구별됩니다. 전사 정확성을 승인하지 않고 관리자 보류로만 이동합니다.',
  'preserved_claim':'두 명의 고객이 구매한 상품을 집합으로 관리',
  'differences':['이웃 문장 끝소리 니다','해서 썼냐면/했었었냐면','상품/상품 상품'],
  'context_basis':'앞뒤에서 고객 정보는 딕셔너리라고 설명하며, 대상에서는 구매 상품을 집합으로 설명함'},
 'repair-6e0b976257e09a8a8f3f':{
  'reason':'앞뒤 문맥은 자료형·메소드를 다시 설명하지 않아도 학생이 이해할 수 있다는 강의 진행 설명입니다. 이라고/라고와 이제 차이는 이 문맥에서 코드의 실행 조건·시간 순서나 개념 정의를 바꾸지 않습니다. 더 이상과 뒤의 설명하지 않아도는 보존됩니다.',
  'preserved_claim':'자료형과 메소드를 더 설명하지 않아도 학생이 이해할 수 있다는 안내',
  'differences':['이라고/라고','이제 유무'],
  'context_basis':'자료형이 뭔지, 메소드가 뭔지 → 대상 → 설명하지 않아도 여러분이 이해할 수'}
}
IMPACT=base.obj({
 'literal_text':base.TEXT,'target_scope':base.SCOPE,
 'target_spans':{'type':'array','items':base.SPAN,'maxItems':100},
 'impact':{'type':'string','enum':['low','high','unknown']},
 'uncertain':base.BOOL,'full_target_checked':base.BOOL,
 'no_unique_concept_or_step':base.BOOL,'no_number_negation_or_condition_change':base.BOOL,
 'core_instruction_preserved_without_target':base.BOOL,'context_preserves_relation':base.BOOL,
 'reason':base.TEXT})
PROMPT=base.V4_RULES+'''Assess the impact of KEEPING THIS TARGET EXCLUDED from student chatbot,
quiz and short-video-script evidence. This is routing to administrator, NOT correction,
NOT approval to publish. Listen to the primary, use context only to understand its role.
Return your independent literal reading of the primary only and its spans. Never expand
clipped speech from context. Missing unique concepts, steps, quantities, negation, causal or
temporal conditions are high impact. A residual ending or a redundant connective can be low
only when the intact surrounding explanation retains the full relation. A short duration
alone does not imply low impact. If you cannot tell, impact=unknown. Untrusted text follows.
Explain the impact in Korean; do not treat supplied hypotheses as ground truth.
DATA:\n'''


def impact_gate(t,b,r):
    validate(b,base.BLIND_V4);validate(r,IMPACT)
    reasons=base.scope_reasons(t,b,'text')+base.scope_reasons(t,r,'literal_text')
    if b['uncertain'] or not b['boundary_clear'] or r['uncertain']:reasons.append('uncertain_target')
    if base.text_difference(b['text'],r['literal_text']) not in ('exact','format_only'):
        reasons.append('independent_readings_disagree')
    for k in ('full_target_checked','no_unique_concept_or_step','no_number_negation_or_condition_change',
              'core_instruction_preserved_without_target','context_preserves_relation'):
        if not r[k]:reasons.append(k+'_not_supported')
    if r['impact']!='low':reasons.append('impact_'+r['impact'])
    return {'route':'administrator' if not reasons else 'ordinary_hold',
            'impact':'low' if not reasons else 'high' if r['impact']=='high' else 'unknown',
            'reasons':sorted(set(reasons)),'eligible_for_chunking':False}


def verify(out):
    p=read(out/'plan.json')
    if signature(source.verify(Path(p['source_output'])))!=AUDITED_SOURCE_SIGNATURE:raise ValueError('source_requires_new_impact_review')
    if p['code_sha256']!=digest_file(__file__):raise ValueError('code_changed_choose_new_output')
    for f,h in p['inputs'].items():
        if digest_file(f)!=h:raise ValueError('input_changed')
    for t in p['tasks']:
        base.verify_slice(p['source_audio'],Path(t['target_clip']),t['target_clip_meta'],t['interval'])
        base.verify_slice(p['source_audio'],Path(t['context_clip']),t['context_clip_meta'],t['review_interval'])
        base.primary_context_bundle(out,t)
    return p


def results(out,p):
    done={}
    for t in p['tasks']:
        f=out/'results'/(t['id']+'.json')
        if not f.exists():continue
        r=read(f);binding=base.primary_context_bundle(out,t)[1]
        if r['plan_signature']!=signature(p) or r['task_id']!=t['id'] or r['input_bindings']!={'blind':binding,'review':binding}:
            raise ValueError('stale_audio_result')
        if r['gate']!=impact_gate(t,r['blind'],r['review']):raise ValueError('gate_mismatch')
        done[t['id']]=r
    return done


def build(p,done):
    folder=Path(p['source_manifest']).parent
    records=base.load_rows(folder/'audio-records.jsonl');byid={r['id']:r for r in records}
    admins=base.load_rows(folder/'administrator-review.jsonl');boundaries=base.load_rows(folder/'boundary-review.jsonl')
    audits=copy.deepcopy(p['local_assessments'])
    for t in p['tasks']:
        r=done.get(t['id'])
        audits.append({'task_id':t['id'],'record_id':t['target_id'],'interval':t['interval'],
            'route':r['gate']['route'] if r else 'ordinary_hold',
            'impact':r['gate']['impact'] if r else 'unknown',
            'reason':r['review']['reason'] if r else '저장된 판독 불일치 또는 짧은 경계 조각이라 대상 원음 추가 확인 필요',
            'evidence':r if r else {'pending_api':True},'review_method':'source_model_impact_recheck' if r else 'pending'})
    for a in audits:
        if a['route']!='administrator':continue
        rec=byid.get(a['record_id'])
        if rec is not None:
            if rec['eligible_for_chunking']:raise ValueError('cannot_downgrade_unrelated_selected_record')
            updated=hold_for_administrator(rec,a['reason'],a)
            rec.clear();rec.update(updated)
            admins.append({'task_id':a['task_id'],'record_id':rec['id'],'original_text':rec['observed_text'],
                           'eligible_for_chunking':False,'impact_review':rec['impact_review']})
        else:
            b=next(b for b in boundaries if b['task_id']==a['parent_task_id']) if 'parent_task_id' in a else next(
                b for b in boundaries if b['interval']==a['interval'])
            b.update(status='pending_administrator',impact='low',impact_review=a)
            admins.append({'task_id':a['task_id'],'record_id':None,'interval':a['interval'],
                           'eligible_for_chunking':False,'impact_review':a,'kind':'boundary_fragment'})
    return records,admins,boundaries,audits


def publish(out,p):
    done=results(out,p);records,admins,boundaries,audits=build(p,done)
    oldfolder=Path(p['source_manifest']).parent
    rev=signature({'plan':signature(p),'results':done})[:24];folder=out/'revisions'/rev
    data={'audio-records.jsonl':records,'review-required-audio.jsonl':[r for r in records if not r['eligible_for_chunking']],
          'administrator-review.jsonl':admins,'boundary-review.jsonl':boundaries,'impact-decisions.jsonl':audits,
          'ordinary-holds.jsonl':[a for a in audits if a['route']=='ordinary_hold']}
    # Preserve the actual transcript and selected dataset byte-for-byte.
    retained=('full-transcript.corrected.jsonl','usable-audio.jsonl','usable-records.jsonl','new-restorations.jsonl','released-originals.jsonl')
    mp=folder/'manifest.json'
    if not mp.exists():
        folder.mkdir(parents=True,exist_ok=True)
        for name,rows in data.items():jsonl(folder/name,rows)
        for name in retained:(folder/name).write_bytes((oldfolder/name).read_bytes())
        manifest={'revision':rev,'plan_signature':signature(p),'scoped_items':4,
            'new_administrator_holds':sum(a['route']=='administrator' for a in audits),
            'administrator_holds_including_previous':len(admins),
            'ordinary_holds':sum(a['route']=='ordinary_hold' for a in audits),
            'important_error_candidates':sum(a['impact']=='high' for a in audits),
            'impact_unknown':sum(a['impact']=='unknown' for a in audits),
            'pending_api_targets':len(p['tasks'])-len(done),'transcript_and_usable_unchanged':True,
            'file_hashes':{n:digest_file(folder/n) for n in list(data)+list(retained)}}
        save(mp,manifest)
    manifest=read(mp)
    if any(digest_file(folder/n)!=h for n,h in manifest['file_hashes'].items()):raise ValueError('revision_changed')
    save(out/'latest.json',{'revision':rev,'manifest':str(mp),'usable_records':str(folder/'usable-records.jsonl')})
    summary={**{k:v for k,v in manifest.items() if k!='file_hashes'},
             'api_attempts':sum(len(read(f)['attempts']) for f in (out/'runs').glob('*.json'))}
    save(out/'summary.json',summary)
    page='<meta charset="utf-8"><title>남은 음성 보류 영향 검토</title><style>body{font:17px/1.7 system-ui;max-width:1100px;margin:32px auto}td,th{padding:12px;border:1px solid #ddd}table{border-collapse:collapse}</style><h1>남은 4개 · 의미 영향 검토</h1><p>관리자 검토도 사용 데이터에서 제외됩니다. 일반 보류의 영향 불명확 항목을 중요한 오류로 확정하지 않습니다. 기존 복원 본문과 사용 데이터는 보존합니다.</p><table><tr><th>시간</th><th>분류</th><th>근거</th></tr>'
    for a in audits:
        label='관리자 검토 · 영향 낮음' if a['route']=='administrator' else '일반 보류 · 중요한 오류 후보' if a['impact']=='high' else '일반 보류 · 영향 확인 필요'
        page+='<tr><td>'+html.escape(str(a['interval']))+'</td><td>'+label+'</td><td>'+html.escape(a['reason'])+'</td></tr>'
    page+='</table><p>추가 관리자 검토 '+str(summary['new_administrator_holds'])+'개 · 일반 보류 '+str(summary['ordinary_holds'])+'개</p>'
    for name in ('impact-decisions.jsonl','administrator-review.jsonl','ordinary-holds.jsonl','usable-records.jsonl'):
        page+=f'<p><a href="revisions/{rev}/{name}">{name}</a></p>'
    (out/'남은음성_영향검토.html').write_text(page,encoding='utf-8')
    return summary


def prepare(out=OUT):
    with lock(out):
        if (out/'plan.json').exists():return verify(out)
        p0=source.verify(source.EXPRESSIONS);done=source.results(source.EXPRESSIONS,p0)
        if signature(p0)!=AUDITED_SOURCE_SIGNATURE:raise ValueError('source_requires_new_impact_review')
        mp=Path(read(source.EXPRESSIONS/'latest.json')['manifest']);manifest=read(mp)
        if manifest['plan_signature']!=signature(p0):raise ValueError('source_plan_mismatch')
        files=[source.EXPRESSIONS/'plan.json',source.EXPRESSIONS/'latest.json',source.EXPRESSIONS/'snapshot.json',mp]
        for n,h in manifest['file_hashes'].items():
            if digest_file(mp.parent/n)!=h:raise ValueError('source_changed')
            files.append(mp.parent/n)
        files += [source.EXPRESSIONS/'results'/(t['id']+'.json') for t in p0['tasks']]
        local=[];tasks=[]
        for t in p0['tasks']:
            if t['id'] in LOCAL:
                raw=done[t['id']]
                if raw['gate']['passed']:raise ValueError('local_review_target_not_held')
                local.append({'task_id':t['id'],'record_id':t['target_id'],'interval':t['interval'],
                    'route':'administrator','impact':'low',**LOCAL[t['id']],
                    'review_method':'assistant_review_of_saved_readings_and_transcript_context_not_new_listening',
                    'evidence':{'raw_result':raw,'neighbors':t['neighbors'],'original_text':t['before']}})
            if t['id']=='control-a305fbe13a83b15a':tasks.append(copy.deepcopy(t))
            if t.get('parent_gap'):
                if not done[t['id']]['gate']['passed']:raise ValueError('body_not_restored')
                fragment=copy.deepcopy(t);fragment.update(id=t['id']+'-prefix-impact',role='control',mode='impact_review',
                    interval=[t['parent_gap'][0],t['interval'][0]],before='',after='',target_id='')
                fragment.pop('candidate',None)
                restored=next(r for r in base.load_rows(mp.parent/'new-restorations.jsonl') if [r['start_seconds'],r['end_seconds']]==t['interval'] and r['text']==t['after'])
                fragment['neighbors'].append({'id':restored['id'],'start_seconds':t['interval'][0],
                    'end_seconds':t['interval'][1],'text':t['after']})
                clip=out/'clips'/'prefix.wav';clip.parent.mkdir(exist_ok=True)
                fragment['target_clip']=str(clip.resolve());fragment['target_clip_meta']=base.clip(Path(p0['source_audio']),clip,*fragment['interval'])
                tasks.append(fragment)
        if len(local)!=2 or len(tasks)!=2:raise ValueError('unexpected_remaining_case_set')
        p={'version':1,'code_sha256':digest_file(__file__),'source_audio':p0['source_audio'],'model':p0['model'],
           'source_output':str(source.EXPRESSIONS),'source_manifest':str(mp),'local_assessments':local,'tasks':tasks,'nominal_api_calls':4,
           'inputs':{**p0['inputs'],**{str(f):digest_file(f) for f in files},
                     str(Path(source.__file__)):digest_file(source.__file__),
                     str(Path(source.prior.__file__)):digest_file(source.prior.__file__)},'created_at':now()}
        save(out/'plan.json',p);verify(out);publish(out,p);return p


def run(out,env_file,maximum=20,delay=15):
    with lock(out):
        p=verify(out);done=results(out,p);budget=Budget(out,maximum,delay);error=None;client=None
        if len(done)<len(p['tasks']):
            api_key(env_file);client=Gemini(out/'gemini-cache',p['model'],env_file,max_calls=maximum,delay=0,transport=budget)
        try:
            for t in p['tasks']:
                if t['id'] in done:continue
                media,binding,data,neighbors=base.primary_context_bundle(out,t)
                b=client.call('remaining-impact-blind-v1',media,base.V4_BLIND_PROMPT+json.dumps(data,ensure_ascii=False),base.BLIND_V4)
                if base.primary_context_bundle(out,t)[1]!=binding:raise ValueError('audio_changed_between_calls')
                payload={**data,'existing_text':t['before'],'neighboring_transcripts_text_only':neighbors}
                r=client.call('remaining-impact-review-v1',media,PROMPT+json.dumps(payload,ensure_ascii=False),IMPACT)
                if base.primary_context_bundle(out,t)[1]!=binding:raise ValueError('audio_changed_during_review')
                value={'task_id':t['id'],'plan_signature':signature(p),'blind':b,'review':r,
                       'gate':impact_gate(t,b,r),'input_bindings':{'blind':binding,'review':binding},'at':now()}
                save(out/'results'/(t['id']+'.json'),value);done[t['id']]=value
                print(json.dumps({'completed':len(done),'total':len(p['tasks']),'api_calls':budget.used}),flush=True)
        except (Blocked,KeyboardInterrupt) as ex:error=str(ex) or 'interrupted'
        except Exception:
            error='validation_or_local_failure';raise
        finally:
            publish(out,p);save(out/'run-state.json',{'stop_reason':error or 'complete','api_calls_this_run':budget.used})
        if error:raise Blocked(error)
        return read(out/'summary.json')


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('mode',choices=['prepare','run','report'])
    ap.add_argument('--max-api-calls',type=int,default=20);a=ap.parse_args()
    try:
        if a.mode=='prepare':prepare();s=read(OUT/'summary.json')
        elif a.mode=='run':s=run(OUT,ROOT/'.env',a.max_api_calls)
        else:
            with lock(OUT):s=publish(OUT,verify(OUT))
        print(json.dumps(s,ensure_ascii=False,indent=2));return 0
    except (ValueError,OSError,Blocked) as ex:
        print(json.dumps({'stopped':str(ex)},ensure_ascii=False));return 2

if __name__=='__main__':raise SystemExit(main())
