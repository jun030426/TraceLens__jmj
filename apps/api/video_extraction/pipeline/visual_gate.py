"""Mandatory source-bound visual gate for ALL common-pipeline image inputs.

Reuses the established calculation gate. Historical approvals are source-hash
bound, not transferable labels. This module never calls a model.
"""
import copy
from PIL import Image
from video_extraction.shared import correction_gate as established
from video_extraction.shared.common import signature, digest_file, bbox_pixels
from video_extraction.video.vision import same_area

VERSION = 1


def scope_risks(before, reported):
    """Flags only; never silently transpose or repair a coordinate proposal."""
    bbox_pixels(before, (1000, 1000)); bbox_pixels(reported, (1000, 1000))
    if before == reported:
        return []
    swapped = [before[1], before[0], before[3], before[2]]
    direct = sum(abs(a-b) for a,b in zip(before, reported))
    transpose = sum(abs(a-b) for a,b in zip(swapped, reported))
    reasons = []
    if transpose <= 16 and direct > transpose + 40:
        reasons.append('possible_coordinate_axis_swap')
    a,b,c,d = before; x,y,z,w = reported
    area = (c-a)*(d-b)
    union_box = (max(c,z)-min(a,x))*(max(d,w)-min(b,y))
    overlap = max(0,min(c,z)-max(a,x))*max(0,min(d,w)-max(b,y))
    if union_box > 4*area or overlap == 0:
        reasons.append('target_scope_changed')
    return reasons


def enforce(candidate, image):
    if candidate.get('image_sha256') != digest_file(image):
        raise ValueError('candidate_source_image_mismatch')
    raw = copy.deepcopy(candidate)
    # A prior receipt is not an approval of a newly changed payload.
    raw.pop('common_gate', None)
    out = established.enforce(raw, image)
    original = {x['id']:x for x in raw['original']['blocks']+raw['original']['visuals']}
    blocked = {}
    def block(i, reason):
        blocked.setdefault(i, set()).add(reason)
    if raw.get('ppt_proposal'):
        from video_extraction.pipeline.ppt_reuse import unresolved
        for item_id in unresolved(raw,image):block(item_id,'ppt_candidate_requires_source_recheck')
    for row in out['calculation_gate']['checks']:
        for reason in row['blocking']:
            block(row['target_id'], reason)
    for layer in ('text', 'visual'):
        for region in raw.get('audit', {}).get(layer+'_regions', []):
            old = original.get(region['target_id'])
            if old:
                try:
                    for reason in scope_risks(old['bbox'], region['bbox']):
                        block(old['id'], reason)
                except ValueError:
                    block(old['id'], 'invalid_audit_bbox')
    # A repair must not manufacture a duplicate and then delete its original ID.
    allowed_aliases = {}
    for event in raw.get('corrections', []):
        if event.get('action') != 'merge_identical_overlap':
            continue
        removed, kept = event['removed_id'], event['target_id']
        a,b = original.get(removed), original.get(kept)
        if a and b and a.get('text') == b.get('text') and a['kind'] == b['kind'] and same_area(a['bbox'],b['bbox']):
            allowed_aliases[removed] = kept
        else:
            block(removed, 'repair_created_duplicate'); block(kept, 'repair_created_duplicate')
    for layer, key, oldkey in [('text','final_blocks','blocks'),('visual','visuals','visuals')]:
        existing = {x['id']:x for x in out[key]}
        for old in raw['original'][oldkey]:
            if old['id'] not in existing and old['id'] not in allowed_aliases:
                block(old['id'], 'original_item_disappeared')
                out[key].append(copy.deepcopy(old))
        for n,item in enumerate(out[key]):
            iid = item['id']
            if item.get('kind') == 'annotation':
                # The coarse visual schema has no per-mark cancellation, word-edge,
                # arrow or audit-ID evidence. It cannot stand in for ink_policy.
                block(iid, 'specialized_ink_verification_required')
            if iid in blocked:
                if iid in original:
                    out[key][n] = copy.deepcopy(original[iid])
                out['holds'].append({'layer':layer, 'target_id':iid,
                    'reason':'common_safety_gate','problems':sorted(blocked[iid])})
    # Once an item is rolled back, relations changed by its merge cannot remain.
    for n,item in enumerate(out['visuals']):
        old = original.get(item['id'])
        if old and any(i in blocked for i in old.get('related_block_ids', [])):
            out['visuals'][n]['related_block_ids'] = copy.deepcopy(old['related_block_ids'])
    effective = {x['id']:x for x in out['final_blocks']+out['visuals']}
    # Keep candidate log separately; exported changes describe effective data only.
    applied = []
    for iid,item in effective.items():
        old = original.get(iid)
        if old != item and iid not in blocked:
            applied.append({'target_id':iid,'action':'replace' if old else 'add',
                            'before':old,'after':copy.deepcopy(item),'applied':True})
    for removed,kept in allowed_aliases.items():
        if removed not in effective and kept not in blocked:
            applied.append({'action':'merge_identical_overlap','target_id':kept,
                            'removed_id':removed,'before':original[removed],'applied':True})
    out['candidate_corrections'] = copy.deepcopy(raw.get('corrections', []))
    out['corrections'] = applied
    out['text'] = '\n\n'.join(x['text'] for x in out['final_blocks'])
    out['changed_blocks'] = len(applied)
    out['status'] = 'needs_review' if out['holds'] else 'calculation_checked'
    out['calculation_gate']['payload_sha256'] = established.payload_digest(out)
    out['common_gate'] = {'version':VERSION,'candidate_sha256':signature(raw),
        'image_sha256':digest_file(image),'blocked':{k:sorted(v) for k,v in blocked.items()},
        'policy':'established_calculations_and_target_identity',
        'payload_sha256':signature(out)}
    require(out, image)
    return out


