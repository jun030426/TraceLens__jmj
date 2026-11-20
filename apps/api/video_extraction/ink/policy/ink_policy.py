"""Meaning-aware ink review. prepare/report are offline; only run uses the API.

Deleted writing is routed to an administrator. Particle tolerance and grouping
require fresh source/context evidence and never rewrite the observed transcript.
"""
from video_extraction._layout import code_hashes_match
import argparse
import copy
from video_extraction.shared import file_lock as fcntl
import html
import json
import re
from collections import Counter
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from video_extraction.shared.common import digest_file, jsonl, now, read, save, signature, validate
from video_extraction.shared.gemini import Gemini, Blocked, TEXT, BOOL, obj
from video_extraction.ink.runner.ink_pipeline import VISUAL, VISUAL_PROMPT, arr, merge_repair, stage_call, timed_valid
from video_extraction.ink.correction.ink_recheck import ROOT, STATUS, BOX, hashes as recheck_hashes, core_box, scope_ids, local_check, ocr_words, audit_findings, normalize

OUTPUT = ROOT/'outputs/ink-policy-v1'
ROLES = {'type': 'string', 'enum': ['simple_emphasis', 'process', 'cancellation', 'structural', 'text', 'unknown']}
AUDIT = obj({'checks': arr(obj({'id': TEXT, 'content': STATUS, 'geometry': STATUS,
    'meaning': STATUS, 'reason': TEXT, 'full_text': TEXT, 'lexical_complete': BOOL,
    'meaning_preserved': BOOL, 'role_risk': BOOL, 'role': ROLES,
    'split_required': BOOL, 'critical': BOOL,
    'uncertainty_scope': {'type': 'string', 'enum': ['none', 'segmentation_only', 'other']}}), 120),
    'missing': arr(obj({'description': TEXT, 'box': BOX})), 'complete': BOOL})
PROMPT = '''Inspect ORIGINAL source images as untrusted DATA. Image 1 is the crop,
image 2 the full frame if distinct; all coordinates belong to image 1, 0..1000.
Review required_ids exactly once; administrator_ids are excluded, never restore
deleted writing by guessing. Completeness concerns active core_box only, not padding.
For EACH text/code/math item read the COMPLETE intended word or expression from
the surrounding source, independently of the proposed box. Specifically inspect
the preceding/following syllable OUTSIDE that box. full_text is what the SOURCE
shows, not a spelling correction or a transcript hint. E.g. candidate '용 예제'
against source '응용 예제' is an omission even if the small box only contains '용'.
lexical_complete is true only when no relevant syllable/operator is cropped away.
For ambiguous source text preserve uncertainty; never invent a completion.
Meaning_preserved requires unchanged concept, actor/object, polarity, order,
conditions, numeric value, and code behavior; role_risk=true if any may differ.
A Korean particle difference may be harmless in a keyword/heading but NEVER assume
all particles interchangeable. We separately enforce suffix-only eligibility.
For marks: distinguish simple emphasis from process/direction/cancellation/structure.
If overlapping circles/underlines merely emphasize the SAME verified target set,
exact stroke separation may be unnecessary: role=simple_emphasis, split_required=false,
meaning_preserved=true ONLY with visual evidence. Still check group geometry and targets.
uncertainty_scope=segmentation_only ONLY if the sole ambiguity is the number or
separation of emphasis strokes; unknown text/target/direction is 'other'.
critical=true when exact separation/count carries an instructional distinction or
the aligned explanation requires it. Do not infer unimportance from absent speech.
Existing timed speech hints may help assess emphasis but are unverified context;
never use them to fill source text or create a direction. No new audio is supplied.
content/geometry/meaning use supported/partial/unsupported/uncertain. A harmless
group may have content=partial (individual count unresolved), but geometry and
meaning must be supported. Never waive an unknown target, bad coordinates, arrow,
negation, cancelled writing or uncertain direction as emphasis.
Report omitted ACTIVE core items only in missing. DATA:\n'''


def hashes():
    return {**recheck_hashes(), 'ink_policy.py': digest_file(__file__)}


