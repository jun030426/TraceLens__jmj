"""Dataset-independent impact routing for normalized audio JSONL.

No lecture IDs, manual case verdicts or fixed output folders are used. Inputs are
immutable. Only run calls Gemini. PCM WAV is the normalized audio input contract.
This stage routes existing holds; it does not extract, repair or approve transcripts.
"""
import argparse
import copy
import json
import math
import wave
from pathlib import Path
from video_extraction.audio import audio_remaining_impact as policy
from video_extraction.audio.audio_meaning_scope import base,read,save,jsonl,signature,digest_file,now,lock,Budget,Gemini,Blocked,api_key
from video_extraction.shared.impact_policy import hold_for_administrator


def hashes():
    return {**base.hashes(),'batch':digest_file(__file__),'impact_policy':digest_file(policy.__file__),
            'admin_router':digest_file(Path(policy.__file__).parents[1]/'shared/impact_policy.py')}


def interval(record,duration):
    a,b=record['start_seconds'],record['end_seconds']
    if any(isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x) for x in (a,b)):
        raise ValueError('invalid_time')
    basis=record.get('time_basis','source_relative')
    offset=record.get('audio_offset_seconds',0)
    if isinstance(offset,bool) or not isinstance(offset,(int,float)) or not math.isfinite(offset):raise ValueError('invalid_offset')
    if basis=='media_absolute':a-=offset;b-=offset
    elif basis!='source_relative' or offset:raise ValueError('ambiguous_time_basis')
    if not 0<=a<b<=duration:raise ValueError('time_outside_audio')
    return [a,b]


def verify(out):
    p=read(out/'plan.json')
    if p['code_hashes']!=hashes():raise ValueError('code_changed_choose_new_output')
    for f,h in p['inputs'].items():
        if digest_file(f)!=h:raise ValueError('input_changed_choose_new_output')
    if digest_file(out/'records.frozen.json')!=p['records_sha256']:raise ValueError('snapshot_changed')
    for t in p['tasks']:
        for k,span in (('target',t['interval']),('context',t['review_interval'])):
            base.verify_slice(t['source_audio'],Path(t[k+'_clip']),t[k+'_clip_meta'],span)
        base.primary_context_bundle(out,t)
    return p


def results(out,p):
    done={}
    for t in p['tasks']:
        f=out/'results'/(t['id']+'.json')
        if not f.exists():continue
        r=read(f);binding=base.primary_context_bundle(out,t)[1]
        if r['plan_signature']!=signature(p) or r['task_id']!=t['id'] or r['input_bindings']!={'blind':binding,'review':binding}:
            raise ValueError('stale_or_mismatched_audio_result')
        if r['gate']!=policy.impact_gate(t,r['blind'],r['review']):raise ValueError('gate_changed')
        done[t['id']]=r
    return done


