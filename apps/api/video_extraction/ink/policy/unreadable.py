"""Final administrator routing; never alters legacy source verdicts on disk."""
import copy
from collections import Counter


def route(package,result):
    out=copy.deepcopy(result);value=out['candidate']
    checks=out.get('final_audit',{}).get('checks',[]);counts=Counter(c['id'] for c in checks)
    byid={c['id']:c for c in checks if counts[c['id']]==1}
    active={d['id'] for d in out['decisions'] if d['status']!='context_only'}
    unreadable=set()
    for item in value['items']:
        c=byid.get(item['id'],{})
        if item['id'] not in active:continue
        if item['kind']=='unclear' or (item['kind'] in ('handwriting','math','code') and
            c.get('content')=='uncertain' and not c.get('full_text','').strip() and
            c.get('reason')!='audit_response_missing_or_duplicate'):
            unreadable.add(item['id'])
    while True:
        linked={x['id'] for x in value['links'] if set(x['from_ids']+x['to_ids']) & unreadable}
        if linked<=unreadable:break
        unreadable|=linked
    nodes={x['id']:x for x in value['items']+value['links']}
    queued={x['local_id'] for x in out['administrator_queue']}
    for decision in out['decisions']:
        iid=decision['id']
        if iid not in unreadable or iid in queued:continue
        decision.update(status='administrator_review',applied=False)
        decision['reasons']=sorted(set(decision['reasons']+['unreadable_source_administrator_review']))
        out['administrator_queue'].append({'id':package['task']['id']+':'+iid,'task_id':package['task']['id'],
            'local_id':iid,'status':'administrator_review','reason':'unreadable_source_or_dependent_relation',
            'impact':'unknown','item':nodes[iid],'source_image':package['task']['evidence']['selected_frame'],
            'crop_image':package['view']['path'],'crop_in_source':package['view']['crop_in_source'],
            'usable_as_active_knowledge':False})
    if unreadable:
        out['records']=[r for r in out['records'] if r['local_id'] not in unreadable]
        out['changes']=[c for c in out['changes'] if c['id'] not in unreadable]
        for group in ('items','links'):
            old={x['id']:x for x in package['base'][group]}
            out['effective_inventory'][group]=[old.get(x['id'],x) if x['id'] in unreadable else x
                                               for x in out['effective_inventory'][group]]
        out['all_review_resolved']=False
        out['effective_inventory']['complete']=False
    return out
