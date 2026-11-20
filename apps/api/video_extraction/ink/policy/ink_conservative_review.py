"""Offline review overlay: preserve extraction; group causes; release only evidence-backed holds.

The frozen continuation remains resumable. No model client is created here. This
layer never rewrites literal text or geometry. Exact source review receipts are
valid only for their original result and pixels, not for similar future samples.
"""
from video_extraction._layout import PACKAGE_ROOT
import argparse
import copy
from video_extraction.shared import file_lock as fcntl
import html
import json
import math
from pathlib import Path

from video_extraction.shared.common import read, save, jsonl, signature, digest_file, now
from video_extraction.ink.runner.ink_continue_v2 import check_plan, ROOT
from video_extraction.ink.correction.ink_discrepancy import ACCEPTED, apply_review, refresh_relations
from video_extraction.ink.recognition.ink_evidence import pixel_evidence
from video_extraction.ink.runner.ink_pipeline import inspect_visual

SOURCE = ROOT/'outputs/ink-continuation-v2'
OUTPUT = ROOT/'outputs/ink-conservative-review-v1'
RECEIPTS = PACKAGE_ROOT/'fixtures/ink_conservative_review/source-reviews.json'


def values(result):
    return {x['id']: x for group in ('items', 'links') for x in result['candidate'][group]}


def protect_original(before, after):
    """Fail closed on changed literals/geometry, lost records, or changed healthy decisions."""
    if before['candidate'] != after['candidate']:
        raise ValueError('candidate_changed_by_review_overlay')
    for key in ('final_audit', 'administrator_queue', 'missing_core'):
        if before.get(key) != after.get(key):
            raise ValueError('protected_evidence_changed:'+key)
    decisions = {d['id']: d for d in after['decisions']}
    for d in before['decisions']:
        if d['status'] != 'held' and decisions.get(d['id']) != d:
            raise ValueError('healthy_decision_changed:'+d['id'])
    rows = {r['id']: r for r in after['records']}
    for row in before['records']:
        if rows.get(row['id']) != row:
            raise ValueError('existing_record_changed:'+row['id'])
    old = before['effective_inventory']; new = after['effective_inventory']
    for group in ('items', 'links'):
        by_id = {x['id']: x for x in new[group]}
        for x in old[group]:
            if by_id.get(x['id']) != x:
                raise ValueError('effective_content_changed:'+x['id'])


def simple_emphasis_eligible(result, iid):
    """Only imprecise shape extent may become a warning; semantics must be supported."""
    items = values(result)
    decisions = {d['id']: d for d in result['decisions']}
    checks = {c['id']: c for c in result['final_audit']['checks']}
    item = items[iid]; d = decisions[iid]; c = checks.get(iid, {})
    if d['status'] != 'held' or d['reasons'] != ['source_geometry_partial']:
        return False
    if (item.get('kind') not in ('circle', 'underline') or item.get('text')
            or item.get('cancelled') or item.get('arrow_points') or item.get('uncertainties')):
        return False
    if not (c.get('content') == c.get('meaning') == 'supported'
            and c.get('geometry') == 'partial' and c.get('role') == 'simple_emphasis'
            and c.get('meaning_preserved') is True and c.get('role_risk') is False
            and c.get('split_required') is False and c.get('critical') is False
            and c.get('uncertainty_scope') == 'none'):
        return False
    box = item['box']; a,b,r,t = [box[k] for k in ('left','top','right','bottom')]
    if not all(type(v) in (int,float) and math.isfinite(v) for v in (a,b,r,t)):
        return False
    if not 0 <= a < r <= 1000 or not 0 <= b < t <= 1000:
        return False
    links = [l for l in result['candidate']['links'] if iid in l['from_ids']+l['to_ids']]
    if not links: return False
    for l in links:
        lc = checks.get(l['id'], {})
        if (l['kind'] != 'emphasis' or l['direction'] != 'not_applicable'
                or iid not in l['from_ids'] or not l['to_ids']
                or not all(lc.get(k) == 'supported' for k in ('content','geometry','meaning'))
                or lc.get('role_risk') is not False or lc.get('critical') is not False
                or lc.get('split_required') is not False):
            return False
        for target in l['from_ids']+l['to_ids']:
            if target == iid: continue
            if (decisions.get(target, {}).get('status') not in ACCEPTED
                    or items.get(target, {}).get('cancelled')
                    or items.get(target, {}).get('kind') in ('arrow','strikethrough','unclear')
                    or items.get(target, {}).get('uncertainties')):
                return False
    # Necessary evidence only; the independent semantic checks above are also required.
    return pixel_evidence(result['final_view']['path'], box)['foreground_pixels'] >= 2


