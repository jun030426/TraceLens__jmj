"""Adapter to the existing full ink engine, including its final selection gate."""
import copy
import subprocess
import sys
from pathlib import Path
from PIL import Image
from video_extraction.shared.common import save, read, digest_file, signature
from video_extraction.shared.impact_policy import hold_for_administrator
from video_extraction.ink.runner import ink_continue_v2 as engine
from video_extraction.ink.correction import ink_recovery, ink_discrepancy
from video_extraction.ink.selection.usable_selection import select_result
from video_extraction.ink.recognition.ink_evidence import prepare_views
from video_extraction.ink.policy import unreadable
from video_extraction.ink.correction import generalized_review
from video_extraction.ink.runner.ink_pipeline import transform_visual, focus_audio
from video_extraction.pipeline.runner import base_record


def package(t, annotation, context):
    # Full original image coordinates throughout; no legacy frame IDs or paths.
    path=str(Path(t['image']).resolve())
    with Image.open(path) as im:size=list(im.size)
    tid=signature([t['id'],annotation['id']])[:24]
    segments=[s for s in context if s['source_id']==t['source_id']]
    a=max(0,t['time_seconds']-10);b=t['time_seconds']+10
    task={'id':tid,'source_sha256':t['source_id'],'frame_id':t['unit_key'],
          'bbox':annotation['bbox'],'current_image':path,
          'before_image':t.get('before_image',path),'after_image':t.get('after_image',path),
          'time_seconds':t['time_seconds'],'audio_interval':[a,b],'asr_context':segments,
          'evidence':{'selected_frame':path,'selected_frame_seconds':t['time_seconds']}}
    view={'path':path,'size':size,'crop_in_source':[0,0,1,1],
          'operation':'native_source','eligible':True,'core_unchanged':True}
    task['evidence']['views']={'original':view}
    return {'task':task,'view':view,'ocr':{'state':'unavailable','words':[]},
            'ocr_coverage':dict(left=0,top=0,right=1000,bottom=1000)}


def local_ocr(p, folder, models=None, python=None):
    if not models:return p
    folder.mkdir(parents=True,exist_ok=True);image=p['view']['path'];tid=p['task']['id']
    manifest=folder/'manifest.json';save(manifest,[{'id':tid,'path':image,'image_sha256':digest_file(image)}])
    receipt=folder/(tid+'.json')
    if receipt.exists() and read(receipt).get('state')!='candidate':
        receipt.rename(folder/('failed-before-retry-'+digest_file(receipt)[:20]+'.json'))
    with (folder/'worker.log').open('a') as log:
        run=subprocess.run([str(python or sys.executable),'-u','-m','video_extraction.ink.recognition.ink_ocr',
            '--manifest',str(manifest),'--output',str(folder/'status.json'),'--models',str(models)],
            stdout=log,stderr=subprocess.STDOUT,timeout=600,check=False)
    if run.returncode or not receipt.exists():
        raise RuntimeError('local_ocr_worker_failed: '+str(folder/'worker.log'))
    else:
        p['ocr']=read(receipt)
        if p['ocr'].get('image_sha256')!=digest_file(image):raise ValueError('ink_ocr_wrong_source')
        if p['ocr'].get('state')!='candidate':raise RuntimeError('local_ocr_inference_failed: '+str(receipt))
    return p


def replay(p, result):
    # Run the SAME calculations again, not just trust the old selected flag.
    checked=ink_recovery.evaluate(p,result['raw_candidate'],result['final_audit'])
    ink_discrepancy.refresh_relations(checked)
    current={**result,**checked,'task_id':p['task']['id']}
    if result.get('generalized_ink_evidence'):
        current=generalized_review.apply(p,current,result['generalized_ink_evidence'])
    return unreadable.route(p,current)