def prepare(records_path,out,model,context_seconds=3,max_target_seconds=60):
    records_path,out=Path(records_path).resolve(),Path(out).resolve()
    if out==records_path or out in records_path.parents:raise ValueError('output_contains_input')
    if not math.isfinite(context_seconds) or not 0<context_seconds<=30 or not math.isfinite(max_target_seconds) or not 0<max_target_seconds<=300:
        raise ValueError('invalid_clip_settings')
    if not model.strip():raise ValueError('model_required')
    with lock(out):
        if (out/'plan.json').exists():
            p=verify(out)
            if (p['records_path'],p['model'],p['context_seconds'],p['max_target_seconds'])!=(str(records_path),model,context_seconds,max_target_seconds):
                raise ValueError('existing_plan_configuration_differs')
            return p
        records=base.load_rows(records_path);inputs={str(records_path):digest_file(records_path)}
        sources={};valid={};errors=[];tasks=[];seen={}
        # Validate all audio rows so neighbour timestamps never come from another file.
        for i,r in enumerate(records):
            if r.get('modality')!='audio':continue
            try:
                if not isinstance(r.get('id'),str) or not r['id']:raise ValueError('missing_record_id')
                if not isinstance(r.get('eligible_for_chunking'),bool):raise ValueError('missing_selection_state')
                path=Path(r['source_audio']);path=path if path.is_absolute() else records_path.parent/path
                path=path.resolve();key=(str(path),r['id'])
                if key in seen:raise ValueError('duplicate_source_record_id')
                seen[key]=i
                if str(path) not in sources:
                    with wave.open(str(path),'rb') as w:
                        sources[str(path)]={'duration':w.getnframes()/w.getframerate(),'sample_rate':w.getframerate(),'sha256':digest_file(path)}
                    inputs[str(path)]=sources[str(path)]['sha256']
                a,b=interval(r,sources[str(path)]['duration'])
                rate=sources[str(path)]['sample_rate']
                if round(a*rate)>=round(b*rate):raise ValueError('target_shorter_than_one_sample')
                text=r.get('observed_text',r.get('text'))
                if not isinstance(text,str):raise ValueError('missing_text_use_empty_string_for_gap')
                valid[i]={'source':str(path),'interval':[a,b],'text':text}
            except (ValueError,KeyError,OSError,wave.Error,TypeError,EOFError) as ex:
                errors.append({'record_index':i,'record_id':r.get('id'),'reason':str(ex),'route':'ordinary_hold','impact':'unknown'})
                if str(ex)=='duplicate_source_record_id':
                    first=seen[key];valid.pop(first,None)
                    if not any(e['record_index']==first for e in errors):errors.append({'record_index':first,'record_id':r['id'],'reason':'duplicate_source_record_id','route':'ordinary_hold','impact':'unknown'})
        (out/'clips').mkdir(exist_ok=True)
        for i,v in valid.items():
            r=records[i]
            # Selection is explicit. Unknown schema never counts as a verified record.
            if r.get('eligible_for_chunking') is not False:continue
            if r.get('impact_review',{}).get('route')=='administrator':continue
            a,b=v['interval']
            if b-a>max_target_seconds:
                errors.append({'record_index':i,'record_id':r['id'],'reason':'target_requires_segmentation','route':'ordinary_hold','impact':'unknown'});continue
            src=v['source'];lo=max(0,a-context_seconds);hi=min(sources[src]['duration'],b+context_seconds)
            identity={'source_sha256':sources[src]['sha256'],'record_id':r['id'],'interval':[a,b],'record_index':i}
            tid='impact-'+signature(identity)[:24]
            t={'id':tid,'record_index':i,'role':'control','mode':'impact_review','review_protocol':4,
               'target_id':r['id'],'before':v['text'],'after':v['text'],'source_audio':src,
               'interval':[a,b],'review_interval':[lo,hi],'neighbors':[]}
            for j,n in valid.items():
                if i==j or n['source']!=src:continue
                x,y=n['interval']
                if lo<=x<y<=hi and (y<=a or x>=b):
                    t['neighbors'].append({'id':records[j]['id'],'text':n['text'],'start_seconds':x,'end_seconds':y})
            t['neighbors'].sort(key=lambda n:n['start_seconds'])
            for k,span in (('target',[a,b]),('context',[lo,hi])):
                dest=out/'clips'/(tid+'-'+k+'.wav');t[k+'_clip']=str(dest)
                t[k+'_clip_meta']=base.clip(Path(src),dest,*span)
            tasks.append(t)
        save(out/'records.frozen.json',records)
        p={'version':1,'created_at':now(),'records_path':str(records_path),'records_sha256':digest_file(out/'records.frozen.json'),
           'inputs':inputs,'code_hashes':hashes(),'model':model,'context_seconds':context_seconds,
           'max_target_seconds':max_target_seconds,'sources':sources,'tasks':tasks,'input_issues':errors,
           'nominal_api_calls':2*len(tasks),'manual_case_verdicts_used':False}
        save(out/'plan.json',p);verify(out);publish(out,p);return p


