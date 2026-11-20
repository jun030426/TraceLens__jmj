"""Offline migration probe for cached ink responses, including rejected ones.

Never imports or calls an API client instance. Preserves the frozen old run.
"""
from video_extraction._layout import PROJECT_ROOT, source_path
import argparse
import json
from collections import Counter
from pathlib import Path

from video_extraction.shared.common import digest_file, read, save, signature, now
from video_extraction.shared.gemini import SYSTEM
from video_extraction.ink.recognition.ink_marks import freeze_check, INVENTORY_PROMPT, INVENTORY, safe_path
from video_extraction.shared.recovery import inspect_batch, plan_recovery

ROOT = PROJECT_ROOT


def adapt_inventory(value):
    units = []
    if not isinstance(value, dict):
        return [value]
    for collection in ('marks', 'targets', 'relations'):
        members = value.get(collection, [])
        if not isinstance(members, list):
            units.append({'id': collection, 'modality': 'unknown', 'location': {}, 'raw': members})
            continue
        for member in members:
            if not isinstance(member, dict):
                units.append(member); continue
            local = member.get('id')
            unit = {'id': collection+':'+local if isinstance(local, str) else None,
                    'modality': 'relation' if collection == 'relations' else 'image',
                    'kind': member.get('kind', collection), 'raw': member, 'location': {}}
            if collection != 'relations':
                unit['location']['geometry'] = {'shape': 'box', 'coordinates': member.get('bbox'),
                    'order': 'xyxy', 'unit': 'normalized_1000', 'reference': 'source',
                    'contract_basis': 'old_prompt_requested_xyxy_not_verified_model_compliance'}
            else:
                refs = []
                for field, prefix in [('mark_ids', 'marks'), ('from_target_ids', 'targets'), ('to_target_ids', 'targets')]:
                    values = member.get(field, [])
                    if not isinstance(values, list) or any(not isinstance(v, str) for v in values):
                        refs = None; break
                    refs += [prefix+':'+v for v in values]
                unit['references'] = refs
            units.append(unit)
    return units


def replay(source, output):
    source, output = Path(source).resolve(), Path(output).resolve()
    if output.exists():
        raise ValueError('output_exists_choose_new_directory')
    plan = freeze_check(source)
    rows = []; tasks = []; hashes = {str(source/'plan.json'): digest_file(source/'plan.json')}
    for task in plan['tasks']:
        stage = 'ink_marks_v1_inventory_'+task['id']
        images = [Path(task[k]) for k in ('before_image', 'current_image', 'after_image')]
        images += [safe_path(source, task['crop'])]
        scope = {k: task[k] for k in ('id', 'bbox', 'anchor_candidates', 'onset_interval_seconds')}
        prompt = INVENTORY_PROMPT+json.dumps(scope, ensure_ascii=False)
        key = signature({'version': 2, 'model': plan['model'], 'system': SYSTEM, 'stage': stage,
                         'images': [digest_file(p) for p in images], 'prompt': prompt, 'schema': INVENTORY})
        path = source/'api-cache'/(key+'.json')
        if path.exists():
            cached = read(path)
            if cached.get('signature') != key or cached.get('stage') != stage:
                raise ValueError('cache_provenance_mismatch')
            raw = cached['parsed']; hashes[str(path)] = digest_file(path)
            units = adapt_inventory(raw)
        else:
            raw = None
            units = [{'id': 'missing_response', 'modality': 'unknown', 'location': {}, 'raw': None}]
        batch = inspect_batch(units, task['source_sha256'], 'ink-v1:'+task['id'],
                              scope=[v/1000 for v in task['bbox']])
        for row in batch:
            row['task_id'] = task['id']
        rows += batch
        tasks.append({'task_id': task['id'], 'raw_response': raw, 'record_count': len(batch),
                      'source_cache': str(path), 'missing_response': raw is None})
    jobs = plan_recovery(rows, max_items=100, max_attempts=2, api_budget=0)
    summary = {'created_at': now(), 'tasks': len(tasks), 'retained_items': len(rows),
               'items_with_errors': sum(any(i['category'] == 'error' for i in r['issues']) for r in rows),
               'items_without_structural_errors': sum(not any(i['category'] in ('error','unprocessed') for i in r['issues']) for r in rows),
               'items_outside_proposal': sum(any(i['code'] == 'outside_proposal' for i in r['issues']) for r in rows),
               'axis_order_candidates': sum(len(r['correction_candidates']) for r in rows),
               'queue': dict(Counter(j['state'] for j in jobs)), 'api_requests': 0,
               'approved': 0, 'accuracy': None,
               'note': 'Structural retention only, not recovered truth. Geometry and semantic links require source evidence. No fixes applied and no old result statuses changed.'}
    output.mkdir(parents=True)
    save(output/'records.json', rows); save(output/'tasks.json', tasks)
    save(output/'recovery-queue.json', jobs); save(output/'summary.json', summary)
    save(output/'provenance.json', {'input_hashes': hashes, 'code_hashes': {
        name: digest_file(source_path(name)) for name in ('recovery.py', 'recovery_replay.py')},
        'source_run': str(source), 'api_requests': 0})
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT/'outputs/ink-marks-v1')
    parser.add_argument('--output', type=Path, default=ROOT/'outputs/recovery-replay-v1')
    args = parser.parse_args()
    print(json.dumps(replay(args.source, args.output), ensure_ascii=False))
