"""Authoritative common dispatcher: invoke specialists, then publish one selection.

prepare/report are offline. Only run constructs a Gemini client. Historical
specialist algorithms remain in their original modules; no sample verdicts enter
new-source decisions. Internal visual candidates are not the published dataset.
"""
import argparse
import copy
import html
import json
import sys
import subprocess
import traceback
from pathlib import Path
from types import SimpleNamespace
from video_extraction.pipeline import runner as base, audio_workflow, ink_workflow, document_workflow
from video_extraction.pdf import workflow as pdf_workflow
from video_extraction.shared import multimodal_checks, preprocessing
from video_extraction.shared.common import read,save,jsonl,signature,digest_file,now
from video_extraction.shared.gemini import Gemini,api_key,Blocked
from video_extraction.audio.audio_crosscheck import Budget,lock
from video_extraction.pipeline import runtime_tools,alignment_bridge
from video_extraction.pipeline import code_workflow
from video_extraction.pipeline import visual_ocr
from video_extraction.pipeline import av_context
from video_extraction.pipeline import audio_batch
from video_extraction.pipeline import ppt_reuse
from video_extraction.pipeline import source_followup,video_followup,audio_followup,document_links
from video_extraction.code import processing as code_processing

VERSION=1
LOW_IMPACT_POLICY='post_recheck_low_impact_warning_v1'
STRICT_SAFETY_REASONS={
    'common_safety_gate','calculation_gate','invalid_bbox',
    'source_interpretation_administrator_review','unselected_relation_target',
    'saved_frame_source_mismatch','selected_timestamp_not_decoded',
    'no_decoded_frames','video_source_check_pending','source_syntax_requires_review',
    'oversized_atomic_code','oversized_code_with_comments'
}


def ocr_executable(path=None):
    # Resolving a venv's Python symlink discards its site-packages environment.
    return str(Path(path or sys.executable).expanduser().absolute())


def check_ocr_runtime(python):
    probe=subprocess.run([ocr_executable(python),'-c',
        'import importlib.util,sys; sys.exit(0 if all(importlib.util.find_spec(n) is not None for n in ("paddleocr","paddle")) else 1)'],
        capture_output=True,text=True,timeout=30,check=False)
    if probe.returncode:
        raise ValueError('OCR 실행 환경에서 PaddleOCR/Paddle을 찾지 못했습니다. --ocr-python에 설치된 환경의 Python 경로를 지정하세요.')


from video_extraction.shared import progress

def hashes():
    # Include specialist dependencies, not just adapter code.
    from video_extraction.ink.runner.ink_continue_v2 import hashes as ink_hashes
    from video_extraction.ink.selection import usable_selection
    from video_extraction.ink.policy import unreadable
    from video_extraction.ink.correction import generalized_review
    from video_extraction.audio import audio_meaning_scope,audio_meaning_review,audio_remaining_impact
    from video_extraction.video import separator_pixels,bbox_cutoff,source_coordinate_review
    from video_extraction.ppt import native_reader
    from video_extraction.audio import word_alignment
    from video_extraction.pipeline import runtime_setup
    return {**base.hashes(),**ink_hashes(),'connected':digest_file(__file__),**{m.__name__:digest_file(m.__file__) for m in
        (progress,audio_batch,ppt_reuse,runtime_setup,document_links,audio_followup,video_followup,source_followup,av_context,visual_ocr,visual_ocr.ink_ocr,code_workflow,code_processing,audio_workflow,ink_workflow,document_workflow,pdf_workflow,usable_selection,unreadable,generalized_review,runtime_tools,alignment_bridge,native_reader,word_alignment,
         audio_meaning_scope,audio_meaning_review,audio_remaining_impact,multimodal_checks,preprocessing,
         base.whisper,separator_pixels,bbox_cutoff,source_coordinate_review)}}


def model_hashes(folder):
    if folder is None:return {}
    root=Path(folder).resolve();result={}
    for name in ('PP-OCRv5_mobile_det','korean_PP-OCRv5_mobile_rec'):
        path=root/name
        if not (path/'inference.yml').is_file():raise ValueError('local_ocr_model_missing:'+str(path))
        for f in path.iterdir():
            if f.is_file() and f.name!='README.md':result[str(f)]=digest_file(f)
    return result