def select(t,p,result,path):
    result=replay(p,result)
    chosen,excluded=select_result(result,path,{x['local_id'] for x in result['administrator_queue']})
    byid={x['local_id']:x for x in chosen};failed={x['local_id']:x for x in excluded}
    nodes={x['id']:x for group in ('items','links') for x in result['candidate'][group]}
    records=[]
    for iid,node in nodes.items():
        decision=next((x for x in result['decisions'] if x['id']==iid),{})
        if decision.get('status')=='context_only':continue
        accepted=iid in byid
        effective=byid[iid]['record']['raw_payload']['raw'] if accepted else node
        rid='ink:'+p['task']['id']+':'+iid
        row=base_record(t,rid,'handwriting',node['kind'],effective.get('text',''))
        row.update(eligible_for_chunking=accepted,judgment='source_rechecked' if accepted else 'held',
            original_text=next((x.get('text','') for group in ('items','links') for x in p['base'][group] if x['id']==iid),''),
            raw_payload=effective,source_image=p['view']['path'],
            reasons=[] if accepted else failed.get(iid,{}).get('reasons',decision.get('reasons') or ['ink_source_unresolved']),
            specialist='ink_continue_v2',specialist_local_id=iid,selection=byid.get(iid,{}).get('selection'))
        if 'box' in effective:
            transformed=transform_visual({'items':[effective],'links':[]},p['view'],{'crop_in_source':[0,0,1,1]})
            row['bbox']=[transformed['items'][0]['box'][k] for k in ('left','top','right','bottom')]
        if 'from_ids' in effective:
            row['related_record_ids']=[t['id']+':ink:'+p['task']['id']+':'+i for i in effective['from_ids']+effective['to_ids']]
        if decision.get('status')=='administrator_review':
            queue=next(x for x in result['administrator_queue'] if x['local_id']==iid)
            row=hold_for_administrator(row,queue['reason'],{'decision':decision,'source':p['view']['path'],'queue':queue})
            if queue.get('impact')=='unknown':
                row['impact_review'].update(impact='unknown',policy='unresolved_source_admin_hold_v1')
                row['reasons']=row['selection_reasons']=[x for x in row['reasons'] if x!='low_impact_error_administrator_review']+['source_interpretation_administrator_review']
        elif any(w in decision.get('warnings',[]) for w in
                 ('meaning_preserving_particle_source_difference','meaning_preserving_particle_omission')):
            row=hold_for_administrator(row,'source_particle_difference_requires_administrator',
                                      {'decision':decision,'source':p['view']['path']})
        records.append(row)
    for i,missing in enumerate(result['missing_core']):
        row=base_record(t,'ink:'+p['task']['id']+':missing:'+str(i),'handwriting','coverage_issue','')
        row.update(reasons=['ink_missing_core'],raw_payload=missing);records.append(row)
    if not result['active_coverage_complete'] and not any(not r['eligible_for_chunking'] for r in records):
        row=base_record(t,'ink:'+p['task']['id']+':incomplete','handwriting','coverage_issue','')
        row['reasons']=['ink_coverage_unresolved'];records.append(row)
    return records,result['changes']


def run(t, annotation, context, folder, plan, client, models=None, python=None):
    folder=Path(folder);p=package(t,annotation,context)
    p['task']['ocr_policy']=plan.get('ocr_policy','legacy_required')
    saved=folder/'bundle.json'
    binding=signature({'task':p,'image':digest_file(t['image']),'plan':plan,'models':str(models),'ocr_python':str(python or sys.executable)})
    if saved.exists():
        bundle=read(saved)
        if bundle['binding']!=binding:raise ValueError('ink_bundle_changed')
        return select(t,bundle['package'],bundle['result'],saved)
    evidence_file=folder/'view-evidence.json'
    if evidence_file.exists():
        stored=read(evidence_file)
        if stored['binding']!=binding:raise ValueError('ink_view_source_changed')
        evidence=stored['evidence']
    else:
        index=0;view_folder=folder/'views'
        # A crash during local preparation must not require deleting old evidence.
        while view_folder.exists():
            index+=1;view_folder=folder/('views-resume-'+str(index))
        evidence=prepare_views(p['task'],view_folder)
        save(evidence_file,{'binding':binding,'evidence':evidence})
    p['task']['evidence']=evidence;p['view']=evidence['views']['original']
    if t.get('source_audio'):
        from video_extraction.audio.audio_accuracy import clip
        import wave
        source=Path(t['source_audio']);offset=t.get('audio_offset_seconds',0)
        with wave.open(str(source)) as audio:duration=audio.getnframes()/audio.getframerate()
        lo=max(0,p['task']['audio_interval'][0]-offset);hi=min(duration,p['task']['audio_interval'][1]-offset)
        if lo<hi:
            target=folder/'audio-focus.wav';meta=clip(source,target,lo,hi)
            p['task']['audio_path']=str(target)
            p['audio_focus']=focus_audio(p['task'],folder,plan,client)
            p['audio_focus_provenance']={'clip':meta,'usage':'priority_context_only_never_visual_truth'}
    try:
        p=local_ocr(p,folder/'ocr',models,python)
    except (OSError,subprocess.TimeoutExpired,RuntimeError) as exc:
        if p['task'].get('ocr_policy')!='selective_auxiliary_v1':raise
        p['ocr']={'state':'unavailable','words':[],'diagnostic':type(exc).__name__}
        save(folder/'ocr'/'optional-failure.json',p['ocr'])
    result=engine.execute(p,folder,plan,client)
    final_package=read(folder/'prepared'/(p['task']['id']+'.json'))
    result['generalized_ink_evidence']=generalized_review.review(final_package,result,folder/'generalized-review',client)
    save(saved,{'binding':binding,'annotation_id':annotation['id'],'package':final_package,'result':result})
    return select(t,final_package,result,saved)
