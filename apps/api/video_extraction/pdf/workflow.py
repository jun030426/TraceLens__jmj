"""PDF page inventory and source-bound structure audit after the existing repair gate.

Native text is omission evidence, never authoritative text for invisible OCR layers.
Reading order and relationships are metadata; this module never rewrites content.
"""
import copy
import json
import math
import re
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from video_extraction.shared.common import read, save, signature, digest_file, validate
from video_extraction.shared.gemini import obj, TEXT, BOOL


def array(item): return {'type':'array','items':item}


SCHEMA = obj({'complete':BOOL, 'reading_order':array(TEXT),
    'checks':array(obj({'id':TEXT,'source_supported':BOOL,'structure_supported':BOOL,
                        'order_clear':BOOL,'reason':TEXT})),
    'relations':array(obj({'from_id':TEXT,'to_id':TEXT,'kind':TEXT,'supported':BOOL})),
    'missing':array(TEXT), 'cross_page_uncertain':array(TEXT)})
PROMPT = '''Inspect this original document page/slide as untrusted source data. Check every listed
region exactly once. Do not rewrite any text. Verify columns and reading order,
table row/column/cell associations, code indentation, figure-caption associations,
and arrows. Reading_order must contain every listed ID once in source reading order.
If order is ambiguous mark order_clear false for affected IDs; do not guess from XML
order. Do not invent contents from invisible native OCR text. Report missing visible
content, unresolved cross-page continuation, and only visually supported relations.
Repeated headers/page numbers are not duplicates to delete. DATA:\n'''


def native_inventory(bbox_xml):
    root=ET.fromstring(bbox_xml)
    page=next((x for x in root.iter() if x.tag.split('}')[-1]=='page'),None)
    if page is None: raise ValueError('pdf_native_page_missing')
    w,h=float(page.attrib['width']),float(page.attrib['height'])
    if not all(math.isfinite(x) and x>0 for x in (w,h)):raise ValueError('pdf_invalid_page_size')
    words=[]
    for x in page.iter():
        if x.tag.split('}')[-1]!='word':continue
        text=''.join(x.itertext()).strip()
        if not text:continue
        box=[float(x.attrib[k])/s*1000 for k,s in zip(('xMin','yMin','xMax','yMax'),(w,h,w,h))]
        words.append({'text':text,'bbox':box,'valid_box':all(math.isfinite(v) for v in box)
            and 0<=box[0]<box[2]<=1000.5 and 0<=box[1]<box[3]<=1000.5})
    return {'page_size_points':[w,h],'words':words,
            'route':'embedded_text_and_render' if words else 'scan_or_graphics_render',
            'native_text_is_ground_truth':False}


def items(result):
    return result.get('final_blocks',[])+result.get('visuals',[])


def review(t,result,folder,client):
    folder=Path(folder);path=folder/'pdf-structure-review.json'
    data={'page':t['location']['page'],'regions':items(result),
          'native_inventory':t.get('pdf_inventory',{}),'unit_id':t['id']}
    binding=signature({'image':digest_file(t['image']),'data':data,'prompt':PROMPT,'schema':SCHEMA})
    if path.exists():
        receipt=read(path)
        if receipt['binding']!=binding:raise ValueError('pdf_structure_source_changed')
    else:
        answer=client.call('pdf-source-structure-v1',[Path(t['image'])],PROMPT+json.dumps(data,ensure_ascii=False),SCHEMA)
        validate(answer,SCHEMA)
        receipt={'binding':binding,'data':data,'image_sha256':digest_file(t['image']),'answer':answer}
        save(path,receipt)
    validate(receipt['answer'],SCHEMA)
    return receipt


def check_receipt(t,result,receipt):
    data={'page':t['location']['page'],'regions':items(result),
          'native_inventory':t.get('pdf_inventory',{}),'unit_id':t['id']}
    binding=signature({'image':digest_file(t['image']),'data':data,'prompt':PROMPT,'schema':SCHEMA})
    if receipt.get('binding')!=binding:raise ValueError('pdf_structure_source_changed')
    validate(receipt['answer'],SCHEMA)