def publish(out,p):
    done=results(out,p);records=read(out/'records.frozen.json');decisions=copy.deepcopy(p['input_issues'])
    for issue in p['input_issues']:
        r=records[issue['record_index']]
        r.update(eligible_for_chunking=False,judgment='held',input_validation_issue=issue['reason'])
    for t in p['tasks']:
        result=done.get(t['id']);r=records[t['record_index']]
        g=result['gate'] if result else {'route':'ordinary_hold','impact':'unknown','reasons':['not_checked']}
        evidence={'task_id':t['id'],'gate':g,'source_audio':t['source_audio'],'target_interval':t['interval']}
        if result:evidence.update(literal_text=result['review']['literal_text'],source_binding=result['input_bindings'])
        reason=result['review']['reason'] if result else '원음 영향 검사 전'
        if g['route']=='administrator':r=hold_for_administrator(r,reason,evidence);records[t['record_index']]=r
        decisions.append({'record_index':t['record_index'],'record_id':r['id'],**g,'reason':reason,'evidence':evidence})
    revision=signature({'plan':signature(p),'results':done})[:24];folder=out/'revisions'/revision;mp=folder/'manifest.json'
    if not mp.exists():
        folder.mkdir(parents=True,exist_ok=True)
        files={'records.jsonl':records,'impact-decisions.jsonl':decisions,
            'administrator-review.jsonl':[d for d in decisions if d['route']=='administrator'],
            'ordinary-holds.jsonl':[d for d in decisions if d['route']=='ordinary_hold']}
        for name,rows in files.items():jsonl(folder/name,rows)
        save(mp,{'revision':revision,'plan_signature':signature(p),'file_hashes':{n:digest_file(folder/n) for n in files}})
    manifest=read(mp)
    if any(digest_file(folder/n)!=h for n,h in manifest['file_hashes'].items()):raise ValueError('revision_changed')
    s={'tasks':len(p['tasks']),'completed':len(done),'pending':len(p['tasks'])-len(done),'input_issues':len(p['input_issues']),
       'new_administrator_holds':sum(d['route']=='administrator' for d in decisions),
       'ordinary_holds':sum(d['route']=='ordinary_hold' for d in decisions),
       'nominal_api_calls':p['nominal_api_calls'],'api_calls':sum(len(read(f)['attempts']) for f in (out/'runs').glob('*.json')),
       'transcript_rewrites':0,'automatic_releases':0,'manual_case_verdicts_used':False}
    save(out/'latest.json',{'revision':revision,'manifest':str(mp),'records':str(folder/'records.jsonl')});save(out/'summary.json',s)
    return s


def run(out,env_file,maximum=20,delay=15):
    with lock(out):
        p=verify(out);done=results(out,p);budget=Budget(out,maximum,delay);error=None;client=None
        if len(done)<len(p['tasks']):
            api_key(env_file);client=Gemini(out/'gemini-cache',p['model'],env_file,max_calls=maximum,delay=0,transport=budget)
        try:
            for t in p['tasks']:
                if t['id'] in done:continue
                media,binding,data,neighbors=base.primary_context_bundle(out,t)
                b=client.call('generic-impact-blind-v1',media,base.V4_BLIND_PROMPT+json.dumps(data,ensure_ascii=False),base.BLIND_V4)
                if base.primary_context_bundle(out,t)[1]!=binding:raise ValueError('audio_changed_between_calls')
                payload={**data,'existing_text':t['before'],'neighboring_transcripts_text_only':neighbors}
                r=client.call('generic-impact-review-v1',media,policy.PROMPT+json.dumps(payload,ensure_ascii=False),policy.IMPACT)
                if base.primary_context_bundle(out,t)[1]!=binding:raise ValueError('audio_changed_during_review')
                save(out/'results'/(t['id']+'.json'),{'task_id':t['id'],'plan_signature':signature(p),'blind':b,'review':r,
                     'gate':policy.impact_gate(t,b,r),'input_bindings':{'blind':binding,'review':binding},'at':now()})
        except (Blocked,KeyboardInterrupt) as ex:error=str(ex) or 'interrupted'
        except Exception:
            error='validation_or_local_failure';raise
        finally:publish(out,p);save(out/'run-state.json',{'stop_reason':error or 'complete','api_calls_this_run':budget.used})
        if error:raise Blocked(error)
        return read(out/'summary.json')


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('mode',choices=['prepare','run','report'])
    ap.add_argument('--records',type=Path);ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--model');ap.add_argument('--context-seconds',type=float,default=3)
    ap.add_argument('--max-target-seconds',type=float,default=60);ap.add_argument('--max-api-calls',type=int,default=20)
    ap.add_argument('--env-file',type=Path,default=base.ROOT/'.env');a=ap.parse_args();out=a.output.resolve()
    try:
        if a.mode=='prepare':
            if not a.records or not a.model:ap.error('prepare requires --records and --model')
            prepare(a.records,out,a.model,a.context_seconds,a.max_target_seconds);s=read(out/'summary.json')
        elif a.mode=='run':s=run(out,a.env_file,a.max_api_calls)
        else:
            with lock(out):s=publish(out,verify(out))
        print(json.dumps(s,ensure_ascii=False,indent=2));return 0
    except (ValueError,OSError,Blocked) as ex:
        print(json.dumps({'stopped':str(ex)},ensure_ascii=False));return 2

if __name__=='__main__':raise SystemExit(main())
