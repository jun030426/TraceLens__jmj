"""Offline, item-isolated validation and bounded recovery planning.

Adapters declare representation, never truth. Unknown payloads are retained.
This module neither invokes models nor approves extracted knowledge.
"""
import copy
import math
from collections import Counter

from video_extraction.shared.common import signature

VERSION = 1
MODALITIES = {'text', 'image', 'audio', 'video', 'document', 'table', 'relation'}


def issue(code, category, action, detail=''):
    return {'code': code, 'category': category, 'action': action, 'detail': detail}


def numbers(values, count):
    if not isinstance(values, (list, tuple)) or len(values) != count:
        raise ValueError('invalid_coordinate_shape')
    if any(type(v) not in (int, float) or not math.isfinite(v) for v in values):
        raise ValueError('invalid_coordinate_number')
    return values


def normalize_box(geometry):
    """Return full-source xyxy in [0,1] only from an explicit contract.

    Outside-source values remain outside; no clamping or guessed axis swaps.
    Rotation/polygons require a dedicated adapter instead of lossy flattening.
    """
    if geometry.get('shape') != 'box' or geometry.get('rotation_degrees', 0) != 0:
        raise ValueError('unsupported_geometry')
    coords = geometry['coordinates']
    order = geometry.get('order')
    if order == 'named':
        if not isinstance(coords, dict):
            raise ValueError('invalid_coordinate_shape')
        a, b, c, d = numbers([coords[k] for k in ('left', 'top', 'right', 'bottom')], 4)
    else:
        a, b, c, d = numbers(coords, 4)
        if order == 'yxyx':
            a, b, c, d = b, a, d, c
        elif order == 'xywh':
            c, d = a+c, b+d
        elif order != 'xyxy':
            raise ValueError('unknown_coordinate_order')
    if c <= a or d <= b:
        raise ValueError('inverted_or_empty_box')
    unit = geometry.get('unit')
    if unit == 'fraction':
        w = h = 1
    elif unit == 'normalized_1000':
        w = h = 1000
    elif unit in ('pixel', 'emu'):
        w, h = numbers(geometry['reference_size'], 2)
        if w <= 0 or h <= 0:
            raise ValueError('invalid_reference_size')
    else:
        raise ValueError('unknown_coordinate_unit')
    box = [a/w, b/h, c/w, d/h]
    if geometry.get('reference') == 'crop':
        x1, y1, x2, y2 = numbers(geometry['crop_in_source'], 4)
        if not 0 <= x1 < x2 <= 1 or not 0 <= y1 < y2 <= 1:
            raise ValueError('invalid_crop_transform')
        a, b, c, d = box
        box = [x1+a*(x2-x1), y1+b*(y2-y1), x1+c*(x2-x1), y1+d*(y2-y1)]
    elif geometry.get('reference') != 'source':
        raise ValueError('unknown_coordinate_reference')
    return box


def normalize_time(location):
    start, end = numbers(location['interval'], 2)
    unit = location.get('unit')
    if unit == 'seconds':
        scale = 1
    elif unit == 'milliseconds':
        scale = 1000
    elif unit == 'samples':
        scale = numbers([location['sample_rate']], 1)[0]
        if scale <= 0:
            raise ValueError('invalid_sample_rate')
    else:
        raise ValueError('unknown_time_unit')
    reference = location.get('reference')
    if reference == 'clip':
        offset = numbers([location['clip_start_seconds']], 1)[0]
        if offset < 0:
            raise ValueError('invalid_clip_start')
    elif reference == 'source':
        offset = 0
    else:
        raise ValueError('unknown_time_reference')
    if start < 0 or end < start:
        raise ValueError('invalid_time_interval')
    return [offset+start/scale, offset+end/scale]


def intersects(a, b):
    return min(a[2], b[2]) > max(a[0], b[0]) and min(a[3], b[3]) > max(a[1], b[1])