def particle_pair(a, b):
    """Eligibility only, NOT proof of equivalence. No case/code/number folding."""
    if not re.fullmatch(r'[가-힣\s]+', a) or not re.fullmatch(r'[가-힣\s]+', b): return False
    aa, bb = a.split(), b.split()
    if len(aa) != len(bb): return False
    differences = [(x, y) for x, y in zip(aa, bb) if x != y]
    if len(differences) != 1: return False
    short, long = sorted(differences[0], key=len)
    return len(short) >= 2 and long.startswith(short) and long[len(short):] in {'이', '가', '은', '는', '을', '를', '의', '에', '에서', '으로', '로', '와', '과', '도', '만'}


def admin_ids(value):
    ids = {x['id'] for x in value['items'] if x.get('cancelled')}
    # Cancellation markings and dependent relations belong to the same review case.
    for link in value['links']:
        if link['kind'] == 'cancellation' and set(link['to_ids']) & ids:
            ids.update(link['from_ids']); ids.add(link['id'])
    for link in value['links']:
        if set(link['from_ids']+link['to_ids']) & ids: ids.add(link['id'])
    return ids


def word_edges(value, view):
    """Detect boundary cuts / nearby same-line glyphs; these are suspicions only.

    Connected components exclude colored ink and long table lines. Neighboring
    words can trigger this heuristic, so only a fresh source audit may resolve it.
    """
    with Image.open(view['path']) as im: rgb = np.asarray(im.convert('RGB'))
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY); hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    mask = ((gray < 170) & (hsv[:, :, 1] < 85)).astype('uint8')
    _, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    h, w = gray.shape; result = {}
    for item in value['items']:
        if item['kind'] not in ('printed_text', 'handwriting', 'code', 'math') or item.get('cancelled'): continue
        b = item['box']; x1, y1, x2, y2 = [b[k]/1000*s for k, s in zip(('left', 'top', 'right', 'bottom'), (w, h, w, h))]
        height = y2-y1
        if height <= 0: continue
        codes = set()
        for x, y, cw, ch, area in stats[1:]:
            if area < 3 or ch < max(2, height*.15) or ch > height*1.6 or cw > height*3: continue
            if min(y+ch, y2)-max(y, y1) < min(ch, height)*.45: continue
            if x < x1 < x+cw or x < x2 < x+cw: codes.add('text_stroke_crosses_box')
            if 0 <= x1-(x+cw) <= height*.85 or 0 <= x-x2 <= height*.85:
                codes.add('adjacent_glyph_requires_word_review')
        if codes: result[item['id']] = sorted(codes)
    return result


def speech_hints(package, value):
    known = {x['id'] for x in value['items']}; interval = package['task']['audio_interval']
    return [b for b in package.get('audio_context', {}).get('bindings', [])
            if b.get('relevance') == 'aligned' and b.get('quote', '').strip()
            and set(b.get('item_ids', [])) <= known and b.get('item_ids') and timed_valid(b, interval)]


