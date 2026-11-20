"""Scoped source re-audit and versioned application of existing ink candidates.

prepare/report are offline. Only run constructs an API client. Never consumes
gold labels, modifies the source run, or promotes model agreement to gold truth.
"""
from video_extraction._layout import code_hashes_match
import argparse
import copy
from video_extraction.shared import file_lock as fcntl
import html
import json
import math
import re
from collections import Counter
from pathlib import Path
from PIL import Image

from video_extraction.shared.common import digest_file, jsonl, now, read, save, signature, validate
from video_extraction.shared.gemini import Gemini, Blocked, TEXT, BOOL, obj
from video_extraction.ink.runner.ink_pipeline import ROOT, BOX, VISUAL, VISUAL_PROMPT, arr, code_hashes, inspect_visual, merge_repair, transform_visual, transform_ocr, stage_call
from video_extraction.ink.recognition.ink_evidence import box_pixels

OUTPUT = ROOT / 'outputs/ink-recheck-v1'
TEXT_KINDS = {'handwriting', 'math', 'printed_text', 'code'}
STATUS = {'type': 'string', 'enum': ['supported', 'partial', 'unsupported', 'uncertain']}
AUDIT = obj({'checks': arr(obj({'id': TEXT, 'content': STATUS, 'geometry': STATUS,
    'meaning': STATUS, 'reason': TEXT}), 120),
    'missing': arr(obj({'description': TEXT, 'box': BOX})), 'complete': BOOL})
AUDIT_PROMPT = '''Verify the candidate against untrusted ORIGINAL image evidence.
Image 1 is the candidate crop; ALL coordinates are normalized 0..1000 in image 1.
Image 2 is the full source frame at the SAME timestamp, for context only.
Image 3, when present, is the original requested frame at another timestamp.
Do NOT transfer new marks from another timestamp. The output belongs to image 1/2.
The required_ids are the review scope: core intersecting items and their direct
relation dependencies. Other context items are retained, not completeness targets.
Check EACH required ID exactly once: content (literal transcription/visible mark),
geometry (actual box/endpoints), meaning (relation target/direction/cancellation).
For text, meaning includes whether cancellation is actually visible. Do not treat
a handwriting stroke as a strike-through without visual evidence. For marks with
no literal text, content means correct mark type. Do not infer unclear glyphs from
context or speech. Ambiguous 0/o stays uncertain. 'supported' needs source evidence.
Scan independently for omitted instructional marks or referred text intersecting
core_box, but do not enumerate unrelated padding, partial peripheral table labels,
or marks outside core_box. A mark crossing core_box remains in scope. Missing boxes
use image 1 coordinates. complete concerns the CORE ONLY, not the entire image.
No audio/gold is provided. DATA:\n'''


def hashes():
    return {**code_hashes(), 'ink_recheck.py': digest_file(__file__)}


def box_list(box):
    return [box[k] for k in ('left', 'top', 'right', 'bottom')]


def overlap(a, b):
    return max(0, min(a[2], b[2])-max(a[0], b[0])) * max(0, min(a[3], b[3])-max(a[1], b[1]))


def core_box(task, view):
    value = {'items': [{'box': dict(zip(('left', 'top', 'right', 'bottom'), task['bbox'])), 'arrow_points': []}]}
    return transform_visual(value, {'crop_in_source': [0, 0, 1, 1]}, view)['items'][0]['box']


def scope_ids(value, core):
    """Crossing marks stay in scope; directly connected text may lie in padding."""
    required = {x['id'] for x in value['items'] if overlap(box_list(x['box']), box_list(core)) > 0}
    core_ids = set(required)
    # One hop only: context cannot recursively expand to a whole slide.
    for link in value['links']:
        refs = set(link['from_ids'] + link['to_ids'])
        if refs & core_ids:
            required.add(link['id']); required.update(refs)
    return required


def normalize(text):
    # Keep case/operators: O/o and variable case are meaningful in source code.
    return re.sub(r'\s+', '', text)


