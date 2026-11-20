"""PPT native-source checks and resumable screen/image/audio review. API only in run.

Original extraction and ink plans remain immutable. Native XML fidelity is not
visual rendering verification or a claim that a lecture's contents are true.
"""
from video_extraction._layout import source_path, code_hashes_match
#ppt 원문 추출,자료검사,결과 저장 기본기능
import argparse
import copy
from video_extraction.shared import file_lock as fcntl
import html
import json
import posixpath
import zipfile#PPTX 내부 파일을 열기
import xml.etree.ElementTree as ET#슬라이드의 텍스트·표 내용을 읽기
from collections import Counter, defaultdict, deque
from pathlib import Path

from PIL import Image
from video_extraction.shared.common import read, save, jsonl, signature, digest_file, now
from video_extraction.shared.gemini import Gemini, Blocked
from video_extraction.video.vision_layers import process_frame_layers, validate_extraction, visual_problems
from video_extraction.audio.audio_review import review_segment
from video_extraction.shared.multimodal_validation import cut_audio
from video_extraction.ink.runner.ink_continue_v2 import ROOT

OUTPUT=ROOT/'outputs/other-data-v1'
PREPROCESS=ROOT/'outputs/preprocessing-v1'
NS={'p':'http://schemas.openxmlformats.org/presentationml/2006/main',
    'a':'http://schemas.openxmlformats.org/drawingml/2006/main',
    'r':'http://schemas.openxmlformats.org/officeDocument/2006/relationships'}
REL='{http://schemas.openxmlformats.org/package/2006/relationships}'
NON_INK='\nThis job covers PRINTED text/code/tables/diagrams only. Handwritten marks and words are handled by a separate pipeline. Do not extract, repair, or flag omission of handwriting/circles/underlines. Preserve printed content obscured by ink as uncertain when necessary. Do not use speech or programming plausibility to fill characters.'


def hashes():
    return {n:digest_file(source_path(n)) for n in ['other_data.py','common.py','gemini.py',
        'vision_layers.py','vision_optimized.py','vision.py','audio_review.py','media.py','multimodal_validation.py']}


def xml_text(body):
    lines=[]
    for p in body.findall('a:p',NS):
        text=''
        for node in p:
            tag=node.tag.split('}')[-1]
            if tag in ('r','fld'):text+=''.join(t.text or '' for t in node.findall('a:t',NS))
            elif tag=='br':text+='\v'
        lines.append(text)
    return '\n'.join(lines)

#원문 추출-Python으로 PPTX 내부 XML을 직접 읽는 방식 
def ppt_native(path):
    """Read actual presentation ordering and XML values without rendering or guessing."""
    rows=[];pending=[];assets=[]
    with zipfile.ZipFile(path) as z:
        rels={x.attrib['Id']:x.attrib.get('Target') for x in ET.fromstring(z.read('ppt/_rels/presentation.xml.rels'))
              if x.attrib.get('TargetMode')!='External'}
        presentation=ET.fromstring(z.read('ppt/presentation.xml'))
        for number,sid in enumerate(presentation.findall('p:sldIdLst/p:sldId',NS),1):
            target=rels[sid.attrib['{'+NS['r']+'}id']]
            part=posixpath.normpath(posixpath.join('ppt',target)) if not target.startswith('/') else target.lstrip('/')
            tree=ET.fromstring(z.read(part));relpart=posixpath.join(posixpath.dirname(part),'_rels',posixpath.basename(part)+'.rels')
            localrels={x.attrib['Id']:x.attrib for x in ET.fromstring(z.read(relpart))} if relpart in z.namelist() else {}
            for node in tree.iter():
                kind=node.tag.split('}')[-1]
                if kind not in ('sp','graphicFrame','pic','cxnSp'):continue
                nv=node.find('.//p:cNvPr',NS)
                if nv is None:continue
                shape=nv.attrib['id'];hidden=nv.attrib.get('hidden') in ('1','true')
                body=node.find('p:txBody',NS);tbl=node.find('.//a:tbl',NS)
                base=dict(slide_number=number,shape_id=shape,source_part=part,hidden=hidden)
                if tbl is not None:
                    cells=[[xml_text(cell.find('a:txBody',NS)) if cell.find('a:txBody',NS) is not None else ''
                            for cell in tr.findall('a:tc',NS)] for tr in tbl.findall('a:tr',NS)]
                    rows.append(dict(**base,kind='table',text=None,rows=cells))
                elif body is not None and xml_text(body).strip():
                    rows.append(dict(**base,kind='unclassified',text=xml_text(body)))
                elif kind=='pic':
                    blip=node.find('.//a:blip',NS);rid=blip.attrib.get('{'+NS['r']+'}embed') if blip is not None else None
                    relationship=localrels.get(rid,{})
                    if relationship.get('TargetMode')=='External' or not relationship.get('Target'):
                        pending.append(dict(**base,reason='external_or_unresolved_image'));continue
                    asset=posixpath.normpath(posixpath.join(posixpath.dirname(part),relationship['Target']))
                    assets.append(dict(**base,package_asset=asset,sha256=__import__('hashlib').sha256(z.read(asset)).hexdigest()))
                elif kind in ('graphicFrame','cxnSp'):
                    pending.append(dict(**base,reason='chart_or_connector_requires_render_review'))
    return rows,assets,pending