def add_released_records(package, previous, result, released):
    rows, _ = inspect_visual(result['candidate'], package['task'], result['final_view'],
                             {'state':'unavailable','words':[]})
    decisions = {d['id']:d for d in result['decisions']}
    for row in rows:
        iid = row['local_id']
        if iid not in released: continue
        d = decisions[iid]
        row.update(judgment=d['status'], approved_for_rag=False, content_verified=False,
                   representation=d.get('representation','literal_observation'),
                   verification={'method':'conservative_emphasis_policy','gold_approved':False},
                   policy_findings={'blocking':[], 'warnings':d['warnings'], 'unprocessed':d['unprocessed']},
                   usable_for_semantic_assertion=True, exact_geometry_verified=False,
                   interpretation_scope='coarse_emphasis_target_only',
                   exact_count_and_element_assignment_verified=False,
                   selected_frame=package['task']['evidence']['selected_frame'])
        row['issues']=[i for i in row['issues'] if i['code']!='geometry_evidence_pending']
        result['records'].append(row)
    for group in ('items','links'):
        known={x['id'] for x in result['effective_inventory'][group]}
        result['effective_inventory'][group] += [copy.deepcopy(x) for x in result['candidate'][group]
                                                if x['id'] in released and x['id'] not in known]


def reconcile(package, previous, receipt=None):
    before = copy.deepcopy(previous); result = copy.deepcopy(previous)
    notices=[]
    if receipt:
        source=package['task']['evidence']['selected_frame']
        bound=(receipt['result_signature']==signature(previous)
               and receipt['source_sha256']==digest_file(source))
        if bound:
            # Classification notes never grant release authority.
            result['direct_observation']=copy.deepcopy(receipt.get('classification',{}))
            if receipt.get('entries'):
                result=apply_review(package,previous,receipt)
                result['direct_observation']=copy.deepcopy(receipt.get('classification',{}))
        else:
            notices.append('source_review_receipt_stale_not_applied')
    held_before={d['id'] for d in result['decisions'] if d['status']=='held'}
    changes=[]
    for d in result['decisions']:
        if simple_emphasis_eligible(result,d['id']):
            d.update(status='usable_with_warning', reasons=[], representation='emphasis_region')
            d['warnings']=list(dict.fromkeys(d['warnings']+['imprecise_simple_emphasis_extent']))
            d['resolution']='semantic_target_checked_geometry_remains_approximate'
            changes.append(d['id'])
    if changes:
        refresh_relations(result)
        # Rechecking dependencies must not rewrite healthy decisions/records.
        old_decisions={d['id']:d for d in before['decisions']}
        result['decisions']=[copy.deepcopy(old_decisions[d['id']])
                             if old_decisions[d['id']]['status']!='held' else d for d in result['decisions']]
        released={d['id'] for d in result['decisions'] if d['id'] in held_before and d['status'] in ACCEPTED}
        for d in result['decisions']:
            if d['id'] in released:
                d['warnings']=list(dict.fromkeys(d['warnings']+['imprecise_simple_emphasis_extent']))
        add_released_records(package,before,result,released)
    result['active_coverage_complete']=(not any(d['status']=='held' for d in result['decisions'])
                                        and not result.get('missing_core'))
    result['all_review_resolved']=result['active_coverage_complete'] and not result['administrator_queue']
    result['effective_inventory']['complete']=result['all_review_resolved']
    result['status']='conservative_checked' if result['active_coverage_complete'] else 'partially_checked'
    result['overlay_notices']=notices
    result['overlay_version']='conservative_review_v1'
    result['overlay_source_signature']=signature(previous)
    result['overlay_api_requests']=0
    protect_original(before,result)
    return result


def cause_groups(result):
    """Group only connected unresolved dependencies, not unrelated items in one frame."""
    ds={d['id']:d for d in result.get('decisions',[]) if d['status']=='held'}
    adjacency={i:set() for i in ds}
    for link in result.get('candidate',{}).get('links',[]):
        iid=link['id']
        if iid not in ds or ds[iid]['reasons']!=['dependency_unresolved']: continue
        for ref in link['from_ids']+link['to_ids']:
            if ref in ds:
                adjacency[iid].add(ref);adjacency[ref].add(iid)
    groups=[];seen=set()
    for iid in sorted(ds):
        if iid in seen: continue
        stack=[iid];members=set()
        while stack:
            j=stack.pop()
            if j in members: continue
            members.add(j);stack.extend(adjacency[j]-members)
        seen |= members
        roots=sorted(j for j in members if ds[j]['reasons']!=['dependency_unresolved'])
        groups.append(dict(task_id=result['task_id'],root_ids=roots or sorted(members),
                           member_ids=sorted(members),status='held',
                           reasons=sorted({r for j in members for r in ds[j]['reasons'] if r!='dependency_unresolved'}),
                           original_decisions=[ds[j] for j in sorted(members)]))
    for i,m in enumerate(result.get('missing_core',[])):
        groups.append(dict(task_id=result['task_id'],root_ids=['missing-'+str(i)],member_ids=[],
                           status='missing_core',reasons=['missing_source_mark'],evidence=m))
    return groups


