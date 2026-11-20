"""Source-bound impact routing for every remaining fragment, including new gaps.

Reuses the existing primary/context and impact gates. Never edits or approves a
transcript. Normal rows are excluded from this stage, not reinterpreted.
"""
import copy
import json
from pathlib import Path
from video_extraction.audio import audio_finalize as final, audio_remaining_impact as policy
from video_extraction.shared.common import read,save,signature
from video_extraction.shared.impact_policy import hold_for_administrator


def route(unit,records,source_rows,source,duration,folder,client,read_only=False):
    from video_extraction.pipeline.audio_workflow import bound_task
    folder=Path(folder);out=copy.deepcopy(records);decisions=[]
    offset=unit['location'].get('audio_offset_seconds',0)
    for row in out:
        if row['eligible_for_chunking'] or row.get('impact_review',{}).get('route')=='administrator':continue
        where=row.get('location',{})
        a=row.get('start_seconds',where.get('start_seconds'))
        b=row.get('end_seconds',where.get('end_seconds'))
        if a is None or b is None or not 0<=a-offset<b-offset<=duration:
            decisions.append({'id':row['id'],'route':'ordinary_hold','reason':'source_interval_unresolved'});continue
        tid='held-'+signature([row['id'],a,b])[:24]
        original=next((r for r in source_rows if r['id']==row['id']),None)
        target_id=original['id'] if original else None
        task=bound_task({'id':tid,'role':'control','target_id':target_id,
            'before':original['text'] if original else '',
            'after':original['text'] if original else '', 'interval':[a-offset,b-offset]},
            source_rows,source,folder/'clips',duration)
        media,binding,data,neighbors=final.primary_context_bundle(folder,task)
        payload={**data,'existing_text':row['observed_text'],'held_reasons':row['reasons'],
                 'neighboring_transcripts_text_only':neighbors}
        key=signature({'task':task,'media':binding,'payload':payload});path=folder/(tid+'.json')
        if path.exists():
            saved=read(path)
            if saved['binding']!=key:raise ValueError('audio_followup_source_changed')
        else:
            if read_only:raise ValueError('audio_followup_evidence_missing')
            blind=client.call('connected-held-fragment-blind-v1',media,
                final.V4_BLIND_PROMPT+json.dumps(data,ensure_ascii=False),final.BLIND_V4)
            answer=client.call('connected-held-fragment-impact-v1',media,
                policy.PROMPT+json.dumps(payload,ensure_ascii=False),policy.IMPACT)
            saved={'binding':key,'blind':blind,'answer':answer};save(path,saved)
        gate=policy.impact_gate(task,saved['blind'],saved['answer'])
        decisions.append({'id':row['id'],'route':gate['route'],'gate':gate,'evidence':str(path)})
        if gate['route']=='administrator':
            row.update(hold_for_administrator(row,saved['answer']['reason'],
                {'assessment':saved['answer'],'gate':gate,'source_binding':binding,'evidence':str(path)}))
    path=folder/'summary.json'
    receipt={'input':signature(records),'output':signature(out),'decisions':decisions}
    if read_only:
        if read(path)!=receipt:raise ValueError('audio_followup_decisions_changed')
    else:save(path,receipt)
    return out,decisions
