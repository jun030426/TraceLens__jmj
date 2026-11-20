"""Reconcile pending records by frame and issue; no media/model calls."""
from video_extraction._layout import PROJECT_ROOT
from collections import Counter
import argparse
from pathlib import Path

from video_extraction.shared.common import digest_file, now, read, save, signature
from video_extraction.video.vision import critical

ROOT=PROJECT_ROOT


def reconcile(source=ROOT/'outputs/multimodal-checks-reviewed/review.json',
              output=ROOT/'outputs/pending-reconciliation/review.json'):
    plan_path=ROOT/'outputs/multimodal-validation/plan.json'
    coordinate_path=ROOT/'outputs/cutoff-source-review/decisions.json'
    optimization_path=ROOT/'outputs/vision-optimization/manifest.json'
    protected={str(p):digest_file(p) for p in (source,plan_path,coordinate_path,optimization_path)}
    report=read(source);plan=read(plan_path);rows=report['groups']['pending']
    coordinates={(r['frame_id'],r['target_id']):r for r in read(coordinate_path)}
    roots=[Path(p) for p in plan['settings']['overrides']]+[Path(plan['settings']['job'])]
    originals={}

    def original(fid):
        if fid not in originals:
            path=next(root/'vision'/fid/'result.json' for root in roots
                      if str(root/'vision'/fid/'result.json') in plan['input_hashes'])
            h=digest_file(path)
            if h!=plan['input_hashes'][str(path)]:raise ValueError('baseline_changed')
            protected[str(path)]=h;originals[fid]=read(path)
        return originals[fid]

    # Merge repeated detectors only for the same frame and anchored content issue.
    uncertain={(r['frame_id'],r['target_id']) for r in rows if r['reason']=='source_uncertainty'}
    symbols={(r['frame_id'],r['target_id']) for r in rows if r['reason']=='zero_o_requires_source_comparison'}
    groups={}
    for index,row in enumerate(rows):
        fid=row['frame_id'];hold=row.get('original_hold',{});region=hold.get('region',{})
        target=row.get('target_id') or hold.get('target_id') or region.get('target_id')
        if row['reason']=='extraction_missing':category='no_baseline_extraction';anchor='frame'
        elif (fid,target) in symbols:category='zero_o_unresolved';anchor=target
        elif (fid,target) in uncertain:category='handwriting_unresolved';anchor=target
        elif hold.get('reason')=='region_budget':category='budget_summary';anchor='budget'
        elif hold.get('reason')=='duplicate_addition':
            category='duplicate_addition_needs_review';anchor=signature(region)
        else:category='other_verification_hold';anchor=target if target and target!='NEW' else signature(region)
        key=(fid,category,anchor)
        if key not in groups:
            groups[key]={'frame_id':fid,'category':category,'target_id':target,
                         'status':'pending','source_record_indices':[],'records':[],
                         'resolved_by_coordinate_review':False}
        group=groups[key];group['source_record_indices'].append(index);group['records'].append(row)
        if (fid,target) in coordinates:
            c=coordinates[fid,target]
            group['coordinate_review']={'decision':c['decision'],'before':c['before'],'after':c['after'],
                'scope':'bbox_only','content_status':'still_pending'}

    # Expand aggregate budget holds from the recorded initial extraction, audit,
    # reuse list and saved limit. This exposes hidden work without counting it twice.
    limit=read(optimization_path)['max_regions']
    budget_regions=[]
    for group in groups.values():
        if group['category']!='budget_summary':continue
        r=original(group['frame_id']);regions=list(r['audit']['regions'])
        targeted={x['target_id'] for x in regions};skip={x['target_id'] for x in r.get('reuse',[])}
        for block in r['original']['blocks']:
            if critical(block) and block['id'] not in targeted and block['id'] not in skip:
                regions.append({'target_id':block['id'],'bbox':block['bbox'],'kind':block['kind'],
                                'issue':'uncertain','reason':'critical_content_policy'})
        remaining=group['records'][0]['original_hold']['remaining']
        if len(regions)-limit!=remaining:raise ValueError('budget_reconstruction_mismatch')
        expanded=[]
        for region in regions[limit:]:
            c=coordinates.get((group['frame_id'],region['target_id']))
            expanded.append({'frame_id':group['frame_id'],'region':region,'status':'not_content_reviewed',
                             'coordinate_review':None if c is None else c['decision']})
        group['remaining_regions']=expanded;budget_regions.extend(expanded)

    all_indices=[i for g in groups.values() for i in g['source_record_indices']]
    assert sorted(all_indices)==list(range(len(rows)))
    counts=dict(Counter(g['category'] for g in groups.values()))
    result={'version':1,'created_at':now(),'api_requests':0,'input_sha256':protected,
            'annotation_review':report.get('annotation_review'),
            'raw_pending_records':len(rows),'grouped_management_items':len(groups),
            'redundant_detector_records':len(rows)-len(groups),'counts':counts,
            'resolved_by_coordinate_review':0,'budget_regions':len(budget_regions),
            'groups':list(groups.values()),
            'notes':[
                'Groups use frame and content issue; repeated appearances across frames remain separate.',
                'Budget summary groups are aggregates, not individual regions. Do not add the expanded regions to those summaries.',
                'Duplicate-addition guards can reject annotations because printed text occupies the same area; they do not prove the annotation was captured.',
                'Coordinate fixes and cutoff false-positive decisions do not verify transcription, graphical descriptions or omissions.',
                'Only exact repeated issue anchors are merged; spatial overlap alone does not prove two issues are identical.',
                'No pending content item is approved or deleted by this reconciliation.',
            ]}
    # Include existing candidates separately, without approving them.
    no_baseline={g['frame_id'] for g in groups.values() if g['category']=='no_baseline_extraction'}
    candidate_only=[]
    for task in plan['tasks']:
        if task['kind']=='audio':continue
        # task frame ID is stored in its source frame structure.
        fid=task.get('frame',{}).get('id') or task.get('frame_id')
        if fid in no_baseline and (ROOT/'outputs/multimodal-validation/receipts'/f'{task["id"]}.json').exists():
            candidate_only.append(fid)
    result['no_baseline_with_unapproved_candidate']=sorted(set(candidate_only))
    if any(digest_file(p)!=h for p,h in protected.items()):raise ValueError('reconciliation_input_changed')
    if output.resolve() in {Path(p).resolve() for p in protected}:raise ValueError('reconciliation_output_overlaps_input')
    save(output,result)
    print({k:result[k] for k in ('raw_pending_records','grouped_management_items','redundant_detector_records',
                               'counts','budget_regions','resolved_by_coordinate_review',
                               'no_baseline_with_unapproved_candidate','api_requests')})
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,default=ROOT/'outputs/multimodal-checks-reviewed/review.json')
    parser.add_argument('--output',type=Path,default=ROOT/'outputs/pending-reconciliation/review.json')
    args=parser.parse_args();reconcile(args.source,args.output)
