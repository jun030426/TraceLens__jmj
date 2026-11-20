"""Bounded recovery of failed ink reviews; previous runs are immutable.

prepare replays stored source audits offline. Only run creates an API client.
No reference/gold annotations are consumed. Coordinates retain their source frame.
"""
from video_extraction._layout import code_hashes_match
import argparse
import copy
from video_extraction.shared import file_lock as fcntl
import html
import json
from collections import Counter
from pathlib import Path

from PIL import Image

from video_extraction.shared.common import digest_file, jsonl, now, read, save, signature, validate
from video_extraction.shared.gemini import Blocked, Gemini
from video_extraction.ink.runner.ink_pipeline import VISUAL, VISUAL_PROMPT, merge_repair, stage_call, transform_visual, transform_ocr
from video_extraction.ink.policy.ink_policy import AUDIT, PROMPT, admin_ids, apply_policy, hashes as policy_hashes, speech_hints, word_edges
from video_extraction.ink.correction.ink_recheck import ROOT, core_box, scope_ids

OUTPUT = ROOT/'outputs/ink-recovery-v1'
RECOVERY_VISUAL_PROMPT = VISUAL_PROMPT.replace('Never emit full-screen coordinates.',
    'If image 1 is the native full frame, use its normalized full-frame coordinates.')


def hashes():
    return {**policy_hashes(), 'ink_recovery.py': digest_file(__file__)}


def required_ids(package, value):
    return scope_ids(value, core_box(package['task'], package['view'])) - admin_ids(value)


def audit_partition(audit, required):
    """A missing/duplicate check blocks that ID only; extra IDs confer no rights."""
    validate(audit, AUDIT)
    counts = Counter(c['id'] for c in audit['checks'])
    valid = {c['id']: copy.deepcopy(c) for c in audit['checks']
             if c['id'] in required and counts[c['id']] == 1}
    return valid, required-set(valid), set(counts)-required


def uncertain_check(iid):
    # Explicit sentinel: never an affirmative model judgement.
    return dict(id=iid, content='uncertain', geometry='uncertain', meaning='uncertain',
                reason='audit_response_missing_or_duplicate', full_text='', lexical_complete=False,
                meaning_preserved=False, role_risk=True, role='unknown', split_required=True,
                critical=True, uncertainty_scope='other')


def safe_audit(audit, required):
    valid, unresolved, extra = audit_partition(audit, required)
    complete = {**copy.deepcopy(audit),
                'checks': [valid.get(i, uncertain_check(i)) for i in sorted(required)],
                'complete': audit['complete'] and not unresolved}
    return complete, unresolved, extra


def normalize_emphasis(value, audit, required):
    """Normalize a metadata contradiction, never guess an arrow or its target.

    Require independent source/meaning support for the relation and each shape.
    Grouping, label, connection, process, arrow and cancellation remain untouched.
    """
    result = copy.deepcopy(value); changes = []
    checks, _, _ = audit_partition(audit, required)
    items = {x['id']: x for x in value['items']}

    def supported(iid):
        c = checks.get(iid, {})
        return (c.get('role') == 'simple_emphasis' and c.get('content') == 'supported'
                and c.get('geometry') == c.get('meaning') == 'supported'
                and c.get('meaning_preserved') and not c.get('role_risk', True)
                and not c.get('split_required', True) and not c.get('critical', True)
                and c.get('uncertainty_scope') == 'none')

    for link in result['links']:
        if (link['id'] not in required or link['kind'] != 'emphasis'
                or link['direction'] != 'observed' or not supported(link['id'])): continue
        refs = link['from_ids'] + link['to_ids']
        if not link['from_ids'] or not link['to_ids'] or any(i not in items for i in refs): continue
        if any(items[i].get('cancelled') or items[i].get('arrow_points') or items[i]['kind'] == 'arrow' for i in refs): continue
        if any(items[i]['kind'] not in ('circle', 'underline', 'bracket') or not supported(i)
               for i in link['from_ids']): continue
        changes.append({'id': link['id'], 'field': 'direction', 'before': 'observed',
                        'after': 'not_applicable', 'basis': 'source_audited_non_directional_emphasis'})
        link['direction'] = 'not_applicable'
    return result, changes