def prepare(out, inputs=None, model=None, whisper_model=None, ocr_models=None,ocr_python=None,reuse=None,kind=None,
            native_python=None,alignment_python=None,alignment_model=None,alignment_allow_download=False,code_python=None,ppt_references=None):
    out=Path(out).resolve()
    with lock(out):
        if (out/'plan.json').exists():
            existing=verify(out)
            if reuse and existing.get('reuse_from')!=str(Path(reuse).resolve()):raise ValueError('different_reuse_source')
            if inputs and existing['source_plan']['request']['sources']!=[str(Path(x).resolve()) for x in inputs]:raise ValueError('different_sources')
            if model and existing['source_plan']['gemini_model']!=model:raise ValueError('different_model')
            if whisper_model and (existing['source_plan'].get('local_whisper') or {}).get('path')!=str(Path(whisper_model).resolve()):raise ValueError('different_whisper_model')
            for key,value in [('ocr_models',ocr_models),('ocr_python',ocr_python)]:
                expected=ocr_executable(value) if key=='ocr_python' else str(Path(value).resolve()) if value else None
                if value and existing[key]!=expected:raise ValueError('different_'+key)
            if kind and existing['source_plan']['request']['kind']!=kind:raise ValueError('different_kind')
            for key,value in [('native_python',native_python),('alignment_python',alignment_python),('code_python',code_python)]:
                if value and existing['tool_runtime'][key]!=ocr_executable(value):raise ValueError('different_'+key)
            if alignment_model and existing['tool_runtime']['alignment_model']!=alignment_model:raise ValueError('different_alignment_model')
            if ppt_references is not None and existing.get('ppt_reference_sources',[])!=[str(Path(x).resolve()) for x in ppt_references]:raise ValueError('different_ppt_references')
            return existing
        seeds={};bindings={}
        if reuse:
            root=Path(reuse).resolve();old=read(root/'plan.json')
            for f,h in old['inputs'].items():
                if digest_file(f)!=h:raise ValueError('reused_input_changed:'+f)
            source_plan=copy.deepcopy(old)
            bindings[str(root/'plan.json')]=digest_file(root/'plan.json')
            for t in old['units']:
                f=root/'results'/(t['unit_key']+'.json')
                if not f.exists() or t['modality']!='visual':continue
                r=read(f)
                if (r['plan_signature']!=signature(old) or r.get('result_payload_sha256')!=signature({k:v for k,v in r.items() if k!='result_payload_sha256'})):
                    raise ValueError('invalid_reused_result')
                raw=r['evidence'].get('visual_result')
                if not raw:continue
                if digest_file(raw)!=r['visual_result_sha256']:raise ValueError('reused_visual_changed')
                candidate=read(raw)
                if 'common_gate' in candidate:
                    # Reuse only a model candidate, not a previous selection verdict.
                    continue
                if candidate['image_sha256']!=digest_file(t['image']):raise ValueError('seed_image_mismatch')
                seeds[t['id']]=raw;bindings[str(f)]=digest_file(f);bindings[raw]=digest_file(raw)
        else:
            if inputs and not model and all((kind or base.adapters.KINDS.get(Path(x).suffix.lower()))=='code' for x in inputs):
                model='local-code-only'
            if not inputs or not model:raise ValueError('input_and_model_required')
            source_plan=base.prepare(inputs,out/'prepared-inputs',model,whisper_model,kind)
        # Upgrade old prepared PDF pages without importing old selection verdicts.
        for unit in source_plan['units']:
            if unit['source_kind']=='pdf' and 'pdf_inventory' not in unit:
                n=unit['location']['page']
                xml=base.adapters.command('pdftotext',['-f',n,'-l',n,'-bbox',unit['source_file'],'-'])
                unit['pdf_inventory']=pdf_workflow.native_inventory(xml)
        has_visual=any(u['modality']=='visual' for u in source_plan['units'])
        if has_visual:
            root=Path(__file__).resolve().parents[2]
            ocr_models=ocr_models or root/'work/extraction-compare/paddlex/official_models'
            ocr_python=ocr_python or root/'work/extraction-compare/env/bin/python'
        runtime=runtime_tools.defaults()
        if native_python:runtime['native_python']=ocr_executable(native_python)
        if alignment_python:runtime['alignment_python']=ocr_executable(alignment_python)
        if code_python:runtime['code_python']=ocr_executable(code_python)
        runtime.update(alignment_model=alignment_model,alignment_allow_download=alignment_allow_download)
        environment=runtime_tools.audit({'source_plan':source_plan,'ocr_models':str(ocr_models) if ocr_models else None,
            'ocr_python':ocr_executable(ocr_python),'tool_runtime':runtime,'ocr_policy':'selective_auxiliary_v1'},out)
        runtime_tools.require_core(environment)
        ocr_ready=all(c['ok'] for c in environment['checks'] if c['tool'] in ('PaddleOCR','PaddleOCR_weights'))
        native=document_workflow.native_inventory(source_plan['sources'],runtime['native_python'],out/'native-reader')
        save(out/'native-inventory.json',native)
        bindings[str(out/'native-inventory.json')]=digest_file(out/'native-inventory.json')
        for receipt in native.get('native_reader_receipts',[]):bindings[receipt['path']]=receipt['sha256']
        ppt_reference=None
        if ppt_references:
            references=ppt_reuse.prepare(ppt_references,out/'ppt-references')
            ppt_reference=str(out/'ppt-references'/'references.json')
            bindings.update(references['inputs'])
            bindings[ppt_reference]=digest_file(ppt_reference)
        tasks=[];seen=set()
        for t in source_plan['units']:
            if t['modality']=='code':tasks.append({'id':t['id'],'kind':'code','unit':t})
            elif t['modality']=='audio':
                if t['source_id'] in seen:continue
                seen.add(t['source_id'])
                tasks.append({'id':t['source_id']+':audio-workflow','kind':'audio','unit':t})
            else:tasks.append({'id':t['id'],'kind':'visual','unit':t})
        for s in source_plan['sources']:
            if s['kind']=='video':tasks.append({'id':s['source_sha256']+':video-coverage','kind':'video_coverage','source':s})
        tasks+=document_links.tasks(source_plan['units'])
        tasks.sort(key=lambda t:{'code':-1,'video_coverage':0,'audio':1,'visual':2,'document_links':3}[t['kind']])
        p={'version':VERSION,'created_at':now(),'source_plan':source_plan,'tasks':tasks,'seeds':seeds,
            'followup_policy':source_followup.POLICY,
            'av_context_policy':av_context.POLICY,
            'low_impact_policy':LOW_IMPACT_POLICY,
            'ocr_policy':'selective_auxiliary_v1','ocr_available':has_visual and ocr_ready,
            'inputs':{**source_plan['inputs'],**bindings,**(model_hashes(ocr_models) if has_visual and ocr_ready else {})},'code_hashes':hashes(),
            'ocr_models':str(Path(ocr_models).resolve()) if ocr_models else None,
            'ocr_python':ocr_executable(ocr_python),
            'tool_runtime':runtime,
            'ppt_reference':ppt_reference,'ppt_reference_sources':[str(Path(x).resolve()) for x in ppt_references or []],
            'reuse_from':str(Path(reuse).resolve()) if reuse else None,
            'execution_policy':'specialists_required_before_selection','accuracy_pct':None}
        save(out/'plan.json',p);verify(out);publish(out,p);return p


