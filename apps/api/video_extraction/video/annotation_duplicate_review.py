"""Apply authored source-image reviews of blocked annotations without any API."""
from video_extraction._layout import PROJECT_ROOT
import copy
import html
from pathlib import Path
import shutil

from video_extraction.shared.common import bbox_pixels, digest_file, now, read, save, signature, validate
from video_extraction.video.source_coordinate_review import matching_decision
from video_extraction.video.vision_layers import VISUAL

ROOT=PROJECT_ROOT
PARENT=ROOT/'outputs/cutoff-source-review'
OUTPUT=ROOT/'outputs/annotation-duplicate-review'


def apply_decisions(original,rows,image_hash):
    result=copy.deepcopy(original)
    if result.get('annotation_duplicate_review'):raise ValueError('already_reviewed_annotations')
    holds=list(result.get('holds',[]));visuals=result.setdefault('visuals',[])
    ids={b['id'] for b in result['final_blocks']+visuals};archived=[];decisions=[]
    for row in rows:
        if row['frame_id']!=result['frame_id'] or row['image_sha256']!=image_hash:
            raise ValueError('annotation_source_changed')
        matches=[i for i,h in enumerate(holds) if h==row['hold']]
        if len(matches)!=1 or row['hold']['reason']!='duplicate_addition':
            raise ValueError('annotation_hold_changed')
        if row['decision'] not in ('missing_annotation','partial_coverage_unresolved_literal'):
            raise ValueError('invalid_annotation_decision')
        visual=copy.deepcopy(row['visual']);validate(visual,VISUAL);bbox_pixels(visual['bbox'],(1000,1000),0)
        if visual['id'] in ids or any(i not in {b['id'] for b in result['final_blocks']} for i in visual['related_block_ids']):
            raise ValueError('invalid_annotation_id_or_reference')
        if (row['decision']=='partial_coverage_unresolved_literal')!=bool(visual['uncertainties']):
            raise ValueError('annotation_uncertainty_lost')
        ids.add(visual['id']);visuals.append(visual);archived.append(holds.pop(matches[0]))
        if visual['uncertainties']:
            holds.append({'layer':'visual','target_id':visual['id'],'reason':'manual_handwriting_unresolved',
                          'details':visual['uncertainties'],'evidence':f'evidence/{row["index"]:02}-source.png'})
        patch=row.get('text_patch')
        if patch:
            blocks=[b for b in result['final_blocks'] if b['id']==patch['target_id']]
            if len(blocks)!=1 or blocks[0]['text']!=patch['before']:raise ValueError('annotation_text_anchor_changed')
            block=blocks[0]
            certificate=matching_decision(block,image_hash,result.get('source_coordinate_review',{}).get('decisions',[]))
            block['text']=patch['after']
            if certificate:
                # Source and bbox are unchanged; only an unsupported literal claim
                # in a broad summary is removed after this direct source review.
                certificate['previous_block_signature']=certificate['reviewed_block_signature']
                certificate['reviewed_block_signature']=signature(block)
                certificate['anchor_update_reason']='manual_annotation_summary_text_correction_bbox_unchanged'
        decisions.append({'index':row['index'],'hold_signature':signature(row['hold']),
                          'decision':row['decision'],'visual_id':visual['id'],'reason':row['reason'],
                          'image_sha256':image_hash,'visual_signature':signature(visual),
                          'text_patch':copy.deepcopy(patch)})
    result['holds']=holds
    result['text']='\n\n'.join(b['text'] for b in result['final_blocks'])
    result['annotation_duplicate_review']={'version':1,'method':'direct_source_image_review',
        'parent_signature':signature(original),'decisions':decisions,'archived_holds':archived,
        'scope':'Only the listed blocked annotations; other holds remain unresolved.'}
    result['signature']=signature({'parent':signature(original),'annotation_review':decisions})
    return result


