"""Offline, version-aware selection for chunking, never embedding or gold approval."""
from video_extraction._layout import code_hashes_match
import argparse
import copy
from video_extraction.shared import file_lock as fcntl
import html
import json
import math
from collections import Counter
from pathlib import Path

from video_extraction.shared.common import read, save, jsonl, digest_file, signature, now
from video_extraction.ink.runner.ink_continue_v2 import check_plan, ROOT
from video_extraction.ink.correction.ink_discrepancy import ACCEPTED
from video_extraction.ink.policy.ink_conservative_review import SOURCE, OUTPUT as REVIEW_OUTPUT

OUTPUT=ROOT/'outputs/usable-selection-v1'
ALLOWED_WARNINGS={'simple_emphasis_group_accepted','imprecise_simple_emphasis_extent',
                  'ocr_false_positive_source_reviewed','ocr_low_confidence','ocr_not_comparable'}
OCR_COVERAGE={'ocr_outside_scanned_area','ocr_partial_word_coverage','ocr_no_detection'}
METHODS={'source_and_context_model_audit','assistant_direct_source_review','conservative_emphasis_policy'}


def select_result(result, result_path, admin_ids=()):
    """Decisions, records and original-source audits must agree; aliases are not truth."""
    rows=result.get('records',[]);selected=[];excluded=[]
    ds={d['id']:d for d in result.get('decisions',[])}
    nodes={x['id']:x for group in ('items','links') for x in result.get('effective_inventory',{}).get(group,[])}
    checks={c['id']:c for c in result.get('final_audit',{}).get('checks',[])}
    check_counts=Counter(c['id'] for c in result.get('final_audit',{}).get('checks',[]))
    counts=Counter(r['local_id'] for r in rows)
    for row in rows:
        iid=row['local_id'];d=ds.get(iid,{});raw=row.get('raw_payload',{}).get('raw',{})
        findings=row.get('policy_findings',{});reasons=[];c=checks.get(iid,{})
        if counts[iid]!=1:reasons.append('duplicate_local_id')
        if result.get('error'):reasons.append('result_execution_error')
        if d.get('status') not in ACCEPTED or row.get('judgment') not in ACCEPTED:reasons.append('not_source_checked')
        if d.get('reasons') or findings.get('blocking'):reasons.append('blocking_findings')
        if iid in admin_ids or raw.get('cancelled'):reasons.append('administrator_or_cancelled')
        if raw.get('uncertainties'):reasons.append('unresolved_literal')
        if iid not in nodes or nodes[iid]!=raw:reasons.append('effective_payload_mismatch')
        if row.get('verification',{}).get('method') not in METHODS:reasons.append('unrecognized_verification')
        warnings=set(findings.get('warnings',[]))|set(d.get('warnings',[]))
        allowed=set(ALLOWED_WARNINGS)
        if (findings.get('ocr_support_policy')=='selective_auxiliary_v1'
                and c.get('content')==c.get('geometry')==c.get('meaning')=='supported'
                and c.get('lexical_complete') and c.get('meaning_preserved')
                and c.get('role_risk') is False and c.get('uncertainty_scope')=='none'):
            from video_extraction.ink.correction.ink_recheck import normalize
            if raw.get('text','').strip() and normalize(c.get('full_text',''))==normalize(raw['text']):
                allowed.update('auxiliary_'+x for x in OCR_COVERAGE|{'ocr_unavailable','ocr_text_conflict'})
        if c.get('meaning_preserved') is True and c.get('role_risk') is False:
            allowed.add('meaning_preserving_particle_ocr_difference')
        if (row.get('verification',{}).get('method')=='assistant_direct_source_review'
                and 'ocr_false_positive_source_reviewed' in warnings):
            allowed.add('ocr_item_variant_difference')
        if warnings-allowed:reasons.append('warning_not_approved_for_selection')
        if set(findings.get('unprocessed',[])) - OCR_COVERAGE:reasons.append('unprocessed_required_check')
        approximate='imprecise_simple_emphasis_extent' in warnings
        geometry_ok=c.get('geometry')=='supported' or (approximate and c.get('geometry')=='partial')
        if check_counts[iid]!=1 or c.get('content')!='supported' or c.get('meaning')!='supported' or not geometry_ok:
            reasons.append('source_audit_not_supported')
        if row.get('usable_for_semantic_assertion') is False:reasons.append('semantic_assertion_disabled')
        source=row.get('selected_frame')
        if not source or not Path(source).is_file():reasons.append('missing_source_image')
        if 'box' in raw:
            b=row.get('normalized',{}).get('box_source_fraction',[])
            if (len(b)!=4 or not all(type(v) in (float,int) and math.isfinite(v) for v in b)
                    or not 0<=b[0]<b[2]<=1 or not 0<=b[1]<b[3]<=1):
                reasons.append('invalid_source_geometry')
        if raw.get('kind') in ('handwriting','printed_text','code','math') and not raw.get('text','').strip():
            reasons.append('empty_literal')
        if reasons:
            excluded.append(dict(task_id=result['task_id'],id=row['id'],local_id=iid,reasons=sorted(set(reasons)),record=copy.deepcopy(row)))
            continue
        text=raw.get('text','')
        selected.append(dict(id=row['id'],task_id=result['task_id'],local_id=iid,
            eligible_for_chunking=True,embedding_created=False,gold_approved=False,
            route='text' if text else 'linked_metadata',text_for_chunking=text,
            source_result=str(result_path),record=copy.deepcopy(row),
            selection=dict(basis='source_checked_with_explicit_policy',warnings=sorted(warnings),
                independent_ocr_coverage=findings.get('unprocessed',[]),
                region_has_unresolved_content=not result.get('active_coverage_complete',False),
                interpretation_scope=row.get('interpretation_scope','literal_observation'),
                exact_geometry_verified=not approximate)))
    # Dependency closure: one excluded target cannot leak back via a selected link.
    while True:
        by_local={r['local_id']:r for r in selected};by_id={r['id'] for r in selected}
        rejected=[]
        for row in selected:
            raw=row['record']['raw_payload']['raw']
            if 'from_ids' not in raw:continue
            refs=raw.get('from_ids',[])+raw.get('to_ids',[])
            if (not raw.get('from_ids') or not raw.get('to_ids')
                    or any(i not in by_local for i in refs)
                    or any(i not in by_id for i in row['record'].get('reference_ids',[]))):
                rejected.append(row)
        if not rejected:break
        bad={r['id'] for r in rejected}
        selected=[r for r in selected if r['id'] not in bad]
        excluded += [dict(task_id=r['task_id'],id=r['id'],local_id=r['local_id'],
                          reasons=['unselected_relation_target'],record=r['record']) for r in rejected]
    # Non-record held/context/admin observations must also remain inspectable.
    represented={r['local_id'] for r in rows}
    all_nodes={x['id']:x for group in ('items','links') for x in result.get('candidate',{}).get(group,[])}
    for iid,d in ds.items():
        if iid not in represented:
            excluded.append(dict(task_id=result['task_id'],local_id=iid,
                reasons=[d['status']],decision=copy.deepcopy(d),observation=copy.deepcopy(all_nodes.get(iid))))
    return selected,excluded


