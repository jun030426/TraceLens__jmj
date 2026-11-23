"""Synthetic local integration tests. No live database, secrets, or provider requests."""

import json
from datetime import timedelta
from types import SimpleNamespace

import httpx
import pytest
from lerny import gemini_provider as provider
from lerny import worker
from lerny.auth import COOKIE
from lerny.config import Settings, settings
from lerny.inference import job_context, perform
from lerny.models import (
    ChatMessage,
    Chunk,
    Enrollment,
    Job,
    Material,
    MaterialVersion,
    Section,
    now,
)
from lerny.narration_lessons import narration_job
from lerny.rag_answers import answer_job
from lerny.rag_index import load_vector, store_vector
from lerny.retrieval import search_public
from pydantic import SecretStr
from sqlalchemy import select
from test_lecture_specs import api  # noqa: F401 -- isolated SQLite, auth, and network blocker

VECTOR = [1.0] + [0.0] * 767


@pytest.fixture
def configured(tmp_path, monkeypatch):
    # Source/response behavior only; shared pacing has isolated-DB tests of its own.
    monkeypatch.setattr(provider, "reserve_slot", lambda *args: ("test", "lease"))
    monkeypatch.setattr(provider, "release_slot", lambda *args: None)
    monkeypatch.setattr(provider, "block_until", lambda *args: None)
    config = settings()
    monkeypatch.setattr(config, "runtime_root", tmp_path)
    monkeypatch.setattr(config, "ai_provider", "gemini")
    monkeypatch.setattr(config, "gemini_calls_enabled", True)
    monkeypatch.setattr(config, "gemini_api_key", SecretStr("synthetic-test-key"))
    monkeypatch.setattr(config, "gemini_embedding_api_key", SecretStr(""))
    monkeypatch.setattr(config, "gemini_content_api_key", SecretStr(""))
    monkeypatch.setattr(config, "rag_storage", "local")
    monkeypatch.setattr(config, "file_storage", "local")
    monkeypatch.setattr(config, "deployment", "local")
    monkeypatch.setattr(config, "dedicated_worker", False)
    return config


@pytest.fixture
def integration(api, configured, monkeypatch):  # noqa: F811 -- pytest fixture injection
    client, session, tokens = api
    session.connection().connection.driver_connection.create_function(
        "pg_advisory_xact_lock", 1, lambda _x: None
    )
    monkeypatch.setattr(worker, "engine", lambda: session.bind)
    # Worker completion heartbeats must use the same isolated database too.
    import lerny.db as database
    monkeypatch.setattr(database, "engine", lambda: session.bind)
    return client, session, tokens


@pytest.fixture
def fake_provider(monkeypatch):
    calls = []

    def request(path, payload, parse):
        calls.append((path, payload))
        if path.endswith(":embedContent"):
            return parse({"embedding": {"values": VECTOR}})
        data = json.loads(payload["input"].rsplit("\n", 1)[1])
        if "source_fragments" in data:
            result={'units':[{'target':u['target'],'verdict':'supported',
                'evidence_ids':[data['source_fragments'][0]['id']]} for u in data['units']]}
        elif "units" in data:
            result = {
                "units": [
                    {
                        "target": u["target"],
                        "verdict": "supported",
                        "evidence": [
                            {
                                "source_id": u["source_ids"][0],
                                "quote": next(
                                    s["text"]
                                    for s in data["sources"]
                                    if s["source_id"] == u["source_ids"][0]
                                ),
                            }
                        ],
                    }
                    for u in data["units"]
                ]
            }
        elif "target_seconds" in data and "retrieved_excerpts" in data:
            source = data["retrieved_excerpts"][0]
            act = {"seconds": "00:00 ~ 00:15", "visual_cue": "Synthetic graphic", "narration": source["text"]}
            result = {
                "title": "Synthetic lesson", "target_seconds": data["target_seconds"], "concept": data["topic"],
                "hook": act, "body": {**act, "key_takeaways": [source["text"]]},
                "outro": {**act, "timestamp_reference": ""},
                "source_id": source["source_id"], "quote": source["text"],
            }
        elif "source_snapshot_id" in data:
            source = data["sources"][0]
            result = {
                "schema_version": "lerny.lesson-draft.v1",
                "request_id": data["request_id"],
                "source_snapshot_id": data["source_snapshot_id"],
                "generation_status": "draft",
                "lesson": {
                    "title": data["concept_name"],
                    "language": "ko-KR",
                    "narration": [source["text"]],
                    "key_facts": [source["text"]],
                    "target_duration_seconds": data["target_duration_seconds"],
                },
                "citations": [
                    {
                        "target": f"/lesson/{field}/0",
                        "source_id": source["source_id"],
                        "quote": source["text"],
                    }
                    for field in ("narration", "key_facts")
                ],
                "reason": "",
            }
        else:
            source = data["sources"][0]
            result = {
                "answerable": True,
                "claims": [
                    {
                        "text": source["text"],
                        "source_id": source["source_id"],
                        "quote": source["text"],
                    }
                ],
                "reason": "",
            }
        return parse({"status": "completed", "output_text": json.dumps(result)})

    monkeypatch.setattr(provider, "request", request)
    return calls