def verify(out):
    out=Path(out);p=read(out/'plan.json')
    if p['code_hashes']!=hashes():raise ValueError('implementation_changed_prepare_new_version')
    for f,h in p['inputs'].items():
        if digest_file(f)!=h:raise ValueError('bound_source_changed:'+f)
    model=p['source_plan'].get('local_whisper')
    if model:
        current=base.whisper.model_info(model['path']);current['options']['language']=model['options']['language']
        if current!=model:raise ValueError('local_whisper_changed')
    return p


def done(out,p):
    out=Path(out)
    results={}
    for t in p['tasks']:
        f=out/'results'/(signature(t['id'])[:24]+'.json')
        if not f.exists():continue
        r=read(f)
        if r.get('binding')!=signature({'plan':signature(p),'task':t}) or r.get('payload_hash')!=signature({k:v for k,v in r.items() if k!='payload_hash'}):
            raise ValueError('invalid_specialist_result')
        for path,h in r['evidence_files'].items():
            if digest_file(path)!=h:raise ValueError('specialist_evidence_changed')
        if r.get('specialist')!=t['kind']:raise ValueError('wrong_specialist_route')
        revalidate_result(out,p,t,r)
        results[t['id']]=r
    return results


def revalidate_result(out,p,task,result):
    """Replay mandatory selection gates; a rehashed selected flag is not evidence."""
    folder=out/'work'/signature(task['id'])[:24]
    if task['kind']=='document_links':
        source_records=[]
        for page in task['pages']:
            saved=read(out/'results'/(signature(page['id'])[:24]+'.json'))
            source_records+=saved['records']
        document_links.verify(task,folder,result,source_records);return
    if task['kind']=='code':
        code_workflow.validate_saved(task['unit'],folder,result,p['tool_runtime']['code_python'])
        return
    if task['kind']=='audio':
        audio_workflow.validate_saved(task['unit'],folder,result)
        return
    if task['kind']=='video_coverage':
        if any(r['eligible_for_chunking'] for r in result['records']):raise ValueError('video_diagnostic_cannot_be_selected')
        return
    t=task['unit'];first=read(folder/'visual-base.json')
    base.validate_result(folder,p['source_plan'],t,first)
    if 'visual_result' not in first['evidence']:
        if result['records']!=first['records']:raise ValueError('rendering_gate_bypassed')
        return
    guarded=read(first['evidence']['visual_result'])
    native=read(out/'native-inventory.json');source_review=None;extra_changes=[];initial_rows=first['records']
    if p.get('followup_policy')==source_followup.POLICY:
        final,source_review,extra_changes=source_followup.run(t,guarded,native,p,folder/'source-followup',None,read_only=True)
        effective_changes=source_followup.effective_changes(guarded,final)
        initial_rows=source_followup.records(t,guarded,final,initial_rows);guarded=final
    pdf_path=Path(source_review['structure_review']) if source_review and source_review.get('structure_review') else folder/'pdf-structure-review.json'
    pdf_review=read(pdf_path) if pdf_path.exists() else None
    expected,_=document_workflow.apply(t,guarded,initial_rows,native,pdf_review,source_review)
    if p.get('ocr_policy')=='selective_auxiliary_v1':
        receipt=visual_ocr.collect(t,guarded,p,folder,read_only=True)
        expected=visual_ocr.apply(t,guarded,expected,receipt,read(folder/'page-ocr-review.json'),p['source_plan']['gemini_model'])
    expected=source_followup.add_unresolved(t,expected,source_review)
    changes=effective_changes if p.get('followup_policy')==source_followup.POLICY else copy.deepcopy(first['changes'])
    for f in sorted((folder/'ink').glob('*/bundle.json')):
        bundle=read(f);package=bundle['package']
        records,edits=ink_workflow.select(t,package,bundle['result'],f)
        aid=bundle['annotation_id']
        for row in expected:
            if row['id']==t['id']+':'+aid:
                row.update(eligible_for_chunking=False,judgment='superseded_observation',reasons=['replaced_by_specialist_ink_records'])
        expected+=records;changes+=edits
    if sorted(expected,key=lambda x:x['id'])!=sorted(result['records'],key=lambda x:x['id']):
        raise ValueError('specialist_selection_changed')
    if sorted(changes,key=signature)!=sorted(result['changes'],key=signature):raise ValueError('specialist_changes_changed')


