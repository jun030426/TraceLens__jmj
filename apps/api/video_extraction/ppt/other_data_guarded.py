"""Versioned continuation with a mandatory offline calculation gate.

prepare reuses saved candidates without API. Only run may create an API client.
Old plans, results, and cache remain untouched; shared locks prevent parallel runs.
"""
from video_extraction._layout import source_path, code_hashes_match
import argparse
import copy
from video_extraction.shared import file_lock as fcntl
import json
import shutil
from pathlib import Path
from contextlib import contextmanager
from video_extraction.ppt import other_data as old
from video_extraction.shared.common import read, save, signature, digest_file, now
from video_extraction.shared.correction_gate import enforce, require_gate, process_guarded, EVIDENCE
from video_extraction.shared.gemini import Gemini, Blocked

ROOT=old.ROOT
OUTPUT=ROOT/'outputs/other-data-v2'


def hashes():
    return {**old.hashes(), **{n:digest_file(source_path(n)) for n in
            ['other_data_guarded.py','correction_gate.py','separator_pixels.py']},
            'gate_evidence':digest_file(EVIDENCE)}


@contextmanager
def locks(output,source=None):
    from contextlib import ExitStack
    output.mkdir(parents=True,exist_ok=True)
    with ExitStack() as stack:
        for path in [ROOT/'outputs/ink-continuation-v2/.run.lock',output/'.run.lock']+([source/'.run.lock'] if source else []):
            path.parent.mkdir(parents=True,exist_ok=True)
            f=stack.enter_context(path.open('a'));fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
        yield


def check_plan(output):
    p=read(output/'plan.json')
    if not code_hashes_match(p['code_hashes'], hashes()):raise ValueError('code_changed_prepare_new_output')
    for name,h in {**p['inputs'],**p['derived']}.items():
        if digest_file(name)!=h:raise ValueError('input_changed:'+name)
    return p


def records(task,result):
    require_gate(result,task['media'])
    rows=old.screen_records(task,result)
    for r in rows:
        r['verification']='model_source_review_with_mandatory_calculation_gate'
        r['calculation_gate_version']=result['calculation_gate']['version']
        r['calculation_gate_payload_sha256']=result['calculation_gate']['payload_sha256']
    return rows


def wrap(task,result,path):
    rows=records(task,result)
    return dict(task_id=task['id'],kind=task['kind'],
                status='held' if result['holds'] or any(not r['eligible_for_chunking'] for r in rows) else 'checked',
                records=rows,changes=result['changed_blocks'],holds=result['holds'],details=str(path),
                gate_adjusted_blocks=sum(c['changed_by_gate'] for c in result['calculation_gate']['checks']))


def report(output,plan):
    # A stale/forged receipt may never reach usable-records.jsonl.
    for t in plan['tasks']:
        p=output/'results'/f"{t['id']}.json"
        if not p.exists() or t['kind']=='audio':continue
        r=read(p)
        if r.get('error') and not r.get('records'):continue
        d=read(r['details']);require_gate(d,t['media'])
        if r['records']!=records(t,d):raise ValueError('records_do_not_match_guarded_payload')
    s=old.report(output,plan)
    s.update(calculation_gate_required=True,api_calls_during_prepare=0)
    save(output/'summary.json',s)
    page=output/'다른자료_처리현황.html'
    page.write_text(page.read_text()+ '<h2>계산 검사 적용</h2><p>화면·PPT 이미지 결과는 저장 전 계산 검사를 거칩니다. '
        '재검사 자르기 범위와 저장 좌표를 구분하고 표의 칸·빈칸, 코드의 중첩 관계, 0/o 변경, '
        '원본 해시가 일치하는 구분선 픽셀 근거를 확인합니다. 픽셀 근거가 없는 개수 변경은 보류합니다. '
        '이는 전수 정답 판정이 아니며 음성의 청취 검증 방식은 기존과 같습니다.</p>')
    return s


