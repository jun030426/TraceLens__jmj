"""Offline adapters for existing extraction outputs; never invokes a model.

Raw tool payloads remain immutable. Normalization is representational, not a
correction, content verification, course assignment, or permission to publish.
"""
from video_extraction._layout import PROJECT_ROOT, source_path
import argparse
import copy
import json
import math
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from video_extraction.shared.common import digest_file, jsonl, now, read, save, signature

ROOT = PROJECT_ROOT
VERSION = 1


def normalize_text(text, kind):
    if text is None:
        return None, []
    if not isinstance(text, str):
        raise ValueError('text_must_be_string')
    # Code/math can contain significant Unicode sequences and whitespace.
    if kind in {'code', 'math', 'table_cell', 'unclassified'}:
        return text, []
    value = text.replace('\r\n', '\n').replace('\r', '\n')
    value = unicodedata.normalize('NFC', value)
    return value, ['nfc_and_line_endings'] if value != text else []


def normalize_table(rows):
    """Keep null/empty/zero/leading zeros distinct; never infer column types."""
    if not isinstance(rows, list) or any(not isinstance(r, list) for r in rows):
        raise ValueError('table_requires_rows')
    for row in rows:
        for cell in row:
            if cell is not None and type(cell) not in (str, bool, int, float):
                raise ValueError('unsupported_table_cell')
            if isinstance(cell, float) and not math.isfinite(cell):
                raise ValueError('non_finite_cell')
    return copy.deepcopy(rows)


def checked(path, expected):
    if not Path(path).is_file() or digest_file(path) != expected:
        raise ValueError('input_missing_or_changed: ' + str(path))


def resolve_sources(entries, search_root=None):
    """Relink moved originals only by SHA256; filenames are merely candidates."""
    files = sorted(p for p in Path(search_root).rglob('*') if p.is_file()) if search_root else []
    result = []
    cache = {}
    for entry in entries:
        old = Path(entry['original_path'])
        candidates = [old] if old.is_file() else []
        candidates += [p for p in files if p != old and (
            unicodedata.normalize('NFC', p.name) == unicodedata.normalize('NFC', old.name)
            or (entry.get('bytes') is not None and p.stat().st_size == entry['bytes']))]
        matched = None
        for p in candidates:
            if p not in cache:
                cache[p] = digest_file(p)
            if cache[p] == entry['sha256']:
                matched = str(p.resolve())
                break
        result.append({**entry, 'resolved_path': matched,
                       'availability': 'hash_verified' if matched else 'missing_original'})
    return result


def record(source, local_id, modality, kind, raw, text=None, location=None,
           parent=None, findings=None, holds=None, extracted=True, checked_locally=False):
    normalized, operations = normalize_text(text, kind)
    holds = copy.deepcopy(holds or [])
    findings = copy.deepcopy(findings or [])
    candidates = [copy.deepcopy(h['context_candidate']) for h in holds if 'context_candidate' in h]
    for c in candidates:
        c.update(applied=False, status='candidate_only')
    uncertain = bool(holds or findings or (raw or {}).get('uncertainties'))
    return {
        'schema_version': VERSION, 'id': source + ':' + local_id,
        'source_sha256': source, 'parent_id': parent, 'modality': modality,
        'kind': kind, 'location': copy.deepcopy(location or {}),
        'raw_payload': copy.deepcopy(raw), 'observed_text': text,
        'normalized_text': normalized, 'normalization_operations': operations,
        'correction_candidates': candidates, 'findings': findings, 'holds': holds,
        'stage': 'not_extracted' if not extracted else ('checked' if checked_locally else 'extracted'),
        'judgment': 'held' if uncertain else 'unassessed',
        'checks': [{'scope': 'imported_local_checks_only', 'status': 'findings_present' if findings else 'no_findings'}]
                  if checked_locally else [],
        'offering_id': None, 'concept_ids': [], 'educational_role': None,
        'importance': {'score': None, 'basis': None, 'status': 'not_assessed'},
        'approved_for_rag': False,
    }


def target_id(row):
    hold = row.get('original_hold', row)
    return row.get('target_id') or hold.get('target_id') or hold.get('region', {}).get('target_id')