def assessment(package, value, audit=None):
    task, view = package['task'], package['view']
    rows, local, required = local_check(value, task, view, package['ocr'], package['ocr_coverage'])
    admin = admin_ids(value); active = required-admin; edges = word_edges(value, view)
    checks = {}; bad = {}; missing = []; ignored = []; contract = False
    if audit is not None:
        validate(audit, AUDIT)
        slim = {'checks': [{k: c[k] for k in ('id', 'content', 'geometry', 'meaning', 'reason')} for c in audit['checks']],
                'missing': audit['missing'], 'complete': audit['complete']}
        bad, missing, ignored, contract = audit_findings(slim, value, active, core_box(task, view))
        checks = {c['id']: c for c in audit['checks']}
    by_id = {x['id']: x for x in value['items']+value['links']}
    for iid, f in local.items():
        f['warnings'] += edges.get(iid, [])
        f['scope'] = 'administrator' if iid in admin else ('required' if iid in active else 'context')
        if iid not in active: continue
        if audit is None:
            f['unprocessed'].append('fresh_policy_audit_required'); continue
        f['blocking'] += bad.get(iid, [])
        c = checks.get(iid); item = by_id[iid]
        if not c or not contract: continue
        safe_meaning = c['meaning'] == 'supported' and c['geometry'] == 'supported' and c['meaning_preserved'] and not c['role_risk']
        if item.get('kind') in ('printed_text', 'handwriting', 'code', 'math'):
            # New common route: only fresh exact source support may settle an
            # OCR-only complaint. Geometry, missing words, roles and uncertainty
            # retain their own blocking checks; historical runs keep old policy.
            if (task.get('ocr_policy')=='selective_auxiliary_v1' and safe_meaning
                and c['content']=='supported' and c['lexical_complete']
                and c['full_text'].strip() and normalize(c['full_text'])==normalize(item['text'])
                and c['uncertainty_scope']=='none'):
                f['ocr_support_policy']='selective_auxiliary_v1'
                for field in ('blocking','unprocessed'):
                    ocr_only=[x for x in f[field] if x.startswith('ocr_')]
                    f[field]=[x for x in f[field] if x not in ocr_only]
                    f['warnings']+=['auxiliary_'+x for x in ocr_only]
            if not c['lexical_complete'] or not c['full_text'].strip():
                f['blocking'].append('whole_word_source_review_unresolved')
            elif normalize(c['full_text']) == normalize(item['text']) and c['content'] == 'supported':
                f['resolved_boundary_checks'] = edges.get(iid, [])
                f['warnings'] = [v for v in f['warnings'] if v not in edges.get(iid, [])]
            elif normalize(c['full_text']) != normalize(item['text']):
                if item['kind'] in ('printed_text', 'handwriting') and safe_meaning and particle_pair(item['text'], c['full_text']) and c['content'] in ('supported', 'partial'):
                    f['blocking'] = [v for v in f['blocking'] if v != 'source_content_partial']
                    f['warnings'].append('meaning_preserving_particle_omission')
                else: f['blocking'].append('partial_word_or_expression_omission')
            if 'ocr_text_conflict' in f['blocking'] and item['kind'] in ('printed_text', 'handwriting') and safe_meaning and c['lexical_complete'] and c['content'] in ('supported', 'partial'):
                words, partial = ocr_words(package['ocr'].get('words', []), item, view)
                observed = ' '.join(w['text'] for w in words)
                if words and not partial and particle_pair(item['text'], observed):
                    f['blocking'].remove('ocr_text_conflict'); f['warnings'].append('meaning_preserving_particle_ocr_difference')
        else:
            links = [x for x in value['links'] if iid in x['from_ids']+x['to_ids']]
            simple_shape = item.get('kind') in ('circle', 'underline', 'bracket') and not item.get('arrow_points') and bool(links)
            simple_link = (iid in {x['id'] for x in value['links']} and item.get('kind') == 'emphasis'
                and item.get('direction') == 'not_applicable' and bool(item['from_ids'])
                and all(by_id.get(i, {}).get('kind') in ('circle', 'underline', 'bracket')
                        and not by_id[i].get('arrow_points') for i in item['from_ids']))
            relations_safe = all(x['kind'] == 'emphasis' and x['direction'] == 'not_applicable' for x in links)
            if (simple_shape or simple_link) and relations_safe and safe_meaning and c['role'] == 'simple_emphasis' and not c['split_required'] and not c['critical'] and c['content'] in ('supported', 'partial'):
                f['blocking'] = [v for v in f['blocking'] if v != 'source_content_partial']
                if c['uncertainty_scope'] == 'segmentation_only':
                    f['blocking'] = [v for v in f['blocking'] if v != 'unclear_item']
                f['warnings'].append('simple_emphasis_group_accepted')
                f['representation'] = 'emphasis_region' if simple_shape else 'emphasis_relation'
    return rows, local, active, admin, checks, missing, ignored, contract


