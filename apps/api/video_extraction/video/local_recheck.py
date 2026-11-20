"""Recheck frozen existing data with current local detectors; never calls an API."""
from video_extraction._layout import source_path
import argparse
from video_extraction.shared import file_lock as fcntl
import html
import json
from pathlib import Path

from PIL import Image,ImageDraw

from video_extraction.shared.common import read, save, signature, digest_file, now, bbox_pixels
from video_extraction.shared.multimodal_checks import inspect_frame, inspect_timeline, audio_windows, inspect_audio, finding, grouped_findings, CATEGORY_LABELS
from video_extraction.shared.multimodal_validation import ROOT, OUTPUT, freeze_check, safe_path
from video_extraction.video.source_coordinate_review import load_reviewed


def key(row):
    return row.get('frame_id'),row.get('target_id')


def check_output(out,protected_roots):
    out=out.resolve()
    for root in protected_roots:
        root=root.resolve()
        if out==root or out in root.parents or root in out.parents:
            raise ValueError('recheck_output_must_be_separate')


def recheck(source,out,reviewed_root=None):
    source=source.resolve();out=out.resolve()
    check_output(out,[source,ROOT/'sources'])
    plan=freeze_check(source,check_code=False)
    original=read(source/'local-checks.json');job=Path(plan['settings']['job'])
    roots=[Path(p) for p in plan['settings']['overrides']]+[job]
    check_output(out,roots)
    if reviewed_root is not None:
        reviewed_root=reviewed_root.resolve();check_output(out,[reviewed_root])
        coordinate_review=read(reviewed_root/'manifest.json')
        if coordinate_review['source_plan_signature']!=signature(plan):raise ValueError('coordinate_review_plan_changed')
    else:coordinate_review=None
    # Bind receipt files too; read them only to recheck their candidate structures.
    protected={p:digest_file(p) for p in source.rglob('*') if p.is_file() and p.name!='.validation.lock'}
    findings=[];metrics=[];results={};images={}
    meta=plan['metadata'];frames=read(job/'frames.json');state=read(job/'state.json')
    for f in frames:
        result=None
        image=safe_path(job,f['path'])
        for root in roots:
            candidate=root/'vision'/f['id']/'result.json'
            if str(candidate) in plan['input_hashes']:
                result=load_reviewed(reviewed_root,candidate,image) if reviewed_root else read(candidate)
                break
        images[f['id']]=image;results[f['id']]=result
        fs,ms=inspect_frame(image,result,[meta['width'],meta['height']])
        findings.extend({'frame_id':f['id'],**x} for x in fs);metrics.append({'frame_id':f['id'],**ms})
    findings.extend(inspect_timeline(frames,meta['duration_seconds'],state['config']['max_frame_gap']))
    # Source/video evidence hashes were verified above. Decoding algorithms did not
    # change, so retain those results rather than spending another full decode pass.
    scan_reasons={'decoded_timestamp_gap_or_order','selected_timestamp_not_decoded','saved_frame_source_mismatch',
                  'possibly_unrepresented_scene_change','no_decoded_frames','decoded_end_short','frames_without_pts'}
    for row in original['findings']:
        if row['reason'] in scan_reasons:
            findings.append(finding(row['modality'],row['reason'],**{k:v for k,v in row.items() if k not in ('modality','reason','status','category')}))
    if meta['audio_present']:
        speech=read(job/'asr.json')['segments'];windows,duration=audio_windows(job/'audio-original.wav')
        af,by=inspect_audio(speech,windows,meta['audio_offset_seconds'],meta['duration_seconds'])
        if abs(duration+meta['audio_offset_seconds']-meta['duration_seconds'])>1:
            af.append(finding('audio','audio_video_duration_mismatch',audio_end=duration+meta['audio_offset_seconds']))
        findings.extend(af)
        for rows in by.values():findings.extend(rows)
    groups=grouped_findings(findings)
    old_cut={key(r):r for r in original['findings'] if r['reason']=='possible_bbox_cutoff'}
    new_cut={key(r):r for r in findings if r['reason']=='possible_bbox_cutoff'}
    comparison={'previous_cutoff_warnings':len(old_cut),'current_cutoff_warnings':len(new_cut),
                'retained':sorted(old_cut.keys()&new_cut.keys()),
                'no_longer_flagged':sorted(old_cut.keys()-new_cut.keys()),
                'newly_flagged':sorted(new_cut.keys()-old_cut.keys()),
                'note':'Fewer warnings do not establish a measured false-positive rate or recall.'}
    candidate_checks=[]
    for task in plan['tasks']:
        receipt=source/'receipts'/f'{task["id"]}.json'
        if not receipt.exists() or task['kind']=='audio':continue
        r=read(receipt)
        if r['signature']!=signature({'plan':signature(plan),'task':task['id']}):raise ValueError('receipt_signature_mismatch')
        c=r['candidate'];fs,_=inspect_frame(safe_path(source,task['media'][-1]),
            {'final_blocks':c['blocks'],'visuals':c['visuals']},[meta['width'],meta['height']])
        candidate_checks.append({'task_id':task['id'],'finding_counts':{k:len(v) for k,v in grouped_findings(fs).items()},'findings':fs,
                                 'approved':False,'applied':False})
    out.mkdir(parents=True,exist_ok=True)
    # Fixed spread of retained/cleared/new alerts for source-image spot checking.
    samples=[]
    for label,keys in [('retained',comparison['retained']),('cleared',comparison['no_longer_flagged']),('new',comparison['newly_flagged'])]:
        chosen=keys if len(keys)<=4 else [keys[round(i*(len(keys)-1)/3)] for i in range(4)]
        for fid,target in chosen:
            result=results[fid];b=next(b for b in result['final_blocks'] if b['id']==target)
            with Image.open(images[fid]) as im:
                x0,y0,x1,y1=bbox_pixels(b['bbox'],im.size,pad=0)
                box=(max(0,x0-16),max(0,y0-16),min(im.width,x1+16),min(im.height,y1+16))
                crop=im.convert('RGB').crop(box);draw=ImageDraw.Draw(crop)
                draw.rectangle((x0-box[0],y0-box[1],x1-box[0]-1,y1-box[1]-1),outline='#00b7d6',width=1)
                # Filenames avoid using arbitrary model IDs as paths.
                rel=f'evidence/sample-{len(samples):02}.png';(out/'evidence').mkdir(exist_ok=True);crop.save(out/rel)
            samples.append({'group':label,'frame_id':fid,'target_id':target,'image':rel,
                            'evidence':new_cut.get((fid,target),{}).get('evidence')})
    pending=[{**r,'category':'pending','status':'pending'} for r in original['deferred']]
    report={'check_version':2,'created_at':now(),'source':str(source),'source_plan_signature':signature(plan),
            'implementation_sha256':{n:digest_file(source_path(n)) for n in ['local_recheck.py','bbox_cutoff.py','multimodal_checks.py','source_coordinate_review.py']},
            'api_requests':0,'coverage':original['coverage'],'finding_counts':{k:len(v) for k,v in groups.items()},
            'previous_flat_findings':len(original['findings']),'current_findings':len(findings),'findings':findings,
            'groups':groups,'cutoff_comparison':comparison,'samples':samples,
            'unselected_api_units':pending,'unselected_api_count':len(pending),
            'candidate_checks':candidate_checks,'video_metrics':original['video_metrics'],
            'frame_metrics':metrics,'coordinate_review':None if coordinate_review is None else
                {'root':str(reviewed_root),'counts':coordinate_review['counts'],
                 'manifest_sha256':digest_file(reviewed_root/'manifest.json')},
            'annotation_review':None if coordinate_review is None else coordinate_review.get('annotation_counts'),
            'video_scan_reused_after_hash_validation':True,'accuracy':None,
            'note':'Pending findings and unselected API units overlap; do not add them. Existing model candidates do not resolve source holds.'}
    save(out/'review.json',report)
    e=html.escape
    sections=''.join(f'<details><summary>{CATEGORY_LABELS[k]}: {len(rows)}</summary><pre>{e(json.dumps(rows,ensure_ascii=False,indent=2))}</pre></details>' for k,rows in groups.items())
    cards=''.join(f'<figure><figcaption>{s["group"]} · {e(s["frame_id"])} · {e(s["target_id"])}</figcaption><img src="{s["image"]}"></figure>' for s in samples)
    (out/'계산검사_재확인.html').write_text(f'''<!doctype html><html lang="ko"><meta charset="utf-8"><title>계산 검사 재확인</title>
<style>body{{max-width:1100px;margin:30px auto;font:16px/1.7 system-ui;padding:20px}}pre{{white-space:pre-wrap;overflow-wrap:anywhere}}details,figure{{border:1px solid #ccd;padding:16px}}img{{max-width:100%;image-rendering:auto}}summary{{cursor:pointer}}</style>
<h1>계산 검사 재확인 · API 0회</h1><p>기존 결과와 모델 판독은 보존했습니다. 구조·시간 오류 / 경고 / 미처리·미확정을 별도로 집계합니다. 확인된 구조 오류가 0이어도 내용 전체가 정확하다는 뜻은 아닙니다.</p>
<p>{'원본 직접 대조 판정을 반영했습니다: '+e(str(coordinate_review['counts'])) if coordinate_review else '원본 직접 대조 판정은 적용하지 않은 계산 검사입니다.'}</p>
<p>{'필기 중복 차단 검토: '+e(str(coordinate_review['annotation_counts'])) if coordinate_review and coordinate_review.get('annotation_counts') else ''}</p>
<p>잘림 경고 {len(old_cut)} → {len(new_cut)}. 경고 감소는 오탐률이나 정확도 개선의 측정값이 아닙니다. 문자 연결 획이 경계 안팎에 이어지는지 검사하며 색 필기·긴 직선은 증거에서 제외합니다. 반전 글자·심하게 붙은 획 등은 놓칠 수 있습니다.</p>
{sections}<p>API 미선택 {len(pending)}개는 별도의 처리 범위 집계입니다. 위의 미처리·미확정 지적 수와 중복되므로 더하지 않습니다. 영상 디코딩 검사는 입력 해시 일치 확인 후 기존 기록을 재사용했습니다.</p>
<h2>원본 대조 표본 · 청록색 선은 추출 영역 경계</h2>{cards}<p><a href="review.json">전체 검사·후보 재검사 기록</a></p></html>''',encoding='utf-8')
    if any(digest_file(p)!=h for p,h in protected.items()):raise ValueError('original_validation_changed')
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--source',type=Path,default=OUTPUT)
    parser.add_argument('--output',type=Path,default=ROOT/'outputs/multimodal-checks-v2')
    parser.add_argument('--reviewed-results',type=Path);args=parser.parse_args()
    with (args.source/'.validation.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        report=recheck(args.source,args.output,args.reviewed_results)
    comparison=report['cutoff_comparison']
    print({'finding_counts':report['finding_counts'],'current_findings':report['current_findings'],
           'cutoff_warnings':{'before':comparison['previous_cutoff_warnings'],'after':comparison['current_cutoff_warnings']},
           'api_requests':0})
    return 0


if __name__=='__main__':raise SystemExit(main())