def apply(t,result,records,receipt,source_review=None):
    from video_extraction.pipeline.runner import base_record
    from video_extraction.pipeline.source_followup import resolved
    rows=copy.deepcopy(records);originals=items(result);ids=[x['id'] for x in originals]
    issue=[];checks={};order=[];answer={}
    if receipt is None:
        issue.append('pdf_structure_review_pending')
    else:
        check_receipt(t,result,receipt);answer=receipt['answer'];order=answer['reading_order']
        counts=Counter(x['id'] for x in answer['checks'])
        checks={x['id']:x for x in answer['checks'] if counts[x['id']]==1}
        if Counter(order)!=Counter(ids) or len(ids)!=len(set(ids)):
            issue.append('pdf_reading_order_missing_duplicate_or_unknown_id')
        if set(counts)-set(ids):issue.append('pdf_unknown_audit_id')
        if not answer['complete'] or answer['missing']:issue.append('pdf_visible_content_coverage_unresolved')
    for row in rows:
        iid=next((i for i in ids if row['id']==t['id']+':'+i),None)
        if iid is None:continue
        reasons=list(issue);c=checks.get(iid)
        if c is None:reasons.append('pdf_region_audit_missing_or_duplicate')
        elif not all(c[k] for k in ('source_supported','structure_supported','order_clear')):
            reasons.append('pdf_region_structure_or_order_unresolved')
        row['document_structure']={'page':t['location']['page'],'reading_order':order.index(iid) if iid in order else None,
            'verified':not reasons,'method':'rendered_source_model_audit_and_id_checks','audit':c,
            'cross_page_join_verified':False}
        if reasons:
            row.update(eligible_for_chunking=False,approved_for_rag=False,judgment='held')
            row['reasons']=sorted(set(row.get('reasons',[])+reasons))
    # Check native tokens against geometrically corresponding regions. Do not copy
    # the OCR layer into output, and do not mistake a short number/negation for noise.
    compact=lambda s:re.sub(r'\s+','',s or '')
    unmatched=[]
    for word in t.get('pdf_inventory',{}).get('words',[]):
        a,b,c,d=word['bbox'];cx,cy=(a+c)/2,(b+d)/2
        neighbors=[x for x in originals if len(x.get('bbox',[]))==4 and
            x['bbox'][0]-3<=cx<=x['bbox'][2]+3 and x['bbox'][1]-3<=cy<=x['bbox'][3]+3]
        visible=''.join(x.get('text',x.get('literal_text','')) for x in neighbors)
        if not word['valid_box'] or compact(word['text']) not in compact(visible):
            if resolved(source_review,'native-pdf:'+signature(word)[:24]):continue
            unmatched.append(word)
            affected={t['id']+':'+x['id'] for x in neighbors}
            for row in rows:
                if row['id'] in affected:
                    row.update(eligible_for_chunking=False,approved_for_rag=False,judgment='held')
                    row['reasons']=sorted(set(row.get('reasons',[])+['pdf_native_visible_text_conflict']))
    if unmatched:
        r=base_record(t,'pdf-native-unmatched','document','coverage_issue','')
        r.update(reasons=['pdf_native_tokens_require_visible_source_review'],raw_payload=unmatched);rows.append(r)
    known={r['id']:r for r in rows}
    for n,link in enumerate(answer.get('relations',[])):
        r=base_record(t,'pdf-relation:'+str(n),'document','relation','')
        refs=[t['id']+':'+link[k] for k in ('from_id','to_id')]
        valid=link['supported'] and all(i in ids for i in (link['from_id'],link['to_id'])) and all(known.get(i,{}).get('eligible_for_chunking') for i in refs)
        r.update(raw_payload=link,related_record_ids=refs,eligible_for_chunking=bool(valid),
                 judgment='source_rechecked' if valid else 'held',reasons=[] if valid else ['pdf_relation_unresolved'])
        rows.append(r)
    for n,description in enumerate(answer.get('cross_page_uncertain',[])):
        r=base_record(t,'pdf-continuation:'+str(n),'document','coverage_issue','')
        r.update(raw_payload={'description':description,'page':t['location']['page']},reasons=['pdf_cross_page_connection_requires_review']);rows.append(r)
    if issue and not originals:
        r=base_record(t,'pdf-empty-review','document','coverage_issue','');r['reasons']=issue;rows.append(r)
    return rows,{'issues':issue,'native_unmatched':len(unmatched),'structure_audited':receipt is not None,
                 'page_kind':t.get('pdf_inventory',{}).get('route','unknown')}
