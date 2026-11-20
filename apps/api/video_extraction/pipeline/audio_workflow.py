"""New-source adapter to existing coverage, scope, repair, and selection policies.

No project-specific reference IDs, approved answers, or old output paths enter a
new recording. All model calls share the caller's budget and durable cache.
"""
import copy
from video_extraction.shared.progress import report
import json
import math
import wave
from pathlib import Path
from video_extraction.audio import audio_coverage as core, audio_coverage_local as local
from video_extraction.audio import audio_finalize as final, audio_meaning_scope as meaning
from video_extraction.audio import audio_remaining_impact as impact
from video_extraction.shared import multimodal_checks as checks
from video_extraction.shared.common import read,save,signature,digest_file,validate
from video_extraction.shared.impact_policy import hold_for_administrator
from video_extraction.pipeline.runner import base_record
from video_extraction.pipeline import av_context
from video_extraction.pipeline import audio_followup
from video_extraction.pipeline import audio_batch


def bound_task(t, rows, source, folder, duration):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    # Fresh Whisper output uses NumPy scalars; JSON cache reads use Python
    # scalars. Normalize times BEFORE comparisons produce numpy.bool_. Never
    # stringify arbitrary objects or weaken the shared signature validator.
    t=copy.deepcopy(t);t['interval']=[float(x) for x in t['interval']]
    rows=[{**r,'start_seconds':float(r['start_seconds']),'end_seconds':float(r['end_seconds'])} for r in rows]
    duration=float(duration);t.update(final.review_unit(t,rows))
    # Preserve neighboring complete segments; score ONLY this task's primary.
    t.update(review_protocol=4,expression_policy=meaning.EXPRESSION_POLICY,connected_comparison=True,strict_content_policy=True)
    a,b=t['interval'];lo,hi=t['review_interval']
    lo=max(0,min(lo,a-5));hi=min(duration,max(hi,b+5));t['review_interval']=[lo,hi]
    t['neighbors']=[{k:r[k] for k in ('id','text','start_seconds','end_seconds')}
                    for r in rows if r['id']!=t['target_id'] and core.overlap(core.span(r),[lo,hi])>0]
    for label,span in [('target',[a,b]),('context',[lo,hi])]:
        path=folder/(t['id']+'-'+label+'.wav')
        meta=final.clip(source,path,*span)
        final.verify_slice(source,path,meta,span)
        t[label+'_clip']=str(path);t[label+'_clip_meta']=meta
    return t


def review_task(t, folder, client):
    media,binding,data,neighbors=final.primary_context_bundle(folder,t)
    if t.get('followup_reason'):data={**data,'prior_discrepancy_not_truth':t['followup_reason']}
    path=folder/'reviews'/(t['id']+'.json')
    task_sig=signature(t)
    if path.exists():
        r=read(path)
        if r['task_signature']!=task_sig or r['input_bindings']!={'blind':binding,'review':binding}:
            raise ValueError('audio_review_binding_changed')
        if r.get('batch_id'):audio_batch.validate_outcome(t,r,folder)
    else:
        b=client.call('connected-audio-blind-v1',media,final.V4_BLIND_PROMPT+json.dumps(data,ensure_ascii=False),final.BLIND_V4)
        payload={**data,'current_text':t['before'],'proposed_text':t['after'],
                 'neighboring_transcripts_text_only':neighbors,
                 'added_fragments':final.additions(t['before'],t['after']) if t['role']=='repair' else []}
        v=client.call('connected-audio-review-v1',media,final.V4_REVIEW_PROMPT+json.dumps(payload,ensure_ascii=False),final.REVIEW_V4)
        if final.primary_context_bundle(folder,t)[1]!=binding:raise ValueError('audio_changed_during_review')
        r={'task_id':t['id'],'task_signature':task_sig,'blind':b,'review':v,
           'input_bindings':{'blind':binding,'review':binding}}
    r['gate']=final.decision(t,r['blind'],r['review']);save(path,r)
    return r


