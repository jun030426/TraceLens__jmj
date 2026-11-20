"""Offline, conservative counting of horizontal dash glyphs in inspected native ROIs.

Run after layer_followup to persist pixel evidence and rebuild its derived report.
No API client is created. The original API receipts and source results stay intact.
"""
import argparse
import copy
from video_extraction.shared import file_lock as fcntl
from pathlib import Path
import shutil
from statistics import median

from PIL import Image

from video_extraction.shared.common import digest_file, now, read, save, signature

# Pixel coordinates, exclusive right/bottom edges. Includes white margins and
# excludes quotes, brackets and adjacent text. Bound to inspected image hashes
# in layer_followup; these are NOT general coordinates for arbitrary slides.
REGIONS = {
    'code_separator': (831, 571, 909, 577),
    'output_separator': (486, 506, 564, 513),
}
THRESHOLDS = {
    'code_separator': (100, 110, 120, 130, 140),
    'output_separator': (85, 90, 100, 105, 110),
}


def count_dashes(image, box, thresholds):
    """Count separated, short horizontal strokes; uncertain shapes fail closed.

    Counts are computed from pixels, never supplied by a model or fixed to 16.
    Requiring multiple thresholds, regular spacing and clear crop margins rejects
    blank/solid lines, clipping, joined strokes and unstable compression gaps.
    """
    if len(thresholds) < 3 or len(set(thresholds)) != len(thresholds):
        raise ValueError('at_least_three_distinct_thresholds_required')
    if not all(isinstance(t, int) and 0 < t < 255 for t in thresholds):
        raise ValueError('invalid_threshold')
    x0, y0, x1, y1 = box
    if not (0 <= x0 < x1 <= image.width and 0 <= y0 < y1 <= image.height):
        raise ValueError('invalid_pixel_roi')
    gray = image.convert('L')
    trials = []
    for threshold in thresholds:
        ink = {(x, y) for y in range(y0, y1) for x in range(x0, x1)
               if gray.getpixel((x, y)) < threshold}
        trial = {'threshold': threshold, 'segments': []}
        trials.append(trial)
        if not ink:
            trial['reason'] = 'blank'; continue
        if any(x in (x0, x1-1) or y in (y0, y1-1) for x, y in ink):
            trial['reason'] = 'clipped_or_contaminated'; continue
        columns = sorted({x for x, y in ink})
        groups = []
        for x in columns:
            if not groups or x != groups[-1][-1] + 1:
                groups.append([])
            groups[-1].append(x)
        if len(groups) < 2:
            trial['reason'] = 'not_separated_dashes'; continue
        bounds = []
        for group in groups:
            ys = [y for x, y in ink if group[0] <= x <= group[-1]]
            bounds.append([group[0], min(ys), group[-1]+1, max(ys)+1])
        widths = [b[2]-b[0] for b in bounds]
        heights = [b[3]-b[1] for b in bounds]
        pitches = [b[0]-a[0] for a, b in zip(bounds, bounds[1:])]
        trial.update(segments=bounds, count=len(bounds))
        if (min(widths) < 2 or any(w < 1.5*h for w, h in zip(widths, heights))
                or max(widths)-min(widths) > max(1, median(widths)*0.35)
                or max(pitches)-min(pitches) > max(1, median(pitches)*0.25)
                or max(b[1] for b in bounds)-min(b[1] for b in bounds) > 1):
            trial['reason'] = 'irregular_strokes'
    evidence = {'method': 'native_pixel_dash_runs_v1', 'bbox_pixels': list(box),
                'image_size': list(image.size), 'trials': trials}
    counts = [t.get('count') for t in trials]
    stable_positions = (all(t.get('segments') for t in trials)
        and len(set(counts)) == 1
        and all(max(t['segments'][i][0] for t in trials)-min(t['segments'][i][0] for t in trials) <= 1
                for i in range(counts[0] or 0)))
    if any('reason' in t for t in trials) or not stable_positions:
        return {**evidence, 'status': 'needs_review', 'reason': 'pixel_count_not_stable'}
    return {**evidence, 'status': 'verified', 'count': counts[0], 'value': '-' * counts[0]}


def inspect(out, config):
    from video_extraction.video.layer_followup import FOCUS_FRAMES, FOCUS_IMAGE_HASHES
    rows = []
    for fid in sorted(FOCUS_FRAMES):
        image_path = out/'frames'/f'{fid}.png'
        image_hash = digest_file(image_path)
        if image_hash != FOCUS_IMAGE_HASHES[fid]:
            raise ValueError('pixel_roi_requires_reinspection:' + fid)
        with Image.open(image_path) as image:
            for region, box in REGIONS.items():
                rows.append({'frame_id': fid, 'region_id': region, 'image_sha256': image_hash,
                             **count_dashes(image, box, THRESHOLDS[region])})
    return {'version': 1, 'plan_signature': signature(config), 'created_at': now(),
            'implementation_sha256': digest_file(__file__), 'api_requests': 0, 'outcomes': rows}


