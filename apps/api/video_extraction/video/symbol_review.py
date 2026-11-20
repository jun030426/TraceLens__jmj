"""Apply recorded offline uncertainty decisions without changing transcribed text."""
import copy

from video_extraction.shared.common import digest_file, signature


def apply_review(result, review, config, out):
    if review['plan_signature'] != signature(config):
        raise ValueError('symbol_review_plan_changed')
    rows = [x for x in review['outcomes'] if x['frame_id'] == result['frame_id']]
    if not rows:
        return result
    if len({x['region_id'] for x in rows}) != len(rows):
        raise ValueError('duplicate_symbol_review')
    r = copy.deepcopy(result)
    for row in rows:
        if row['region_id'] != 'index' or row['status'] != 'needs_review':
            raise ValueError('unsupported_symbol_review')
        if digest_file(out/'frames'/f'{r["frame_id"]}.png') != row['image_sha256']:
            raise ValueError('symbol_review_image_changed')
        blocks = [b for b in r['final_blocks'] if b['id'] == row['target_id']]
        checks = [s for s in r['followup']['symbol_checks']
                  if s['region_id'] == row['region_id'] and s['target_id'] == row['target_id']]
        if len(blocks) != 1 or len(checks) != 1:
            raise ValueError('symbol_review_target_changed')
        block, check = blocks[0], checks[0]
        if signature(block['text']) != row['expected_text_signature']:
            raise ValueError('symbol_review_text_changed')
        candidate = row['context_candidate']
        if candidate['value'] != '0' or candidate['applied'] is not False or candidate['source_verified'] is not False:
            raise ValueError('context_candidate_must_not_be_source_confirmation')
        previous = copy.deepcopy(check)
        check.clear()
        check.update(region_id='index', target_id=row['target_id'], label=previous['label'],
                     old_value=previous.get('old_value', ''), status='needs_review',
                     existing_transcription=row['existing_transcription'], alternatives=['0', 'o'],
                     reason=row['reason'], reason_detail=row['reason_detail'],
                     context_candidate=copy.deepcopy(candidate), model_check=previous,
                     evidence=previous.get('evidence'), method='offline_uncertainty_review')
        uncertainty = 'name = student[...]: 0/o 미확정. 문맥상 후보는 0이며 원본 문자로 확정하거나 본문에 적용하지 않음.'
        if uncertainty not in block['uncertainties']:
            block['uncertainties'].append(uncertainty)
        r['holds'] = [h for h in r['holds'] if not (h.get('layer') == 'text'
                     and h.get('target_id') == row['target_id'] and h.get('region_id') == 'index')]
        r['holds'].append({'layer': 'text', 'target_id': row['target_id'], 'region_id': 'index',
                           'reason': row['reason'], 'context_candidate': copy.deepcopy(candidate)})
        for correction in r['followup']['corrections']:
            if correction.get('target_id') == row['target_id'] and correction.get('region_id') == 'index':
                correction.update(approval_status='withdrawn', reason=row['reason'],
                                  note='이전 변경 이력 보존. 현재 저장 문자는 미확정이며 추가 문자 변경 없음.')
    r['followup']['uncertainty_reviews'] = copy.deepcopy(rows)
    r['status'] = 'needs_review'
    r['signature'] = signature({'parent': result['signature'], 'symbol_review': review})
    return r