def ocr_words(words, item, view):
    w, h = view['size']; b = box_list(item['box']); found = []
    partial = False
    for word in words:
        a, y, c, d = word['bbox_pixels']; rect = [a/w*1000, y/h*1000, c/w*1000, d/h*1000]
        area = max(0, rect[2]-rect[0])*max(0, rect[3]-rect[1])
        ratio = overlap(b, rect)/max(area, 1e-9)
        if ratio >= .8:
            found.append(word)
        elif ratio > 0:
            partial = True
    return found, partial


def ocr_findings(item, view, receipt, coverage):
    result = {'blocking': [], 'warnings': [], 'unprocessed': []}
    if item['kind'] not in TEXT_KINDS or not item['text'].strip():
        return result
    if receipt.get('state') != 'candidate':
        result['unprocessed'].append('ocr_unavailable'); return result
    box = box_list(item['box']); area = (box[2]-box[0])*(box[3]-box[1])
    if overlap(box, box_list(coverage)) < area * .98:
        result['unprocessed'].append('ocr_outside_scanned_area'); return result
    words, partial = ocr_words(receipt.get('words', []), item, view)
    if not words:
        result['unprocessed'].append('ocr_partial_word_coverage' if partial else 'ocr_no_detection')
        return result
    text = normalize(' '.join(w['text'] for w in words))
    low = any(w['score'] < .65 for w in words)
    if low: result['warnings'].append('ocr_low_confidence')
    if normalize(item['text']) not in text:
        if low or partial: result['warnings'].append('ocr_not_comparable')
        else: result['blocking'].append('ocr_text_conflict')
    # Compare the SAME item's coverage, not the crop's concatenated transcript.
    if 'alternative_words' in receipt:
        other, other_partial = ocr_words(receipt['alternative_words'], item, view)
        if other and not partial and not other_partial and not low and all(w['score'] >= .65 for w in other):
            alt = normalize(' '.join(w['text'] for w in other))
            if alt != text: result['warnings'].append('ocr_item_variant_difference')
    return result


def load_ocr(source, task, view):
    original = task['evidence']['views']['original']
    receipt = {'state': 'unavailable', 'words': []}
    for name in ('original', 'contrast'):
        path = source/'ocr'/(task['id']+'-'+name+'.json')
        if not path.exists(): continue
        row = read(path)
        if row.get('image_sha256') != digest_file(task['evidence']['views'][name]['path']):
            continue
        moved = transform_ocr(row, original, view)
        if name == 'original': receipt = moved
        elif row.get('state') == 'candidate': receipt['alternative_words'] = moved['words']
    # OCR only saw the smaller original crop, even when boxes are transformed.
    coverage = transform_visual({'items': [{'box': dict(left=0, top=0, right=1000, bottom=1000),
        'arrow_points': []}]}, original, view)['items'][0]['box']
    return receipt, coverage


def recheck_view(task, old_view, folder):
    """Add source pixels for boundary repair without expanding the task's core.

    Use exactly the chosen frame, not a temporal composite or an enlarged bitmap.
    All existing item/arrow coordinates are transformed separately by the caller.
    """
    with Image.open(task['evidence']['selected_frame']) as image:
        w, h = image.size
        a, b, c, d = old_view['crop_in_source']
        dx = max(24/w, (c-a)*.5); dy = max(24/h, (d-b)*.5)
        rect = [max(0, math.floor((a-dx)*w)), max(0, math.floor((b-dy)*h)),
                min(w, math.ceil((c+dx)*w)), min(h, math.ceil((d+dy)*h))]
        folder.mkdir(parents=True, exist_ok=True); path = folder/'source-context.png'
        image.crop(tuple(rect)).save(path)
    x, y, z, t = rect
    return {'path': str(path.resolve()), 'size': [z-x, t-y],
            'crop_in_source': [x/w, y/h, z/w, t/h], 'operation': 'source_crop_only',
            'eligible': True, 'core_unchanged': True}


