"""Local keyword baseline plus LlamaIndex persisted vector retrieval."""
#벡터 저장·자료 검색. LlamaIndex로 벡터를 저장하고, 질문에 맞는 자료를 벡터 검색과 키워드 검색으로 찾아 합쳐
from collections import Counter
import math
import re

from video_extraction.shared.common import read, save, signature
from .corpus import canonical
from .source_context import search_text


STOP={'무엇','무엇인가요','어떻게','알려줘','설명해줘','인가요','왜','대한','해주세요','차이점은','뭐야','무슨'}


def tokens(text):
    words=re.findall(r'[a-zA-Z_]+|[가-힣]+|\d+',canonical(text).lower())
    result=[]
    for w in words:
        if w in STOP:continue
        result.append(w)
        if re.fullmatch('[가-힣]+',w) and len(w)>2:result.extend(w[i:i+2] for i in range(len(w)-1))
    return result


def keyword_search(chunks,question,limit=8):
    query=set(tokens(question));counts=[Counter(tokens(c['title']+'\n'+search_text(c))) for c in chunks]
    avg=sum(sum(c.values()) for c in counts)/max(1,len(counts));rows=[]
    for chunk,c in zip(chunks,counts):
        score=0.0;length=sum(c.values())
        for word in query:
            if not c[word]:continue
            df=sum(bool(x[word]) for x in counts);idf=math.log(1+(len(counts)-df+.5)/(df+.5))
            score+=idf*c[word]*2.5/(c[word]+1.5*(.25+.75*length/max(avg,1)))
        if score>0:rows.append({**chunk,'keyword_score':score})
    return sorted(rows,key=lambda x:(-x['keyword_score'],x['id']))[:limit]


def fuse(chunks,vector_hits,keyword_hits,limit=4):
    byid={x['id']:x for x in chunks};scores={};extra={}
    for name,items in [('vector',vector_hits),('keyword',keyword_hits)]:
        for rank,item in enumerate(items,1):
            fid=item['id']
            if fid not in byid:raise ValueError('retrieved_unknown_source')
            scores[fid]=scores.get(fid,0)+1/(60+rank)
            extra.setdefault(fid,{})[name+'_score']=item[name+'_score']
    return [{**byid[fid],**extra[fid],'fusion_score':scores[fid]} for fid in
             sorted(scores,key=lambda x:(-scores[x],x))[:limit]]


def adapter(client):
    try:
        from llama_index.core.base.embeddings.base import BaseEmbedding
        from pydantic import PrivateAttr
    except ImportError:raise RuntimeError('LlamaIndex 미설치: RAG_최소흐름_실행.command를 먼저 실행하세요.') from None
    class GeminiEmbedding2(BaseEmbedding):
        _client:object=PrivateAttr()
        def __init__(self):
            super().__init__(model_name=client.embedding_model,embed_batch_size=1)
            self._client=client
        def _get_query_embedding(self,query):return self._client.embed(query,query=True)
        async def _aget_query_embedding(self,query):return self._get_query_embedding(query)
        def _get_text_embedding(self,text):
            raise RuntimeError('Document embeddings must be explicitly precomputed with source titles.')
    return GeminiEmbedding2()


def index_signature(corpus,client):
    return signature({'corpus':corpus['signature'],'model':client.embedding_model,'dimensions':client.dimensions,
                      'format':'embedding2-question-answering-v1','index_version':2})


def build_index(out,corpus,client):
    from .code_regions import validate_code_chunk
    if not corpus['chunks']:raise ValueError('no_usable_chunks_to_embed')
    for chunk in corpus['chunks']:validate_code_chunk(chunk)
    from .shared_vectors import from_env
    shared = from_env(getattr(client, 'env_file', None))
    if shared is not None:
        from .shared_retrieval import build_shared
        return build_shared(out, corpus, client, shared, index_signature(corpus, client))
    embed=adapter(client)
    from llama_index.core import VectorStoreIndex
    from llama_index.core.schema import TextNode
    key=index_signature(corpus,client);folder=out/'indexes'/key
    if (folder/'ready.json').exists():
        if read(folder/'ready.json')['signature']!=key:raise ValueError('index_signature_mismatch')
        if read(folder/'ready.json').get('storage', 'local') == 'local':return folder
    nodes=[]
    for number,c in enumerate(corpus['chunks'],1):
        vector=client.embed(search_text(c),title=c['title'])
        metadata={k:v for k,v in c.items() if k not in ('id','text')}
        nodes.append(TextNode(id_=c['id'],text=c['text'],metadata=metadata,embedding=vector,
            excluded_embed_metadata_keys=list(metadata),excluded_llm_metadata_keys=list(metadata)))
        print(f'자료 임베딩 {number}/{len(corpus["chunks"])}',flush=True)
    index=VectorStoreIndex(nodes=nodes,embed_model=embed,show_progress=False)
    index.storage_context.persist(persist_dir=str(folder))
    save(folder/'ready.json',{'signature':key,'corpus_signature':corpus['signature'],
        'embedding_model':client.embedding_model,'dimensions':client.dimensions,'nodes':len(nodes)})
    save(out/'index-ready.json',read(folder/'ready.json'))
    return folder


def vector_search(out,corpus,client,question,limit=8):
    from .shared_vectors import from_env
    shared = from_env(getattr(client, 'env_file', None))
    if shared is not None:
        from .shared_retrieval import search_shared
        return search_shared(corpus, client, shared, question, limit)
    embed=adapter(client)
    from llama_index.core import StorageContext,load_index_from_storage
    folder=out/'indexes'/index_signature(corpus,client)
    if not (folder/'ready.json').exists():raise RuntimeError('자료 임베딩을 먼저 실행하세요: python -m rag_mvp index')
    index=load_index_from_storage(StorageContext.from_defaults(persist_dir=str(folder)),embed_model=embed)
    hits=index.as_retriever(similarity_top_k=min(limit,len(corpus['chunks']))).retrieve(question)
    return [{'id':h.node.node_id,'vector_score':float(h.score or 0)} for h in hits]