def choose(snapshot,tasks,outcomes):
    """Existing selective application and neighbor queue are mandatory."""
    return final.selection(snapshot,tasks,outcomes,final.LOCAL_POLICY)


def validate_saved(unit,folder,result):
    av_context.validate_receipts(folder,unit)
    evidence=read(folder/'selection-evidence.json')
    for t in evidence['all_controls']+evidence['tasks']:
        r=evidence['all_outcomes'][t['id']]
        if r.get('batch_id'):audio_batch.validate_outcome(t,r,folder)
        if final.primary_context_bundle(folder,t)[1]!=r['input_bindings']['review']:
            raise ValueError('audio_source_scope_changed')
        if final.decision(t,r['blind'],r['review'])!=r['gate']:raise ValueError('audio_gate_changed')
    if any(t['role']=='control' for t in evidence['tasks']):
        calculated=choose(evidence['snapshot'],evidence['tasks'],evidence['outcomes'])
        if calculated!=evidence['bundle']:raise ValueError('audio_selection_calculation_changed')
        allowed={r['id']:r for r in calculated['selected']}
    else:allowed={}
    selected={r['id']:r for r in result['records'] if r['eligible_for_chunking']}
    if set(allowed)!=set(selected):raise ValueError('audio_selected_ids_changed')
    for rid,r in selected.items():
        if any(r.get(k)!=allowed[rid].get(k) for k in ('observed_text','original_text','start_seconds','end_seconds')):
            raise ValueError('audio_selected_content_changed')
    if result['changes']!=evidence['bundle']['receipts']:raise ValueError('audio_change_receipts_changed')
    if 'followup_input_records' in evidence:
        actual,_=audio_followup.route(unit,evidence['followup_input_records'],evidence['snapshot']['rows'],
            Path(unit['source_audio']),evidence['snapshot']['source_plan']['duration_seconds'],folder/'held-followup',None,read_only=True)
        if actual!=result['records']:raise ValueError('audio_followup_selection_changed')