def administrator_groups(entries):
    groups=[]
    # Task and connected references, not proximity or matching words, establish identity.
    for task in sorted({e['task_id'] for e in entries}):
        rows={e['local_id']:e for e in entries if e['task_id']==task}
        adj={i:set() for i in rows}
        for iid,row in rows.items():
            for ref in row.get('item',{}).get('from_ids',[])+row.get('item',{}).get('to_ids',[]):
                if ref in rows: adj[iid].add(ref);adj[ref].add(iid)
        seen=set()
        for iid in sorted(rows):
            if iid in seen:continue
            stack=[iid];members=set()
            while stack:
                j=stack.pop()
                if j in members:continue
                members.add(j);stack.extend(adj[j]-members)
            seen |= members
            groups.append(dict(task_id=task,member_ids=sorted(members),status='administrator_review',
                               entries=[rows[j] for j in sorted(members)]))
    return groups


def render(output, summary, groups, admin, results, releases, inherited):
    esc=lambda x:html.escape(str(x))
    cards=[]
    for group in groups:
        r=results.get(group['task_id'],{})
        view=r.get('final_view',{}).get('path')
        note=r.get('direct_observation',{})
        cards.append('<article><h2>'+esc(group['task_id'])+' · '+esc(', '.join(group['root_ids']))+'</h2>'
                     +('<img src="'+Path(view).as_uri()+'">' if view else '')
                     +'<p>'+esc(note.get('summary','추가 원본 검토가 필요합니다.'))+'</p>'
                     +'<p>묶인 항목: '+esc(', '.join(group['member_ids']))+'</p><details><summary>근거와 상태</summary><pre>'
                     +esc(json.dumps({'group':group,'observation':note},ensure_ascii=False,indent=2))+'</pre></details></article>')
    for pending in inherited:
        cards.append('<article><h2>기존 의미 미확정 · '+esc(pending.get('task_id'))+'</h2>'
                     '<p>괄호형 모양은 확인했지만 정확한 기호와 의미는 확정하지 않았습니다. 기존 보류를 유지합니다.</p>'
                     '<details><summary>상태</summary><pre>'+esc(json.dumps(pending,ensure_ascii=False,indent=2))+'</pre></details></article>')
    for group in admin:
        first=group['entries'][0];img=first.get('crop_image') or first.get('source_image')
        cards.append('<article><h2>관리자 검토 · '+esc(group['task_id'])+'</h2>'
                     +('<img src="'+Path(img).as_uri()+'">' if img else '')
                     +'<p>지워진 필기와 관련 표시를 한 건으로 묶었습니다. 원래 상태는 유지됩니다.</p><details><summary>원래 항목</summary><pre>'
                     +esc(json.dumps(group,ensure_ascii=False,indent=2))+'</pre></details></article>')
    labels={'processed_regions':'검토한 영역','unprocessed_regions':'미처리 영역','held_items_before':'기존 보류 항목',
            'held_items_after':'남은 보류 항목','released_items':'오탐 해제·경고 전환 항목','held_cause_groups':'남은 보류 원인 묶음',
            'missing_mark_groups':'별도 표시 누락 건','inherited_semantic_pending':'기존 의미 미확정',
            'administrator_entries':'관리자 원래 항목','administrator_groups':'관리자 검토 묶음',
            'preserved_healthy_decisions':'그대로 보존한 기존 비보류 판정','literal_or_geometry_edits':'글자·좌표 변경','api_requests':'API 호출'}
    table='<table>'+''.join('<tr><th>'+label+'</th><td>'+esc(summary[k])+'</td></tr>' for k,label in labels.items())+'</table>'
    changes='<h2>상태 변경 내역</h2><ul>'+''.join('<li>'+esc(c['task_id'])+' / '+esc(c['id'])+' — '+
             ('OCR 오탐 원본 확인' if c['after'].get('resolution')=='release_ocr_false_positive' else
              '단순 강조 범위 정밀도 경고' if 'imprecise_simple_emphasis_extent' in c['after']['warnings'] else '연결 대상 재확인')+
             '</li>' for c in releases)+'</ul>'
    (output/'보류원인_검토.html').write_text('<!doctype html><meta charset="utf-8"><title>보류 원인 검토</title>'
        '<style>body{font-family:system-ui;max-width:1050px;margin:32px auto;padding:16px}article{border-top:1px solid #ccc;padding:20px 0}img{max-width:100%}pre{white-space:pre-wrap}</style>'
        '<h1>정상 추출을 보호하는 보류 원인 검토</h1><p>글자·좌표는 변경하지 않았습니다. 확인된 OCR 오탐과 조건을 충족한 단순 강조만 상태를 조정했습니다. 묶음 수 감소는 정확도 향상을 뜻하지 않습니다.</p>'
        +table+changes+'<h2>남은 원인별 검토</h2>'+''.join(cards),encoding='utf-8')