def visual(t,p,folder,client,context):
    source_plan=p['source_plan'];seed=p['seeds'].get(t['id'])
    t=copy.deepcopy(t)
    if p.get('ppt_reference'):
        proposal=ppt_reuse.choose(t,read(p['ppt_reference']))
        if proposal:
            t['ppt_proposal']=proposal
            save(folder/'ppt-reuse.json',proposal)
    av_link=None
    if p.get('av_context_policy')==av_context.POLICY:
        context,av_link=av_context.audio_for_frame(t,context)
        t['audio_context_interval']=av_link.get('source_interval')
        save(folder/'audio-context-binding.json',av_link)
    if t['source_kind']=='video' and source_plan.get('units'):
        frames=sorted((u for u in source_plan['units'] if u['source_id']==t['source_id'] and u['modality']=='visual'),key=lambda u:u['time_seconds'])
        pos=next(i for i,u in enumerate(frames) if u['id']==t['id'])
        t.update(before_image=frames[max(0,pos-1)]['image'],after_image=frames[min(len(frames)-1,pos+1)]['image'])
        audio=next((u for u in source_plan['units'] if u['source_id']==t['source_id'] and u['modality']=='audio'),None)
        if audio:t.update(source_audio=audio['source_audio'],audio_offset_seconds=audio['location'].get('audio_offset_seconds',0))
    result=base.process_visual(folder,source_plan,t,client,context,read(seed) if seed else None)
    original=copy.deepcopy(result)
    original.update(plan_signature=signature(source_plan),unit_id=t['id'])
    if 'visual_result' in original['evidence']:original['visual_result_sha256']=digest_file(original['evidence']['visual_result'])
    original['result_payload_sha256']=signature(original);save(folder/'visual-base.json',original)
    if 'visual_result' not in result['evidence']:
        return {**result,'executed':['rendering_gate_failed_no_publication']}
    guarded=read(result['evidence']['visual_result'])
    native=read(Path(p['_output'])/'native-inventory.json');source_review=None;initial_rows=result['records']
    if p.get('followup_policy')==source_followup.POLICY:
        final,source_review,changes=source_followup.run(t,guarded,native,p,folder/'source-followup',client)
        result['changes']=source_followup.effective_changes(guarded,final)
        initial_rows=source_followup.records(t,guarded,final,initial_rows);guarded=final
    structural=t['source_kind']=='pdf' or (t['source_kind']=='ppt' and p.get('followup_policy'))
    pdf_review=(read(source_review['structure_review']) if source_review and source_review.get('structure_review') else
        pdf_workflow.review(t,guarded,folder,client) if structural and 'pdf_inventory' in t else None)
    rows,local=document_workflow.apply(t,guarded,initial_rows,native,pdf_review,source_review)
    page_ocr=None
    if p.get('ocr_policy')=='selective_auxiliary_v1':
        page_ocr=visual_ocr.collect(t,guarded,p,folder)
        checked=visual_ocr.review(t,guarded,page_ocr,folder,client,source_plan['gemini_model'])
        rows=visual_ocr.apply(t,guarded,rows,page_ocr,checked,source_plan['gemini_model'])
        local['auxiliary_ocr']={'state':page_ocr['state'],'regions':len(page_ocr['regions']),
            'words':len(page_ocr['words']),'discrepancies':len(checked['data']['issues'])}
    rows=source_followup.add_unresolved(t,rows,source_review)
    # Coarse annotation rows stay as observations, while the existing specialist
    # produces the authoritative mark/word/link records. Never use coarse text as gold.
    annotations=[v for v in guarded['original']['visuals'] if v['kind']=='annotation']
    annotations += [v for v in guarded['visuals'] if v['kind']=='annotation' and v['id'] not in {x['id'] for x in annotations}]
    if t['source_kind']=='ink' and not annotations:
        annotations=[{'id':'whole-source-ink','bbox':[0,0,1000,1000]}]
    for a in annotations:
        new,changes=ink_workflow.run(t,a,context,folder/'ink'/signature(a['id'])[:16],
            {'source_signature':signature(source_plan),'model':source_plan['gemini_model'],'ocr_policy':p.get('ocr_policy')},client,
            p['ocr_models'] if p.get('ocr_available',True) else None,p['ocr_python'])
        for row in rows:
            if row['id']==t['id']+':'+a['id']:
                row.update(eligible_for_chunking=False,judgment='superseded_observation',
                           reasons=['replaced_by_specialist_ink_records'])
        rows+=new;result['changes']+=changes
    return {**result,'records':rows,'local_checks':local,'av_context':av_link,'source_followup':source_review,
            'executed':([ppt_reuse.POLICY] if t.get('ppt_proposal') else [])+(['selective_auxiliary_ocr','ocr_source_discrepancy_review'] if page_ocr is not None else [])+['visual_extraction','correction_gate','source_coordinate_identity','frame_checks','native_document_comparison']+
                       (['ink_continue_v2','ink_ocr','ink_policy','ink_selection'] if annotations else [])+
                       (['source_timed_audio_hints'] if av_link and av_link['record_ids'] else [])}


