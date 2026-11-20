# ruff: noqa: F811 -- pytest resolves imported fixtures by name
import json
from types import SimpleNamespace

import httpx
import pytest
from lerny import rag_index, retrieval, worker
from lerny.config import Settings
from lerny.models import Chunk, Material
from pydantic import SecretStr, ValidationError
from rag_mvp.shared_retrieval import build_shared, search_shared
from rag_mvp.shared_vectors import (
    DIMENSIONS,
    MODEL,
    SharedIndexError,
    SharedVectors,
    document_key,
    from_env,
)
from sqlalchemy import select
from test_gemini_integration import configured, integration  # noqa: F401
from test_lecture_specs import api  # noqa: F401

VECTOR = [1.0] + [0.0] * 767


def test_embedding_continuation_batches_verified_lookups_and_preserves_duplicates(integration, configured, remote, monkeypatch):
    monkeypatch.setattr(configured,'rag_storage','supabase')
    monkeypatch.setattr(rag_index,'shared_store',lambda:remote[0])
    chunks=[SimpleNamespace(id=str(i),version_id='v',content=f'completed {i}',locator={}) for i in range(201)]
    for chunk in chunks:remote[1][document_key(chunk.content)]={'embedding':VECTOR}
    chunks += [SimpleNamespace(id='new'+str(i),version_id='v',content='new source',locator={}) for i in range(2)]
    calls=[]
    monkeypatch.setattr(worker,'embed',lambda texts:calls.append(texts) or [VECTOR])
    monkeypatch.setattr(rag_index,'load_local_vector',lambda _:None)
    worker.embed_chunks(iter(chunks),SimpleNamespace(add=lambda _:None))
    assert calls==[['new source']]
    reads=[body for request,body in remote[2] if request.url.path.endswith('/lerny_rag_fetch')]
    assert len(reads)==2 and all(body['p_vectors'] for body in reads)
    worker.embed_chunks(chunks,SimpleNamespace(add=lambda _:None))
    assert calls==[['new source']]
    assert len([1 for request,_ in remote[2] if request.url.path.endswith('/lerny_rag_fetch')])==4


def test_batched_embedding_resume_still_rejects_invalid_cached_vectors(integration, configured, remote, monkeypatch):
    monkeypatch.setattr(configured,'rag_storage','supabase')
    monkeypatch.setattr(rag_index,'shared_store',lambda:remote[0])
    chunk=SimpleNamespace(id='bad',content='invalid vector',version_id='v',locator={})
    remote[1][document_key(chunk.content)]={'embedding':[0.0]*768}
    monkeypatch.setattr(worker,'embed',lambda _:pytest.fail('Invalid stored vector must fail closed'))
    with pytest.raises(ValueError,match='INVALID_SHARED_EMBEDDING'):
        worker.embed_chunks([chunk],SimpleNamespace(add=lambda _:None))


@pytest.fixture
def remote():
    records, requests = {}, []

    def handle(request):
        body = json.loads(request.content)
        requests.append((request, body))
        assert request.headers["apikey"] == "sb_secret_synthetic"
        assert "authorization" not in request.headers
        if request.url.path.endswith("/rag_shared_embeddings"):
            records.setdefault(body["input_hash"], body)
            return httpx.Response(201)
        if request.url.path.endswith("/lerny_rag_fetch"):
            return httpx.Response(
                200,
                json=[
                    {
                        "input_hash": key,
                        "embedding": json.dumps(records[key]["embedding"])
                        if body["p_vectors"]
                        else None,
                    }
                    for key in body["p_keys"]
                    if key in records
                ],
            )
        if request.url.path.endswith("/lerny_rag_match"):
            rows = [
                {
                    "input_hash": key,
                    "score": sum(
                        a * b
                        for a, b in zip(records[key]["embedding"], body["p_query"], strict=True)
                    ),
                }
                for key in body["p_keys"]
                if key in records
            ]
            return httpx.Response(
                200,
                json=sorted(rows, key=lambda r: (-r["score"], r["input_hash"]))[: body["p_limit"]],
            )
        raise AssertionError("Unexpected endpoint")

    return (
        SharedVectors(
            "https://example.supabase.co",
            "sb_secret_synthetic",
            transport=httpx.MockTransport(handle),
        ),
        records,
        requests,
    )


def test_content_identity_includes_exact_input_title_and_model_profile():
    assert document_key("text") == document_key("text", "none")
    assert len({document_key("text"), document_key("text "), document_key("text", "Title")}) == 3


@pytest.mark.parametrize("vector", [[1.0], [0.0] * 768, [float("nan")] * 768, [True] * 768])
def test_invalid_vectors_never_reach_the_network(remote, vector):
    store, _, requests = remote
    with pytest.raises(ValueError):
        store.put("source", vector)
    assert not requests


def test_dedup_fetch_and_database_similarity(remote):
    store, records, _ = remote
    first = store.put("same source", VECTOR)
    store.put("same source", [2.0] + [0.0] * 767)
    second = store.put("other source", [0.0, 1.0] + [0.0] * 766)
    assert len(records) == 2
    assert store.fetch([first])[first] == VECTOR
    assert store.match([first, second], VECTOR)[0]["input_hash"] == first
    assert set(store.fetch([first, "a" * 64], include_vectors=False)) == {first}


def test_matching_combines_batches_and_scopes_every_request(remote):
    store, records, requests = remote
    keys = []
    for i in range(205):
        key = document_key(str(i))
        keys.append(key)
        records[key] = {"embedding": VECTOR if i == 204 else [0.0, 1.0] + [0.0] * 766}
    assert len(store.fetch(keys, include_vectors=False)) == 205
    assert store.match(keys, VECTOR, limit=1)[0]["input_hash"] == keys[-1]
    for request, body in requests:
        assert set(body["p_keys"]) <= set(keys)
        assert len(body["p_keys"]) <= 200