def build(out=OUTPUT):
    from video_extraction.shared.multimodal_validation import OUTPUT as API_OUTPUT, freeze_check
    from video_extraction.shared.multimodal_checks import inspect_frame
    from video_extraction.video.local_recheck import check_output
    plan=freeze_check(API_OUTPUT,check_code=False);parent=read(PARENT/'manifest.json')
    check_output(out,[PARENT,API_OUTPUT,ROOT/'sources',Path(plan['settings']['job']),
                      *(Path(p) for p in plan['settings']['overrides'])])
    if parent['source_plan_signature']!=signature(plan):raise ValueError('annotation_plan_changed')
    protected={p:digest_file(p) for root in (PARENT,API_OUTPUT) for p in root.rglob('*')
               if p.is_file() and p.name!='.validation.lock'}
    rows=read(out/'decisions.json')
    pending=read(ROOT/'outputs/pending-reconciliation/review.json')
    expected={(g['frame_id'],signature(g['records'][0]['original_hold'])) for g in pending['groups']
              if g['category']=='duplicate_addition_needs_review'}
    actual=[(r['frame_id'],signature(r['hold'])) for r in rows]
    if len(set(actual))!=len(actual) or set(actual)!=expected:raise ValueError('annotation_review_coverage_changed')
    # Carry forward all coordinate-reviewed frames, not only the seven edited here.
    manifest=copy.deepcopy(parent);manifest.update(created_at=now(),parent_manifest_sha256=digest_file(PARENT/'manifest.json'),
        annotation_decisions_sha256=digest_file(out/'decisions.json'),api_requests=0,raw_residuals=[],
        annotation_counts={'cases_reviewed':len(rows),'missing_added':sum(r['decision']=='missing_annotation' for r in rows),
                           'partial_with_unresolved_literal':sum(r['decision']=='partial_coverage_unresolved_literal' for r in rows),
                           'confirmed_duplicates':0,'visuals_added':len(rows)})
    manifest['coordinate_decisions_sha256']=manifest['decisions_sha256']
    manifest['decisions_sha256']=digest_file(out/'decisions.json')
    for fid,entry in manifest['results'].items():
        path=PARENT/'vision'/fid/'result.json';image=PARENT/'frames'/f'{fid}.png'
        if digest_file(path)!=entry['result_sha256'] or digest_file(image)!=entry['image_sha256']:
            raise ValueError('annotation_parent_changed')
        if digest_file(entry['baseline'])!=entry['baseline_sha256']:raise ValueError('annotation_baseline_changed')
        selected=[r for r in rows if r['frame_id']==fid]
        for row in selected:
            if Path(row['baseline'])!=path or row['baseline_sha256']!=digest_file(path):
                raise ValueError('annotation_decision_baseline_changed')
        result=apply_decisions(read(path),selected,entry['image_sha256']) if selected else read(path)
        # Preserve coordinate review evidence references in the copied frame results.
        for record in result.get('source_coordinate_review',{}).get('decisions',[]):
            evidence=Path(record['evidence'])
            if not evidence.is_absolute():record['evidence']=str(PARENT/evidence)
        dest=out/'vision'/fid/'result.json';save(dest,result)
        (out/'frames').mkdir(exist_ok=True);shutil.copyfile(image,out/'frames'/f'{fid}.png')
        findings,metrics=inspect_frame(image,result,[plan['metadata']['width'],plan['metadata']['height']])
        entry.update(result_sha256=digest_file(dest),remaining_findings=findings,
                     coordinate_parent_sha256=digest_file(path))
        manifest['raw_residuals'].extend({'frame_id':fid,**x} for x in metrics.get('reviewed_cutoff_findings',[]))
    if any(digest_file(p)!=h for p,h in protected.items()):raise ValueError('annotation_protected_input_changed')
    freeze_check(API_OUTPUT,check_code=False)
    save(out/'manifest.json',manifest)
    cards=[]
    for row in rows:
        v=row['visual']
        cards.append(f'<article><h2>{row["index"]+1}. {html.escape(row["frame_id"])}</h2>'
            f'<p>{html.escape(row["reason"])}</p><p>{html.escape(v["description"])}</p>'
            f'<p>필기 전사: {html.escape(v["literal_text"]) or "문자 없는 표시"} · '
            f'불확실성: {html.escape("; ".join(v["uncertainties"])) or "없음"}</p>'
            f'<img src="evidence/{row["index"]:02}-after.png"><p>연결된 본문: {html.escape(", ".join(v["related_block_ids"]))}</p></article>')
    (out/'필기_중복차단_검토.html').write_text('<!doctype html><html lang="ko"><meta charset="utf-8">'
        '<title>필기 중복 차단 검토</title><style>body{max-width:1100px;margin:30px auto;font:16px/1.7 system-ui;padding:20px}article{border-top:1px solid #ddd;padding:15px}img{max-width:100%}</style>'
        '<h1>25건 원본 대조 · API 0회</h1><p>필기 누락 24건을 추가했고, 포괄적 요약에만 있던 1건은 별도 영역으로 분리해 정확한 문자 판독을 보류했습니다. 완전한 중복으로 확인된 건은 없습니다.</p>'
        '<p>인쇄 문자는 본문에 유지하고, 빨간 표시와 필기만 visuals에 기록했습니다. 기존 차단 기록은 삭제하지 않고 이력에 보존했습니다.</p>'
        +''.join(cards),encoding='utf-8')
    print(manifest['annotation_counts'])
    return manifest


if __name__=='__main__':build()