#원문 추출값과 기존 데이터를 비교해 차이를 반영하고 수정 전후를 저장합니다. 숨김 항목·평가용 정답 자료는 사용 대상에서 제외합니다.
def native_documents(registry,old_rows):
    old={(r['source_sha256'],r['location'].get('slide_number'),str(r['raw_payload'].get('shape_id'))):r
         for r in old_rows if r['modality']=='document' and isinstance(r.get('raw_payload'),dict)}
    roles={(r['source_sha256'],r['location'].get('slide_number')):r.get('educational_role')
           for r in old_rows if r['modality']=='document'}
    records=[];changes=[];pending=[];assets=[]
    for source in registry:
        if source.get('media_type')!='pptx':continue
        path=Path(source['resolved_path'])
        if digest_file(path)!=source['sha256']:raise ValueError('ppt_source_changed')
        native,pictures,issues=ppt_native(path)
        for item in native:
            previous=old.get((source['sha256'],item['slide_number'],item['shape_id']))
            role=roles.get((source['sha256'],item['slide_number']))
            iid=source['sha256']+':native:'+str(item['slide_number'])+':'+item['shape_id']
            before=previous.get('observed_text') if previous else None
            if item['kind']=='table':before=previous.get('normalized_rows') if previous else None
            value=item.get('rows') if item['kind']=='table' else item['text']
            changed=before!=value
            record=dict(id=iid,modality='document',kind=item['kind'],source_sha256=source['sha256'],
                source_file=str(path),source_part=item['source_part'],slide_number=item['slide_number'],shape_id=item['shape_id'],
                observed_text=item['text'],table_rows=item.get('rows'),original_record_id=previous.get('id') if previous else None,
                educational_role=role,judgment='native_source_checked',verification='exact_ooxml_content',
                visual_layout_verified=False,hidden=item['hidden'],gold_approved=False,
                eligible_for_chunking=not item['hidden'] and role!='evaluation_reference')
            records.append(record)
            if changed:changes.append(dict(id=iid,before=before,after=value,reason='native_source_fidelity',applied=True))
        assets += [dict(**x,source_file=str(path),source_sha256=source['sha256'],source_id=source['source_id']) for x in pictures]
        pending += [dict(**x,source_file=str(path),source_sha256=source['sha256']) for x in issues]
    return records,changes,assets,pending
#화면·음성·이미지 작업을 번갈아 배치해 한 종류만 먼저 처리되는 것을 막습니다.
def fair_queue(groups):
    queues=[deque(g) for g in groups];tasks=[]
    while any(queues):
        for q in queues:
            if q:tasks.append(q.popleft())
    return tasks