def test_failed_shared_store_does_not_return_local_or_expose_credentials():
    store = SharedVectors(
        "https://example.supabase.co",
        "private-test-token",
        transport=httpx.MockTransport(
            lambda _: httpx.Response(401, json={"secret": "do-not-print"})
        ),
    )
    with pytest.raises(SharedIndexError) as exc:
        store.fetch(["a" * 64])
    assert str(exc.value) == "SUPABASE_VECTOR_REQUEST_FAILED"


def test_response_cannot_add_unrequested_candidates():
    store = SharedVectors(
        "https://example.supabase.co",
        "private-test-token",
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json=[{"input_hash": "b" * 64, "score": 1.0}])
        ),
    )
    with pytest.raises(SharedIndexError):
        store.match(["a" * 64], VECTOR)


def test_shared_mode_requires_server_credentials():
    with pytest.raises(ValidationError):
        Settings(rag_storage="supabase")
    assert Settings().rag_storage == "local"


def test_cli_uses_unified_configuration_and_process_override(monkeypatch):
    from lerny import environment

    monkeypatch.setattr(
        environment,
        "read_env",
        lambda _: {
            "LERNY_RAG_STORAGE": "supabase",
            "SUPABASE_URL": "https://example.supabase.co",
            "SUPABASE_SECRET_KEY": "sb_secret_synthetic",
        },
    )
    monkeypatch.delenv("LERNY_RAG_STORAGE", raising=False)
    assert isinstance(from_env(), SharedVectors)
    monkeypatch.setenv("LERNY_RAG_STORAGE", "local")
    assert from_env() is None


def test_service_reuses_across_pc_ids_and_migrates_verified_local_vector(
    integration, configured, remote, monkeypatch
):
    _, session, _ = integration
    chunk = session.get(Chunk, "src_stack_01")
    rag_index.store_vector(chunk, VECTOR)
    monkeypatch.setattr(configured, "rag_storage", "supabase")
    monkeypatch.setattr(rag_index, "shared_store", lambda: remote[0])
    monkeypatch.setattr(
        worker, "embed", lambda _: pytest.fail("Existing vector must not be regenerated")
    )
    worker.embed_chunks([chunk], session)
    other_pc = SimpleNamespace(
        id="different-id", version_id="different-version", content=chunk.content, locator={}
    )
    assert rag_index.load_vector(other_pc) == VECTOR
    assert len(remote[1]) == 1
    worker.embed_chunks([other_pc], SimpleNamespace(add=lambda _: None))
    assert len(remote[1]) == 1


def test_status_and_search_keep_material_permissions(integration, configured, remote, monkeypatch):
    client, session, _ = integration
    monkeypatch.setattr(configured, "rag_storage", "supabase")
    monkeypatch.setattr(configured, "supabase_url", "https://example.supabase.co")
    monkeypatch.setattr(configured, "supabase_service_key", SecretStr("sb_secret_synthetic"))
    monkeypatch.setattr(rag_index, "shared_store", lambda: remote[0])
    monkeypatch.setattr(retrieval, "perform", lambda *a, **k: {"embeddings": [VECTOR]})
    for chunk in session.scalars(select(Chunk)):
        rag_index.store_vector(chunk, VECTOR)
    rows = retrieval.public_rows(session, "course")
    allowed = {document_key(row[0].content) for row in rows}
    response = client.get("/api/v1/courses/course/rag/status")
    assert response.status_code == 200
    assert response.json()["storage"] == "supabase"
    assert response.json()["index_ready"]
    result = retrieval.search_gemini(session, "course", "스택")
    assert result
    for request, body in remote[2]:
        if "/rpc/" in request.url.path:
            assert set(body["p_keys"]) <= allowed
    session.get(Material, "material").visibility = "private"
    session.commit()
    before = len(remote[2])
    assert retrieval.search_gemini(session, "course", "스택") == []
    assert len(remote[2]) == before


def test_missing_shared_index_stops_before_paid_query_embedding(
    integration, configured, remote, monkeypatch
):
    _, session, _ = integration
    monkeypatch.setattr(configured, "rag_storage", "supabase")
    monkeypatch.setattr(rag_index, "shared_store", lambda: remote[0])
    monkeypatch.setattr(
        retrieval, "perform", lambda *a, **k: pytest.fail("No paid query for missing index")
    )
    with pytest.raises(ValueError, match="GEMINI_INDEX_REQUIRED"):
        retrieval.search_gemini(session, "course", "스택")


def test_standalone_uses_shared_vectors_without_local_llamaindex(tmp_path, remote):
    store, records, _ = remote
    calls = []
    client = SimpleNamespace(
        embedding_model=MODEL,
        dimensions=DIMENSIONS,
        embed=lambda text, **kw: calls.append((text, kw)) or VECTOR,
    )
    corpus = {
        "signature": "corpus",
        "chunks": [
            {"id": "one", "title": "Title", "text": "source"},
            {"id": "two", "title": "Title", "text": "source"},
        ],
    }
    build_shared(tmp_path, corpus, client, store, "signature")
    assert len(calls) == 1 and len(records) == 1
    build_shared(tmp_path, corpus, client, store, "signature")
    assert len(calls) == 1
    assert len(search_shared(corpus, client, store, "question", 8)) == 2
    assert calls[-1][1] == {"query": True}
    assert not list(tmp_path.rglob("*vector_store*"))