def index_all(session):
    for chunk in session.scalars(select(Chunk)):
        store_vector(chunk, VECTOR)


def post_lesson(client, key="lesson-one"):
    return client.post(
        "/api/v1/courses/course/narration-lessons",
        headers={"Idempotency-Key": key},
        json={
            "concept_id": "concept_stack",
            "learning_objective": "Explain the stack rule",
            "target_duration_seconds": 45,
        },
    )


def test_api_queue_worker_preview_idempotency(integration, fake_provider):
    client, session, _ = integration
    response = client.post(
        "/api/v1/courses/course/rag/reindex", headers={"Idempotency-Key": "index-one"}
    )
    assert response.status_code == 202, response.text
    assert worker.run_once(response.json()["job_id"])
    session.expire_all()
    assert session.get(Job, response.json()["job_id"]).status == "succeeded"
    assert client.get("/api/v1/courses/course/rag/status").json()["index_ready"]
    first = post_lesson(client)
    assert first.status_code == 202, first.text
    assert post_lesson(client).json()["job_id"] == first.json()["job_id"]
    assert worker.run_once(first.json()["job_id"])
    session.expire_all()
    response = client.get(first.json()["poll_url"])
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["status"] == "succeeded", result
    assert result["result"]["validation"] == "model_reviewed"
    assert result["video_plan"]["type"] == "lerny_studio_plan"
    assert result["render_settings"]["voice_id"] == "2ce38bee20b645d89ec69c06a1d73621"
    assert result["render_settings"]["avatar_id"] == "0522eeb015a64c95a7564ddbb55c93b3"
    assert result["render_settings"]["engine"] == "avatar_v"
    assert result["render_settings"]["resolution"] == "1080p"
    assert result["render_settings"]["motion_prompt_applied"] is False
    assert result["video_generated"] is False and result["publication_allowed"] is False
    slides_url = first.json()["poll_url"] + "/slides-preview"
    narration = result["result"]["draft"]["lesson"]["narration"]
    mapping = {"slides": [{"asset_id": "reviewed-image", "script": " ".join(narration)}]}
    assert client.post(slides_url, json=mapping).json()["heygen_request"]["type"] == "studio"
    mapping["slides"][0]["script"] = "강의와 다른 대본"
    assert client.post(slides_url, json=mapping).status_code == 409
    assert all(
        path == "interactions" or path.endswith(":embedContent") for path, _ in fake_provider
    )
    assert client.get("/api/v1/jobs/" + result["job_id"]).status_code == 404
    session.get(Material, "material").visibility = "private"
    session.commit()
    assert client.get(first.json()["poll_url"]).status_code == 409


@pytest.mark.parametrize("role", ["student", "outsider"])
def test_staff_only_routes(integration, role):
    client, _, tokens = integration
    client.cookies.set(COOKIE, tokens[role][0])
    client.headers["X-CSRF-Token"] = tokens[role][1]
    assert post_lesson(client).status_code == 404
    assert client.get("/api/v1/courses/course/rag/status").status_code == 404