#검사할 자료와 작업 목록을 준비합니다. 특히 추출한 이미지가 해당 PPT에 실제로 들어 있던 이미지인지 확인합니다.
def prepare(output):
    output=output.resolve()
    if (output/'plan.json').exists():return check_plan(output)
    if output.exists() and any(output.iterdir()):raise ValueError('output_not_empty')
    registry=read(PREPROCESS/'source-registry.json')['sources'];evaluation=read(PREPROCESS/'evaluation-inputs.json')
    old=[json.loads(l) for l in (PREPROCESS/'records.jsonl').read_text().splitlines()]
    paths=[PREPROCESS/n for n in ['source-registry.json','evaluation-inputs.json','records.jsonl']]
    inputs={str(p):digest_file(p) for p in paths}
    for s in registry:
        p=Path(s['resolved_path'])
        if digest_file(p)!=s['sha256']:raise ValueError('source_changed')
        inputs[str(p)]=s['sha256']
    documents,changes,assets,native_pending=native_documents(registry,old)
    output.mkdir(parents=True,exist_ok=True)
    jsonl(output/'native-documents.jsonl',documents);jsonl(output/'native-changes.jsonl',changes)
    jsonl(output/'native-pending.jsonl',native_pending)
    per_frame=defaultdict(list)
    for r in old:
        if r['location'].get('frame_id'):per_frame[r['location']['frame_id']].append(r)
    screen=[];audio=[];images=[];local_issues=[]
    for frame in evaluation['frames']:
        rows=per_frame[frame['id']];inputs[frame['path']]=digest_file(frame['path'])
        blocks=[{k:r['raw_payload'][k] for k in ('id','kind','bbox','text','uncertainties')}
                for r in rows if r['modality']=='screen_text' and r['kind']!='annotation']
        legacy_kinds={b['id']:b['kind'] for b in blocks if b['kind']=='diagram'}
        for b in blocks:
            # Legacy diagram blocks contain printed labels; retain every character.
            if b['kind']=='diagram':b['kind']='text'
        visuals=[{k:r['raw_payload'][k] for k in ('id','kind','bbox','description','literal_text','related_block_ids','uncertainties')}
                 for r in rows if r['modality']=='image' and r['kind']=='diagram']
        # Hold exact prior uncertain observations until separately adjudicated; never erase them by model agreement.
        protected=[r for r in rows if r['modality'] in ('screen_text','image') and (r.get('holds') or r.get('findings'))]
        baseline=dict(blocks=blocks,visuals=visuals,readable=True,notes=[]) if blocks or visuals else None
        if baseline:
            with Image.open(frame['path']) as im:validate_extraction(baseline,im.size)
        screen.append(dict(id='screen-'+frame['id'],kind='screen',frame=frame,source_sha256=evaluation['source_sha256'],
                           media=frame['path'],baseline=baseline,protected=protected,legacy_block_kinds=legacy_kinds))
    # Review missing full-frame extractions before already available baselines.
    screen.sort(key=lambda t:(t['baseline'] is not None,t['frame']['time_seconds']))
    speech_rows={r['raw_payload']['id']:r for r in old if r['modality']=='audio'}
    offset=evaluation['audio_offset_seconds'];raw=Path(evaluation['audio_path']);inputs[str(raw)]=digest_file(raw)
    for segment in evaluation['speech']:
        row=speech_rows[segment['id']];issues=[]
        for f in row.get('findings',[]):issues.append(f.get('reason') or f.get('code') or f.get('category','review'))
        start,end=segment['start_seconds'],segment['end_seconds']
        if not 0<=start<end<=evaluation['duration_seconds']:issues.append('invalid_audio_interval')
        audio.append(dict(id='audio-'+segment['id'],kind='audio',segment=segment,source_sha256=evaluation['source_sha256'],
                          audio=str(raw),offset=offset,local_issues=issues,priority=row['judgment']=='held'))
    audio.sort(key=lambda t:(not t['priority'],t['segment']['start_seconds']))
    for row in old:
        if row['kind']!='embedded_image':continue
        path=Path(row['location']['image_path']);inputs[str(path)]=digest_file(path)
        # Require the imported bitmap to match a picture actually embedded in the original PPT.
        matches=[a for a in assets if a['source_sha256']==row['source_sha256'] and a['slide_number']==row['location']['slide_number']
                 and a['shape_id']==str(row['raw_payload']['shape_id']) and a['sha256']==inputs[str(path)]]
        if len(matches)!=1:raise ValueError('ppt_asset_not_bound_to_original')
        with Image.open(path) as im:im.verify()
        images.append(dict(id='asset-'+signature(row['id'])[:20],kind='image',media=str(path),baseline=None,protected=[],
                           source_sha256=row['source_sha256'],source_location=row['location'],original_record_id=row['id']))
    tasks=fair_queue([screen,audio,images])
    if len({t['id'] for t in tasks})!=len(tasks) or any(Path(t['id']).name!=t['id'] for t in tasks):raise ValueError('invalid_task_ids')
    derived={str(output/n):digest_file(output/n) for n in ['native-documents.jsonl','native-changes.jsonl','native-pending.jsonl']}
    plan=dict(version=1,created_at=now(),model=read(ROOT/'outputs/ink-continuation-v2/plan.json')['model'],
              tasks=tasks,inputs=inputs,derived=derived,code_hashes=hashes(),api_budget_per_run=60,
              scope='Existing 115 representative video frames, 599 ASR intervals, 9 PPT images and 5 PPT native packages; not continuous-video completeness.')
    save(output/'plan.json',plan);report(output,plan)
    return plan