def result_paths(source,plan,snapshot):
    """Select one authoritative version per task, including 24 earlier completed regions."""
    old=Path(plan['source']);old_plan=read(old/'plan.json')
    earliest=Path(old_plan['completed_source']);reviewed=Path(plan['reviewed_source'])
    paths={}
    for tid in plan['earlier_excluded_ids']:paths[tid]=earliest/'results'/(tid+'.json')
    for tid in plan['excluded_processed_ids']:
        candidate=reviewed/'results'/(tid+'.json')
        paths[tid]=candidate if candidate.exists() else old/'results'/(tid+'.json')
    for task in plan['tasks']:
        raw=source/'results'/(task['id']+'.json')
        if not raw.exists():continue
        reviewed_path=snapshot/'results'/raw.name
        if not reviewed_path.exists():raise ValueError('review_missing_for_completed_task')
        r=read(reviewed_path)
        if r.get('candidate') and r.get('overlay_source_signature')!=signature(read(raw)):
            raise ValueError('review_stale_for_completed_task')
        paths[task['id']]=reviewed_path
    if any(not p.is_file() for p in paths.values()):raise ValueError('historical_result_missing')
    return paths


def build(source=SOURCE,review=REVIEW_OUTPUT,output=OUTPUT):
    source=source.resolve();review=review.resolve();output=output.resolve()
    if output in (source,review) or source in output.parents or review in output.parents:
        raise ValueError('separate_output_required')
    output.mkdir(parents=True,exist_ok=True)
    with (source/'.run.lock').open('a') as lock,(output/'.build.lock').open('a') as outlock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);fcntl.flock(outlock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        plan=check_plan(source);snapshot=Path(read(review/'latest.json')['snapshot'])
        from video_extraction.ink.runner.ink_continue import check_plan as check_previous
        check_previous(Path(plan['source']))
        manifest=read(snapshot/'manifest.json')
        from video_extraction.ink.policy import ink_conservative_review
        if not code_hashes_match(manifest['code_sha256'], digest_file(ink_conservative_review.__file__)):raise ValueError('review_code_changed_rebuild')
        for path,expected in manifest['inputs'].items():
            if digest_file(path)!=expected:raise ValueError('review_input_changed')
        paths=result_paths(source,plan,snapshot)
        inputs={str(snapshot/'manifest.json'):digest_file(snapshot/'manifest.json'),
                str(source/'plan.json'):digest_file(source/'plan.json')}
        selected=[];excluded=[];pending=[]
        for tid,path in paths.items():
            r=read(path);inputs[str(path)]=digest_file(path)
            admin={a.get('local_id') for a in r.get('administrator_queue',[])}
            admin|={a.get('local_id') for a in plan['inherited_administrator_queue'] if a['task_id']==tid}
            good,bad=select_result(r,path,admin);selected+=good;excluded+=bad
            pending += [dict(task_id=tid,status='missing_core',**m) for m in r.get('missing_core',[])]
            for row in r.get('records',[]):
                image=row.get('selected_frame')
                if image and Path(image).is_file():inputs[image]=digest_file(image)
        ids=Counter(r['id'] for r in selected)
        if any(c!=1 for c in ids.values()):raise ValueError('duplicate_selected_record_id')
        # Imported normalization is not semantic verification. Do not mix it into the index.
        imported=ROOT/'outputs/preprocessing-v1/records.jsonl'
        other_rows=[json.loads(l) for l in imported.read_text().splitlines()] if imported.exists() else []
        if imported.exists():inputs[str(imported)]=digest_file(imported)
        other_status=dict(source=str(imported),snapshot_only=True,automatic_processing_configured=False,
                          records=len(other_rows),modalities=dict(Counter(r['modality'] for r in other_rows)),
                          judgments=dict(Counter(r['judgment'] for r in other_rows)),
                          reason='Normalized imported data require separate modality-specific source validation; not selected here.')
        other_output=ROOT/'outputs/other-data-v1'
        active=ROOT/'outputs/other-data-active.json'
        if active.exists():other_output=Path(read(active)['output'])
        other_summary=other_output/'summary.json'
        other_report=other_output/'다른자료_처리현황.html'
        if other_summary.exists():
            inputs[str(other_summary)]=digest_file(other_summary)
            other_status.update(automatic_processing_configured=True,processing_summary=read(other_summary),
                                report=str(other_report),
                                reason='Separate native-source and API review pipeline; its selected pool stays separate until cross-source chunking.')
        completed=sum((source/'results'/(t['id']+'.json')).exists() for t in plan['tasks'])
        remaining=len(plan['tasks'])-completed
        summary=dict(scope='detected_ink_and_its_checked_text_context',
            catalogue_regions=len(plan['tasks'])+len(plan['excluded_processed_ids'])+len(plan['earlier_excluded_ids']),
            processed_regions=len(paths),remaining_regions=remaining,
            stage='partial_selection' if remaining else 'ink_processing_and_selection_complete',
            all_modalities_complete=False,selected_records=len(selected),
            text_records=sum(r['route']=='text' for r in selected),
            metadata_records=sum(r['route']=='linked_metadata' for r in selected),
            excluded_observations=len(excluded),missing_core=len(pending),
            separate_imported_records=len(other_rows),api_requests=0,embedding_created=False,accuracy=None)
        for p,h in inputs.items():
            if digest_file(p)!=h:raise ValueError('input_changed_during_selection')
        m=dict(inputs=inputs,code_sha256=digest_file(__file__),summary=summary)
        dest=output/'snapshots'/signature(m)[:20];dest.mkdir(parents=True,exist_ok=True)
        jsonl(dest/'usable-records.jsonl',selected)
        jsonl(dest/'text-for-chunking.jsonl',[r for r in selected if r['route']=='text'])
        jsonl(dest/'linked-metadata.jsonl',[r for r in selected if r['route']=='linked_metadata'])
        jsonl(dest/'excluded-observations.jsonl',excluded);jsonl(dest/'missing-content.jsonl',pending)
        save(dest/'other-modality-status.json',other_status);save(dest/'manifest.json',m);save(dest/'summary.json',summary)
        save(output/'latest.json',dict(at=now(),snapshot=str(dest),summary=summary))
        esc=lambda x:html.escape(str(x))
        labels={'processed_regions':'검토한 필기 구역','remaining_regions':'남은 필기 구역',
                'selected_records':'사용할 데이터','text_records':'글자·코드·필기',
                'metadata_records':'표시·연결 정보','excluded_observations':'사용에서 제외한 데이터',
                'missing_core':'누락 의심 항목','separate_imported_records':'다른 자료 검토 대기'}
        table='<table>'+''.join('<tr><th>'+v+'</th><td>'+esc(summary[k])+'</td></tr>' for k,v in labels.items())+'</table>'
        reasons=Counter(x for r in excluded for x in r['reasons'])
        page='<!doctype html><meta charset="utf-8"><title>사용 가능 데이터 선별</title><style>body{font-family:system-ui;max-width:1000px;margin:35px auto}th,td{text-align:left;padding:7px}pre{white-space:pre-wrap}</style><h1>사용 가능 데이터 선별</h1><p>'+('진행 중인 부분 선별입니다.' if remaining else '감지된 필기 영역의 처리·선별이 끝났습니다.')+' 본문·음성·문서 전체 검증 완료를 의미하지 않습니다. 임베딩은 아직 생성하지 않았습니다.</p>'+table
        page+='<p>보류·관리자 검토·미확정 관찰은 제외합니다. 원문과 보정 후보는 분리하며, 표시와 연결 관계는 독립 텍스트로 만들어내지 않습니다. 선택된 항목에도 경고와 검사 범위가 보존됩니다.</p><h2>선별 결과</h2>'
        if other_summary.exists():
            osum=other_status['processing_summary']
            page+='<h2>본문·음성·PPT 별도 처리</h2><p>PPT 원문 확인 '+str(osum['native_ppt_records'])+'개, 이 분야에서 사용할 데이터 '+str(osum['usable_records'])+'개. 남은 API 작업 '+str(osum['remaining'])+'개입니다. 위 필기 수치와는 별도로 집계합니다.</p><p><a href="'+other_report.as_uri()+'">본문·음성·PPT 처리 결과 보기</a></p>'
        for name in ['usable-records.jsonl','text-for-chunking.jsonl','linked-metadata.jsonl','excluded-observations.jsonl','other-modality-status.json']:
            page+='<p><a href="'+(dest/name).as_uri()+'">'+name+'</a></p>'
        page+='<h2>제외 사유별 수</h2><pre>'+esc(json.dumps(reasons,ensure_ascii=False,indent=2))+'</pre>'
        (dest/'사용가능데이터_선별.html').write_text(page,encoding='utf-8');(output/'사용가능데이터_선별.html').write_text(page,encoding='utf-8')
        return summary


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',type=Path,default=SOURCE)
    p.add_argument('--review',type=Path,default=REVIEW_OUTPUT);p.add_argument('--output',type=Path,default=OUTPUT)
    a=p.parse_args();print(json.dumps(build(a.source,a.review,a.output),ensure_ascii=False))


if __name__=='__main__':main()
