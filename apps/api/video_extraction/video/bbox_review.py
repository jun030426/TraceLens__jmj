"""Apply hash-bound, offline coordinate corrections to derived results only."""
import copy

from video_extraction.shared.common import digest_file, signature


def apply_review(result, review, config, out):
    if review['plan_signature'] != signature(config):
        raise ValueError('bbox_review_plan_changed')
    rows = [x for x in review['outcomes'] if x['frame_id'] == result['frame_id']]
    if not rows:
        return result
    if len({x['target_id'] for x in rows}) != len(rows):
        raise ValueError('duplicate_bbox_target')
    r = copy.deepcopy(result)
    for row in rows:
        if digest_file(out/'frames'/f'{r["frame_id"]}.png') != row['image_sha256']:
            raise ValueError('bbox_review_image_changed')
        blocks = [b for b in r['final_blocks'] if b['id'] == row['target_id']]
        if len(blocks) != 1:
            raise ValueError('bbox_review_target_changed')
        block = blocks[0]
        if block['bbox'] != row['before'] or signature(block['text']) != row['expected_text_signature']:
            raise ValueError('bbox_review_anchor_changed')
        box = row['after']
        if (len(box) != 4 or not all(type(x) is int for x in box)
                or not (0 <= box[0] < box[2] <= 1000 and 0 <= box[1] < box[3] <= 1000)):
            raise ValueError('invalid_reviewed_bbox')
        block['bbox'] = list(box)
        r['followup']['corrections'].append({'layer': 'text', 'target_id': block['id'],
            'field': 'bbox', 'before': row['before'], 'after': box,
            'method': 'offline_source_coordinate_review', 'evidence': 'bbox-review.json'})
    r['followup']['coordinate_reviews'] = copy.deepcopy(rows)
    r['followup']['changed_items'] = len(r['followup']['corrections'])
    r['signature'] = signature({'parent': result['signature'], 'bbox_review': review})
    return r
