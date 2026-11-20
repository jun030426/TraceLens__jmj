"""Run successive v2 batches under ONE API request budget. User-terminal only.

The immutable extraction plan, stage receipts and existing local OCR are reused.
The same lock is shared with the one-batch entry point, preventing parallel runs.
"""
from video_extraction._layout import code_hashes_match
import argparse
from video_extraction.shared import file_lock as fcntl
import json
from pathlib import Path

from video_extraction.shared.common import read, save, now, signature, digest_file
from video_extraction.shared.gemini import Gemini, Blocked
from video_extraction.ink.runner.ink_continue import select_batch, local_batch
from video_extraction.ink.runner.ink_continue_v2 import ROOT, OUTPUT, check_plan, execute, report


def prepare_runner(output):
    with (output/'.run.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        plan=check_plan(output)
        policy=dict(version=1,extraction_plan_signature=signature(plan),
                    runner_sha256=digest_file(__file__),budget_scope='whole_invocation',
                    resume='saved_stage_then_next_batch',default_max_api_calls=60)
        dest=output/'execution-policy.json'
        if dest.exists() and read(dest)!=policy:raise ValueError('runner_policy_changed')
        save(dest,policy)
        return dict(prepared=True,api_requests=0,queue_size=len(plan['tasks']))


def run(output,env_file,python,models,max_calls=60,delay=15):
    if max_calls<1 or delay<15:raise ValueError('invalid_limits')
    with (output/'.run.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        plan=check_plan(output);policy=read(output/'execution-policy.json')
        if policy['extraction_plan_signature']!=signature(plan) or not code_hashes_match(policy['runner_sha256'], digest_file(__file__)):
            raise ValueError('stale_runner_policy')
        client=None;batch={'ids':[]};visited=[];completed=[];current=None
        reason='running';started=now();run_path=output/'runs'/('auto-'+started.replace(':','-')+'.json')

        def checkpoint():
            summary=report(output)
            state=dict(at=now(),started_at=started,mode='automatic_batches',stop_reason=reason,
                max_api_calls=max_calls,budget_scope='whole_invocation',batch_ids=batch['ids'],
                visited_batches=visited,completed_task_ids_this_run=completed,current_task_id=current,
                api_stats=client.stats if client else {'requests':0},summary=summary,
                resume_instruction='Run the same command; saved stages are reused. A new invocation has a new request allowance.')
            save(output/'run-state.json',state);save(run_path,state)
            return state

        try:
            while True:
                # Selecting validates all result signatures, resumes unfinished batch,
                # or advances only once every result in the current batch is saved.
                batch=select_batch(output,plan)
                if not batch['ids']:
                    reason='all_tasks_processed';break
                if client is not None and client.stats['requests']>=max_calls:
                    reason='request_budget_exhausted';break
                visited.append(list(batch['ids']));checkpoint()
                data=local_batch(output,plan,batch,python,models)
                for tid in batch['ids']:
                    dest=output/'results'/(tid+'.json')
                    if dest.exists():continue
                    if client is not None and client.stats['requests']>=max_calls:
                        reason='request_budget_exhausted';break
                    current=tid
                    if client is None:
                        client=Gemini(output/'api-cache',plan['model'],env_file,max_calls=max_calls,delay=delay)
                    try:result=execute(data['tasks'][tid],output,plan,client)
                    except Blocked as exc:
                        if str(exc)=='request_budget_exhausted':
                            reason='request_budget_exhausted';break
                        if str(exc)!='invalid_model_response':raise
                        # Bounded model failure is a review outcome, never success or an endless retry.
                        result=dict(task_id=tid,plan_signature=signature(plan),status='review_required',
                            error=str(exc),active_coverage_complete=False,records=[],decisions=[],changes=[])
                    save(dest,result);completed.append(tid);current=None;checkpoint()
                    print(json.dumps(dict(task=tid,state=result['status'],requests=client.stats['requests'],
                        max_api_calls=max_calls,completed_this_run=len(completed)),ensure_ascii=False),flush=True)
                if reason=='request_budget_exhausted':break
        except KeyboardInterrupt:
            reason='interrupted';raise
        except Blocked as exc:
            reason=str(exc);raise
        except Exception:
            reason='execution_error';raise
        finally:
            state=checkpoint()
        return {**state['summary'],'stop_reason':reason,'api_requests':state['api_stats']['requests'],
                'completed_this_run':len(completed)}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('mode',choices=['prepare','run']);p.add_argument('--output',type=Path,default=OUTPUT)
    p.add_argument('--env-file',type=Path,default=ROOT/'.env');p.add_argument('--max-api-calls',type=int,default=60)
    p.add_argument('--delay',type=float,default=15)
    p.add_argument('--ocr-python',type=Path,default=ROOT/'work/extraction-compare/env/bin/python')
    p.add_argument('--ocr-models',type=Path,default=ROOT/'work/extraction-compare/paddlex/official_models')
    a=p.parse_args();out=a.output.resolve()
    result=prepare_runner(out) if a.mode=='prepare' else run(out,a.env_file,a.ocr_python,a.ocr_models,a.max_api_calls,a.delay)
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
