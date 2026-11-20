"""Code specialist and replay gate for the existing common dispatcher."""
import copy
import subprocess
import sys
from pathlib import Path
from video_extraction.code import processing
from video_extraction.shared.common import read,save,signature,digest_file


def analyze(unit,folder,python=None):
    if digest_file(unit['source_file'])!=unit['source_id']:raise ValueError('code_source_changed')
    if unit['language']=='java' and python and Path(python).absolute()!=Path(sys.executable).absolute():
        target=Path(folder)/'parsed-code.json'
        proc=subprocess.run([str(python),'-m','video_extraction.code.processing','--input',unit['source_file'],
            '--output',str(target)],capture_output=True,text=True,timeout=90)
        if proc.returncode:raise ValueError('java_parser_failed_check_code_python_environment')
        analysis=read(target)
    else:analysis=processing.analyze(unit['source_file'])
    if analysis['source_sha256']!=unit['source_id']:raise ValueError('code_source_changed_during_parse')
    return analysis


def records(unit,analysis):
    from video_extraction.shared.records import base_record
    rows=[];structures={c['id']:c for c in analysis['structures']}
    for i,part in enumerate(analysis['parts']):
        r=base_record(unit,'code:'+str(i),'code','code',part['text'])
        r.update(language=analysis['language'],encoding=analysis['encoding'],code_role=part['kind'],
            symbol_name=part['name'],parent_symbol_id=part.get('parent_id'),concept_ids=[],
            concept_candidates=[{**c,'scope':'file'} for c in analysis['concept_candidates']],
            location={**unit['location'],'line_start':part['line_start'],'line_end':part['line_end'],
                'char_start':part['start'],'char_end':part['end'],'byte_start':part['byte_start'],'byte_end':part['byte_end']},
            eligible_for_chunking=part['eligible'],judgment=part['status'],reasons=[part['reason']] if part['reason'] else [],
            code_checks=analysis.get('checks',{}),source_encoding=analysis['encoding'],
            module_context=[x['text'] for x in analysis['imports']],class_context=[],
            comment_context=part.get('comment_context',[]),statement_count=part.get('statement_count'),
            semantic_correctness='not_proven',automatic_repairs=[])
        parent=part.get('parent_id')
        while parent:
            c=structures[parent]
            r['class_context'].append({'symbol':c['name'],'id':c['id'],
                'source_spans':c['context_spans'],'text_parts':[analysis['text'][a:b] for a,b in c['context_spans']]})
            parent=c.get('parent_id')
        rows.append(r)
    if not rows:
        r=base_record(unit,'source-review','code','code','')
        r.update(reasons=[analysis.get('reason') or 'empty_source'],raw_source_sha256=analysis['source_sha256'])
        rows.append(r)
    return rows


def run(unit,folder,python=None):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    a=analyze(unit,folder,python);save(folder/'analysis.json',a)
    return {'records':records(unit,a),'changes':[],'status':'complete',
            'executed':['native_code_parse','source_range_partition','literal_source_gate'],
            'analysis_sha256':digest_file(folder/'analysis.json'),'api_calls':0}


def validate_saved(unit,folder,result,python=None):
    if digest_file(Path(folder)/'analysis.json')!=result['analysis_sha256']:raise ValueError('code_evidence_changed')
    # Replay from the immutable input; a modified result + recomputed hash is insufficient.
    a=analyze(unit,Path(folder)/'replay',python)
    if a!=read(Path(folder)/'analysis.json'):raise ValueError('code_analysis_changed')
    if records(unit,a)!=result['records'] or result['changes']:
        raise ValueError('code_selection_differs_from_source')


def corpus_for(rows):
    chunks=[]
    for r in rows:
        if r.get('modality')!='code' or not r.get('eligible_for_chunking'):continue
        code=r['observed_text'];marker='`'*max(3,1+max((len(x) for x in __import__('re').findall(r'`+',code)),default=0))
        text=marker+r['language']+'\n'+code+('' if code.endswith('\n') else '\n')+marker+'\n'
        chunks.append({'id':r['id'],'text':text,'code_text':code,'source_text':code,'code_format':'fenced','source_already_fenced':False,
            'kind':'code','language':r['language'],'title':Path(r['source_file']).name+' · '+r['symbol_name'],
            'source_file':r['source_file'],'source_sha256':r['source_sha256'],'source_locator':f"줄 {r['location']['line_start']}–{r['location']['line_end']}",
            'slide_number':r['location']['line_start'],'location':r['location'],
            'quality':'source_code_structure_checked','eligible_for_chunking':True,
            'concept_ids':r['concept_ids'],'concept_candidates':r['concept_candidates'],
            'module_context':r['module_context'],'class_context':r['class_context'],'code_checks':r['code_checks'],
            'comment_context':r.get('comment_context',[]),'code_role':r['code_role'],'statement_count':r.get('statement_count'),
            'semantic_correctness':'not_proven'})
    data={'version':1,'chunks':chunks,'pipeline':'common-source-code-v1'}
    data['signature']=signature({'version':1,'chunks':chunks});return data


def validate_corpus_selection(corpus):
    receipt=corpus.get('common_selection')
    if not receipt:raise ValueError('common_code_selection_receipt_required')
    manifest=Path(receipt['manifest'])
    if digest_file(manifest)!=receipt['sha256']:raise ValueError('common_code_manifest_changed')
    meta=read(manifest)
    for name,sha in meta['files'].items():
        if Path(name).name!=name or digest_file(manifest.parent/name)!=sha:raise ValueError('common_code_selection_changed')
    rows=[__import__('json').loads(line) for line in (manifest.parent/'usable-records.jsonl').read_text().splitlines()]
    expected=corpus_for(rows)
    if corpus['signature']!=expected['signature'] or corpus['chunks']!=expected['chunks']:
        raise ValueError('code_corpus_differs_from_common_selection')
    # Replay the SAME code gate without requiring OCR/Whisper in the RAG environment.
    from video_extraction.shared.records import base_record
    from video_extraction._layout import PROJECT_ROOT
    out=manifest.parents[2];p=read(out/'plan.json')
    if meta['plan_signature']!=signature(p):raise ValueError('common_code_plan_changed')
    for key,path in [('video_extraction.pipeline.code_workflow',__file__),
        ('video_extraction.code.processing',processing.__file__),('record_schema',base_record.__code__.co_filename)]:
        if p['code_hashes'].get(key)!=digest_file(path):raise ValueError('common_code_implementation_changed')
    expected_rows=[]
    for task in p['tasks']:
        if task['kind']!='code':continue
        key=signature(task['id'])[:24];result_path=out/'results'/(key+'.json')
        if not result_path.exists():continue
        result=read(result_path)
        if result['binding']!=signature({'plan':signature(p),'task':task}):raise ValueError('common_code_result_binding_changed')
        validate_saved(task['unit'],out/'work'/key,result,PROJECT_ROOT/'.venv-rag/bin/python')
        expected_rows.extend(r for r in result['records'] if r['eligible_for_chunking'])
    if corpus_for(expected_rows)['chunks']!=expected['chunks']:raise ValueError('common_code_source_gate_bypassed')