def run(unit, units, folder, plan, client, transcriber, visual_units=None):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    source=Path(unit['source_audio']);offset=unit['location'].get('audio_offset_seconds',0)
    with wave.open(str(source)) as w:duration=w.getnframes()/w.getframerate()
    cursor=0
    for window in sorted(units,key=lambda t:t['interval'][0]):
        a,b=window['interval']
        if abs(a-cursor)>1e-6 or b<=a or window['source_id']!=unit['source_id']:
            raise ValueError('audio_window_gap_overlap_or_wrong_source')
        for part,span in [('target',[a,b]),('context',window['review_interval'])]:
            final.verify_slice(source,Path(window[part+'_clip']),window[part+'_clip_meta'],span)
        cursor=b
    if abs(cursor-duration)>1e-6:raise ValueError('audio_windows_do_not_cover_full_source')
    if transcriber is None:raise ValueError('local_whisper_required_for_audio')
    report('transcribe')
    baseline=transcriber.transcribe(source)
    save(folder/'initial.json',baseline)
    rows=[]
    for i,s in enumerate(baseline['segments']):
        a,b=float(s['start']),float(s['end'])
        if not 0<=a<b<=duration+.02:raise ValueError('invalid_source_asr_time')
        b=min(duration,b)
        if not s['text'].strip():continue
        rows.append({'id':unit['source_id']+':speech:'+str(i),'task_id':'speech-'+str(i),
            'start_seconds':a,'end_seconds':b,'text':s['text'],'baseline_text':s['text'],
            'prior_selected':False,'original_words':s.get('words',[]),'word_alignment_required':False,
            'words':[{**w,'start_seconds':w['start'],'end_seconds':w['end']} for w in s.get('words',[])],
            'avg_logprob':s.get('avg_logprob',0),'no_speech_prob':s.get('no_speech_prob',0)})
    report('speech_check')
    sound=core.detect_speech(source)
    timeline=core.audit_timeline(rows,duration,sound)
    energy,_=checks.audio_windows(source)
    local_findings,segment_findings=checks.inspect_audio(rows,energy,0,duration)
    save(folder/'local-checks.json',{'timeline':timeline,'audio':local_findings,'segments':segment_findings})
    if timeline['invalid_time_ids']:raise ValueError('invalid_audio_timeline')
    controls=[];outcomes={};previous=[]
    for row in rows:
        task=bound_task({'id':'control-'+signature(row['id'])[:16],'role':'control','target_id':row['id'],
            'before':row['text'],'after':row['text'],'interval':core.span(row)},rows,source,folder/'clips',duration)
        controls.append(task)
    completed=0
    for group in audio_batch.groups(controls):
        report('audio_review', completed, len(rows))
        outcomes.update(audio_batch.run(group,folder,client))
        completed+=len(group)
        report('audio_review', completed, len(rows))
    for row,task in zip(rows,controls):
        r=outcomes[task['id']]
        row['prior_selected']=r['gate']['passed']
        rec=base_record(unit,row['task_id'],'audio','speech',row['text'])
        rec.update(id=row['id'],eligible_for_chunking=r['gate']['passed'],
            start_seconds=row['start_seconds']+offset,end_seconds=row['end_seconds']+offset,
            reasons=[] if r['gate']['passed'] else ['audio_source_review_unresolved'])
        previous.append(rec)
    windows=[];results=[];all_findings=[];av_receipts=[]
    for i,t in enumerate(units):
        report('audio_coverage', i, len(units))
        label=f'W{i+1:05}';a,b=t['interval']
        window={'label':label,'core':[a,b],'clip_meta':t['context_clip_meta'],
                'row_ids':[r['id'] for r in rows if core.overlap(core.span(r),t['review_interval'])>0]}
        windows.append(window);audio=Path(t['context_clip'])
        local_text=transcriber.transcribe(audio)['text']
        current=[{k:r[k] for k in ('id','text','start_seconds','end_seconds')} for r in rows if r['id'] in window['row_ids']]
        payload={'audio_start_seconds':t['review_interval'][0],'audio_end_seconds':t['review_interval'][1],
                 'owned_core':window['core'],'existing_segments':current,'local_context_transcript':local_text}
        if plan.get('av_context_policy')==av_context.POLICY:
            reply,av_receipt=av_context.inspect_window(unit,visual_units or [],t,payload,client,
                folder/'av-context'/(label+'.json'),{r['id']:r['prior_selected'] for r in rows})
            av_receipts.append(av_receipt)
        else:
            reply=client.call('connected-whole-audio-coverage-v1',[audio],local.PROMPT+json.dumps(payload,ensure_ascii=False),core.SCHEMA)
        validate(reply,core.SCHEMA)
        calculated=[core.check_finding(f,window,rows,local_text) for f in reply['findings']]
        if not reply['checked_full_core'] or reply['speech_unresolved']:
            for c in calculated:
                if c['candidate']:c.update(candidate=False,status='held');c['reasons'].append('window_not_fully_resolved')
        result={'label':label,'plan_signature':signature(plan),'independent_text':local_text,
                'review':reply,'checks':calculated}
        save(folder/'coverage'/'results'/(label+'.json'),result)
        results.append(result);all_findings+=calculated
    # Existing collector detects competing repairs across different windows.
    # collect binds the complete passed plan, so supply a dedicated coverage plan.
    coverage_plan={'windows':windows,'source_sha256':unit['source_id']}
    for r in results:
        r['plan_signature']=signature(coverage_plan);save(folder/'coverage'/'results'/(r['label']+'.json'),r)
    report('audio_finalize')
    _,candidates,calculated=core.collect(folder/'coverage',coverage_plan)
    repairs=[]
    for c in candidates:
        f=c['finding'];row=next((r for r in rows if r['id']==f['target_id']),None)
        task={'id':'repair-'+c['candidate_id'],'role':'repair','candidate':c,'target_id':f['target_id'],
              'before':f['before'],'after':f['after'],'interval':core.span(row) if row else [f['start'],f['end']]}
        task=bound_task(task,rows,source,folder/'clips',duration)
        repairs.append(task);outcomes[task['id']]=review_task(task,folder,client)
    held=[c for c in calculated if c['status']=='held']
    # Reuse the narrow, source-timed partial-body proposal. Prefix remains held.
    for task in list(repairs):
        if task['before'] or outcomes[task['id']]['gate']['passed']:continue
        attempt={**task,'mode':'restore'}
        try:text,interval=meaning.body_candidate(attempt,outcomes[task['id']])
        except ValueError:continue
        f={**task['candidate']['finding'],'after':text,'start':interval[0],'end':interval[1]}
        owner=next((w for w in windows if w['core'][0]<=(interval[0]+interval[1])/2<w['core'][1]),None)
        if owner is None:continue
        c=core.check_finding(f,owner,rows,text);c['batch_conflict']=task['candidate']['batch_conflict']
        if not c['candidate']:continue
        child=bound_task({**task,'id':task['id']+'-body','candidate':c,'interval':interval,'after':text},rows,source,folder/'clips',duration)
        r=review_task(child,folder,client)
        if not r['gate']['passed']:continue
        prefix={**task['candidate']['finding'],'end':interval[0],'after':''}
        held.append({'finding':prefix,'status':'held','candidate':False,'reasons':['excluded_prefix_needs_own_review']})
        repairs.remove(task);repairs.append(child);outcomes[child['id']]=r
        save(folder/'partial-restorations'/(child['id']+'.json'),{'parent':task,'child':child,'prefix':prefix,'parent_outcome':outcomes[task['id']]})
    # A control on the repair target is a pre-repair observation, not a competing
    # post-repair veto. Other normal controls and their failures remain independent.
    targeted={t['target_id'] for t in repairs if t['target_id']}
    tasks=[t for t in controls if t['target_id'] not in targeted]+repairs
    # Neighbor clues have their own primary target. Never let an unrelated
    # neighbor veto an accepted repair, and never silently discard the clue.
    followup_queue=[]
    if plan.get('followup_policy'):
        for issue in final.neighbor_queue(tasks,outcomes):
            if issue['status']!='needs_own_source_recheck':continue
            row=next((r for r in rows if r['id']==issue['neighbor_id']),None)
            if row is None or row['id'] in targeted:continue
            if any(q['target_id']==row['id'] for q in followup_queue):continue
            task=bound_task({'id':'neighbor-'+signature(row['id'])[:24],'role':'control','target_id':row['id'],
                'before':row['text'],'after':row['text'],'interval':core.span(row),'followup_reason':issue},
                rows,source,folder/'clips',duration)
            outcomes[task['id']]=review_task(task,folder,client)
            tasks=[t for t in tasks if not (t['role']=='control' and t['target_id']==row['id'])]+[task]
            followup_queue.append({'target_id':row['id'],'task_id':task['id'],'passed':outcomes[task['id']]['gate']['passed']})
            if outcomes[task['id']]['gate']['passed']:
                for rec in previous:
                    if rec['id']==row['id']:rec.update(eligible_for_chunking=True,reasons=[])
    selected_outcomes={t['id']:outcomes[t['id']] for t in tasks}
    snapshot={'rows':rows,'held':held,'previous_records':previous,'previous_usable':[],
        'coverage_results':results,'source_plan':{'source_sha256':unit['source_id'],'source_audio':str(source),
            'duration_seconds':duration,'audio_offset_seconds':offset,'windows':windows}}
    if any(t['role']=='control' for t in tasks):
        bundle=choose(snapshot,tasks,selected_outcomes)
        records=copy.deepcopy(bundle['selected']+bundle['excluded'])
    else:
        # Empty or wholly defective recordings cannot invent a passing control.
        records=[{**r,'eligible_for_chunking':False,'judgment':'held','reasons':['no_independently_supported_control']} for r in previous]
        bundle={'receipts':[],'held_findings':[c['finding'] for c in calculated],
                'neighbor_issues':[],'application_decisions':{}}
    lookup={t['target_id']:t for t in controls}
    for rec in records:
        rec.update(source_id=unit['source_id'],source_file=unit['source_file'],unit_id=unit['id'],
                   detected_language=baseline.get('language') or plan.get('source_plan',{}).get('config',{}).get('language'),
                   location={'start_seconds':rec.get('start_seconds'),'end_seconds':rec.get('end_seconds')},
                   time_basis='media_absolute' if offset else 'source_relative',audio_offset_seconds=offset,specialist='audio_coverage_and_finalize')
        rec['local_findings']=segment_findings.get(rec['id'],[])
        if rec['eligible_for_chunking'] or plan.get('followup_policy'):continue
        t=lookup.get(rec['id'])
        if not t:continue
        media,_,data,neighbors=final.primary_context_bundle(folder,t)
        answer=client.call('connected-audio-impact-v1',media,impact.PROMPT+json.dumps({**data,'existing_text':t['before'],
            'neighboring_transcripts_text_only':neighbors},ensure_ascii=False),impact.IMPACT)
        route=impact.impact_gate(t,outcomes[t['id']]['blind'],answer)
        if route['route']=='administrator':rec.update(hold_for_administrator(rec,answer['reason'],{'assessment':answer,'gate':route}))
    for i,f in enumerate(bundle['held_findings']):
        rec=base_record(unit,'finding:'+str(i),'audio','coverage_issue','')
        rec.update(reasons=['unresolved_audio_finding'],raw_payload=f,
                   source_audio=str(source),audio_offset_seconds=offset,
                   start_seconds=f['start']+offset,end_seconds=f['end']+offset,
                   time_basis='media_absolute' if offset else 'source_relative',
                   location={'start_seconds':f['start']+offset,'end_seconds':f['end']+offset})
        records.append(rec)
    if not rows and (any(not r['review']['checked_full_core'] or r['review']['speech_unresolved'] for r in results) or candidates):
        rec=base_record(unit,'unresolved-empty','audio','coverage_issue','');rec['reasons']=['unresolved_empty_transcript'];records.append(rec)
    extra={};impact_decisions=[]
    if plan.get('followup_policy'):
        extra['followup_input_records']=copy.deepcopy(records)
        records,impact_decisions=audio_followup.route(unit,records,rows,source,duration,folder/'held-followup',client)
    save(folder/'selection-evidence.json',{'snapshot':snapshot,'tasks':tasks,'outcomes':selected_outcomes,
         'all_controls':controls,'all_outcomes':outcomes,'bundle':bundle,**extra})
    comparison_notes=copy.deepcopy([n for r in av_receipts for n in r['comparisons']])
    for note in comparison_notes:
        target=next((r for r in records if r['id']==note['target_id']),None)
        note['initial_status']=note['status']
        note['status']=('audio_source_rechecked_repair_applied' if target.get('audio_coverage_repair_applied') else
                        'audio_supported_original_preserved') if target and target['eligible_for_chunking'] else 'audio_recheck_unresolved'
        if target:
            note.update(before=target.get('original_text'),after=target['observed_text'],
                        start_seconds=target['start_seconds'],end_seconds=target['end_seconds'],
                        review_reasons=target.get('reasons',[]))
    av_summary={'policy':plan.get('av_context_policy'),'windows':len(av_receipts),
        'windows_with_frames':sum(bool(r['request']['visual_context']['frames']) for r in av_receipts),
        'comparisons':comparison_notes,
        'frames_are_hints_only':True,'repair_rechecks_audio_only':True}
    save(folder/'av-summary.json',av_summary)
    return {'records':records,'changes':bundle['receipts'],'neighbor_queue':bundle['neighbor_issues'],
            'neighbor_followup':followup_queue,'impact_followup':impact_decisions,
            'av_context':av_summary,
            'local_findings':{'timeline':timeline,'audio':local_findings},'status':'complete',
            'executed':['local_whisper',audio_batch.POLICY,'full_time_coverage','original_scope_samples','neighbor_ownership',
                        'source_recheck','selective_application','partial_body_recheck','impact_routing']+
                       (['source_timed_visual_hints','audio_only_repair_recheck'] if av_receipts else [])}