#준비 당시와 현재의 코드·원본·중간 파일이 같은지 검사합니다
def check_plan(output):
    p=read(output/'plan.json')
    if not code_hashes_match(p['code_hashes'], hashes()):raise ValueError('code_changed_prepare_new_output')
    for name,h in {**p['inputs'],**p['derived']}.items():
        if digest_file(name)!=h:raise ValueError('input_changed:'+name)
    return p

#기존 추출 결과가 있으면 재사용하고, Gemini 검사 범위를 인쇄된 본문·코드·표·그림으로 제한합니다. 필기는 별도 처리합니다.
class ScopedClient:
    def __init__(self,client,baseline):self.client=client;self.model=client.model;self.baseline=baseline
    def call(self,stage,media,prompt,schema):
        if stage=='layers_extract' and self.baseline is not None:
            with Image.open(media[0]) as im:validate_extraction(self.baseline,im.size)
            return copy.deepcopy(self.baseline)
        return self.client.call('other_data_'+stage,media,prompt+NON_INK,schema)

#이미지 검사 결과를 공통 데이터 형식으로 바꾸고, 불명확한 내용이나 연결 문제가 있으면 보류합니다.
def screen_records(task,result):
    held=set();global_hold=False
    for h in result['holds']+result.get('deferred_regions',[]):
        tid=h.get('target_id') or h.get('region',{}).get('target_id')
        if tid and tid!='NEW':held.add(tid)
        else:global_hold=True
    protected={r['raw_payload']['id'] for r in task.get('protected',[])}
    rows=[]
    for layer,items in [('text',result['final_blocks']),('visual',result['visuals'])]:
        for item in items:
            if item['kind']=='annotation':continue # Never supersede independently reviewed ink.
            reasons=[]
            if global_hold:reasons.append('unresolved_frame_coverage')
            if item['id'] in held:reasons.append('source_review_hold')
            if item['id'] in protected:reasons.append('prior_source_hold_preserved')
            if item['uncertainties']:reasons.append('uncertain_content')
            if layer=='visual':reasons+=visual_problems(item,result['final_blocks'])
            text=item.get('text',item.get('literal_text',''))
            if '[ILLEGIBLE]' in text:reasons.append('illegible')
            rows.append(dict(id=task['source_sha256']+':'+task['id']+':'+item['id'],task_id=task['id'],local_id=item['id'],
                modality='screen_text' if layer=='text' else 'image',kind=item['kind'],raw_payload=item,
                observed_text=text,interpretation=item.get('description'),source_image=task['media'],
                source_sha256=task['source_sha256'],location=task.get('frame',task.get('source_location')),
                judgment='held' if reasons else 'model_source_checked',eligible_for_chunking=not reasons,
                reasons=reasons,gold_approved=False,verification='source_audit_and_targeted_repair',
                dependent_local_ids=item.get('related_block_ids',[])))
    eligible={r['local_id'] for r in rows if r['eligible_for_chunking']}
    for row in rows:
        if any(i not in eligible for i in row['dependent_local_ids']):
            row.update(eligible_for_chunking=False,judgment='held');row['reasons'].append('unusable_related_text')
    return rows