def adapt_frame(source, frame, result, findings, image_path=None):
    fid = frame['id']
    parent_id = source + ':' + fid
    loc = {'frame_id': fid, 'time_seconds': frame['time_seconds'], 'image_path': image_path or frame['path']}
    parent = record(source, fid, 'video_frame', 'frame',
                    {'frame': frame, 'extraction': result}, location=loc,
                    findings=findings, holds=(result or {}).get('holds'),
                    extracted=result is not None, checked_locally=True)
    rows = [parent]
    if result is None:
        return rows
    for layer, blocks in [('text', result.get('final_blocks', [])), ('visual', result.get('visuals', []))]:
        for block in blocks:
            bid = block['id']
            holds = [h for h in result.get('holds', []) if target_id(h) == bid]
            fs = [f for f in findings if target_id(f) == bid]
            text = block.get('literal_text') if layer == 'visual' else block.get('text')
            row = record(source, fid + ':' + layer + ':' + bid,
                         'image' if layer == 'visual' else 'screen_text', block['kind'], block, text,
                         {**loc, 'bbox': block['bbox'], 'coordinate_system': 'xyxy_0_1000'},
                         parent_id, fs, holds, checked_locally=True)
            # Descriptions are model/reviewer interpretation, not literal image text.
            if layer == 'visual':
                row['interpretation'] = block.get('description', '')
            row['scoped_adjudications'] = [copy.deepcopy(x) for x in
                result.get('source_coordinate_review', {}).get('decisions', []) if x['target_id'] == bid]
            row['related_block_ids'] = block.get('related_block_ids', [])
            rows.append(row)
    return rows


def adapt_speech(source, segment, findings):
    row = record(source, segment['id'], 'audio', 'speech', segment, segment['text'],
                 {'start_seconds': segment['start_seconds'], 'end_seconds': segment['end_seconds']},
                 findings=findings, checked_locally=True)
    if segment.get('review_reasons'):
        row['judgment'] = 'held'
    return row


def adapt_slide(source, slide, asset_root=None):
    sid = slide['id']
    loc = {'slide_number': slide['slide_number'], 'source_file': slide['source_file']}
    parent = record(source, sid, 'document', 'slide', slide, location=loc)
    # Existing role is provenance from the importer, not an AI classification.
    parent['educational_role'] = slide.get('role')
    rows = [parent]
    for b in slide['blocks']:
        # Native PPT text may contain code: preserve it verbatim until typed.
        kind = 'table' if b['kind'] == 'table' else 'unclassified'
        row = record(source, sid + ':shape:' + str(b['shape_id']), 'document', kind, b,
                     b.get('raw_text', b.get('text')), {**loc, 'bbox': b['bbox_emu'],
                     'coordinate_system': 'left_top_width_height_emu'}, parent['id'])
        if 'rows' in b:
            row['normalized_rows'] = normalize_table(b['rows'])
            row['column_schema_status'] = 'not_declared_no_type_coercion'
        rows.append(row)
    for a in slide.get('assets', []):
        rows.append(record(source, sid + ':asset:' + str(a['shape_id']), 'image', 'embedded_image', a,
                           location={**loc, 'image_path': str((Path(asset_root)/a['path']).resolve()) if asset_root else a['path'], 'bbox': a['bbox_emu'],
                                     'coordinate_system': 'left_top_width_height_emu'},
                           parent=parent['id'], extracted=False))
    if slide.get('notes'):
        rows.append(record(source, sid + ':notes', 'document', 'unclassified', {'text': slide['notes']},
                           slide['notes'], loc, parent['id']))
    for row in rows:
        row['educational_role'] = slide.get('role')
    return rows


def route(category, reasons):
    if category == 'no_baseline_extraction':
        return ['screen_extraction'], 4, 'not_extracted'
    if category == 'audio_review':
        methods = []
        if set(reasons) & {'asr_chunk_boundary', 'overlapping_transcript_intervals'}:
            methods.append('alignment_poc_then_source_listening')
        if set(reasons) - {'asr_chunk_boundary', 'overlapping_transcript_intervals'}:
            methods.append('source_listening')
        return methods, 2, 'source_review'
    if category == 'zero_o_unresolved':
        return ['source_crop', 'independent_ocr_comparison'], 2, 'source_review'
    return ['source_region_review'], 2, 'budget' if category == 'budget_region' else 'source_review'


