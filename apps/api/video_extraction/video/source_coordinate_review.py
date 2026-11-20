"""Offline, source-bound coordinate decisions. Never infer or call a model."""
from video_extraction._layout import PROJECT_ROOT
import argparse
import copy
import html
from pathlib import Path
import shutil

from PIL import Image

from video_extraction.shared.common import bbox_pixels, digest_file, now, read, save, signature


def matching_decision(block,image_sha256,decisions):
    """A changed image, text, kind, or bbox invalidates the recorded adjudication."""
    rows=[r for r in decisions if r.get('target_id')==block['id']]
    if len(rows)!=1:return None
    row=rows[0]
    if (row.get('decision') not in ('corrected','false_positive')
            or row.get('image_sha256')!=image_sha256
            or row.get('reviewed_block_signature')!=signature(block)):
        return None
    return row


def apply_decisions(result,rows,image_sha256,size):
    r=copy.deepcopy(result)
    if len({x['target_id'] for x in rows})!=len(rows):raise ValueError('duplicate_coordinate_decision')
    recorded=[]
    for row in rows:
        if row['frame_id']!=r['frame_id'] or row['image_sha256']!=image_sha256:
            raise ValueError('coordinate_review_image_changed')
        blocks=[b for b in r['final_blocks'] if b['id']==row['target_id']]
        if len(blocks)!=1:raise ValueError('coordinate_review_target_changed')
        block=blocks[0]
        if block['bbox']!=row['before'] or block['text']!=row['text'] or block.get('kind')!=row['kind']:
            raise ValueError('coordinate_review_anchor_changed')
        bbox_pixels(row['after'],size,pad=0)
        if row['decision'] not in ('corrected','false_positive'):raise ValueError('invalid_coordinate_decision')
        if (row['decision']=='false_positive')!=(row['before']==row['after']):
            raise ValueError('coordinate_decision_does_not_match_change')
        block['bbox']=list(row['after'])
        recorded.append({k:copy.deepcopy(row[k]) for k in
                         ('index','frame_id','target_id','image_sha256','before','after','decision','reason')})
        recorded[-1].update(reviewed_block_signature=signature(block),
                           method='direct_source_image_review',scope='bbox_only',
                           post_review_note=row.get('post_review_note','원본과 보정 후 영역을 대조하여 해당 대상의 포함을 확인했다.'),
                           evidence=f'evidence/{row["index"]:02}-after.png')
    r['source_coordinate_review']={'version':1,'decisions':recorded,
                                  'parent_result_signature':signature(result),
                                  'content_and_holds_unchanged':True}
    r['signature']=signature({'parent':signature(result),'coordinate_decisions':recorded})
    return r


def load_reviewed(root,baseline_path,image):
    """Only overlay the exact baseline inspected during the manual review."""
    manifest=read(root/'manifest.json')
    fid=baseline_path.parent.name
    entry=manifest['results'].get(fid)
    if entry is None:return read(baseline_path)
    if str(baseline_path.resolve())!=entry['baseline'] or digest_file(baseline_path)!=entry['baseline_sha256']:
        raise ValueError('coordinate_review_baseline_changed')
    if digest_file(image)!=entry['image_sha256']:raise ValueError('coordinate_review_image_changed')
    path=root/'vision'/fid/'result.json'
    if digest_file(path)!=entry['result_sha256']:raise ValueError('coordinate_review_result_changed')
    return read(path)