def local_check(value, task, view, receipt, coverage):
    rows, legacy = inspect_visual(value, task, view, {'state': 'unavailable', 'words': []})
    required = scope_ids(value, core_box(task, view)); findings = {}
    for x in value['items'] + value['links']:
        iid = x['id']
        f = {'blocking': [v for v in legacy.get(iid, []) if not v.startswith('ocr_') and v != 'dependency_unresolved'],
             'warnings': [], 'unprocessed': []}
        if x in value['items']:
            o = ocr_findings(x, view, receipt, coverage)
            for key in f: f[key] += o[key]
            if x.get('cancelled') and not x.get('text'):
                f['blocking'] = [v for v in f['blocking'] if v != 'empty_text']
                f['warnings'].append('cancelled_text_unreadable_preserved')
            if any(x['box'][k] <= 1 for k in ('left', 'top')) or any(x['box'][k] >= 999 for k in ('right', 'bottom')):
                if iid in required: f['blocking'].append('required_item_touches_crop_boundary')
                else: f['warnings'].append('context_crop_boundary')
        f['scope'] = 'required' if iid in required else 'context'
        findings[iid] = f
    # Do not add a second copy of the same observed mark under a new ID.
    for n, item in enumerate(value['items']):
        for other in value['items'][:n]:
            if item['kind'] != other['kind'] or item['text'] != other['text']: continue
            a, b = box_list(item['box']), box_list(other['box'])
            intersection = overlap(a, b)
            union = (a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-intersection
            if union > 0 and intersection/union >= .9:
                findings[item['id']]['blocking'].append('possible_duplicate_item')
                findings[other['id']]['blocking'].append('possible_duplicate_item')
    return rows, findings, required


def audit_findings(audit, value, required, core):
    validate(audit, AUDIT)
    counts = Counter(c['id'] for c in audit['checks'])
    # A malformed or incomplete ID contract never authorizes partial application.
    contract = set(counts) == required and all(n == 1 for n in counts.values())
    bad = {}
    for iid in required:
        check = next((c for c in audit['checks'] if c['id'] == iid), None)
        if not contract: bad[iid] = ['audit_id_contract_invalid']
        elif any(check[k] != 'supported' for k in ('content', 'geometry', 'meaning')):
            bad[iid] = ['source_'+k+'_'+check[k] for k in ('content', 'geometry', 'meaning') if check[k] != 'supported']
    missing = []; context_missing = []; invalid = False
    for entry in audit['missing']:
        try: box_pixels(entry['box'], [1000, 1000])
        except ValueError: invalid = True; continue
        (missing if overlap(box_list(entry['box']), box_list(core)) else context_missing).append(entry)
    return bad, missing, context_missing, contract and not invalid


def apply_checked(base, candidate, task, view, receipt, coverage, audit):
    rows, local, required = local_check(candidate, task, view, receipt, coverage)
    bad, missing, context_missing, contract = audit_findings(audit, candidate, required, core_box(task, view))
    entities = candidate['items'] + candidate['links']
    reasons = {x['id']: local[x['id']]['blocking'] + bad.get(x['id'], []) for x in entities}
    accepted = {iid for iid in required if iid in reasons and not reasons[iid] and contract}
    # No dangling or unreviewed relation endpoints; unrelated siblings survive.
    for link in candidate['links']:
        if link['id'] in accepted and not set(link['from_ids']+link['to_ids']) <= accepted:
            accepted.remove(link['id']); reasons[link['id']].append('dependency_unresolved')
    effective = copy.deepcopy(base); changes = []; decisions = []
    for group in ('items', 'links'):
        old = {x['id']: x for x in base[group]}
        for x in candidate[group]:
            iid = x['id']; applied = iid in accepted
            changed = iid not in old or x != old[iid]
            if applied and changed:
                effective[group] = [copy.deepcopy(x) if v['id'] == iid else v for v in effective[group]]
                if iid not in old: effective[group].append(copy.deepcopy(x))
                changes.append({'id': iid, 'before': old.get(iid), 'after': x,
                                'basis': 'local_checks_and_fresh_source_audit'})
            decisions.append({'id': iid, 'scope': local[iid]['scope'],
                'status': 'model_source_checked' if applied else ('context_only' if iid not in required else 'held'),
                'applied': applied and changed, 'reasons': reasons[iid],
                'warnings': local[iid]['warnings'], 'unprocessed': local[iid]['unprocessed']})
    complete = contract and audit['complete'] and not missing and required <= accepted
    effective['complete'] = bool(complete)
    records = []
    for row in rows:
        if row['local_id'] not in accepted: continue
        row.update(judgment='model_source_checked', content_verified=False, approved_for_rag=False,
                   verification={'method': 'local_checks_and_model_source_audit', 'gold_approved': False},
                   selected_frame=task['evidence']['selected_frame'],
                   selected_frame_seconds=task['evidence'].get('selected_frame_seconds'),
                   local_findings=local[row['local_id']])
        row['issues'] = [i for i in row['issues'] if i['code'] != 'geometry_evidence_pending']
        records.append(row)
    return {'effective_inventory': effective, 'decisions': decisions, 'changes': changes,
        'records': records, 'missing_core': missing, 'missing_context': context_missing,
        'coverage_complete': bool(complete), 'status': 'checked' if complete else 'partially_checked',
        'audit_contract_valid': contract, 'applied': bool(changes), 'gold_approved': False, 'accuracy': None}


def prepare(source, output):
    source = source.resolve(); output = output.resolve()
    if output.exists(): raise ValueError('output_exists_choose_new_folder')
    old = read(source/'plan.json')
    inputs = {str(source/'plan.json'): digest_file(source/'plan.json')}
    # Verify old frozen media without requiring today's module version to match.
    for path, expected in old['input_hashes'].items():
        if digest_file(path) != expected: raise ValueError('changed_source:'+path)
        inputs[path] = expected
    output.mkdir(parents=True); tasks = []
    for task in old['tasks']:
        path = source/'results'/(task['id']+'.json')
        if not path.exists(): raise ValueError('source_result_missing:'+task['id'])
        result = read(path)
        if result.get('plan_signature') != signature(old): raise ValueError('source_plan_mismatch')
        inputs[str(path)] = digest_file(path)
        base = result['inventory']; candidate = base
        for repair in result.get('repairs', []):
            if 'proposed' in repair: candidate = repair['proposed']
        validate(candidate, VISUAL); validate(base, VISUAL)
        original_view = result['final_view']
        view = recheck_view(task, original_view, output/'evidence'/task['id'])
        base = transform_visual(base, original_view, view)
        candidate = transform_visual(candidate, original_view, view)
        for p in (view['path'], original_view['path'], task['evidence']['views']['original']['path'],
                  task['evidence']['views']['contrast']['path'], task['evidence']['selected_frame'], task['current_image']):
            inputs[p] = digest_file(p)
        for p in (source/'ocr').glob(task['id']+'-*.json'): inputs[str(p)] = digest_file(p)
        receipt, coverage = load_ocr(source, task, view)
        _, findings, required = local_check(candidate, task, view, receipt, coverage)
        package = {'task': task, 'view': view, 'base': base, 'candidate': candidate,
            'original_view': original_view, 'coordinate_transform': 'source_equivalent_no_semantic_change',
            'ocr': receipt, 'ocr_coverage': coverage, 'local_findings': findings,
            'required_ids': sorted(required), 'old_flags': result.get('flags', {}),
            'audio_context': result.get('audio_context', {}), 'audio_status': 'retained_candidate_not_applied'}
        dest = output/'prepared'/(task['id']+'.json'); save(dest, package)
        inputs[str(dest)] = digest_file(dest); tasks.append({'id': task['id'], 'package': str(dest)})
    plan = {'version': 1, 'created_at': now(), 'model': old['model'], 'source': str(source),
        'tasks': tasks, 'input_hashes': inputs, 'code_hashes': hashes(),
        'normal_logical_calls': len(tasks), 'max_logical_calls': 3*len(tasks),
        'policy': 'one source audit; at most one targeted repair then mandatory source re-audit; versioned partial application'}
    save(output/'plan.json', plan)
    return report(output)


def check_plan(output):
    plan = read(output/'plan.json')
    if not code_hashes_match(plan['code_hashes'], hashes()): raise ValueError('code_changed_prepare_new_output')
    for path, expected in plan['input_hashes'].items():
        if digest_file(path) != expected: raise ValueError('changed_input:'+path)
    return plan


def execute(package, output, plan, client):
    task = package['task']; view = package['view']; core = core_box(task, view)
    candidate = package['candidate']; receipt = package['ocr']; coverage = package['ocr_coverage']
    media = list(dict.fromkeys([Path(view['path']), Path(task['evidence']['selected_frame']), Path(task['current_image'])]))
    def audit(value, name):
        required = scope_ids(value, core)
        payload = {'core_box': core, 'required_ids': sorted(required), 'candidate': value,
                   'selected_frame_seconds': task['evidence'].get('selected_frame_seconds')}
        return stage_call(task, output, plan, client, name, media,
                          AUDIT_PROMPT+json.dumps(payload, ensure_ascii=False), AUDIT)
    initial = audit(candidate, 'source_reaudit'); final = initial; repair_used = False
    _, local, required = local_check(candidate, task, view, receipt, coverage)
    bad, missing, _, contract = audit_findings(initial, candidate, required, core)
    requested = {i for i in required if local.get(i, {}).get('blocking') or i in bad}
    if missing or not initial['complete']: requested.add('__scope__')
    if requested and contract:
        patch = stage_call(task, output, plan, client, 'targeted_repair', media,
            VISUAL_PROMPT+json.dumps({'candidate': candidate, 'repair_only_ids': sorted(requested),
                'core_box': core, 'audit': initial, 'local_findings': local,
                'instruction': 'Only image 1 coordinates. Repair requested IDs; retain all other IDs. '
                'Add only core missing items and necessary relation targets. No peripheral inventory. '
                'Use full source image to check meaning; never infer from audio. Preserve ambiguity.'}, ensure_ascii=False), VISUAL)
        candidate = merge_repair(candidate, patch, requested)
        # Mandatory: repaired content cannot inherit an audit of older content.
        final = audit(candidate, 'final_source_reaudit'); repair_used = True
    result = apply_checked(package['base'], candidate, task, view, receipt, coverage, final)
    result.update(task_id=task['id'], plan_signature=signature(plan), candidate=candidate,
        candidate_signature=signature(candidate), final_audit=final, initial_audit=initial,
        repair_used=repair_used, final_view=view, audio_context=package['audio_context'],
        audio_status='retained_candidate_not_applied')
    return result


def report(output):
    plan = read(output/'plan.json'); results = []; cards = []; records = []; pending = []
    counts = Counter(); e = html.escape
    for task in plan['tasks']:
        package = read(task['package']); dest = output/'results'/(task['id']+'.json')
        result = read(dest) if dest.exists() else None
        if result:
            results.append(result); records += result.get('records', [])
            decisions = result.get('decisions', [])
            pending += [{'task_id': task['id'], **d} for d in decisions if d['status'] == 'held']
            pending += [{'task_id': task['id'], 'status': 'missing_core', **m} for m in result.get('missing_core', [])]
            if not result.get('coverage_complete'): pending.append({'task_id': task['id'], 'status': 'coverage_unresolved'})
        else:
            decisions = [{'id': iid, 'status': 'source_reaudit_pending', **f} for iid, f in package['local_findings'].items()]
            pending.append({'task_id': task['id'], 'status': 'source_reaudit_pending'})
        for f in package['local_findings'].values():
            for category in ('blocking', 'warnings', 'unprocessed'):
                for code in f[category]: counts[category+':'+code] += 1
        changes = (result or {}).get('changes', [])
        rows = ''.join('<tr><td>'+e(d['id'])+'</td><td>'+e(d['status'])+'</td><td>'+e(', '.join(d.get('reasons', d.get('blocking', []))+d.get('warnings', [])+d.get('unprocessed', [])))+'</td></tr>' for d in decisions)
        before_after = ''.join('<li>'+e(c['id'])+'<pre>'+e(json.dumps({'수정 전': c['before'], '반영 후': c['after']}, ensure_ascii=False, indent=2))+'</pre></li>' for c in changes)
        cards.append('<article><h2>'+e(task['id'])+'</h2><img src="'+e(Path(package['view']['path']).as_uri(), quote=True)+'">'
            '<p>원본 재검사 '+('완료' if result and 'final_audit' in result else '대기')+' · 반영 변경 '+str(len(changes))+'개</p>'
            '<table><tr><th>항목</th><th>상태</th><th>검사 내역</th></tr>'+rows+'</table><ul>'+before_after+'</ul>'
            '<details><summary>후보·원본 좌표·검사 근거</summary><pre>'+e(json.dumps(result or package, ensure_ascii=False, indent=2))+'</pre></details></article>')
    summary = {'prepared': len(plan['tasks']), 'processed': len(results),
        'changed_items_applied': sum(len(r.get('changes', [])) for r in results),
        'checked_records': len(records), 'coverage_complete_tasks': sum(r.get('coverage_complete', False) for r in results),
        'pending_entries': len(pending), 'local_finding_counts': dict(sorted(counts.items())),
        'normal_logical_calls': plan['normal_logical_calls'], 'max_logical_calls': plan['max_logical_calls'],
        'accuracy': None, 'gold_approved': False, 'approved_for_rag': False}
    save(output/'summary.json', summary); jsonl(output/'records.jsonl', records); jsonl(output/'pending.jsonl', pending)
    (output/'필기수정_재검사.html').write_text('<!doctype html><meta charset="utf-8"><title>필기 수정 재검사</title>'
        '<style>body{font-family:system-ui;max-width:1100px;margin:30px auto}article{padding:20px 0;border-bottom:1px solid #ccc}img{max-width:100%}pre{white-space:pre-wrap;overflow-wrap:anywhere}td,th{border:1px solid #ddd;padding:8px}table{border-collapse:collapse}</style>'
        '<h1>필기 수정 후보 → 원본 재검사 → 결과 반영</h1><p>기존 결과와 정답지는 보존합니다. 반영은 새 데이터 버전에만 적용합니다. 모델 검사를 통과해도 정답·정확도 확정은 아닙니다. 음성 연결은 별도 후보로 유지합니다.</p>'
        '<p>처리 '+str(len(results))+'/'+str(len(plan['tasks']))+' · 실제 반영 변경 '+str(summary['changed_items_applied'])+'개</p>'+''.join(cards), encoding='utf-8')
    return summary


def run(output, env_file, max_calls=72, delay=15):
    if max_calls < 1 or delay < 15: raise ValueError('invalid_limits')
    with (output/'.run.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        plan = check_plan(output); client = None
        try:
            for task in plan['tasks']:
                dest = output/'results'/(task['id']+'.json')
                if dest.exists():
                    if read(dest)['plan_signature'] != signature(plan): raise ValueError('stale_result')
                    continue
                if client is None: client = Gemini(output/'api-cache', plan['model'], env_file, max_calls=max_calls, delay=delay)
                try: result = execute(read(task['package']), output, plan, client)
                except Blocked as exc:
                    if str(exc) != 'invalid_model_response': raise
                    result = {'task_id': task['id'], 'plan_signature': signature(plan), 'status': 'held',
                        'error': str(exc), 'coverage_complete': False, 'changes': [], 'records': [], 'decisions': []}
                save(dest, result)
                print(json.dumps({'task': task['id'], 'status': result['status'], 'applied_changes': len(result['changes']), 'requests': client.stats['requests']}, ensure_ascii=False), flush=True)
        finally:
            save(output/'run-state.json', {'at': now(), 'api_stats': client.stats if client else {'requests': 0}, 'summary': report(output)})
    return report(output)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('mode', choices=['prepare', 'run', 'report'])
    p.add_argument('--source', type=Path, default=ROOT/'outputs/ink-pipeline-v2')
    p.add_argument('--output', type=Path, default=OUTPUT)
    p.add_argument('--env-file', type=Path, default=ROOT/'.env')
    p.add_argument('--max-api-calls', type=int, default=72); p.add_argument('--delay', type=float, default=15)
    a = p.parse_args(); out = a.output.resolve()
    if a.mode == 'prepare': result = prepare(a.source, out)
    elif a.mode == 'run': result = run(out, a.env_file, a.max_api_calls, a.delay)
    else: check_plan(out); result = report(out)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__': main()