def build_queue(source, grouped, warnings, created_at, previous=None):
    tasks = []
    previous = {t['id']: t for t in (previous or [])}

    def add(category, anchor, records, target, stage='checked'):
        reasons = sorted({r.get('reason', category) for r in records})
        methods, cost, wait = route(category, reasons)
        tid = signature({'source': source, 'category': category, 'anchor': anchor})
        fingerprint = signature(records)
        old = previous.get(tid, {})
        first = old.get('first_seen_at', created_at) if old.get('input_signature') == fingerprint else created_at
        tasks.append({'id': tid, 'source_sha256': source, 'category': category, 'target': target,
                      'input_signature': fingerprint, 'evidence_records': records,
                      'first_seen_at': first, 'last_seen_at': created_at,
                      'stage': stage, 'judgment': 'unassessed' if stage == 'not_extracted' else 'held',
                      'work_status': 'queued', 'waiting_reason': wait,
                      'methods': methods, 'estimated_effort_units': cost,
                      'importance_score': None,
                      'risk_score': 1.0 if category == 'zero_o_unresolved' else .8 if category == 'audio_review' else .6})

    for g in grouped:
        target = {'frame_id': g['frame_id'], 'target_id': g.get('target_id')}
        if g['category'] == 'budget_summary':
            for region in g['remaining_regions']:
                add('budget_region', [g['frame_id'], region['region']], [region],
                    {**target, 'region': region['region']}, stage='extracted')
        else:
            regions = sorted({signature(r.get('original_hold', r).get('region', {}).get('bbox'))
                              for r in g['records']}) if g.get('target_id') == 'NEW' else []
            add(g['category'], [g['frame_id'], g.get('target_id'), regions],
                g['records'], target, stage='not_extracted' if g['category'] == 'no_baseline_extraction' else 'checked')
    by_segment = defaultdict(list)
    for w in warnings:
        ids = w.get('segment_ids', []) + ([w['segment_id']] if w.get('segment_id') else [])
        for sid in set(ids):
            by_segment[sid].append(w)
    for sid, rows in sorted(by_segment.items()):
        add('audio_review', sid, rows, {'segment_id': sid})
    if len({t['id'] for t in tasks}) != len(tasks):
        raise ValueError('duplicate_task_ids')
    return tasks


def plan_batch(tasks, budget, max_items, at):
    """Planning only. Every fifth slot prioritizes oldest affordable work."""
    if budget < 0 or max_items < 0:
        raise ValueError('negative_budget')
    clock = datetime.fromisoformat(at)
    waiting = copy.deepcopy(tasks)
    for t in waiting:
        if not math.isfinite(t['estimated_effort_units']) or t['estimated_effort_units'] <= 0:
            raise ValueError('invalid_effort_estimate')
        age = max(0, (clock - datetime.fromisoformat(t['first_seen_at'])).total_seconds() / 86400)
        t['priority_score'] = round(3*t['risk_score'] + min(age, 30)/10 + (t['importance_score'] or 0), 4)
    chosen = []
    spent = 0
    while len(chosen) < max_items:
        affordable = [t for t in waiting if t['estimated_effort_units'] <= budget-spent]
        if not affordable:
            break
        if len(chosen) % 5 == 0:
            item = min(affordable, key=lambda t: (t['first_seen_at'], t['id']))
            reason = 'oldest_affordable_fairness_slot'
        else:
            item = min(affordable, key=lambda t: (-t['priority_score'], t['id']))
            reason = 'risk_age_importance'
        waiting.remove(item)
        spent += item['estimated_effort_units']
        chosen.append({**item, 'selection_reason': reason, 'execution_status': 'not_started'})
    return {'budget_effort_units': budget, 'planned_effort_units': spent, 'selected': chosen,
            'deferred': [{'task_id': t['id'], 'status': 'DEFERRED_BUDGET',
                          'reason': 'exceeds_batch_budget' if t['estimated_effort_units'] > budget else 'batch_capacity'}
                         for t in waiting], 'api_requests': 0,
            'note': 'Effort units are planning weights, not API request/token estimates. No tasks executed.'}


