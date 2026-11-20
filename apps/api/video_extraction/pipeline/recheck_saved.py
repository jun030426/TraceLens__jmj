"""Offline re-selection of saved common-pipeline candidates; never an API client.

Source results/revisions remain immutable. New plan binds all reused evidence.
"""
import argparse
import copy
import shutil
from pathlib import Path
from video_extraction.pipeline import runner as m, visual_gate
from video_extraction.shared.common import read, save, signature, digest_file, now


def recheck(source, out):
    source=Path(source).resolve();out=Path(out).resolve()
    if source==out or source in out.parents or out in source.parents:
        raise ValueError('separate_output_required')
    with m.lock(out):
        if (out/'plan.json').exists():
            p=m.verify(out)
            if p.get('rechecked_from')!=str(source):raise ValueError('different_recheck_source')
            # Existing incomplete migration can resume from source below.
        old=read(source/'plan.json')
        for f,h in old['inputs'].items():
            if digest_file(f)!=h:raise ValueError('old_input_changed:'+f)
        p=copy.deepcopy(old);p.update(code_hashes=m.hashes(),created_at=now(),rechecked_from=str(source),
            recheck_policy='mandatory_source_calculation_gate_v1',prior_plan_signature=signature(old))
        p['inputs'][str(source/'plan.json')]=digest_file(source/'plan.json')
        cached={}
        for t in old['units']:
            f=source/'results'/(t['unit_key']+'.json')
            if not f.exists():continue
            r=read(f)
            if (r.get('result_payload_sha256')!=signature({k:v for k,v in r.items() if k!='result_payload_sha256'})
                    or r['plan_signature']!=signature(old) or r['unit_id']!=t['id']):
                raise ValueError('invalid_historical_result')
            p['inputs'][str(f)]=digest_file(f)
            if 'visual_result' in r['evidence']:
                v=Path(r['evidence']['visual_result'])
                if digest_file(v)!=r['visual_result_sha256']:raise ValueError('old_visual_evidence_changed')
                p['inputs'][str(v)]=digest_file(v)
            if t['modality']=='audio':
                f=source/'units'/t['unit_key']/'initial.json'
                if digest_file(f)!=r['evidence']['initial_sha256']:raise ValueError('old_audio_initial_changed')
                p['inputs'][str(f)]=digest_file(f)
            cached[t['id']]=r
        if (out/'plan.json').exists():
            existing=read(out/'plan.json');p['created_at']=existing['created_at']
            if p!=existing:raise ValueError('recheck_inputs_changed_choose_new_output')
        else:save(out/'plan.json',p)
        m.verify(out)
        for t in p['units']:
            dest=out/'results'/(t['unit_key']+'.json')
            if dest.exists():m.validate_result(out,p,t,read(dest));continue
            if t['id'] not in cached:
                failure=source/'unit-errors'/(t['unit_key']+'.json')
                if failure.exists():save(out/'unit-errors'/failure.name,read(failure))
                continue
            r=copy.deepcopy(cached[t['id']])
            if t['modality']=='visual' and 'visual_result' in r['evidence']:
                candidate=read(r['evidence']['visual_result'])
                result=visual_gate.enforce(candidate,t['image'])
                target=out/'vision'/t['unit_key']/'result.json';save(target,result)
                records=visual_gate.records(t,result,m.base_record)
                previous={x['id']:x for x in r['records']}
                for record in records:
                    oldrec=previous.get(record['id'],{});ir=oldrec.get('impact_assessment')
                    # Reuse low-impact routing only for the exact unchanged source
                    # region and no newly discovered calculation/identity defect.
                    if (ir and not record['eligible_for_chunking'] and
                        not record.get('safety_findings') and
                        oldrec.get('bbox')==record.get('bbox') and
                        oldrec['observed_text']==record['observed_text']):
                        record['impact_assessment']=ir
                        if m.visual_impact_gate(record,ir):
                            name=signature(record['id'])[:16]+'.png'
                            oldcrop=source/'units'/t['unit_key']/name
                            crop=out/'units'/t['unit_key']/name;crop.parent.mkdir(parents=True,exist_ok=True)
                            shutil.copyfile(oldcrop,crop)
                            record.update(m.hold_for_administrator(record,ir['reason'],
                                {'assessment':ir,'source_sha256':t['source_id'],'crop_sha256':digest_file(crop)}))
                r.update(records=records,changes=result['corrections'],holds=result['holds']+result['deferred_regions'],
                    evidence={'visual_result':str(target),'visual_signature':result['signature']},
                    visual_result_sha256=digest_file(target))
            elif t['modality']=='audio':
                initial=source/'units'/t['unit_key']/'initial.json'
                save(out/'units'/t['unit_key']/'initial.json',read(initial))
                before=read(initial)['text'];ev=r['evidence'];task=m.task_audio(t,before,m.audio_proposal(before,ev['blind']['text']))
                gate=m.audio_gate(task,ev['blind'],ev['review']);ev['gate']=gate
                if not gate['passed']:
                    record=r['records'][0]
                    record.update(observed_text=before,original_text=before,eligible_for_chunking=False,
                        judgment='held',reasons=gate['reasons'],word_alignment_required=False)
                    r['changes']=[];r['holds']=[{'unit_id':t['id'],'reasons':gate['reasons']}]
            r.update(plan_signature=signature(p),unit_id=t['id'],at=now())
            r.pop('result_payload_sha256',None);r['result_payload_sha256']=signature(r)
            m.validate_result(out,p,t,r);save(dest,r)
        summary=m.publish(out,p)
        save(out/'offline-recheck.json',{'source':str(source),'api_calls':0,'summary':summary,
            'historical_results_unchanged':True,'method':'saved_candidates_through_mandatory_gate',
            'accuracy_measured':False})
        return summary


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--source',type=Path,required=True);ap.add_argument('--output',type=Path,required=True)
    a=ap.parse_args();print(recheck(a.source,a.output))

if __name__=='__main__':main()