def video(t,p,folder):
    source=t['source'];sid=source['source_sha256'];units=[u for u in p['source_plan']['units'] if u['source_id']==sid and u['modality']=='visual']
    frames=[{'id':u['unit_key'],'path':u['image'],'time_seconds':u['time_seconds']} for u in units]
    timeline=multimodal_checks.inspect_timeline(frames,source['video_metadata']['duration_seconds'],p['source_plan']['config']['max_frame_gap'])
    events,metrics=multimodal_checks.scan_video(Path(source['source_file']),frames,source['video_metadata'],folder,
        scan_fps=p['source_plan']['config']['scan_fps'],frame_root=Path('/'))
    if source.get('supplemental_scan'):
        supplemental=read(source['supplemental_scan'])
        events += [{'reason':'supplemental_source_frame_unresolved','category':'warning',
            'start_seconds':r['requested'],'end_seconds':r['requested'],'detail':r['reason']}
            for r in supplemental['unresolved']]
    rows=[]
    for i,f in enumerate(timeline+events):
        unit=units[0] if units else {'id':t['id'],'source_id':sid,'source_file':source['source_file'],'location':{}}
        r=base.base_record(unit,'video-coverage:'+str(i),'video','coverage_issue','')
        r.update(reasons=[f['reason']],raw_payload=f);rows.append(r)
    save(folder/'video-coverage.json',{'timeline':timeline,'events':events,'metrics':metrics})
    return {'records':rows,'changes':[],'status':'complete','executed':['video_timeline','decoded_source_frame_comparison','scene_change_scan'],'metrics':metrics}


def canonical_record(r,low_impact_policy=None):
    # Reuse the established normalization without replacing observations/evidence.
    out=copy.deepcopy(r);text=r.get('observed_text') or ''
    normalized,ops=preprocessing.normalize_text(text,r['kind'])
    out.update(normalized_text=normalized,normalization_operations=ops,
               approved_for_rag=bool(r.get('eligible_for_chunking')),gold_approved=False)
    for key,value in {'schema_version':preprocessing.VERSION,'parent_id':r.get('unit_id'),
                      'concept_ids':[],'educational_role':None,'correction_candidates':[],
                      'importance':{'score':None,'basis':None,'status':'not_assessed'}}.items():
        out.setdefault(key,value)
    if low_impact_policy==LOW_IMPACT_POLICY and not out.get('eligible_for_chunking'):
        ir=out.get('impact_review') or {}
        reasons=set(out.get('reasons',[]))
        if (ir.get('route')=='administrator' and ir.get('impact')=='low'
                and out.get('modality')!='code' and out.get('kind')!='code'
                and not (reasons & STRICT_SAFETY_REASONS)):
            has_content=bool(text.strip()) or (out.get('kind') not in ('coverage_issue','text','speech','handwriting','printed_text','table','math','code')
                                               and bool(out.get('related_record_ids') or out.get('bbox')))
            if out.get('kind')!='coverage_issue' and has_content:
                out.update(eligible_for_chunking=True,approved_for_rag=True,
                           judgment='accepted_with_low_impact_warning',
                           warnings=sorted(set(out.get('warnings',[])+['low_impact_warning_accepted',*out.get('reasons',[])])),
                           low_impact_warning={'policy':LOW_IMPACT_POLICY,'status':'included_with_warning',
                                               'reason':ir.get('reason',''),'original_reasons':list(out.get('reasons',[]))},
                           importance={'score':'low_error_impact','basis':ir.get('policy','impact_gate'),'status':'assessed_post_recheck'})
                if isinstance(out.get('eligible_for_generation'),dict):
                    out['eligible_for_generation']={k:True for k in out['eligible_for_generation']}
            else:
                out.update(judgment='low_impact_omission_resolved',
                           low_impact_warning={'policy':LOW_IMPACT_POLICY,'status':'omission_resolved_without_chunk',
                                               'reason':ir.get('reason',''),'original_reasons':list(out.get('reasons',[]))},
                           importance={'score':'low_error_impact','basis':ir.get('policy','impact_gate'),'status':'assessed_post_recheck'})
        elif out.get('judgment') not in ('superseded_observation','context_only'):
            out['importance']={'score':ir.get('impact','high_or_unknown'),'basis':'strict_hold_after_recheck','status':'held_for_review'}
    return out