def test_disabled_provider_cannot_enqueue(integration, configured):
    client, session, _ = integration
    configured.gemini_calls_enabled = False
    assert post_lesson(client).status_code == 409
    assert session.scalar(select(Job).where(Job.kind == "narration_lesson")) is None


def test_index_keeps_qwen_and_detects_source_change(integration, fake_provider):
    _, session, _ = integration
    chunk = session.get(Chunk, "src_stack_01")
    chunk.embedding, chunk.embedding_model = [0.5, 0.5], "qwen3-embedding:0.6b"
    worker.embed_chunks([chunk], session)
    assert chunk.embedding == [0.5, 0.5] and chunk.embedding_model == "qwen3-embedding:0.6b"
    assert load_vector(chunk) == VECTOR
    chunk.content += " changed"
    assert load_vector(chunk) is None
    with pytest.raises(ValueError, match="GEMINI_INDEX_REQUIRED"):
        search_public(session, "course", "rule")


@pytest.mark.parametrize(
    "field,value",
    [
        ("visibility", "private"),
        ("deleted", True),
        ("active_version_id", None),
        ("internal_use", "validation_grading"),
    ],
)
def test_revoked_or_private_sources_never_reach_provider(integration, fake_provider, field, value):
    _, session, _ = integration
    index_all(session)
    setattr(session.get(Material, "material"), field, value)
    session.flush()
    assert search_public(session, "course", "rule") == []
    assert fake_provider == []


def test_wrong_course_never_searches_cached_vectors(integration, fake_provider):
    _, session, _ = integration
    index_all(session)
    assert search_public(session, "foreign-course", "rule") == []
    assert fake_provider == []


def test_private_extract_stays_local(integration, fake_provider, monkeypatch):
    _, session, _ = integration
    material = session.get(Material, "material")
    material.visibility = "private"
    version = session.get(MaterialVersion, "version")
    monkeypatch.setattr(worker, "extract", lambda *_: [("PRIVATE_ANSWER_KEY", {"page": 1})])
    job = Job(
        owner_id="teacher", course_id="course", kind="extract", payload={"version_id": version.id}
    )
    session.add(job)
    session.flush()
    worker.extract_job(session, job)
    assert fake_provider == []


def test_pending_ollama_jobs_are_not_taken_by_gemini_worker(integration):
    _, session, _ = integration
    job = Job(owner_id="teacher", course_id="course", kind="chat", payload={})
    session.add(job)
    session.flush()
    job.payload = {"_ai_provider": "ollama"}
    session.commit()
    assert worker.run_once(job.id) is False
    assert job.status == "queued"


def test_bad_quote_prevents_video_request(integration, fake_provider, monkeypatch):
    client, session, _ = integration
    index_all(session)
    original = worker.model_json

    def tampered(prompt, schema):
        out = original(prompt, schema)
        if "quote" in out:
            out["quote"] = "invented citation"
        return out

    monkeypatch.setattr(worker, "model_json", tampered)
    response = post_lesson(client)
    job = session.get(Job, response.json()["job_id"])
    with pytest.raises(ValueError, match="INVALID_CITATION"):
        narration_job(session, job)


def test_semantic_rejection_holds_draft(integration, fake_provider, monkeypatch):
    client, session, _ = integration
    index_all(session)
    original = worker.model_json

    def reject(prompt, schema):
        out = original(prompt, schema)
        if "units" in out:
            out["units"][0]["verdict"] = "unsupported"
        return out

    monkeypatch.setattr(worker, "model_json", reject)
    response = post_lesson(client)
    job = session.get(Job, response.json()["job_id"])
    result = narration_job(session, job)
    assert result["validation"] == "held"


