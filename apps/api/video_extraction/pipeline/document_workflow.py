"""Connect native PPT extraction and existing frame checks to visual selection."""
import copy
import re
import subprocess
from pathlib import Path
from video_extraction.shared.common import read,digest_file
from video_extraction.ppt.other_data import native_documents
from video_extraction.shared.multimodal_checks import inspect_frame
from video_extraction.pipeline.runner import base_record


def native_inventory(sources,native_python=None,folder=None):
    registry=[{'media_type':'pptx','resolved_path':s['source_file'],'sha256':s['source_sha256'],
               'source_id':s['source_sha256']} for s in sources if s['kind']=='ppt']
    records,changes,assets,pending=native_documents(registry,[])
    readers=[]
    if native_python:
        folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
        for source in registry:
            target=folder/(source['sha256']+'.json')
            proc=subprocess.run([str(native_python),'-m','video_extraction.ppt.native_reader',
                '--input',source['resolved_path'],'--output',str(target)],capture_output=True,text=True,timeout=90)
            if proc.returncode:raise ValueError('python_pptx_native_reader_failed')
            result=read(target)
            if result['source_sha256']!=source['sha256']:raise ValueError('python_pptx_source_changed')
            readers.append({'path':str(target),'sha256':digest_file(target),'source_sha256':source['sha256'],'tool':result['tool'],'version':result['version']})
            other={(r['slide_number'],r['shape_id']):r for r in result['rows']}
            ours={(r['slide_number'],r['shape_id']):r for r in records if r['source_sha256']==source['sha256']}
            for key in sorted(set(other)|set(ours)):
                a=ours.get(key);b=other.get(key)
                av=a.get('table_rows') if a and a.get('table_rows') is not None else a.get('observed_text') if a else None
                bv=b.get('rows') if b and b.get('kind')=='table' else b.get('text') if b else None
                if a and b and av==bv:
                    a['native_reader_agreement']={'tool':'python-pptx','receipt':str(target)}
                else:
                    pending.append({'source_sha256':source['sha256'],'slide_number':key[0],'shape_id':key[1],
                        'reason':'native_ppt_parsers_disagree','xml_value':av,'python_pptx_value':bv,'receipt':str(target)})
    return {'records':records,'changes':changes,'assets':assets,'pending':pending,'native_reader_receipts':readers}


def compact(text):
    # No case folding, punctuation, code operators, values or zero/o conversion.
    return re.sub(r'\s+','',text or '')


def apply(t, result, records, native, pdf_review=None, source_review=None):
    from video_extraction.pipeline.source_followup import resolved
    from video_extraction.shared.common import signature
    rows=copy.deepcopy(records)
    findings,metrics=inspect_frame(t['image'],result,t['dimensions'])
    for f in findings:
        targets=[r for r in rows if not f.get('target_id') or r['id']==t['id']+':'+f['target_id']]
        for r in targets:
            r.setdefault('local_findings',[]).append(f)
            if f['category']=='error':
                r.update(eligible_for_chunking=False,judgment='held')
                r['reasons']=sorted(set(r['reasons']+[f['reason']]))
    # Native text is separate source evidence, not an LLM spelling suggestion.
    native_rows=[r for r in native.get('records',[]) if r['source_sha256']==t['source_id']
                 and r['slide_number']==t['location'].get('page') and not r['hidden']]
    visible='\n'.join(x['text'] for x in result['final_blocks'])
    observed=compact(visible)
    for source in native_rows:
        parts=[cell for line in source['table_rows'] for cell in line if cell.strip()] if source.get('table_rows') is not None else [source['observed_text']]
        missing=[x for x in parts if compact(x) not in observed]
        if missing and resolved(source_review,'native-ppt:'+source['shape_id']):continue
        if not missing:
            for r in rows:
                if any(compact(x) and compact(x) in compact(r['observed_text']) for x in parts):
                    r.setdefault('native_source_ids',[]).append(source['id'])
            continue
        r=base_record(t,'native-missing:'+source['shape_id'],'document','coverage_issue','')
        r.update(reasons=['native_ppt_content_not_matched_in_rendered_extraction'],
                 native_record=source,missing_fragments=missing)
        rows.append(r)
    # PDF embedded text detects possible omissions; it is not automatically true
    # (invisible OCR layers / off-page content require source verification).
    if t['source_kind']=='pdf' and t.get('native_text'):
        missing=[line.strip() for line in t['native_text'].splitlines()
                 if len(compact(line))>=8 and compact(line) not in observed
                 and not resolved(source_review,'native-line:'+signature(line.strip())[:24])]
        if missing:
            r=base_record(t,'native-pdf-differences','document','coverage_issue','')
            r.update(reasons=['embedded_pdf_text_requires_source_comparison'],missing_fragments=missing)
            rows.append(r)
    for item in native.get('pending',[]):
        if item['source_sha256']==t['source_id'] and item['slide_number']==t['location'].get('page'):
            if resolved(source_review,'native-structure:'+item['shape_id']):continue
            r=base_record(t,'native-structure:'+item['shape_id'],'document','coverage_issue','')
            r.update(reasons=[item['reason']],raw_payload=item);rows.append(r)
    pdf_checks={}
    if (t['source_kind']=='pdf' or pdf_review is not None) and 'pdf_inventory' in t:
        from video_extraction.pdf import workflow
        rows,pdf_checks=workflow.apply(t,result,rows,pdf_review,source_review)
    return rows,{'frame_findings':findings,'frame_metrics':metrics,'native_rows_compared':len(native_rows),'pdf_checks':pdf_checks,
                 'pdf_route':'embedded_text_and_rendered_source' if t.get('native_text') else 'rendered_image'}