def apply_policy(package, value, audit):
    rows, local, active, admin, checks, missing, ignored, contract = assessment(package, value, audit)
    accepted = {i for i in active if contract and not local[i]['blocking']}
    for link in value['links']:
        if link['id'] in accepted and not set(link['from_ids']+link['to_ids']) <= accepted:
            accepted.remove(link['id']); local[link['id']]['blocking'].append('dependency_unresolved')
    effective = copy.deepcopy(package['base']); changes = []; decisions = []; administrator = []
    for group in ('items', 'links'):
        old = {x['id']: x for x in effective[group]}
        for item in value[group]:
            iid = item['id']; f = local[iid]; changed = item != old.get(iid)
            if iid in accepted and changed:
                effective[group] = [copy.deepcopy(item) if x['id'] == iid else x for x in effective[group]]
                if iid not in old: effective[group].append(copy.deepcopy(item))
                changes.append({'id': iid, 'before': old.get(iid), 'after': item, 'basis': 'fresh_source_and_meaning_policy_audit'})
            state = ('administrator_review' if iid in admin else
                     ('usable_with_warning' if f['warnings'] else 'model_source_checked') if iid in accepted else
                     'held' if iid in active else 'context_only')
            decisions.append({'id': iid, 'status': state, 'applied': iid in accepted and changed,
                              'reasons': f['blocking'], 'warnings': f['warnings'], 'unprocessed': f['unprocessed'],
                              'representation': f.get('representation', 'literal_observation')})
            if iid in admin:
                administrator.append({'id': package['task']['id']+':'+iid, 'task_id': package['task']['id'],
                    'local_id': iid, 'status': 'administrator_review', 'reason': 'cancelled_writing_or_dependent_mark',
                    'item': item, 'source_image': package['task']['evidence']['selected_frame'],
                    'crop_image': package['view']['path'], 'crop_in_source': package['view']['crop_in_source'],
                    'time_seconds': package['task']['evidence'].get('selected_frame_seconds'),
                    'onset_interval_seconds': package['task'].get('onset_interval_seconds'),
                    'usable_as_active_knowledge': False, 'interpretation': 'provisional_cancellation_requires_administrator'})
    records = []
    for row in rows:
        iid = row['local_id']
        if iid not in accepted: continue
        row.update(judgment='usable_with_warning' if local[iid]['warnings'] else 'model_source_checked',
            approved_for_rag=False, content_verified=False, policy_findings=local[iid],
            verification={'method': 'source_and_context_model_audit', 'gold_approved': False},
            source_complete_text_candidate=checks[iid]['full_text'],
            representation=local[iid].get('representation', 'literal_observation'),
            selected_frame=package['task']['evidence']['selected_frame'],
            selected_frame_seconds=package['task']['evidence'].get('selected_frame_seconds'))
        row['issues'] = [i for i in row['issues'] if i['code'] != 'geometry_evidence_pending']
        records.append(row)
    active_complete = contract and audit['complete'] and not missing and active <= accepted
    effective['complete'] = bool(active_complete and not admin)
    return {'effective_inventory': effective, 'candidate': value, 'decisions': decisions,
        'changes': changes, 'records': records, 'administrator_queue': administrator,
        'missing_core': missing, 'missing_context': ignored, 'active_coverage_complete': bool(active_complete),
        'all_review_resolved': bool(active_complete and not admin), 'audit_contract_valid': contract,
        'status': 'active_checked' if active_complete else 'partially_checked',
        'accuracy': None, 'gold_approved': False}


def execute(package, output, plan, client):
    task = package['task']; value = package['candidate']; view = package['view']
    media = list(dict.fromkeys([Path(view['path']), Path(task['evidence']['selected_frame'])]))
    def audit(candidate, stage):
        admin = admin_ids(candidate); active = scope_ids(candidate, core_box(task, view))-admin
        payload = {'candidate': candidate, 'required_ids': sorted(active), 'administrator_ids': sorted(admin),
            'core_box': core_box(task, view), 'boundary_suspicions': word_edges(candidate, view),
            'timed_speech_hints': speech_hints(package, candidate)}
        if not active: return {'checks': [], 'missing': [], 'complete': True}
        return stage_call(task, output, plan, client, stage, media, PROMPT+json.dumps(payload, ensure_ascii=False), AUDIT)
    first = audit(value, 'meaning_source_audit'); final = first; repaired = False
    _, local, active, admin, _, missing, _, contract = assessment(package, value, first)
    requested = {i for i in active if local[i]['blocking']}
    if missing or not first['complete']: requested.add('__scope__')
    if requested and contract:
        patch = stage_call(task, output, plan, client, 'whole_word_targeted_repair', media,
            VISUAL_PROMPT+json.dumps({'candidate': value, 'repair_only_ids': sorted(requested),
                'administrator_ids': sorted(admin), 'core_box': core_box(task, view), 'audit': first,
                'instruction': 'Preserve admin and all unaffected IDs. Correct partial words by reading surrounding SOURCE pixels, '
                'including preceding syllables outside old boxes. Do not infer missing text from speech. '
                'Do not split simple emphasis merely to count strokes. Preserve uncertainties. No deletion.'}, ensure_ascii=False), VISUAL)
        value = merge_repair(value, patch, requested)
        final = audit(value, 'final_meaning_source_audit'); repaired = True
    result = apply_policy(package, value, final)
    result.update(task_id=task['id'], plan_signature=signature(plan), candidate_signature=signature(value),
                  final_audit=final, initial_audit=first, repair_used=repaired, final_view=view)
    return result