def require(result, image):
    established.require_gate(result, image)
    receipt = result.get('common_gate', {})
    payload = {k:v for k,v in result.items() if k != 'common_gate'}
    if (receipt.get('version') != VERSION or receipt.get('image_sha256') != digest_file(image)
            or receipt.get('payload_sha256') != signature(payload)):
        raise ValueError('missing_or_stale_common_visual_gate')
    if result.get('ppt_proposal'):
        from video_extraction.pipeline.ppt_reuse import unresolved
        for item_id in unresolved(result,image):
            if not any(h.get('target_id')==item_id and 'ppt_candidate_requires_source_recheck' in h.get('problems',[])
                       for h in result['holds']):
                raise ValueError('missing_ppt_source_recheck_hold')


def records(t, result, base_record):
    """Single deterministic selection path, also rerun when reading results."""
    from video_extraction.video.vision_layers import visual_problems
    require(result, t['image'])
    from video_extraction.pipeline.generalized_visual import verify
    verify(result,t['image'])
    rows = []; holds = result['holds']+result['deferred_regions']
    originals = {x['id']:x for x in result['original']['blocks']+result['original']['visuals']}
    for layer,key in [('text','final_blocks'),('visual','visuals')]:
        for item in result[key]:
            iid = item['id']
            modality = ('handwriting' if item['kind']=='annotation' else 'image' if layer=='visual'
                        else 'document' if t['source_kind'] in ('ppt','pdf') else 'screen_text')
            rec = base_record(t,iid,modality,item['kind'],item.get('text',item.get('literal_text','')))
            blockers = [h for h in holds if (not h.get('layer') or h['layer']==layer)
                        and (not h.get('target_id') or h['target_id'] in ('NEW',iid))]
            if item.get('uncertainties'): blockers.append({'reason':'uncertain_source'})
            if layer == 'visual': blockers += [{'reason':r} for r in visual_problems(item,result['final_blocks'])]
            try: bbox_pixels(item['bbox'],t['dimensions'])
            except ValueError: blockers.append({'reason':'invalid_bbox'})
            old = originals.get(iid,{})
            rec.update(original_text=old.get('text',old.get('literal_text','')),
                bbox=item['bbox'],bbox_coordinate_system='normalized_0_1000_xyxy',source_image=t['image'],
                image_dimensions=t['dimensions'],description=item.get('description',''),
                uncertainties=item.get('uncertainties',[]),
                related_record_ids=[t['id']+':'+x for x in item.get('related_block_ids',[])],
                eligible_for_chunking=not blockers,judgment='held' if blockers else 'source_rechecked',
                reasons=sorted({h.get('reason','deferred_or_unresolved') for h in blockers}),
                safety_findings=[r for h in blockers for r in h.get('problems',[])],
                native_document_text_reference=t.get('native_text',''))
            rows.append(rec)
    if not rows or holds:
        rec = base_record(t,'unresolved-regions','review','coverage_issue','')
        rec.update(reasons=['unresolved_visual_regions'] if holds else ['empty_visual_extraction'],raw_findings=holds)
        rows.append(rec)
    return rows