def inspect_unit(unit, source, adapter, scope=None):
    raw = copy.deepcopy(unit)
    row = {'schema_version': VERSION, 'source_sha256': source, 'adapter': adapter,
           'raw_payload': raw, 'input_signature': signature(raw), 'normalized': {},
           'issues': [], 'correction_candidates': [], 'approved_for_rag': False,
           'judgment': 'unassessed', 'content_verified': False}
    issues = row['issues']
    if not isinstance(unit, dict):
        issues.append(issue('invalid_item_envelope', 'unprocessed', 'adapter_review'))
        return row
    if unit.get('modality') not in MODALITIES:
        issues.append(issue('unsupported_modality', 'unprocessed', 'adapter_review'))
    location = unit.get('location')
    if not isinstance(location, dict):
        issues.append(issue('missing_location_contract', 'unprocessed', 'adapter_review'))
        return row
    if 'geometry' in location:
        geometry = location['geometry']
        try:
            box = normalize_box(geometry)
            row['normalized']['box_source_fraction'] = box
            if any(v < 0 or v > 1 for v in box):
                issues.append(issue('outside_source', 'error', 'coordinate_review'))
            if scope and not intersects(box, scope):
                issues.append(issue('outside_proposal', 'warning', 'boundary_review',
                                    'Proposal boundary is not a content validity boundary.'))
            elif scope and (box[0] < scope[0] or box[1] < scope[1] or box[2] > scope[2] or box[3] > scope[3]):
                issues.append(issue('crosses_proposal', 'warning', 'boundary_review'))
            # A well-formed coordinate is never evidence that the pixels agree.
            issues.append(issue('geometry_evidence_pending', 'pending', 'source_geometry_review'))
            if scope and not intersects(box, scope) and geometry.get('order') in ('xyxy', 'yxyx'):
                alternative = copy.deepcopy(geometry)
                alternative['order'] = 'yxyx' if geometry['order'] == 'xyxy' else 'xyxy'
                swapped = normalize_box(alternative)
                if all(0 <= v <= 1 for v in swapped) and intersects(swapped, scope):
                    row['correction_candidates'].append({'kind': 'axis_order_hypothesis',
                        'box_source_fraction': swapped, 'applied': False,
                        'basis': 'Alternative order intersects proposal; source evidence still required.'})
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            issues.append(issue('geometry_contract_error', 'error', 'coordinate_review', str(exc)))
    if 'time' in location:
        try:
            interval = normalize_time(location['time'])
            row['normalized']['time_source_seconds'] = interval
            duration = location['time'].get('source_duration_seconds')
            if duration is not None:
                duration = numbers([duration], 1)[0]
                if duration < 0 or interval[1] > duration:
                    issues.append(issue('outside_source_time', 'error', 'time_review'))
            issues.append(issue('timing_evidence_pending', 'pending', 'source_time_review'))
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            issues.append(issue('time_contract_error', 'error', 'time_review', str(exc)))
    if unit.get('modality') == 'relation':
        issues.append(issue('semantic_link_pending', 'pending', 'relation_review',
                            'Spatial proximity and temporal overlap do not establish meaning.'))
    if not location and unit.get('modality') in ('image', 'audio', 'video'):
        issues.append(issue('missing_location_contract', 'unprocessed', 'adapter_review'))
    return row


def inspect_batch(units, source, adapter, scope=None):
    """Malformed members and ambiguous IDs affect only their dependent items."""
    if not isinstance(units, list):
        units = [units]
    names = [u.get('id') if isinstance(u, dict) else None for u in units]
    counts = Counter(n for n in names if isinstance(n, str) and n)
    rows = []
    for index, unit in enumerate(units):
        row = inspect_unit(unit, source, adapter, scope)
        name = names[index]
        # Preserve every duplicate occurrence instead of dictionary overwrite.
        valid_name = isinstance(name, str) and bool(name)
        unique = valid_name and counts[name] == 1
        key = ['id', name] if unique else ['occurrence', index]
        row['id'] = source+':'+signature([adapter, *key])
        row['local_id'] = name if valid_name else None
        if not unique:
            row['issues'].append(issue('missing_or_duplicate_id', 'error', 'identity_review'))
        refs = unit.get('references', []) if isinstance(unit, dict) else []
        if not isinstance(refs, list) or any(not isinstance(r, str) for r in refs):
            row['issues'].append(issue('invalid_references', 'error', 'relation_review'))
            refs = []
        row['reference_ids'] = [source+':'+signature([adapter, 'id', r]) for r in refs]
        if any(counts[r] != 1 for r in refs):
            row['issues'].append(issue('missing_or_ambiguous_reference', 'error', 'relation_review'))
        rows.append(row)
    # References to malformed members stay pending; unrelated members continue.
    bad = {r['id'] for r in rows if any(i['category'] in ('error', 'unprocessed') for i in r['issues'])}
    while True:
        extra = {r['id'] for r in rows if set(r['reference_ids']) & bad} - bad
        if not extra:
            break
        bad |= extra
    for row in rows:
        if set(row['reference_ids']) & bad:
            row['issues'].append(issue('dependency_unresolved', 'pending', 'dependency_review'))
        categories = {i['category'] for i in row['issues']}
        row['stage'] = 'unprocessed' if 'unprocessed' in categories else 'checked'
        row['judgment'] = 'held' if categories else 'unassessed'
    return rows


def plan_recovery(rows, history=None, max_items=100, max_attempts=2, api_budget=0, api_actions=()):
    """A deterministic plan only; attempts are supplied by a future executor.

    Attempt keys include payload, adapter and action. Repeating an unchanged
    failure cannot consume unbounded requests. No action is executed here.
    """
    if any(type(v) is not int or v < 0 for v in (max_items, max_attempts, api_budget)):
        raise ValueError('invalid_recovery_limits')
    history = history or {}
    jobs = {}; selected = 0; calls = 0
    for row in rows:
        for action in sorted({i['action'] for i in row['issues']}):
            key = signature({'version': VERSION, 'id': row['id'], 'input': row['input_signature'], 'action': action})
            if key in jobs:
                continue
            attempts = history.get(key, 0)
            if type(attempts) is not int or attempts < 0:
                raise ValueError('invalid_attempt_history')
            cost = int(action in api_actions)
            if attempts >= max_attempts:
                state = 'review_required'
            elif selected >= max_items or calls+cost > api_budget:
                state = 'deferred_budget'
            else:
                state = 'planned'; selected += 1; calls += cost
            jobs[key] = {'id': key, 'item_id': row['id'], 'action': action, 'state': state,
                         'attempts': attempts, 'requires_api': bool(cost), 'executed': False}
    return list(jobs.values())