def prepare(source, output):
    source = source.resolve(); output = output.resolve()
    if output.exists(): raise ValueError('output_exists_choose_new_folder')
    previous = read(source/'plan.json'); inputs = {str(source/'plan.json'): digest_file(source/'plan.json')}
    for path, expected in previous['input_hashes'].items():
        if digest_file(path) != expected: raise ValueError('changed_source:'+path)
        inputs[path] = expected
    output.mkdir(parents=True); tasks = []
    for entry in previous['tasks']:
        package = read(entry['package']); dest = source/'results'/(entry['id']+'.json'); result = read(dest)
        if result['plan_signature'] != signature(previous): raise ValueError('stale_source_result')
        inputs[str(dest)] = digest_file(dest)
        package = copy.deepcopy(package)
        package['base'] = result['effective_inventory']; package['candidate'] = result['candidate']
        validate(package['base'], VISUAL); validate(package['candidate'], VISUAL)
        _, local, active, admin, *_ = assessment(package, package['candidate'])
        package['local_findings'] = local; package['required_ids'] = sorted(active)
        # Queue cancelled items immediately, without a network request.
        package['administrator_ids'] = sorted(admin)
        path = output/'prepared'/(entry['id']+'.json'); save(path, package)
        inputs[str(path)] = digest_file(path); tasks.append({'id': entry['id'], 'package': str(path)})
    plan = {'version': 1, 'created_at': now(), 'source': str(source), 'model': previous['model'],
        'tasks': tasks, 'input_hashes': inputs, 'code_hashes': hashes(),
        'normal_logical_calls': len(tasks), 'max_logical_calls': 3*len(tasks),
        'policy': 'administrator cancellation; source/context-gated particle tolerance; emphasis regions; complete-word source review'}
    save(output/'plan.json', plan); return report(output)


def check_plan(output):
    plan = read(output/'plan.json')
    if not code_hashes_match(plan['code_hashes'], hashes()): raise ValueError('code_changed_prepare_new_output')
    for path, expected in plan['input_hashes'].items():
        if digest_file(path) != expected: raise ValueError('changed_input:'+path)
    return plan