def test_chat_memory_is_student_section_thread_and_epoch_scoped(integration, fake_provider):
    _, session, _ = integration
    from publication_fixtures import published
    session.get(Material,"material").kind="lecture"
    published(session,"course")
    index_all(session)
    session.add(Section(id="section", course_id="course", title="section"))
    session.flush()
    session.add(
        Enrollment(student_id="student", section_id="section", course_id="course", status="active")
    )
    for student, thread, epoch, text in [
        ("student", "thread", 1, "OWN_CONTEXT"),
        ("outsider", "thread", 1, "FOREIGN_STUDENT"),
        ("student", "old-thread", 1, "OTHER_THREAD"),
        ("student", "thread", 0, "REVOKED_CONTEXT"),
    ]:
        session.add(
            ChatMessage(
                student_id=student,
                section_id="section",
                thread_id=thread,
                question=text,
                answer={"answer": text},
                access_epoch=epoch,
                created_at=now() - timedelta(minutes=1),
            )
        )
    message = ChatMessage(
        student_id="student",
        section_id="section",
        thread_id="thread",
        question="stack rule",
        access_epoch=1,
    )
    session.add(message)
    session.flush()
    job = Job(
        owner_id="student", course_id="course", kind="chat", payload={"message_id": message.id}
    )
    session.add(job)
    session.flush()
    result = answer_job(session, job)
    assert result["answer_kind"] == "grounded"
    prompt = next(p["input"] for path, p in fake_provider if path == "interactions")
    assert "OWN_CONTEXT" in prompt
    assert all(x not in prompt for x in ("FOREIGN_STUDENT", "OTHER_THREAD", "REVOKED_CONTEXT"))


def test_provider_cache_payload_and_no_fallback(configured, monkeypatch):
    calls = []
    original_client = httpx.Client

    def transport(req):
        calls.append(json.loads(req.content))
        assert req.url.host == "generativelanguage.googleapis.com"
        return httpx.Response(200, json={"embedding": {"values": VECTOR}})

    monkeypatch.setattr(
        provider.httpx,
        "Client",
        lambda **kwargs: original_client(transport=httpx.MockTransport(transport), **kwargs),
    )
    with job_context(SimpleNamespace(id="test", payload={})):
        assert perform("embed", {"input": ["one", "two"]})["embeddings"] == [VECTOR, VECTOR]
        perform("embed", {"input": ["one"]})
        perform("embed", {"input": ["question"], "task": "query"})
    assert len(calls) == 3
    assert calls[0]["content"]["parts"][0]["text"] == "title: none | text: one"
    assert calls[2]["content"]["parts"][0]["text"] == "task: question answering | query: question"
    assert calls[0]["embedContentConfig"] == {"outputDimensionality": 768, "autoTruncate": False}
    for path in configured.runtime_root.rglob("*.json"):
        assert "synthetic-test-key" not in path.read_text()


def test_uncertain_call_not_automatically_repeated(configured, monkeypatch):
    calls = []
    original_client = httpx.Client

    def transport(req):
        calls.append(req)
        raise httpx.ReadTimeout("synthetic timeout")

    monkeypatch.setattr(
        provider.httpx,
        "Client",
        lambda **kwargs: original_client(transport=httpx.MockTransport(transport), **kwargs),
    )
    with job_context(SimpleNamespace(id="test", payload={})):
        for _ in range(2):
            with pytest.raises(ValueError, match="GEMINI_CALL_UNCERTAIN"):
                perform("embed", {"input": ["same"]})
    assert len(calls) == 1


def test_source_embedding_budget_resumes_and_does_not_raise_content_budget(configured, monkeypatch):
    monkeypatch.setattr(configured, "gemini_max_calls_per_job", 1)
    calls = []
    original_client = httpx.Client

    def transport(req):
        calls.append(req)
        return httpx.Response(200, json={"embedding": {"values": VECTOR}})

    monkeypatch.setattr(provider.httpx, "Client", lambda **kwargs: original_client(
        transport=httpx.MockTransport(transport), **kwargs))
    context = SimpleNamespace(id="source-budget", payload={})
    with job_context(context):
        perform("embed", {"input": ["one"]})
        with pytest.raises(ValueError, match="GEMINI_CALL_BUDGET_EXCEEDED"):
            perform("embed", {"input": ["two"]})
    with job_context(context), provider.embedding_call_budget(2):
        assert perform("embed", {"input": ["one", "two"]})["embeddings"] == [VECTOR, VECTOR]
        with pytest.raises(ValueError, match="GEMINI_CALL_BUDGET_EXCEEDED"):
            perform("embed", {"input": ["three"]})
        with pytest.raises(ValueError, match="GEMINI_CALL_BUDGET_EXCEEDED"):
            provider.request("interactions", {"input": "content"}, lambda x: x)
    # Scope cleanup restores the ordinary cap for unrelated jobs.
    with job_context(SimpleNamespace(id="ordinary-budget", payload={})):
        perform("embed", {"input": ["one"]})
        with pytest.raises(ValueError, match="GEMINI_CALL_BUDGET_EXCEEDED"):
            perform("embed", {"input": ["two"]})
    assert len(calls) == 3


