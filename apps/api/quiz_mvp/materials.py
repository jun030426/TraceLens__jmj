"""Immutable prepared-material revisions and offering-scoped RAG adapter."""
import copy
from pathlib import Path
from rag_mvp.evidence import retrieve_evidence
from rag_mvp.retrieval import build_index
from rag_mvp.markdown_tools import split_chunk
from rag_mvp.code_regions import validate_code_chunk
from video_extraction.shared.common import read, save, signature
from .courses import ScopeError


def install_material(store,out,oid,corpus):
    store.course(oid)
    if not isinstance(corpus,dict) or corpus.get('version')!=1:
        raise ValueError('추출·검증을 마친 version=1 corpus.json이 필요합니다.')
    chunks=corpus.get('chunks')
    if not isinstance(chunks,list) or not 1<=len(chunks)<=10000:raise ValueError('자료 청크가 없거나 너무 많습니다.')
    if corpus.get('signature')!=signature({'version':1,'chunks':chunks}):raise ValueError('자료 해시 검증에 실패했습니다.')
    if any(c.get('quality')=='source_code_structure_checked' for c in chunks if isinstance(c,dict)):
        from video_extraction.pipeline.code_workflow import validate_corpus_selection
        validate_corpus_selection(corpus)
    seen=set();scoped=[]
    expanded=[]
    for c in chunks:
        if not isinstance(c,dict) or not isinstance(c.get('id'),str) or not isinstance(c.get('text'),str):
            raise ValueError('청크의 ID와 본문이 필요합니다.')
        validate_code_chunk(c)
        expanded.extend(split_chunk(c))
    if len(expanded)>10000:raise ValueError('분할 후 청크 수가 10000개를 초과합니다.')
    for c in expanded:
        if not isinstance(c,dict) or any(not isinstance(c.get(k),str) or not c[k].strip() for k in ['id','text','title','source_file']):
            raise ValueError('청크의 ID·본문·제목·원본 파일명이 필요합니다.')
        if c['id'] in seen:raise ValueError('중복 청크 ID가 있습니다.')
        seen.add(c['id'])
        if c.get('offering_id') not in (None,oid):raise ScopeError('다른 강좌에 등록된 자료입니다. 원본 추출 자료를 명시적으로 등록하세요.')
        if not isinstance(c.get('slide_number'),int) or c['slide_number']<1:raise ValueError('원본 페이지/슬라이드 번호가 필요합니다.')
        if c.get('quality') not in ['native_xml_text_coverage_checked','source_code_structure_checked']:
            raise ValueError('원문 검증 자료 또는 공통 통로에서 선별한 코드 자료만 등록할 수 있습니다.')
        source=copy.deepcopy(c)
        source.update(id=oid+':'+c['id'],origin_chunk_id=c['id'],offering_id=oid,course_id=oid)
        scoped.append(source)
    scoped_corpus={'version':1,'chunks':scoped,'offering_id':oid,'origin_signature':corpus['signature']}
    scoped_corpus['signature']=signature({'version':1,'chunks':scoped})
    relative=Path('courses')/oid/scoped_corpus['signature']/'corpus.json'
    save(out/relative,scoped_corpus)
    return store.register_material(oid,scoped_corpus['signature'],str(relative),len(scoped))


def active_material(store,out,oid):
    rows=[m for m in store.materials(oid) if m['active']]
    if not rows:raise ValueError('선택한 강좌에 자료를 먼저 등록하세요.')
    material=rows[0];path=(out/material['relative_path']).resolve()
    if not path.is_relative_to((out/'courses'/oid).resolve()):raise ScopeError('자료 저장 경로가 강좌 범위를 벗어났습니다.')
    corpus=read(path)
    if corpus.get('offering_id')!=oid or any(c.get('offering_id')!=oid for c in corpus['chunks']):raise ScopeError('자료의 강좌 정보가 일치하지 않습니다.')
    actual=signature({'version':1,'chunks':corpus['chunks']})
    if actual!=material['corpus_version'] or corpus.get('signature')!=actual:raise ValueError('저장된 자료가 변경되었습니다.')
    return path.parent,corpus


class ScopedRag:
    def __init__(self,store,out,oid,client):
        self.context=store.course(oid);self.concepts=self.context['concepts'];self.offering_id=oid
        self.out,self.corpus=active_material(store,out,oid);self.client=client

    def prepare(self):return build_index(self.out,self.corpus,self.client)

    def retrieve(self,query):
        result=retrieve_evidence(self.out,self.corpus,self.client,query)
        if any(s.get('offering_id')!=self.offering_id for s in result['sources']):raise ScopeError('다른 강좌의 검색 결과입니다.')
        return {**result,'offering_id':self.offering_id}