def report(output):
    plan = read(output/'plan.json'); results = []; cards = []; records = []; queue = []; pending = []
    e = html.escape
    labels = {'administrator_review': '관리자 검토', 'usable_with_warning': '경고와 함께 사용 가능',
        'model_source_checked': '원본 검사 통과', 'held': '보류', 'context_only': '주변 참고', 'awaiting_source_audit': '원본 검사 대기'}
    for entry in plan['tasks']:
        p = read(entry['package']); path = output/'results'/(entry['id']+'.json')
        r = read(path) if path.exists() else None
        if r:
            results.append(r); records += r.get('records', []); queue += r.get('administrator_queue', [])
            decisions = r.get('decisions', [])
            pending += [{'task_id': entry['id'], **d} for d in decisions if d['status'] == 'held']
            pending += [{'task_id': entry['id'], 'status': 'missing_core', **m} for m in r.get('missing_core', [])]
            if not r.get('active_coverage_complete'): pending.append({'task_id': entry['id'], 'status': 'active_coverage_unresolved'})
        else:
            provisional = apply_policy(p, p['candidate'], {'checks': [], 'missing': [], 'complete': False})
            queue += provisional['administrator_queue']
            decisions = [{**d, 'status': 'awaiting_source_audit' if d['status'] == 'held' else d['status']} for d in provisional['decisions']]
            pending.append({'task_id': entry['id'], 'status': 'awaiting_source_audit'})
        display = (r or p).get('candidate', p['candidate']); items = {x['id']: x for x in display['items']+display['links']}
        rows = ''.join('<tr><td>'+e(d['id'])+'</td><td>'+e(items.get(d['id'], {}).get('text', ''))+'</td><td>'+e(labels.get(d['status'], d['status']))+'</td><td>'+e(', '.join(d.get('warnings', [])+d.get('reasons', [])))+'</td></tr>' for d in decisions)
        cards.append('<article><h2>'+e(entry['id'])+'</h2><img src="'+e(Path(p['view']['path']).as_uri(), quote=True)+'">'
            '<table><tr><th>항목</th><th>관찰된 내용</th><th>처리</th><th>근거</th></tr>'+rows+'</table>'
            '<details><summary>수정 전후·문맥 판정·검사 근거</summary><pre>'+e(json.dumps(r or p, ensure_ascii=False, indent=2))+'</pre></details></article>')
    summary = {'prepared': len(plan['tasks']), 'processed': len(results),
        'changed_items_applied': sum(len(r.get('changes', [])) for r in results),
        'usable_records': len(records), 'usable_with_warning': sum(r['judgment']=='usable_with_warning' for r in records),
        'administrator_entries': len(queue), 'administrator_tasks': len({x['task_id'] for x in queue}),
        'active_complete_tasks': sum(r.get('active_coverage_complete', False) for r in results),
        'pending_entries': len(pending), 'accuracy': None, 'gold_approved': False}
    jsonl(output/'records.jsonl', records); jsonl(output/'administrator-review.jsonl', queue); jsonl(output/'pending.jsonl', pending)
    save(output/'summary.json', summary)
    (output/'필기정책_검토.html').write_text('<!doctype html><meta charset="utf-8"><title>필기 처리 기준 검토</title>'
        '<style>body{font-family:system-ui;max-width:1100px;margin:30px auto}article{padding:20px 0;border-bottom:1px solid #ccc}img{max-width:100%}pre{white-space:pre-wrap;overflow-wrap:anywhere}td,th{border:1px solid #ddd;padding:8px}table{border-collapse:collapse}</style>'
        '<h1>필기 처리 기준: 관리자 검토 · 경고 · 수정</h1><p>지워진 필기는 관리자 검토로 보존하며 정상 내용의 진행을 막지 않습니다. '
        '조사 차이는 의미 유지가 확인된 경우만 허용합니다. 단순 강조는 영역으로 보존하고 정확한 획 수를 주장하지 않습니다. '
        '원문과 OCR은 덮어쓰지 않습니다. API 실행 전에는 문맥 판정·내용 수정이 완료된 것이 아닙니다.</p>'
        '<p>처리 '+str(len(results))+'/'+str(len(plan['tasks']))+' · 새 반영 '+str(summary['changed_items_applied'])+' · 관리자 항목 '+str(len(queue))+'</p>'+''.join(cards), encoding='utf-8')
    return summary


def run(output, env_file, max_calls=72, delay=15):
    if max_calls < 1 or delay < 15: raise ValueError('invalid_limits')
    with (output/'.run.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB); plan = check_plan(output); client = None
        try:
            for entry in plan['tasks']:
                dest = output/'results'/(entry['id']+'.json')
                if dest.exists():
                    if read(dest)['plan_signature'] != signature(plan): raise ValueError('stale_result')
                    continue
                p = read(entry['package'])
                if p['required_ids'] and client is None: client = Gemini(output/'api-cache', plan['model'], env_file, max_calls=max_calls, delay=delay)
                try: result = execute(p, output, plan, client)
                except Blocked as exc:
                    if str(exc) != 'invalid_model_response': raise
                    result = apply_policy(p, p['candidate'], {'checks': [], 'missing': [], 'complete': False})
                    result.update(task_id=entry['id'], plan_signature=signature(plan), error=str(exc))
                save(dest, result)
                print(json.dumps({'task': entry['id'], 'status': result['status'], 'applied_changes': len(result['changes']),
                    'administrator_entries': len(result['administrator_queue']), 'requests': client.stats['requests'] if client else 0}, ensure_ascii=False), flush=True)
        finally:
            save(output/'run-state.json', {'at': now(), 'api_stats': client.stats if client else {'requests': 0}, 'summary': report(output)})
    return report(output)


def main():
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('mode', choices=['prepare', 'run', 'report'])
    p.add_argument('--source', type=Path, default=ROOT/'outputs/ink-recheck-v1'); p.add_argument('--output', type=Path, default=OUTPUT)
    p.add_argument('--env-file', type=Path, default=ROOT/'.env'); p.add_argument('--max-api-calls', type=int, default=72)
    p.add_argument('--delay', type=float, default=15); a = p.parse_args(); out = a.output.resolve()
    if a.mode == 'prepare': result = prepare(a.source, out)
    elif a.mode == 'run': result = run(out, a.env_file, a.max_api_calls, a.delay)
    else: check_plan(out); result = report(out)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__': main()