def publish(out,p):
    results=done(out,p);rows=[];changes=[];pending=[]
    for t in p['tasks']:
        if t['id'] in results:
            rows+=results[t['id']]['records'];changes+=results[t['id']]['changes']
        else:pending.append({'id':t['id'],'kind':t['kind'],'status':'unprocessed'})
    for issue in p['source_plan'].get('source_issues',[]):
        pending.append({'id':issue['source_sha256'],'kind':'source','status':'unprocessed','reason':issue['reason']})
    rows=[canonical_record(r,p.get('low_impact_policy')) for r in rows]
    resolved={i for r in results.values() for i in r.get('resolved_coverage_ids',[])}
    # A middle page may depend on both neighbors. One pair must not clear a
    # continuation still unresolved (or unprocessed) in the other pair.
    for row in rows:
        if row['id'] not in resolved:continue
        relevant=[t for t in p['tasks'] if t['kind']=='document_links' and any(u['id']==row.get('unit_id') for u in t['pages'])]
        if any(row['id'] not in results.get(t['id'],{}).get('resolved_coverage_ids',[]) for t in relevant):resolved.discard(row['id'])
    for row in rows:
        if row['id'] in resolved and row['reasons']==['pdf_cross_page_connection_requires_review']:
            row.update(judgment='superseded_observation',resolution='adjacent_original_pages_rechecked')
    # Source-frame diagnostics are selection gates, not a disconnected report.
    for t in p['tasks']:
        if t['kind']!='video_coverage':continue
        sid=t['source']['source_sha256'];check=results.get(t['id'])
        events=[] if check is None else [r['raw_payload'] for r in check['records']]
        frames={u['id']:u['unit_key'] for u in p['source_plan']['units'] if u['source_id']==sid and u['modality']=='visual'}
        for r in rows:
            if r.get('unit_id') not in frames or not r['eligible_for_chunking']:continue
            failures=[e['reason'] for e in events if (e.get('category')=='error' or e['reason'] in
                      ('selected_timestamp_not_decoded','no_decoded_frames')) and
                      (not e.get('frame_id') or e['frame_id']==frames[r['unit_id']])]
            if check is None:failures.append('video_source_check_pending')
            if failures:
                r.update(eligible_for_chunking=False,approved_for_rag=False,judgment='held')
                r.pop('low_impact_warning',None)
                r['reasons']=sorted(set(r['reasons']+failures))
    if len({r['id'] for r in rows})!=len(rows):raise ValueError('duplicate_common_record_id')
    selected=[r for r in rows if r.get('eligible_for_chunking')]
    # No dangling selected relationships. Keep both records and reason history.
    while True:
        ids={r['id'] for r in selected};bad=[r for r in selected if set(r.get('related_record_ids',[]))-ids]
        if not bad:break
        for r in bad:
            r.update(eligible_for_chunking=False,approved_for_rag=False,judgment='held')
            r.pop('low_impact_warning',None)
            r['reasons']+=['unselected_relation_target']
        selected=[r for r in selected if r['eligible_for_chunking']]
    rev=signature({'plan':signature(p),'results':results,'records':rows})[:24];dest=out/'revisions'/rev
    held=[r for r in rows if not r['eligible_for_chunking'] and r['judgment'] not in ('superseded_observation','context_only','low_impact_omission_resolved')]
    files={'records.jsonl':rows,'usable-records.jsonl':selected,'review-required.jsonl':held,
           'neighbor-review-queue.jsonl':[{'task_id':tid,**x} for tid,r in results.items() for x in r.get('neighbor_queue',[])],
           'followup-decisions.jsonl':[{'task_id':tid,**x} for tid,r in results.items() for x in r.get('impact_followup',[])+r.get('neighbor_followup',[])],
           'audiovisual-comparisons.jsonl':[{'task_id':tid,**n} for tid,r in results.items()
                for n in (r.get('av_context') or {}).get('comparisons',[])],
           'administrator-review.jsonl':[r for r in held if r.get('impact_review',{}).get('route')=='administrator'],
           'word-alignment-queue.jsonl':[r for r in selected if r.get('modality')=='audio' and r.get('word_alignment_required')],
           'changes.jsonl':changes,'pending.jsonl':pending}
    if p.get('low_impact_policy')==LOW_IMPACT_POLICY:
        files['low-impact-warnings.jsonl']=[r for r in rows if r.get('low_impact_warning')]
    if any(t['kind']=='code' for t in p['tasks']):
        files['code-context.jsonl']=[r for r in rows if r.get('modality')=='code' and r['judgment']=='context_only']
    from video_extraction.pipeline import data_integration
    code_corpus=code_workflow.corpus_for(selected) if any(t['kind']=='code' for t in p['tasks']) else None
    bundles=data_integration.integrate_records(selected,units=p.get('source_plan',{}).get('units',[]),code_corpus=code_corpus)
    files['multimodal-bundles.jsonl']=bundles
    manifest=dest/'manifest.json'
    if not manifest.exists():
        dest.mkdir(parents=True,exist_ok=True)
        for name,items in files.items():jsonl(dest/name,items)
        save(manifest,{'plan_signature':signature(p),'files':{name:digest_file(dest/name) for name in files}})
    for name,h in read(manifest)['files'].items():
        if digest_file(dest/name)!=h:raise ValueError('published_output_changed')
    latest={'manifest':str(manifest),'records':str(dest/'records.jsonl'),'usable_records':str(dest/'usable-records.jsonl'),
            'multimodal_bundles':str(dest/'multimodal-bundles.jsonl'),'pending':str(dest/'pending.jsonl')}
    if any(t['kind']=='code' for t in p['tasks']):
        corpus=code_workflow.corpus_for(selected)
        corpus['common_selection']={'manifest':str(manifest),'sha256':digest_file(manifest)}
        corpus_path=dest/'code-rag'/'corpus.json'
        if corpus_path.exists() and read(corpus_path)!=corpus:raise ValueError('published_code_corpus_changed')
        save(corpus_path,corpus);latest['code_corpus']=str(corpus_path)
    aligned=None
    if p.get('tool_runtime') and any(r.get('modality')=='audio' for r in selected):
        aligned=alignment_bridge.prepare(out,p,latest['usable_records'])
        latest['usable_records_with_word_timing']=aligned['records_with_timing']
        latest['word_timing_review']=aligned['word_timing_review']
    save(out/'latest.json',latest)
    summary={'tasks':len(p['tasks']),'completed':len(results),'pending':len(pending),'usable_records':len(selected),
             'multimodal_bundles':len(bundles),
             'held_records':len(held),'superseded_observations':sum(r['judgment']=='superseded_observation' for r in rows),
             'administrator_holds':sum(r.get('impact_review',{}).get('route')=='administrator' for r in held),
             'low_impact_warning_records':sum(r.get('judgment')=='accepted_with_low_impact_warning' for r in rows),
             'low_impact_omissions_resolved':sum(r.get('judgment')=='low_impact_omission_resolved' for r in rows),
             'low_impact_policy':p.get('low_impact_policy'),
             'api_attempts':sum(len(read(f)['attempts']) for f in (out/'runs').glob('*.json')),
             'accuracy_pct':None,'all_tasks_processed':not pending}
    summary.update(unresolved_records=len(held),processing_finished=not pending,
                   review_finished=not pending and not held,
                   source_followup_tasks=sum(bool(r.get('source_followup')) for r in results.values()),
                   document_link_tasks=sum(r.get('specialist')=='document_links' for r in results.values()))
    summary['audiovisual_comparison']={
        'audio_windows_with_frames':sum((r.get('av_context') or {}).get('windows_with_frames',0) for r in results.values()),
        'visual_tasks_with_audio_context':sum(bool((r.get('av_context') or {}).get('record_ids')) for r in results.values()),
        'comparisons':sum(len((r.get('av_context') or {}).get('comparisons',[])) for r in results.values()),
        'policy':p.get('av_context_policy'),'accuracy_pct':None}
    if (out/'page-ocr/summary.json').exists():
        summary['local_ocr']=read(out/'page-ocr/summary.json')
    if aligned:summary['alignment']={k:aligned[k] for k in ('state','targets','pending_or_unresolved','records_with_timing')}
    save(out/'summary.json',summary)
    page='<meta charset="utf-8"><title>유형별 기능 연결 결과</title><style>body{font:17px/1.7 system-ui;max-width:1100px;margin:32px auto}pre{white-space:pre-wrap}</style><h1>유형별 기능 연결 결과</h1><p>검증된 기능을 호출하는 실행 경로입니다. API 미실행/보류는 정답 판정이 아닙니다. 영상 변화는 표본 검사이며 전체 장면 무누락을 보증하지 않습니다.</p><pre>'+html.escape(json.dumps(summary,ensure_ascii=False,indent=2))+'</pre>'
    for name in files:page+='<p><a href="revisions/'+rev+'/'+name+'">'+name+'</a></p>'
    notes=files['audiovisual-comparisons.jsonl']
    if p.get('av_context_policy'):
        page+='<h2>음성·화면 대조</h2><p>화면과 말의 차이 자체는 오류가 아닙니다. 화면은 후보 탐지에만 사용하고, 음성 수정은 원음만으로 다시 검사합니다. 추출한 화면 일부를 참고하므로 영상 전체 내용의 무누락 검사가 아닙니다.</p>'
        labels={'audio_supported_original_preserved':'원음 확인 후 기존 전사 유지',
                'audio_source_rechecked_repair_applied':'원음 재검사 후 수정 반영',
                'audio_recheck_unresolved':'원음 판독 미확정 · 기존 보류 유지'}
        for n in notes:
            page+='<details><summary>'+html.escape(labels[n['status']]+' · '+n['target_id'])+'</summary><p>'+html.escape(n['reason'])+'</p><pre>'+html.escape(json.dumps(n,ensure_ascii=False,indent=2))+'</pre></details>'
    if aligned:page+='<p>음성 단어 시간: '+html.escape(aligned['state'])+' · <a href="alignment-status.json">정렬 상태</a></p>'
    for r in rows:page+='<details><summary>'+html.escape(r['id']+' · '+r['judgment'])+'</summary><pre>'+html.escape(json.dumps(r,ensure_ascii=False,indent=2))+'</pre></details>'
    (out/'유형별연결_처리결과.html').write_text(page,encoding='utf-8');return summary