def evaluate(package, value, audit):
    required = required_ids(package, value)
    normalized, edits = normalize_emphasis(value, audit, required)
    safe, unresolved, extra = safe_audit(audit, required)
    result = apply_policy(package, normalized, safe)
    result.update(raw_candidate=copy.deepcopy(value), final_audit=copy.deepcopy(audit),
                  audit_contract_valid=not unresolved and not extra,
                  unresolved_audit_ids=sorted(unresolved), ignored_audit_ids=sorted(extra),
                  format_normalizations=edits, final_view=package['view'])
    # Keep the old API audit and the original observation, even after normalization.
    edited = {e['id'] for e in edits}
    for change in result['changes']:
        change['change_type'] = ('format_normalization' if change['id'] in edited
            and {k: v for k, v in (change['before'] or {}).items() if k != 'direction'}
                == {k: v for k, v in change['after'].items() if k != 'direction'}
            else 'content_or_geometry')
    for d in result['decisions']:
        if d['id'] in unresolved: d['reasons'].append('audit_check_unresolved')
    for row in result['records']:
        normalization = next((e for e in edits if e['id'] == row['local_id']), None)
        if normalization:
            row['format_normalization'] = normalization
            row['original_relation'] = next(copy.deepcopy(x) for x in value['links'] if x['id'] == row['local_id'])
    return result


def widen_to_source(package):
    """One bounded fallback to native full-frame coordinates, not bitmap upscaling.

    Core scope remains unchanged. Both OCR variants AND scanned coverage move with
    all candidate/base boxes and arrow endpoints. New pixels are not called OCR'd.
    """
    p = copy.deepcopy(package); old = p['view']
    path = p['task']['evidence']['selected_frame']
    with Image.open(path) as im: size = list(im.size)
    view = dict(path=path, size=size, crop_in_source=[0, 0, 1, 1],
                operation='native_full_source_boundary_fallback', eligible=True, core_unchanged=True)
    for key in ('base', 'candidate'): p[key] = transform_visual(p[key], old, view)
    receipt = transform_ocr(p['ocr'], old, view)
    if 'alternative_words' in p['ocr']:
        receipt['alternative_words'] = transform_ocr({'words': p['ocr']['alternative_words']}, old, view)['words']
    p['ocr'] = receipt
    p['ocr_coverage'] = transform_visual({'items': [{'box': p['ocr_coverage'], 'arrow_points': []}]}, old, view)['items'][0]['box']
    p['view'] = view
    return p


def needs_wider(result):
    return any('required_item_touches_crop_boundary' in d['reasons']
               for d in result['decisions'] if d['status'] == 'held')


def source_audit(package, value, output, plan, client, stage):
    """One complete scan, at most one selective ID-fill call for this candidate."""
    required = required_ids(package, value)
    payload = dict(candidate=value, required_ids=sorted(required),
                   administrator_ids=sorted(admin_ids(value)), core_box=core_box(package['task'], package['view']),
                   boundary_suspicions=word_edges(value, package['view']),
                   timed_speech_hints=speech_hints(package, value))
    media = list(dict.fromkeys([Path(package['view']['path']), Path(package['task']['evidence']['selected_frame'])]))
    audit = stage_call(package['task'], output, plan, client, stage, media,
                       PROMPT+json.dumps(payload, ensure_ascii=False), AUDIT)
    good, missing, extra = audit_partition(audit, required)
    trace = {'missing_ids': sorted(missing), 'extra_ids': sorted(extra), 'fill_attempted': bool(missing)}
    if missing:
        payload.update(required_ids=sorted(missing), instruction='Only return the requested missing/duplicate ID checks. '
            'Do not repeat other checks. Scan the same active core for omissions. Coordinates and candidate are unchanged.')
        fill = stage_call(package['task'], output, plan, client, stage+'_fill_ids', media,
                          PROMPT+json.dumps(payload, ensure_ascii=False), AUDIT)
        more, _, fill_extra = audit_partition(fill, missing)
        good.update(more)
        omissions = {signature(m): m for m in audit['missing'] + fill['missing']}
        audit = dict(checks=list(good.values()), missing=list(omissions.values()),
                     complete=audit['complete'] and fill['complete'])
        trace['fill_extra_ids'] = sorted(fill_extra)
    trace['unresolved_ids'] = sorted(required-set(good))
    return audit, trace