#작업 종류에 맞는 검사 코드를 호출합니다. PPT 이미지라면 이미지 추출·원본 대조 흐름으로 보냅니다.
def execute(task,output,plan,client):
    work=output/'work'/task['id'];work.mkdir(parents=True,exist_ok=True)
    if task['kind']=='audio':
        interval=task['segment'];clip=work/'source.wav'
        actual=cut_audio(Path(task['audio']),interval['start_seconds'],interval['end_seconds'],task['offset'],clip)
        if any(abs(a-b)>.001 for a,b in zip(actual,[interval['start_seconds'],interval['end_seconds']])):
            return dict(task_id=task['id'],kind='audio',status='held',records=[],reasons=['source_interval_clipped'])
        updated=review_segment(interval,Path(task['audio']),work,{'audio_offset_seconds':task['offset']},client)
        verified=updated.get('status')=='audio_auto_checked'
        timing=[r for r in task['local_issues'] if any(k in r for k in ('overlap','boundary','interval'))]
        accepted=verified and not timing
        row=dict(id=task['source_sha256']+':'+task['id'],task_id=task['id'],modality='audio',kind='speech',
            source_sha256=task['source_sha256'],observed_text=updated['text'],original_text=interval['text'],
            source_audio=task['audio'],start_seconds=interval['start_seconds'],end_seconds=interval['end_seconds'],
            original_words=interval.get('words',[]),words=updated.get('words',[]),
            word_alignment_required=updated['text']!=interval['text'],eligible_for_chunking=accepted,
            judgment='model_source_checked' if accepted else 'held',gold_approved=False,
            reasons=timing+([] if verified else ['audio_source_review_unresolved']),verification='original_audio_reread_and_compare')
        return dict(task_id=task['id'],kind='audio',status='checked' if accepted else 'held',records=[row],
                    changes=int(accepted and updated['text']!=interval['text']))
    frame=dict(id=task['id'],path=task['media'],time_seconds=task.get('frame',{}).get('time_seconds',0))
    result=process_frame_layers(frame,[frame],[],work,ScopedClient(client,task['baseline']),40,40)
    with Image.open(task['media']) as im:
        validate_extraction(dict(blocks=result['final_blocks'],visuals=result['visuals'],readable=True,notes=[]),im.size)
    rows=screen_records(task,result)
    return dict(task_id=task['id'],kind=task['kind'],status='held' if result['holds'] or any(not r['eligible_for_chunking'] for r in rows) else 'checked',
                records=rows,changes=result['changed_blocks'],holds=result['holds'],details=str(work/'vision'/task['id']/'result.json'))

