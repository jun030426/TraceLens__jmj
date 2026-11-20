"""Versioned boundary shared by QA and downstream learning features."""
from .corpus import load_corpus
from .retrieval import vector_search, keyword_search, fuse


def retrieve_evidence(out, corpus, client, query):
    chunks = corpus['chunks']
    hits = fuse(chunks, vector_search(out, corpus, client, query), keyword_search(chunks, query))
    return {'schema_version': 1, 'retriever_version': 'local-rag-v1',
            'corpus_version': corpus['signature'], 'query': query, 'sources': hits}


class LocalRag:
    version = 'local-rag-v1'

    def __init__(self, out, client):
        self.out, self.client = out, client
        self.corpus = load_corpus(out)

    def retrieve(self, query):
        return retrieve_evidence(self.out, self.corpus, self.client, query)