def execute(package, output, plan, client):
    p = copy.deepcopy(package); value = p['candidate']
    first, trace = source_audit(p, value, output, plan, client, 'recovery_source_audit')
    initial = evaluate(p, value, first); final = first; traces = [trace]; repairs = []
    # Only pre-existing failures (and newly found missing core units) can be changed.
    allowed = set(p['failed_ids'])
    held = {d['id'] for d in initial['decisions'] if d['status'] == 'held'}
    requested = (held & allowed) - set(initial['unresolved_audit_ids'])
    if initial['missing_core'] or not first['complete']: requested.add('__scope__')
    if requested:
        if needs_wider(initial) and p['view']['crop_in_source'] != [0, 0, 1, 1]:
            p['candidate'] = value; p = widen_to_source(p); value = p['candidate']
            # Old audit coordinates no longer apply. Use failures as reasons only.
        media = list(dict.fromkeys([Path(p['view']['path']), Path(p['task']['evidence']['selected_frame'])]))
        payload = dict(candidate=value, repair_only_ids=sorted(requested),
                       administrator_ids=sorted(admin_ids(value)), core_box=core_box(p['task'], p['view']),
                       findings=[d for d in initial['decisions'] if d['id'] in requested],
                       instruction='Use original SOURCE pixels. Read whole words/operators beyond the old box. '
                       'All coordinates belong to image 1. Do not invent ambiguous 0/o or erased text. '
                       'Preserve all unaffected IDs. No deletion. Emphasis circles/underlines have direction '
                       'not_applicable; only visible arrow endpoints justify observed direction. '
                       'Never convert an arrow/process to emphasis to pass validation.')
        patch = stage_call(p['task'], output, plan, client, 'recovery_targeted_repair', media,
                           RECOVERY_VISUAL_PROMPT+json.dumps(payload, ensure_ascii=False), VISUAL)
        value = merge_repair(value, patch, requested)
        final, after = source_audit(p, value, output, plan, client, 'recovery_final_audit')
        traces.append(after); repairs = sorted(requested)
    result = evaluate(p, value, final)
    result.update(task_id=p['task']['id'], plan_signature=signature(plan),
                  candidate_signature=signature(value), initial_audit=first, audit_recovery=traces,
                  repair_requested_ids=repairs, repair_used=bool(repairs),
                  verification_run='fresh_source_recovery', api_execution_required=False)
    return result


def prepare(source, output):
    source = source.resolve(); output = output.resolve()
    if output.exists(): raise ValueError('output_exists_choose_new_folder')
    old_plan = read(source/'plan.json'); input_hashes = {str(source/'plan.json'): digest_file(source/'plan.json')}
    for name, expected in old_plan['input_hashes'].items():
        if digest_file(name) != expected: raise ValueError('changed_source_input:'+name)
    manifests = {}
    for path in sorted((source/'batches').glob('*/local.json')):
        m = read(path)
        if m['plan_signature'] != signature(old_plan) or m['task_signature'] != signature(m['tasks']):
            raise ValueError('stale_local_manifest')
        for name, expected in m['hashes'].items():
            if digest_file(name) != expected: raise ValueError('changed_local_evidence:'+name)
        manifests.update(m['tasks']); input_hashes[str(path.resolve())] = digest_file(path)
    tasks = []; replay = []
    inherited_admin = list(old_plan.get('inherited_administrator_queue', []))
    for path in sorted((source/'results').glob('*.json')):
        r = read(path)
        if r['plan_signature'] != signature(old_plan): raise ValueError('stale_source_result')
        input_hashes[str(path.resolve())] = digest_file(path)
        inherited_admin += r.get('administrator_queue', [])
        if r.get('active_coverage_complete'): continue
        if not r.get('candidate') or not r.get('final_audit'): raise ValueError('missing_recovery_evidence:'+path.stem)
        if r['candidate_signature'] != signature(r['candidate']): raise ValueError('changed_source_candidate')
        p = copy.deepcopy(manifests[path.stem]); p.update(base=r['effective_inventory'], candidate=r['candidate'],
            view=r['final_view'], audio_context=r.get('audio_context', {}),
            failed_ids=[d['id'] for d in r['decisions'] if d['status'] == 'held'])
        # Bind source pixels and the previous OCR's coordinate system.
        if p['view'] != manifests[path.stem]['view']: raise ValueError('unexpected_source_view')
        for image in (p['view']['path'], p['task']['evidence']['selected_frame']): input_hashes[image] = digest_file(image)
        local = evaluate(p, p['candidate'], r['final_audit'])
        local.update(task_id=path.stem, verification_run='stored_source_audit_replay', api_requests=0,
                     previous_held=len(p['failed_ids']))
        replay.append(local)
        # Source-boundary failures get all original pixels BEFORE any API call.
        if needs_wider(local): p = widen_to_source(p)
        package_path = output/'prepared'/(path.stem+'.json'); save(package_path, p)
        tasks.append(dict(id=path.stem, package=str(package_path),
                          needs_api=not local['active_coverage_complete']))
        save(output/'local-replay'/(path.stem+'.json'), local)
    for t in tasks: input_hashes[t['package']] = digest_file(t['package'])
    plan = dict(version=1, created_at=now(), source=str(source), model=old_plan['model'],
                tasks=tasks, code_hashes=hashes(), input_hashes=input_hashes,
                inherited_administrator_queue=inherited_admin, max_logical_calls_per_task=5,
                scope='Existing failed regions only; no new catalogue batches, gold labels, or original-audio API.')
    save(output/'plan.json', plan)
    for t, r in zip(tasks, replay):
        if not t['needs_api']:
            r.update(plan_signature=signature(plan), api_execution_required=False)
            save(output/'results'/(t['id']+'.json'), r)
    return report(output)