def prepare(output=OUTPUT,source=old.OUTPUT):
    output=output.resolve();source=source.resolve()
    if output==source or source in output.parents:raise ValueError('separate_output_required')
    with locks(output,source):
        if (output/'plan.json').exists():return check_plan(output)
        p=copy.deepcopy(old.check_plan(source));p.update(version=2,created_at=now(),code_hashes=hashes(),
            api_budget_per_run=600,migration_source=str(source),calculation_gate_required=True)
        native=['native-documents.jsonl','native-changes.jsonl','native-pending.jsonl']
        for name in native:shutil.copy2(source/name,output/name)
        p['derived']={str(output/n):digest_file(output/n) for n in native}
        source_receipts={str(source/'plan.json'):digest_file(source/'plan.json')}
        migrated=[]
        for t in p['tasks']:
            src=source/'results'/f"{t['id']}.json"
            if not src.exists():continue
            r=read(src)
            if r.get('plan_signature')!=signature(read(source/'plan.json')):raise ValueError('stale_source_result')
            source_receipts[str(src)]=digest_file(src)
            save(output/'source-receipts'/src.name,r)
            if t['kind']!='audio' and r.get('details'):
                detail=Path(r['details']);source_receipts[str(detail)]=digest_file(detail)
                original=read(detail);save(output/'source-receipts'/t['id']/'result.json',original)
                guarded=enforce(original,t['media'])
                dest=output/'work'/t['id']/'vision'/t['id']/'result.json';save(dest,guarded)
                r=wrap(t,guarded,dest)
            r['plan_signature']=signature(p);save(output/'results'/src.name,r);migrated.append(t['id'])
        # Cache keys include model, prompt and actual media; copied cache is advisory only.
        if (source/'api-cache').exists():shutil.copytree(source/'api-cache',output/'api-cache',dirs_exist_ok=True)
        for name,h in source_receipts.items():
            if digest_file(name)!=h:raise ValueError('source_changed_during_migration')
        save(output/'migration.json',dict(at=now(),api_calls=0,tasks=migrated,source_sha256=source_receipts))
        save(output/'plan.json',p);report(output,p)
        save(ROOT/'outputs/other-data-active.json',{'output':str(output),'version':2})
        return p


def execute(task,output,plan,client):
    if task['kind']=='audio':return old.execute(task,output,plan,client)
    work=output/'work'/task['id'];work.mkdir(parents=True,exist_ok=True)
    frame=dict(id=task['id'],path=task['media'],time_seconds=task.get('frame',{}).get('time_seconds',0))
    result=process_guarded(frame,[frame],[],work,old.ScopedClient(client,task['baseline']))
    return wrap(task,result,work/'vision'/task['id']/'result.json')


def run(output,env,max_calls=600,delay=15):
    if max_calls<1 or delay<15:raise ValueError('invalid_limits')
    with locks(output):
        plan=check_plan(output);client=None;done=[];current=None;reason='running';started=now()
        def checkpoint():
            state=dict(started_at=started,at=now(),stop_reason=reason,completed_this_run=done,current_task=current,
                       api_stats=client.stats if client else {'requests':0},summary=report(output,plan))
            save(output/'run-state.json',state);save(output/'runs'/(started.replace(':','-')+'.json'),state)
            return state
        try:
            for task in plan['tasks']:
                dest=output/'results'/(task['id']+'.json')
                if dest.exists():
                    if read(dest).get('plan_signature')!=signature(plan):raise ValueError('stale_result')
                    continue
                current=task['id']
                if client is None:client=Gemini(output/'api-cache',plan['model'],env,max_calls=max_calls,delay=delay)
                if client.stats['requests']>=max_calls:reason='request_budget_exhausted';break
                try:r=execute(task,output,plan,client)
                except Blocked as e:
                    if str(e)=='request_budget_exhausted':reason=str(e);break
                    if str(e)!='invalid_model_response':raise
                    r=dict(task_id=task['id'],kind=task['kind'],status='held',records=[],error=str(e))
                r['plan_signature']=signature(plan);save(dest,r);done.append(task['id']);current=None;checkpoint()
                print(json.dumps(dict(completed=len(done),task=task['id'],state=r['status'],requests=client.stats['requests']),ensure_ascii=False),flush=True)
            else:reason='all_tasks_processed'
        except KeyboardInterrupt:reason='interrupted';raise
        except Exception:reason='execution_error';raise
        finally:state=checkpoint()
        return state


def main():
    a=argparse.ArgumentParser(description=__doc__);a.add_argument('mode',choices=['prepare','run','report'])
    a.add_argument('--output',type=Path,default=OUTPUT);a.add_argument('--source',type=Path,default=old.OUTPUT)
    a.add_argument('--env-file',type=Path,default=ROOT/'.env');a.add_argument('--max-api-calls',type=int,default=600)
    a.add_argument('--delay',type=float,default=15);args=a.parse_args();out=args.output.resolve()
    try:
        if args.mode=='prepare':p=prepare(out,args.source);result=report(out,p)
        elif args.mode=='report':
            with locks(out):result=report(out,check_plan(out))
        else:result=run(out,args.env_file,args.max_api_calls,args.delay)
    except BlockingIOError:
        raise SystemExit('다른 본문/PPT 또는 필기 실행이 진행 중입니다. 해당 실행 종료 후 다시 실행하세요. API를 새로 호출하지 않았습니다.')
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