@pytest.mark.parametrize("count", [-1, 5001, True, 2.5])
def test_embedding_source_budget_is_bounded(count):
    with pytest.raises(ValueError, match="EMBEDDING_SOURCE_BUDGET_EXCEEDED"):
        with provider.embedding_call_budget(count):
            pytest.fail("Invalid source size must stop before execution")


@pytest.mark.parametrize("storage", ["local", "supabase"])
def test_worker_embedding_budget_covers_unique_source_chunks(configured, monkeypatch, storage):
    from lerny import rag_index
    from lerny.inference import current_material_version
    monkeypatch.setattr(configured, "gemini_max_calls_per_job", 1)
    monkeypatch.setattr(configured, "rag_storage", storage)
    calls, stored = [], []
    original_client = httpx.Client

    def transport(req):
        calls.append(current_material_version())
        return httpx.Response(200, json={"embedding": {"values": VECTOR}})

    monkeypatch.setattr(provider.httpx, "Client", lambda **kwargs: original_client(
        transport=httpx.MockTransport(transport), **kwargs))
    monkeypatch.setattr(rag_index, "indexed_ids", lambda *a, **k: set())
    monkeypatch.setattr(rag_index, "load_local_vector", lambda _: None)
    monkeypatch.setattr(rag_index, "store_vector", lambda chunk, vector: stored.append(chunk.content))
    chunks = [SimpleNamespace(id=str(i), content=text, version_id=version) for i, (text, version) in
              enumerate([("one", "first"), ("two", "second"), ("one", "first")])]
    with job_context(SimpleNamespace(id="worker-source-budget", payload={})):
        worker.embed_chunks(chunks, SimpleNamespace(add=lambda _: None))
        assert current_material_version() is None
    assert calls == ["first", "second"]
    assert stored == (["one", "two", "one"] if storage == "local" else ["one", "two"])


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_explicit_temporary_provider_rejection_can_resume(configured, monkeypatch, status):
    clock = [1000.0]
    monkeypatch.setattr(provider.time, "time", lambda: clock[0])
    calls = []
    original_client = httpx.Client
    def transport(req):
        calls.append(req)
        return httpx.Response(status, json={"error": {"message": "temporary"}}) if len(calls) == 1 else httpx.Response(200, json={"embedding": {"values": VECTOR}})
    monkeypatch.setattr(provider.httpx, "Client", lambda **kwargs: original_client(
        transport=httpx.MockTransport(transport), **kwargs))
    with job_context(SimpleNamespace(id="temporary", payload={})):
        with pytest.raises(ValueError, match="GEMINI_(RATE_LIMITED|TEMPORARILY_UNAVAILABLE)"):
            perform("embed", {"input": ["same"]})
        with pytest.raises(provider.ProviderDeferred):
            perform("embed", {"input": ["same"]})
        assert len(calls) == 1
        clock[0] += 61
        assert perform("embed", {"input": ["same"]})["embeddings"] == [VECTOR]
        assert perform("embed", {"input": ["same"]})["embeddings"] == [VECTOR]
    assert len(calls) == 2


def test_worker_schedules_temporary_provider_error_without_busy_loop(integration, monkeypatch):
    from lerny import weekly_content as automatic
    _, session, _ = integration
    monkeypatch.setattr(worker, "heartbeat", lambda *args: None)
    def unavailable(*args):
        raise ValueError("GEMINI_TEMPORARILY_UNAVAILABLE")
    monkeypatch.setattr(automatic, "generate_job", unavailable)
    job = Job(owner_id="teacher", course_id="course", kind="weekly_content", payload={})
    session.add(job); session.commit()
    assert worker.run_once(job.id)
    session.expire_all()
    assert job.status == "queued" and job.error_code == "GEMINI_TEMPORARILY_UNAVAILABLE"
    assert worker.run_once(job.id) is False