def check_plan(output):
    plan = read(output/'plan.json')
    if not code_hashes_match(plan['code_hashes'], hashes()): raise ValueError('code_changed_prepare_new_output')
    for path, expected in plan['input_hashes'].items():
        if digest_file(path) != expected: raise ValueError('changed_input:'+path)
    return plan


def report(output):
    plan = read(output/'plan.json'); rows = []; records = []; pending = []; changes = []; cards = []
    for task in plan['tasks']:
        path = output/'results'/(task['id']+'.json')
        replay = read(output/'local-replay'/(task['id']+'.json'))
        r = read(path) if path.exists() else replay
        if path.exists():
            if r['plan_signature'] != signature(plan): raise ValueError('stale_result')
            rows.append(r); records += r['records']; changes += r['changes']
        else: pending.append(dict(task_id=task['id'], status='api_recheck_pending'))
        pending += [dict(task_id=task['id'], **d) for d in r['decisions'] if d['status'] == 'held']
        if r.get('missing_core'): pending.append(dict(task_id=task['id'], status='missing_core', items=r['missing_core']))
        cards.append('<article><h2>'+html.escape(task['id'])+'</h2><p>'+
            ('API 재검사 대기' if not path.exists() else html.escape(r['verification_run']))+'</p><pre>'+
            html.escape(json.dumps({k:r.get(k) for k in ('changes','decisions','unresolved_audit_ids','active_coverage_complete')}, ensure_ascii=False, indent=2))+'</pre></article>')
    admin = {a['id']: a for a in plan['inherited_administrator_queue']}
    for r in rows:
        for a in r['administrator_queue']: admin[a['id']] = a
    summary = dict(failed_regions=len(plan['tasks']), api_regions=sum(t['needs_api'] for t in plan['tasks']),
        processed_regions=len(rows), complete_regions=sum(r['active_coverage_complete'] for r in rows),
        remaining_api_regions=sum(not (output/'results'/(t['id']+'.json')).exists() for t in plan['tasks']),
        format_changes=sum(c.get('change_type')=='format_normalization' for c in changes),
        content_or_geometry_changes=sum(c.get('change_type')=='content_or_geometry' for c in changes),
        administrator_entries=len(admin), accuracy=None)
    save(output/'summary.json', summary); jsonl(output/'records.jsonl', records)
    jsonl(output/'pending.jsonl', pending); jsonl(output/'changes.jsonl', changes)
    jsonl(output/'administrator-review.jsonl', list(admin.values()))
    (output/'반복오류_복구검토.html').write_text('<!doctype html><meta charset="utf-8"><title>반복 오류 복구</title>'
        '<style>body{font-family:system-ui;max-width:1100px;margin:auto}pre{white-space:pre-wrap}article{border-top:1px solid #ccc}</style>'
        '<h1>기존 실패 항목 복구</h1><p>형식 정규화와 내용 수정을 구분합니다. 모델 검사는 정답 확정·정확도 측정이 아닙니다.</p><pre>'+
        html.escape(json.dumps(summary, ensure_ascii=False, indent=2))+'</pre>'+''.join(cards), encoding='utf-8')
    return summary


def run(output, env_file, max_calls=60, delay=15):
    if max_calls < 1 or delay < 15: raise ValueError('invalid_limits')
    with (output/'.run.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB); plan = check_plan(output); client = None
        try:
            for task in plan['tasks']:
                path = output/'results'/(task['id']+'.json')
                if path.exists():
                    if read(path)['plan_signature'] != signature(plan): raise ValueError('stale_result')
                    continue
                if client is None: client = Gemini(output/'api-cache', plan['model'], env_file, max_calls=max_calls, delay=delay)
                result = execute(read(task['package']), output, plan, client)
                save(path, result)
                print(json.dumps(dict(task=task['id'], state=result['status'], requests=client.stats['requests']), ensure_ascii=False), flush=True)
        finally:
            save(output/'run-state.json', dict(at=now(), api_stats=client.stats if client else {'requests':0}, summary=report(output)))
    return report(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['prepare','run','report'])
    parser.add_argument('--source', type=Path, default=ROOT/'outputs/ink-continuation-v1')
    parser.add_argument('--output', type=Path, default=OUTPUT)
    parser.add_argument('--env-file', type=Path, default=ROOT/'.env')
    parser.add_argument('--max-api-calls', type=int, default=60)
    parser.add_argument('--delay', type=float, default=15)
    args = parser.parse_args(); output = args.output.resolve()
    if args.mode == 'prepare': result = prepare(args.source, output)
    elif args.mode == 'run': result = run(output, args.env_file, args.max_api_calls, args.delay)
    else: check_plan(output); result = report(output)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__': main()