def apply_review(result, review, config, out):
    from video_extraction.video.layer_followup import PATTERNS
    if review['plan_signature'] != signature(config):
        raise ValueError('pixel_review_plan_changed')
    r = copy.deepcopy(result)
    rows = [x for x in review['outcomes'] if x['frame_id'] == r['frame_id']]
    if not rows:
        return r
    if len({x['region_id'] for x in rows}) != len(rows):
        raise ValueError('duplicate_pixel_review_region')
    parent = r['signature']
    for row in rows:
        if digest_file(out/'frames'/f'{r["frame_id"]}.png') != row['image_sha256']:
            raise ValueError('pixel_review_image_changed')
        matches = [(b, m) for b in r['final_blocks']
                   if (row['region_id'] == 'code_separator') == (b['kind'] == 'code')
                   for m in PATTERNS[row['region_id']].finditer(b['text'])]
        if len(matches) != 1:
            raise ValueError('ambiguous_separator_anchor')
        b, match = matches[0]
        checks = [s for s in r['followup']['symbol_checks'] if s['region_id'] == row['region_id']]
        if len(checks) != 1 or checks[0]['target_id'] != b['id']:
            raise ValueError('pixel_review_requires_completed_symbol_check')
        check = checks[0]
        previous = copy.deepcopy(check)
        before = match.group(1)
        check.clear()
        check.update(region_id=row['region_id'], target_id=b['id'], label=previous.get('label'),
                     old_value=before, status=row['status'], method=row['method'],
                     pixel_evidence=row, model_check=previous)
        # This replaces only the matching symbol decision, never a whole-code hold.
        r['holds'] = [h for h in r['holds'] if not (h.get('layer') == 'text'
                     and h.get('target_id') == b['id'] and h.get('region_id') == row['region_id'])]
        if row['status'] == 'verified':
            start, end = match.span(1)
            b['text'] = b['text'][:start] + row['value'] + b['text'][end:]
            check.update(value=row['value'], hyphen_count=row['count'])
            if before != row['value']:
                r['followup']['corrections'].append({'layer': 'text', 'target_id': b['id'],
                    'region_id': row['region_id'], 'before': before, 'after': row['value'],
                    'method': row['method'], 'evidence': 'pixel-review.json'})
        else:
            check['reason'] = row['reason']
            r['holds'].append({'layer': 'text', 'target_id': b['id'], 'region_id': row['region_id'],
                               'reason': row['reason']})
    r['followup']['pixel_checks'] = rows
    r['followup']['changed_items'] = len(r['followup']['corrections'])
    r['text'] = '\n\n'.join(b['text'] for b in r['final_blocks'])
    r['status'] = 'needs_review' if r['holds'] else 'pixel_repaired'
    r['signature'] = signature({'parent': parent, 'pixel_review': review})
    return r


def load_frozen_plan(out):
    """Read-only validation for offline reporting of a historical API run."""
    config = read(out/'plan.json')
    for relative, expected in config['source_hashes'].items():
        if digest_file(Path(config['source'])/relative) != expected:
            raise ValueError('frozen_source_changed:' + relative)
        if relative.startswith('frames/') and digest_file(out/relative) != expected:
            raise ValueError('copied_frame_changed:' + relative)
    return config


def main():
    from video_extraction.video.layer_followup import OUTPUT, render
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output', type=Path, default=OUTPUT)
    args = ap.parse_args(); out = args.output.resolve()
    with (out/'.followup.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        config = load_frozen_plan(out)
        state = read(out/'run-state.json')
        if state['state'] not in ('complete', 'complete_with_review'):
            raise ValueError('finish_api_run_before_pixel_review')
        review = inspect(out, config)
        # Validate all receipts and merges before writing derived results.
        from video_extraction.video.layer_followup import merge_frame, receipt_path
        for fid in config['selected_ids']:
            tasks = [t for t in config['tasks'] if t['frame_id'] == fid]
            receipts = [read(receipt_path(out, t)) for t in tasks]
            for task, receipt in zip(tasks, receipts):
                if receipt['signature'] != signature({'plan': config, 'task': task['id']}):
                    raise ValueError('receipt_signature_mismatch')
            base = read(Path(config['source'])/'vision'/fid/'result.json')
            apply_review(merge_frame(base, receipts, tasks), review, config, out)
        backup = out/'before-pixel-review'
        if not backup.exists():
            backup.mkdir()
            for name in ['summary.json', 'run-state.json', '미검증_후속검토.html']:
                shutil.copy2(out/name, backup/name)
            shutil.copytree(out/'vision', backup/'vision')
        # Preserve identical evidence on a repeated invocation.
        path = out/'pixel-review.json'
        if path.exists():
            previous = read(path)
            if {k:v for k,v in previous.items() if k != 'created_at'} == {k:v for k,v in review.items() if k != 'created_at'}:
                review = previous
        save(path, review)
        report = render(out, config, state)
        print({'pixel_verified': sum(x['status'] == 'verified' for x in review['outcomes']),
               'remaining_holds': report['remaining_hold_records'], 'api_requests': 0})
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