def run(out,env_file,maximum=600,delay=15,local_only=False,transport=None):
    out=Path(out).resolve()
    with lock(out):
        p=verify(out);results=done(out,p)
        needs_api=not local_only and any(t['id'] not in results and t['kind'] in ('audio','visual','document_links') for t in p['tasks'])
        budget=Budget(out,maximum,delay,**({'transport':transport} if transport else {})) if needs_api else SimpleNamespace(used=0)
        client=None
        if len(results)<len(p['tasks']):
            environment=runtime_tools.audit(p,out)
            runtime_tools.require_core(environment)
            for check in environment['checks']:
                if not check['ok']:
                    print('선택 도구 준비 필요: '+check['tool']+' · 해당 보조 단계의 미실행 상태를 기록합니다.',flush=True)
            if p.get('ocr_policy')=='selective_auxiliary_v1':
                print('OCR은 화면 판독 후 필요한 영역에만 보조로 사용합니다. 전체 화면 선행 OCR은 실행하지 않습니다.',flush=True)
        transcriber=base.whisper.LocalWhisper(p['source_plan']['local_whisper'],out/'whisper-cache') if p['source_plan'].get('local_whisper') and not local_only else None
        error=None;failure=None;active_task=None
        try:
            for t in p['tasks']:
                if t['id'] in results:continue
                if local_only and t['kind'] not in ('code','video_coverage'):continue
                if t['kind']=='document_links' and any(u['id'] not in results for u in t['pages']):continue
                progress.report('video_review' if t['kind']=='visual' else 'source_check', len(results), len(p['tasks']))
                active_task=t['id']
                key=signature(t['id'])[:24];folder=out/'work'/key;folder.mkdir(parents=True,exist_ok=True)
                print(json.dumps({'specialist':t['kind'],'completed':len(results),'total':len(p['tasks']),'task':t['id']},ensure_ascii=False),flush=True)
                try:
                    if t['kind'] in ('audio','visual','document_links') and client is None:
                        api_key(env_file);client=Gemini(out/'gemini-cache',p['source_plan']['gemini_model'],env_file,max_calls=maximum,delay=0,transport=budget)
                    if t['kind']=='code':r=code_workflow.run(t['unit'],folder,p['tool_runtime']['code_python'])
                    elif t['kind']=='document_links':r=document_links.run(t,results,folder,client)
                    elif t['kind']=='audio':
                        units=[u for u in p['source_plan']['units'] if u['source_id']==t['unit']['source_id'] and u['modality']=='audio']
                        frames=av_context.usable_frames(p,results,t['unit']['source_id'])
                        r=audio_workflow.run(t['unit'],units,folder,p,client,transcriber,visual_units=frames)
                    elif t['kind']=='visual':
                        context=[{**r,'text':r['observed_text']} for result in results.values() for r in result['records'] if r['modality']=='audio' and r['kind']=='speech' and r['eligible_for_chunking']]
                        r=visual(t['unit'],{**p,'_output':str(out)},folder,client,context)
                    else:r=video(t,p,folder)
                except ValueError as ex:
                    save(out/'errors'/(key+'.json'),{'task':t['id'],'reason':str(ex)});continue
                r.update(specialist=t['kind'],binding=signature({'plan':signature(p),'task':t}),
                    evidence_files={str(f):digest_file(f) for f in folder.rglob('*') if f.is_file() and f.suffix in ('.json','.wav','.png')})
                r['payload_hash']=signature(r);save(out/'results'/(key+'.json'),r);results[t['id']]=r
                publish(out,p)
        except (Blocked,KeyboardInterrupt) as ex:error=str(ex) or 'interrupted'
        except Exception as ex:
            error='unexpected_error'
            # Stack locations only: exception values/locals can contain keys or
            # request data. Keep a useful durable diagnosis without secrets.
            failure={'exception_type':type(ex).__name__,'task_id':active_task,
                     'stack':[{'file':f.filename,'line':f.lineno,'function':f.name}
                              for f in traceback.extract_tb(ex.__traceback__)]}
            save(out/'last-failure.json',failure)
            raise
        finally:
            progress.report('finalize')
            state={'stop_reason':error or 'finalizing','api_calls_this_run':budget.used,'failure':failure}
            save(out/'run-state.json',state)
            summary=publish(out,p)
            state['stop_reason']=error or ('pending' if summary['pending'] else 'complete')
            save(out/'run-state.json',state)
        if error:raise Blocked(error)
        if summary['all_tasks_processed'] and not local_only:
            save(out/'run-state.json',{'stop_reason':'word_alignment_running','api_calls_this_run':budget.used,'failure':None})
            progress.report('alignment')
            aligned=alignment_bridge.run(out,p)
            summary=publish(out,p)
            summary['alignment']={k:aligned[k] for k in ('state','targets','pending_or_unresolved','records_with_timing')}
            save(out/'summary.json',summary)
            save(out/'run-state.json',{'stop_reason':'complete' if aligned['state'] in ('complete','not_required') else 'complete_with_alignment_review',
                 'api_calls_this_run':budget.used,'alignment_state':aligned['state'],'failure':None})
        return summary


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('mode',choices=['prepare','run','report','doctor','bundle'])
    ap.add_argument('--output',type=Path,required=True);ap.add_argument('--input',type=Path,action='append')
    ap.add_argument('--reuse-plan',type=Path);ap.add_argument('--gemini-model');ap.add_argument('--whisper-model',type=Path)
    ap.add_argument('--ocr-models',type=Path);ap.add_argument('--ocr-python',type=Path);ap.add_argument('--kind')
    ap.add_argument('--native-python',type=Path);ap.add_argument('--alignment-python',type=Path)
    ap.add_argument('--code-python',type=Path);ap.add_argument('--local-only',action='store_true',help='코드·로컬 진단만 처리. Gemini API 호출 없음')
    ap.add_argument('--alignment-model');ap.add_argument('--allow-alignment-download',action='store_true')
    ap.add_argument('--env-file',type=Path,default=Path('.env'));ap.add_argument('--max-api-calls',type=int,default=600);ap.add_argument('--delay',type=float,default=15)
    a=ap.parse_args();out=a.output.resolve()
    try:
        if a.mode=='prepare':prepare(out,a.input,a.gemini_model,a.whisper_model,a.ocr_models,a.ocr_python,a.reuse_plan,a.kind,
            a.native_python,a.alignment_python,a.alignment_model,a.allow_alignment_download,a.code_python);s=read(out/'summary.json')
        elif a.mode=='doctor':
            s=runtime_tools.audit(read(out/'plan.json'),out)
            print(json.dumps(s,ensure_ascii=False,indent=2));return 0 if s['core_ready'] else 2
        elif a.mode=='bundle':
            from video_extraction.pipeline import data_integration
            s, _ = data_integration.bundle_directory(out)
            print(json.dumps(s,ensure_ascii=False,indent=2));return 0
        elif a.mode=='run':s=run(out,a.env_file,a.max_api_calls,a.delay,a.local_only)
        else:
            with lock(out):s=publish(out,verify(out))
        print(json.dumps(s,ensure_ascii=False,indent=2));return 0
    except (ValueError,OSError,RuntimeError,Blocked) as ex:print(json.dumps({'stopped':str(ex)},ensure_ascii=False));return 2
    except Exception as ex:
        print(json.dumps({'stopped':'unexpected_error','exception_type':type(ex).__name__,
                          'diagnostic':str(out/'last-failure.json')},ensure_ascii=False));return 2

if __name__=='__main__':raise SystemExit(main())