def build(source=SOURCE, output=OUTPUT, receipts=RECEIPTS):
    source=source.resolve();output=output.resolve()
    if output==source or source in output.parents: raise ValueError('separate_output_required')
    output.mkdir(parents=True,exist_ok=True)
    with (source/'.run.lock').open('a') as lock, (output/'.build.lock').open('a') as outlock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        fcntl.flock(outlock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        plan=check_plan(source); reviews=read(receipts)
        inputs={str(receipts.resolve()):digest_file(receipts),str(source/'plan.json'):digest_file(source/'plan.json')}
        results={};groups=[];records=[];admin={a['id']:a for a in plan['inherited_administrator_queue']}
        before_count=0;releases=[];healthy=0
        for task in plan['tasks']:
            path=source/'results'/(task['id']+'.json')
            if not path.exists():continue
            previous=read(path);inputs[str(path)]=digest_file(path)
            if previous['plan_signature']!=signature(plan):raise ValueError('stale_result')
            result=copy.deepcopy(previous)
            if previous.get('candidate'):
                pkgpath=source/'prepared'/path.name;package=read(pkgpath)
                inputs[str(pkgpath)]=digest_file(pkgpath)
                for p in {package['task']['evidence']['selected_frame'],previous['final_view']['path']}:
                    inputs[p]=digest_file(p)
                before_count+=sum(d['status']=='held' for d in previous['decisions'])
                healthy+=sum(d['status']!='held' for d in previous['decisions'])
                result=reconcile(package,previous,reviews.get(task['id']))
                old={d['id']:d for d in previous['decisions']}
                releases += [dict(task_id=task['id'],id=d['id'],before=old[d['id']],after=d)
                             for d in result['decisions'] if old[d['id']]['status']=='held' and d['status']!='held']
                groups+=cause_groups(result)
            else:
                groups.append(dict(task_id=task['id'],status='review_required',root_ids=['execution'],member_ids=[],reasons=[previous.get('error','incomplete_result')]))
            results[task['id']]=result;records+=result.get('records',[])
            for a in result.get('administrator_queue',[]):admin[a['id']]=a
        for p,expected in inputs.items():
            if digest_file(p)!=expected:raise ValueError('source_changed_during_review')
        admins=administrator_groups(list(admin.values()))
        remaining=sum(d['status']=='held' for r in results.values() for d in r.get('decisions',[]))
        summary=dict(processed_regions=len(results),unprocessed_regions=len(plan['tasks'])-len(results),
            held_items_before=before_count,held_items_after=remaining,released_items=len(releases),
            held_cause_groups=sum(g['status']=='held' for g in groups),missing_mark_groups=sum(g['status']=='missing_core' for g in groups),
            inherited_semantic_pending=len(plan['inherited_pending']),administrator_entries=len(admin),administrator_groups=len(admins),
            preserved_healthy_decisions=healthy,literal_or_geometry_edits=0,api_requests=0,accuracy=None)
        manifest=dict(inputs=inputs,code_sha256=digest_file(__file__),summary=summary)
        snapshot=output/'snapshots'/signature(manifest)[:20];snapshot.mkdir(parents=True,exist_ok=True)
        for tid,r in results.items():save(snapshot/'results'/(tid+'.json'),r)
        save(snapshot/'manifest.json',manifest);save(snapshot/'summary.json',summary)
        jsonl(snapshot/'records.jsonl',records);jsonl(snapshot/'review-groups.jsonl',groups)
        jsonl(snapshot/'administrator-groups.jsonl',admins);jsonl(snapshot/'administrator-review.jsonl',list(admin.values()))
        jsonl(snapshot/'status-changes.jsonl',releases);jsonl(snapshot/'inherited-pending.jsonl',plan['inherited_pending'])
        render(snapshot,summary,groups,admins,results,releases,plan['inherited_pending'])
        save(output/'latest.json',dict(at=now(),snapshot=str(snapshot),summary=summary))
        # Stable entry page; detailed snapshots remain immutable for different input sets.
        report=snapshot/'보류원인_검토.html'
        (output/'보류원인_검토.html').write_text(report.read_text(),encoding='utf-8')
        return summary


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',type=Path,default=SOURCE);p.add_argument('--output',type=Path,default=OUTPUT)
    a=p.parse_args();print(json.dumps(build(a.source,a.output),ensure_ascii=False))


if __name__=='__main__':main()