def validate_records(records):
    ids = {r['id'] for r in records}
    if len(ids) != len(records):
        raise ValueError('duplicate_record_ids')
    for row in records:
        if row['parent_id'] and row['parent_id'] not in ids:
            raise ValueError('missing_parent_record')
        if any(c['applied'] for c in row['correction_candidates']):
            raise ValueError('candidate_was_applied')
        loc = row['location']
        if 'start_seconds' in loc:
            a, b = loc['start_seconds'], loc['end_seconds']
            if not all(math.isfinite(x) for x in (a, b)) or not 0 <= a <= b:
                raise ValueError('invalid_time_interval')
        if loc.get('coordinate_system') == 'xyxy_0_1000':
            x1, y1, x2, y2 = loc['bbox']
            if not 0 <= x1 < x2 <= 1000 or not 0 <= y1 < y2 <= 1000:
                raise ValueError('invalid_normalized_bbox')


def build(output, source_root=None, previous=None, budget=40, max_items=20):
    validation = ROOT/'outputs/multimodal-validation'
    overlay = ROOT/'outputs/annotation-duplicate-review'
    review_path = ROOT/'outputs/multimodal-checks-annotations/review.json'
    pending_path = ROOT/'outputs/pending-reconciliation-annotations/review.json'
    slides_root = ROOT/'outputs/extraction-repair'
    output = Path(output).resolve()
    if output.exists():
        raise ValueError('output_exists_choose_new_directory')
    plan = read(validation/'plan.json')
    job = Path(plan['settings']['job'])
    protected_roots = [validation, overlay, review_path.parent, pending_path.parent, slides_root,
                       job, ROOT/'sources', *map(Path, plan['settings']['overrides'])]
    if source_root:
        protected_roots.append(Path(source_root).resolve())
    if previous:
        protected_roots.append(Path(previous).resolve())
    for p in protected_roots:
        if output == p or output in p.parents or p in output.parents:
            raise ValueError('output_overlaps_inputs')
    protected = {}

    def track(p, expected=None):
        p = Path(p).resolve()
        h = digest_file(p)
        if expected is not None and h != expected:
            raise ValueError('input_changed: ' + str(p))
        protected[str(p)] = h
        return p

    entries = read(track(slides_root/'manifest.json'))
    state = read(job/'state.json')
    if state['source_sha256'] not in {e['sha256'] for e in entries}:
        entries.append({'source_id': 'video', 'original_path': state['source_path'], 'sha256': state['source_sha256']})
    sources = resolve_sources(entries, source_root)
    moved = {s['original_path']: s['resolved_path'] for s in sources}
    missing = []
    for name, h in plan['input_hashes'].items():
        resolved = moved.get(name) or name
        if not Path(resolved).is_file() and name in moved:
            missing.append(name)
        else:
            track(resolved, h)
    for s in sources:
        if s['resolved_path']:
            track(s['resolved_path'], s['sha256'])
    track(validation/'plan.json')
    local = read(track(validation/'local-checks.json'))
    if signature(local) != plan['local_checks_signature']:
        raise ValueError('local_checks_changed')
    report = read(track(review_path))
    pending = read(track(pending_path))
    manifest = read(track(overlay/'manifest.json'))
    if report['source_plan_signature'] != signature(plan) or manifest['source_plan_signature'] != signature(plan):
        raise ValueError('plan_binding_changed')
    if report['coordinate_review']['manifest_sha256'] != digest_file(overlay/'manifest.json'):
        raise ValueError('review_overlay_changed')
    pending_hashes = {str((ROOT/Path(p)).resolve()): h for p, h in pending['input_sha256'].items()}
    if pending_hashes.get(str(review_path)) != digest_file(review_path):
        raise ValueError('pending_review_changed')
    for p, h in pending_hashes.items():
        track(p, h)
    frames = read(job/'frames.json')
    speech = read(job/'asr.json')['segments']
    by_frame, by_speech = defaultdict(list), defaultdict(list)
    for f in report['findings']:
        if f.get('frame_id'):
            by_frame[f['frame_id']].append(f)
        for sid in set(f.get('segment_ids', []) + ([f['segment_id']] if f.get('segment_id') else [])):
            by_speech[sid].append(f)
    roots = [Path(p) for p in plan['settings']['overrides']] + [job]
    records = []
    source = state['source_sha256']
    for frame in frames:
        image = (job/frame['path']).resolve()
        result = None
        for root in roots:
            candidate = root/'vision'/frame['id']/'result.json'
            if str(candidate) not in plan['input_hashes']:
                continue
            result = read(candidate)
            entry = manifest['results'].get(frame['id'])
            if entry:
                if entry['baseline'] != str(candidate) or entry['baseline_sha256'] != digest_file(candidate):
                    raise ValueError('overlay_baseline_changed')
                checked(image, entry['image_sha256'])
                result = read(track(overlay/'vision'/frame['id']/'result.json', entry['result_sha256']))
            break
        records.extend(adapt_frame(source, frame, result, by_frame[frame['id']], str(image)))
    records.extend(adapt_speech(source, s, by_speech[s['id']]) for s in speech)
    slide_manifest = {s['source_id']: s for s in sources}
    for line in track(slides_root/'slides.jsonl').read_text().splitlines():
        slide = json.loads(line)
        for asset in slide.get('assets', []):
            track(slides_root/asset['path'], asset['sha256'])
        records.extend(adapt_slide(slide_manifest[slide['source_id']]['sha256'], slide, slides_root))
    validate_records(records)
    previous_tasks = None
    if previous:
        previous_tasks = read(track(Path(previous)/'review-queue.json'))['tasks']
    created = now()
    tasks = build_queue(source, pending['groups'], report['groups']['warning'], created, previous_tasks)
    batch = plan_batch(tasks, budget, max_items, created)
    # Copy snapshots, not mutate the extraction outputs or the RAG corpus.
    output.mkdir(parents=True, exist_ok=False)
    save(output/'source-registry.json', {'sources': sources, 'missing_originals': missing})
    jsonl(output/'records.jsonl', records)
    save(output/'review-queue.json', {'version': VERSION, 'tasks': tasks,
         'unselected_api_units_audit_only': report['unselected_api_units'],
         'scope': 'Existing video findings; imported PPT assets still require independent triage.'})
    save(output/'next-batch.json', batch)
    save(output/'evaluation-inputs.json', {'source_sha256': source,
         'frames': [{**f, 'path': str((job/f['path']).resolve())} for f in frames],
         'speech': speech, 'audio_path': str(track(job/'audio-original.wav')),
         'audio_offset_seconds': plan['metadata']['audio_offset_seconds'],
         'duration_seconds': plan['metadata']['duration_seconds'],
         'original_video': moved.get(state['source_path'])})
    summary = {'version': VERSION, 'created_at': created, 'api_requests': 0,
        'record_counts': dict(Counter(r['modality'] for r in records)),
        'total_records': len(records), 'missing_screen_extractions': sum(r['modality']=='video_frame' and r['stage']=='not_extracted' for r in records),
        'queue_counts': dict(Counter(t['category'] for t in tasks)), 'queued_tasks': len(tasks),
        'planned_tasks': len(batch['selected']), 'deferred_tasks': len(batch['deferred']),
        'normalized_text_changes': sum(bool(r['normalization_operations']) for r in records),
        'context_candidates': sum(len(r['correction_candidates']) for r in records),
        'verified_original_files': sum(s['availability']=='hash_verified' for s in sources),
        'missing_original_files': sum(s['availability']=='missing_original' for s in sources),
        'accuracy': None, 'approved_for_rag': False,
        'limits': ['Native document content is not automatically classified as code/text.',
                   'No OCR, ASR, Gemini, alignment or content review is executed by these adapters.',
                   'Table dates/units/types are preserved; no domain schema has been declared.',
                   'Inspection coverage is separate from semantic correctness.']}
    save(output/'summary.json', summary)
    for p, h in protected.items():
        checked(p, h)
    save(output/'manifest.json', {'version': VERSION, 'created_at': created, 'input_sha256': protected,
         'implementation_sha256': digest_file(__file__),
         'output_sha256': {p.name: digest_file(p) for p in sorted(output.iterdir()) if p.is_file()}})
    return summary


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--source-root', type=Path)
    p.add_argument('--previous', type=Path)
    p.add_argument('--budget', type=int, default=40)
    p.add_argument('--max-items', type=int, default=20)
    a = p.parse_args()
    print(json.dumps(build(a.output, a.source_root, a.previous, a.budget, a.max_items), ensure_ascii=False))


if __name__ == '__main__':
    main()