#결과 및 사용 데이터 저장
def report(output,plan):
    results=[];records=[]
    for t in plan['tasks']:
        p=output/'results'/(t['id']+'.json')
        if not p.exists():continue
        r=read(p)
        if r.get('plan_signature')!=signature(plan):raise ValueError('stale_result')
        results.append(r);records+=r.get('records',[])
    native=[json.loads(l) for l in (output/'native-documents.jsonl').read_text().splitlines()]
    all_rows=native+records;eligible=[r for r in all_rows if r['eligible_for_chunking']]
    pending_native=[json.loads(l) for l in (output/'native-pending.jsonl').read_text().splitlines()]
    summary=dict(native_ppt_records=len(native),native_ppt_usable=sum(r['eligible_for_chunking'] for r in native),
        native_changes=len((output/'native-changes.jsonl').read_text().splitlines()),native_visual_pending=len(pending_native),
        total_tasks=dict(Counter(t['kind'] for t in plan['tasks'])),processed=dict(Counter(r['kind'] for r in results)),
        remaining=len(plan['tasks'])-len(results),held_tasks=sum(r['status']=='held' for r in results),
        applied_changes=sum(r.get('changes',0) for r in results),usable_records=len(eligible),
        all_tasks_attempted=len(results)==len(plan['tasks']),all_content_verified=False,embedding_created=False)
    save(output/'summary.json',summary);jsonl(output/'records.jsonl',all_rows);jsonl(output/'usable-records.jsonl',eligible)
    jsonl(output/'review-required.jsonl',[r for r in all_rows if not r['eligible_for_chunking']])
    jsonl(output/'task-review.jsonl',[r for r in results if r['status']=='held'])
    labels={'native_ppt_records':'PPT 원문에서 확인한 항목','native_ppt_usable':'사용 가능한 PPT 항목',
            'native_changes':'PPT 추출 차이 반영','native_visual_pending':'PPT 그림 구조 검토 대기',
            'remaining':'남은 API 처리 작업','held_tasks':'보류가 남은 작업','applied_changes':'API 재검사 후 변경',
            'usable_records':'사용할 데이터'}
    page='<!doctype html><meta charset="utf-8"><title>다른 자료 처리</title><style>body{font-family:system-ui;max-width:1000px;margin:32px auto}td,th{padding:8px;text-align:left}pre{white-space:pre-wrap}</style><h1>본문·그림·음성·PPT 처리</h1><p>PPT는 원본 내부 텍스트·표를 대조했습니다. 실제 슬라이드 배치 검증과 지식의 사실성 검증은 별개입니다. 음성·화면·이미지는 사용자 터미널의 API 실행 후 갱신됩니다. 필기 결과는 별도로 보존합니다.</p><table>'
    page+=''.join('<tr><th>'+v+'</th><td>'+str(summary[k])+'</td></tr>' for k,v in labels.items())+'</table><h2>분야별 작업</h2><pre>'+html.escape(json.dumps({'전체':summary['total_tasks'],'처리':summary['processed']},ensure_ascii=False,indent=2))+'</pre>'
    page+='<p>evaluation_reference로 지정된 정답 자료는 자동 선별에서 제외했습니다. 보류·연결 문제·기존 미확정 판독은 모델의 동의만으로 해제하지 않습니다.</p>'
    for name in ['usable-records.jsonl','native-changes.jsonl','native-pending.jsonl','review-required.jsonl','task-review.jsonl']:
        page+='<p><a href="'+(output/name).as_uri()+'">'+name+'</a></p>'
    (output/'다른자료_처리현황.html').write_text(page,encoding='utf-8');return summary

#API 한도 안에서 미처리 작업을 실행하고 중간 저장합니다. 재실행하면 완료한 작업은 건너뜁니다.
def run(output,env,max_calls=60,delay=15):
    if max_calls<1 or delay<15:raise ValueError('invalid_limits')
    # Same lock as the ink runner: prevents the two API launchers running together.
    with (ROOT/'outputs/ink-continuation-v2/.run.lock').open('a') as global_lock,(output/'.run.lock').open('a') as lock:
        fcntl.flock(global_lock,fcntl.LOCK_EX|fcntl.LOCK_NB);fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        plan=check_plan(output);client=None;done=[];current=None;reason='running';started=now()
        def checkpoint():
            summary=report(output,plan)
            state=dict(started_at=started,at=now(),stop_reason=reason,completed_this_run=done,current_task=current,
                       api_stats=client.stats if client else {'requests':0},summary=summary)
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

#터미널 명령을 읽어 준비·실행·보고서 생성 중 필요한 기능을 시작합니다.
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('mode',choices=['prepare','run','report'])
    p.add_argument('--output',type=Path,default=OUTPUT);p.add_argument('--env-file',type=Path,default=ROOT/'.env')
    p.add_argument('--max-api-calls',type=int,default=60);p.add_argument('--delay',type=float,default=15)
    a=p.parse_args();out=a.output.resolve()
    if a.mode=='prepare':plan=prepare(out);print(json.dumps(report(out,plan),ensure_ascii=False))
    elif a.mode=='report':print(json.dumps(report(out,check_plan(out)),ensure_ascii=False))
    else:
        s=run(out,a.env_file,a.max_api_calls,a.delay);print(json.dumps({'stop_reason':s['stop_reason'],'summary':s['summary']},ensure_ascii=False))


if __name__=='__main__':main()