def build(out):
    # Decisions are authored only after viewing originals and corrected crops.
    from video_extraction.shared.multimodal_validation import OUTPUT, freeze_check
    from video_extraction.shared.multimodal_checks import inspect_frame
    from video_extraction.video.local_recheck import check_output
    plan=freeze_check(OUTPUT,check_code=False)
    rows=read(out/'decisions.json')
    prior=read(PROJECT_ROOT/'outputs/multimodal-checks-v2/review.json')
    expected={(x['frame_id'],x['target_id']) for x in prior['findings'] if x['reason']=='possible_bbox_cutoff'}
    actual=[(r['frame_id'],r['target_id']) for r in rows]
    if len(actual)!=len(set(actual)) or set(actual)!=expected:raise ValueError('coordinate_review_coverage_changed')
    check_output(out,[OUTPUT,Path(plan['settings']['job']),*(Path(p) for p in plan['settings']['overrides']),
                      PROJECT_ROOT/'sources'])
    protected={p:digest_file(p) for p in OUTPUT.rglob('*') if p.is_file() and p.name!='.validation.lock'}
    manifest={'version':1,'created_at':now(),'api_requests':0,'source_plan_signature':signature(plan),
              'decisions_sha256':digest_file(out/'decisions.json'),'results':{},'raw_residuals':[],
              'counts':{k:sum(r['decision']==k for r in rows) for k in ('corrected','false_positive')}}
    for fid in sorted({r['frame_id'] for r in rows}):
        selected=[r for r in rows if r['frame_id']==fid];anchor=selected[0]
        source=Path(anchor['result']);image=Path(anchor['image'])
        if plan['input_hashes'].get(str(source))!=anchor['result_sha256'] or digest_file(source)!=anchor['result_sha256']:
            raise ValueError('coordinate_review_result_source_changed')
        if any(r['result']!=str(source) or r['result_sha256']!=anchor['result_sha256'] for r in selected):
            raise ValueError('inconsistent_coordinate_baseline')
        if plan['input_hashes'].get(str(image))!=anchor['image_sha256'] or digest_file(image)!=anchor['image_sha256']:
            raise ValueError('coordinate_review_image_changed')
        with Image.open(image) as im:size=im.size
        result=apply_decisions(read(source),selected,anchor['image_sha256'],size)
        dest=out/'vision'/fid/'result.json';save(dest,result)
        (out/'frames').mkdir(exist_ok=True);shutil.copyfile(image,out/'frames'/f'{fid}.png')
        fs,metrics=inspect_frame(image,result,size)
        manifest['raw_residuals'].extend({'frame_id':fid,**x} for x in metrics.get('reviewed_cutoff_findings',[]))
        manifest['results'][fid]={'baseline':str(source),'baseline_sha256':anchor['result_sha256'],
                                 'image_sha256':anchor['image_sha256'],'result_sha256':digest_file(dest),
                                 'remaining_findings':fs}
    # Check the immutable API evidence as well as all frozen inputs after writing.
    freeze_check(OUTPUT,check_code=False)
    if any(digest_file(p)!=h for p,h in protected.items()):raise ValueError('original_validation_changed')
    save(out/'manifest.json',manifest)
    cards=[]
    for r in rows:
        label='좌표 수정' if r['decision']=='corrected' else '오탐 정리'
        cards.append(f'<article><h2>{r["index"]+1}. {html.escape(r["frame_id"])} · {html.escape(r["target_id"])} — {label}</h2>'
                     f'<p>{html.escape(r["reason"])}</p><p>{r["before"]} → {r["after"]}</p>'
                     f'<div><figure><figcaption>기존 영역 · 청록색</figcaption><img src="evidence/{r["index"]:02}-before.png"></figure>'
                     f'<figure><figcaption>검토 후 영역 · 초록색</figcaption><img src="evidence/{r["index"]:02}-after.png"></figure></div></article>')
    (out/'잘림_원본대조.html').write_text('<!doctype html><html lang="ko"><meta charset="utf-8"><title>잘림 원본 대조</title>'
        '<style>body{font:16px/1.6 system-ui;max-width:1200px;margin:30px auto;padding:20px}article{border-top:1px solid #ddd;padding:16px 0}div{display:flex;flex-wrap:wrap}figure{margin:10px;max-width:100%}img{max-width:100%}</style>'
        f'<h1>62건 원본 대조 · API 0회</h1><p>좌표 수정 {manifest["counts"]["corrected"]}건 · 오탐 {manifest["counts"]["false_positive"]}건. '
        '텍스트 전사·기존 보류·API 응답은 유지했습니다. 수정된 결과는 vision 폴더에 저장했습니다.</p>'
        '<p>원본·대상 블록이 바뀌면 판정을 재사용하지 않습니다. 계산 신호가 남는 경우도 원본 대조 근거와 함께 보존합니다.</p>'
        +''.join(cards),encoding='utf-8')
    return manifest


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=PROJECT_ROOT/'outputs/cutoff-source-review')
    args=parser.parse_args();report=build(args.output.resolve())
    print({'api_requests':0,'counts':report['counts'],'frames':len(report['results']),
           'raw_signals_adjudicated':len(report['raw_residuals'])})


if __name__=='__main__':main()