def test_quota_retry_after_defers_other_jobs_without_extra_requests(configured, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(provider.time, "time", lambda: clock[0])
    calls = []
    original_client = httpx.Client
    def transport(req):
        calls.append(req)
        return (httpx.Response(429, headers={"Retry-After":"11480"}, json={"error":{}})
                if len(calls)==1 else httpx.Response(200,json={"embedding":{"values":VECTOR}}))
    monkeypatch.setattr(provider.httpx,"Client",lambda **kwargs:original_client(
        transport=httpx.MockTransport(transport),**kwargs))
    for name in ["quota-first","quota-second"]:
        with job_context(SimpleNamespace(id=name,payload={})):
            with pytest.raises(provider.ProviderDeferred) as pending:
                provider.perform("embed",{"input":["quota evidence"]})
            assert pending.value.retry_at == 12480
    assert len(calls)==1
    clock[0]=12481
    with job_context(SimpleNamespace(id="quota-first",payload={})):
        assert provider.perform("embed",{"input":["quota evidence"]})["embeddings"]
    assert len(calls)==2


def test_daily_quota_does_not_exhaust_job_retries(integration,monkeypatch):
    from lerny import weekly_content as automatic
    from lerny.models import now
    _,session,_=integration
    deadline=now().timestamp()+11480
    monkeypatch.setattr(worker,"heartbeat",lambda *args:None)
    def unavailable(*args):raise provider.ProviderDeferred("GEMINI_RATE_LIMITED",deadline)
    monkeypatch.setattr(automatic,"generate_job",unavailable)
    job=Job(owner_id="teacher",course_id="course",kind="weekly_content",payload={},attempt=8)
    session.add(job);session.commit()
    assert worker.run_once(job.id)
    session.expire_all()
    from datetime import UTC
    stored = job.lease_until.replace(tzinfo=UTC) if job.lease_until.tzinfo is None else job.lease_until
    assert job.status=="queued" and abs(stored.timestamp()-deadline)<1
    assert worker.run_once(job.id) is False


@pytest.mark.parametrize(
    "vector", [[0.0] * 768, [1.0], [True] + [0.0] * 767, [float("nan")] + [0.0] * 767]
)
def test_invalid_vectors_fail_closed(vector):
    with pytest.raises(ValueError, match="INVALID_GEMINI_EMBEDDING"):
        provider.normalized_vector(vector)


def test_provider_not_activated_by_default():
    assert Settings().ai_provider == "ollama"
    assert Settings().gemini_calls_enabled is False


def test_ollama_embedding_and_retrieval_remain_available(integration, configured, monkeypatch):
    from lerny import retrieval

    _, session, _ = integration
    configured.ai_provider = "ollama"
    monkeypatch.setattr(worker, "embed", lambda texts: [[1.0, 0.0] for _ in texts])
    monkeypatch.setattr(retrieval, "embed", lambda texts: [[1.0, 0.0] for _ in texts])
    chunks = list(session.scalars(select(Chunk)))
    worker.embed_chunks(chunks, session)
    session.flush()
    assert all(c.embedding_model == "qwen3-embedding:0.6b" for c in chunks)
    assert len(retrieval.search_public(session, "course", "stack")) == 2


def test_quiz_uses_gemini_without_copying_teammate_database(integration, monkeypatch):
    from lerny.assessment import generate_job
    from lerny.models import Question

    _, session, _ = integration
    index_all(session)
    blind_checks = []

    def request(path, payload, parse):
        if path.endswith(":embedContent"):
            return parse({"embedding": {"values": VECTOR}})
        data = json.loads(payload["input"].rsplit("\n", 1)[1])
        if "topic" in data:
            source = data["retrieved_excerpts"][0]
            result = {"concept_id": "concept_stack", "question": "Explain synthetic rule " + data["difficulty"],
                      "options": ["rule", "wrong1", "wrong2", "wrong3"], "correct_index": 0,
                      "explanation": source["text"], "distractor_rationales": ["supported", "wrong", "wrong", "wrong"],
                      "source_id": source["source_id"], "quote": source["text"]}
        elif "concept" in data:
            ids = [s["chunk_id"] for s in data["evidence"]]
            items = []
            for i in range(3):
                items.append(
                    {
                        "kind": "mcq" if i < 2 else "essay",
                        "prompt": f"Explain synthetic rule {i}",
                        "options": ["rule", "wrong1", "wrong2", "wrong3"] if i < 2 else [],
                        "answer_index": 0,
                        "explanation": "Synthetic public stack rule 1",
                        "criteria": [] if i < 2 else ids[:2],
                        "sources": [{"chunk_id": ids[0]}],
                    }
                )
            result = items[-1]
        elif "options" in data:
            blind_checks.append(data)
            assert "answer_index" not in data and "explanation" not in data
            result = {"correct_options": [data["options"][0]]}
        else:
            assert data["private_validation_only"] == []
            result = {"supported": True, "unambiguous": True, "answer_correct": True}
        return parse({"status": "completed", "output_text": json.dumps(result)})

    monkeypatch.setattr(provider, "request", request)
    job = Job(
        owner_id="teacher",
        course_id="course",
        kind="questions",
        payload={"concept_id": "concept_stack"},
    )
    session.add(job)
    session.flush()
    result = generate_job(session, job)
    assert result["count"] == 3 and len(blind_checks) == 2
    assert len(list(session.scalars(select(Question)))) == 3


def test_changed_source_during_chat_is_rejected(integration, fake_provider, monkeypatch):
    _, session, _ = integration
    from publication_fixtures import published
    session.get(Material,"material").kind="lecture"
    published(session,"course")
    index_all(session)
    session.add(Section(id="section", course_id="course", title="section"))
    session.flush()
    session.add(
        Enrollment(student_id="student", section_id="section", course_id="course", status="active")
    )
    message = ChatMessage(
        student_id="student",
        section_id="section",
        thread_id="thread",
        question="rule",
        access_epoch=1,
    )
    session.add(message)
    session.flush()
    job = Job(
        owner_id="student", course_id="course", kind="chat", payload={"message_id": message.id}
    )
    session.add(job)
    session.flush()
    original = worker.model_json

    def revoke(prompt, schema):
        out = original(prompt, schema)
        session.get(Material, "material").visibility = "private"
        session.flush()
        return out

    monkeypatch.setattr(worker, "model_json", revoke)
    with pytest.raises(ValueError, match="SOURCE_CHANGED"):
        answer_job(session, job)
    assert message.answer is None


def test_reindex_continues_in_bounded_batches(integration, configured, fake_provider, monkeypatch):
    client, session, _ = integration
    monkeypatch.setattr(configured, "gemini_max_calls_per_job", 1)
    for number in range(2):
        response = client.post(
            "/api/v1/courses/course/rag/reindex",
            headers={"Idempotency-Key": f"batch-{number}"},
        )
        assert response.status_code == 202
        assert worker.run_once(response.json()["job_id"])
        session.expire_all()
        result = session.get(Job, response.json()["job_id"]).result
        assert result["indexed_chunks"] == number + 1
        assert result["remaining_chunks"] == 1 - number
        assert result["index_ready"] == (number == 1)
    assert len(fake_provider) == 2


def test_shared_narration_contract_matches_server():
    from pathlib import Path

    from lerny.narration_lessons import LessonDraft

    root = Path(__file__).resolve().parents[3] / "docs/contracts"
    schema = json.loads((root / "narration-lesson.schema.json").read_text(encoding="utf-8"))
    example = json.loads((root / "narration-lesson.example.json").read_text(encoding="utf-8"))
    assert schema == LessonDraft.model_json_schema()
    draft = LessonDraft.model_validate(example)
    assert draft.generation_status == "draft"
    assert draft.lesson.language == "ko-KR"
