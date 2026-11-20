"""One short, intact slide per node. Native XML coverage checked before inclusion."""
#자료 준비·검증. 기존 추출 결과에서 12개 슬라이드를 골라 원본 PPT 텍스트와 대조하고, 슬라이드별 검색 단위와 출처를 생성
import json
import re
import unicodedata
import zipfile
import xml.etree.ElementTree as ET

from . import ROOT, VERSION
from video_extraction.shared.common import digest_file, read, save, signature
from .markdown_tools import parse, split_chunk

SLIDES = (4, 8, 12, 18, 20, 22, 23, 24, 25, 26, 28, 29)
SOURCE_ID = 'chapter6'


def canonical(s):
    # Code bytes/Unicode must not be silently normalized for evidence matching.
    if '`' in s or re.search(r'(?m)^\s*~{3,}',s):return s
    return unicodedata.normalize('NFC', s).replace('\r\n', '\n')


def select_rows(rows, requested):
    result=[]
    for row in rows:
        if row['id'] not in requested:continue
        if row.get('role')!='lecture' or row.get('assets') or row.get('review_flags'):
            raise ValueError('ineligible_source:'+row['id'])
        if not row['text'].strip():raise ValueError('empty_slide:'+row['id'])
        parse(row['text'])
        if '[ILLEGIBLE]' in row['text'] or '\ufffd' in row['text']:
            raise ValueError('uncertain_source:'+row['id'])
        result.append(row)
    if len(result)!=len(requested) or {r['id'] for r in result}!=set(requested):
        raise ValueError('missing_or_duplicate_selected_slide')
    return sorted(result,key=lambda x:x['slide_number'])


def prepare(out):
    from .document_ingest import extract, chunks_for_document
    source=ROOT/'outputs/extraction-compare/native'
    manifest=read(source/'manifest.json')
    item=next(x for x in manifest if x['source_id']==SOURCE_ID)
    original=ROOT/item['original_path']
    if digest_file(original)!=item['sha256']:raise ValueError('source_ppt_changed')
    rows=[json.loads(line) for line in (source/'slides.jsonl').read_text().splitlines()]
    selected=select_rows(rows,[f'{SOURCE_ID}-s{n:03}' for n in SLIDES])
    chunks=[];coverage=[];review=[]
    document=extract(original)
    with zipfile.ZipFile(original) as deck:
        for row in selected:
            part=next((u['source_part'] for u in document['units'] if u['page']==row['slide_number']),None)
            if part is None:raise ValueError('native_slide_not_available:'+row['id'])
            xml=ET.fromstring(deck.read(part))
            runs=[canonical(x.text.strip()) for x in xml.iter('{http://schemas.openxmlformats.org/drawingml/2006/main}t') if x.text and x.text.strip()]
            missing=[t for t in runs if t not in canonical(row['text'])]
            if missing:raise ValueError('native_text_coverage_failed:'+row['id'])
            coverage.append({'slide_id':row['id'],'checked_text_runs':len(runs),'missing':[]})
            native_chunks,native_held,_=chunks_for_document(document,pages={row['slide_number']})
            # Where code is present, use literal native runs, not earlier flattened slide text.
            if any(c.get('kind')=='code' for c in native_chunks+native_held):
                chunks.extend({**c,'title':row['title'],'parent_slide_id':row['id'],
                    'course_id':'local-data-structures'} for c in native_chunks)
                review.extend(native_held)
                continue
            chunks.extend(split_chunk({'id':row['id'],'text':row['text'],'title':row['title'],
              'source_id':SOURCE_ID,'source_file':item['filename'],'source_sha256':item['sha256'],
              'slide_number':row['slide_number'],'course_id':'local-data-structures',
              'quality':'native_xml_text_coverage_checked','scope':'local_mvp_not_student_publication'}))
    fingerprint=signature({'version':VERSION,'chunks':chunks})
    data={'version':VERSION,'signature':fingerprint,'chunks':chunks,'source_sha256':item['sha256'],
      'coverage':coverage,'limits':'Text-only selected slides; original factual accuracy and visual reading order are not independently guaranteed.'}
    path=out/'corpus.json'
    if path.exists() and read(path)['signature']!=fingerprint:
        raise ValueError('frozen_corpus_changed_use_new_output')
    save(path,data)
    save(out/'review-queue.json',review)
    return data


def load_corpus(out):
    data=read(out/'corpus.json')
    if signature({'version':data['version'],'chunks':data['chunks']})!=data['signature']:
        raise ValueError('corpus_integrity_failed')
    if data.get('pipeline')=='common-source-code-v1':
        from video_extraction.pipeline.code_workflow import validate_corpus_selection
        validate_corpus_selection(data)
    for chunk in data['chunks']:
        from .code_regions import validate_code_chunk
        validate_code_chunk(chunk)
        if chunk.get('kind')!='code':parse(chunk['text'])
    return data
