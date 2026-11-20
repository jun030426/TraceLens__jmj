"""Deterministic worker crash/reclaim tests. No model or shared database calls."""

import copy
import hashlib
import json
import time
from types import SimpleNamespace

import httpx
import pytest
from lerny.ingestion_engine import TeamIngestionEngine
from lerny.ingestion_store import MODEL, PIPELINE, IngestionError, SupabaseIngestion, encoded
from lerny.ingestion_worker import Lease, process, run_once
from pydantic import SecretStr


def job():
    return {"id": "ad1868b6-5c28-45ab-a312-c18d026d36a1", "source_id": "source",
            "lease_token": "token", "pipeline_version": PIPELINE,
            "file_name": "lecture.txt", "file_path": "ingestion/raw/lecture.txt",
            "file_hash": hashlib.sha256(b"lecture").hexdigest(),
            "config": {"embedding_model": MODEL, "answer_model": "synthetic-test-only"}}


class MemoryStore:
    def __init__(self):
        self.saved, self.artifacts, self.results = {}, {}, {}
        self.live, self.published, self.downloads, self.heartbeats = True, 0, 0, 0
        self.failure = None

    def claim(self, _):
        return job()

    def heartbeat(self, _):
        self.heartbeats += 1
        return self.live

    def source(self, _):
        return {"course_id": "course", "title": "스택", "visibility": "public", "internal_use": "none"}

    def checkpoints(self, _):
        return copy.deepcopy(self.saved)

    def checkpoint(self, _, stage, output, review):
        self.saved[stage] = copy.deepcopy(output)

    def download(self, _, path, limit, check):
        check()
        self.downloads += 1
        path.write_bytes(b"lecture")
        return hashlib.sha256(b"lecture").hexdigest()

    def save_artifact(self, _, stage, value):
        self.artifacts[stage] = copy.deepcopy(value)
        return {"stage": stage}

    def load_artifact(self, _, pointer, scratch):
        return copy.deepcopy(self.artifacts[pointer["stage"]])

    def rows(self, table, **_):
        return list(self.results.get(table, {}).values())

    def upsert(self, _, table, row):
        if not self.live:
            raise IngestionError("STALE_LEASE")
        key = row.get("chunk_key", row.get("quiz_key", row.get("shorts_key")))
        self.results.setdefault(table, {})[key] = copy.deepcopy(row)

    def counts(self, _):
        return {k: len(self.results.get(k, {})) for k in
                ("course_vectors", "concept_quizzes", "shorts_scripts", "lab_quizzes")}

    def publish(self, _, counts):
        self.published += 1
        return counts

    def fail(self, _, code, retryable):
        self.failure = (code, retryable)


class Engine:
    def __init__(self, _, source, lease):
        self.lease = lease
        self.embeds = 0

    def extract(self, path, scratch):
        (scratch / "frames").mkdir()
        (scratch / "frames" / "frame.png").write_bytes(b"scratch")
        return {"text": path.read_text(), "review_items": []}

    def chunk(self, _):
        return {"chunks": [{"id": "chunk", "text": "스택은 후입선출입니다."}]}

    def embed(self, _):
        self.embeds += 1
        return [1.0] + [0.0] * 767

    def generate(self, _):
        return {"concept_quizzes": [{"quiz_key": "quiz"}], "shorts_scripts": [{"shorts_key": "shorts"}]}


def test_five_stages_publish_and_cleanup(tmp_path):
    store = MemoryStore()
    result = process(store, job(), Engine, tmp_path)
    assert set(store.saved) == {1, 2, 3, 4, 5}
    assert store.artifacts[2]["text"] == "lecture"
    assert result == {"course_vectors": 1, "concept_quizzes": 1, "shorts_scripts": 1, "lab_quizzes": 0}
    assert store.published == 1 and not list(tmp_path.iterdir())


def test_stage_two_survives_machine_reclaim_and_no_duplicate_vectors(tmp_path):
    store = MemoryStore()
    class Interrupted(Engine):
        def generate(self, _):
            raise IngestionError("SIMULATED_CRASH")
    with pytest.raises(IngestionError):
        process(store, job(), Interrupted, tmp_path)
    assert not list(tmp_path.iterdir())
    class Resume(Engine):
        def extract(self, *_):
            pytest.fail("checkpoint 2 should avoid redownload/extraction")
        def embed(self, _):
            pytest.fail("checkpoint 4 should avoid embedding again")
    process(store, {**job(), "lease_token": "replacement"}, Resume, tmp_path)
    assert store.downloads == 1 and store.counts(job())["course_vectors"] == 1


def test_partial_content_upsert_is_idempotent(tmp_path):
    store = MemoryStore()
    original = store.upsert
    def fail_shorts(j, table, row):
        if table == "shorts_scripts":
            raise IngestionError("INGESTION_CONNECTION_FAILED")
        original(j, table, row)
    store.upsert = fail_shorts
    with pytest.raises(IngestionError):
        process(store, job(), Engine, tmp_path)
    assert 5 not in store.saved
    store.upsert = original
    process(store, job(), Engine, tmp_path)
    assert store.counts(job())["concept_quizzes"] == 1


def test_heartbeat_background_and_lease_loss(tmp_path):
    store = MemoryStore()
    with Lease(store, job(), interval=0.01) as lease:
        time.sleep(0.04)
        assert store.heartbeats >= 2
        store.live = False
        time.sleep(0.04)
        with pytest.raises(IngestionError, match="STALE_LEASE"):
            lease.check()
    assert not lease.thread.is_alive()


def test_bad_hash_and_count_mismatch_never_publish(tmp_path):
    store = MemoryStore()
    with pytest.raises(IngestionError, match="FILE_HASH_MISMATCH"):
        process(store, {**job(), "file_hash": "0" * 64}, Engine, tmp_path)
    assert not store.published and not list(tmp_path.iterdir())
    store = MemoryStore()
    store.counts = lambda _: {"course_vectors": 99}
    with pytest.raises(IngestionError, match="RESULT_COUNTS_MISMATCH"):
        process(store, job(), Engine, tmp_path)
    assert not store.published and not list(tmp_path.iterdir())


def test_worker_records_failure_without_raw_exception(tmp_path):
    store = MemoryStore()
    class Failing(Engine):
        def generate(self, _):
            raise ValueError("secret must never enter logs")
    assert run_once(store, Failing, tmp_path, "test")
    assert store.failure == ("PROCESSING_FAILED", True)


def test_real_native_chunker_limit_and_holds(tmp_path, monkeypatch):
    from lerny import ingestion_engine
    cfg = SimpleNamespace(runtime_root=tmp_path, gemini_answer_model="synthetic-test-only", gemini_max_calls_per_job=80)
    monkeypatch.setattr(ingestion_engine, "settings", lambda: cfg)
    j = job()
    engine = TeamIngestionEngine(j, MemoryStore().source(j), SimpleNamespace(check=lambda: None, sleep=lambda _: None), None)
    path = tmp_path / "source.txt"
    path.write_text("스택은 후입선출 구조입니다.\n\n" * 150, encoding="utf-8")
    corpus = engine.chunk(engine.extract(path, tmp_path))
    assert len(corpus["chunks"]) > 1
    assert all(len(c["text"]) <= 1800 for c in corpus["chunks"])
    assert all(c["course_id"] == "course" for c in corpus["chunks"])
    assert "data_structures.stack" in corpus["concept_index"]


def test_postgrest_rpc_upsert_and_bounded_storage(monkeypatch, tmp_path):
    from lerny import ingestion_store
    cfg = SimpleNamespace(supabase_service_key=SecretStr("sb_secret_test"), supabase_url="https://test.supabase.co")
    monkeypatch.setattr(ingestion_store, "settings", lambda: cfg)
    requests = []
    def transport(request):
        requests.append(request)
        if "/rpc/ingestion_claim" in request.url.path:
            return httpx.Response(200, json=[job()])
        if "/storage/" in request.url.path:
            return httpx.Response(200, content=b"over-limit")
        return httpx.Response(201, json=[])
    store = SupabaseIngestion(httpx.Client(transport=httpx.MockTransport(transport)))
    assert store.claim("test")["id"] == job()["id"]
    store.upsert(job(), "concept_quizzes", {"quiz_key": "q"})
    assert "resolution=merge-duplicates" in requests[-1].headers["Prefer"]
    assert json.loads(requests[-1].content)["lease_token"] == "token"
    assert "authorization" not in requests[-1].headers
    with pytest.raises(IngestionError, match="FILE_TOO_LARGE"):
        store.download("ingestion/raw/x", tmp_path / "file", 2)
    with pytest.raises(IngestionError, match="INVALID_STORAGE_PATH"):
        store.object_url("ingestion/../private")
    store.close()


def test_artifact_json_rejects_nan():
    with pytest.raises(ValueError):
        encoded({"bad": float("nan")})


def test_team_generation_adapters_use_grounded_quiz_and_shorts(tmp_path, monkeypatch):
    from lerny import ingestion_engine
    cfg = SimpleNamespace(runtime_root=tmp_path, gemini_answer_model="synthetic-test-only", gemini_max_calls_per_job=80)
    monkeypatch.setattr(ingestion_engine, "settings", lambda: cfg)
    lease = SimpleNamespace(check=lambda: None, sleep=lambda _: None)
    engine = TeamIngestionEngine(job(), MemoryStore().source(job()), lease, None)
    source = {"id": "c1", "text": "스택은 후입선출 구조입니다.", "title": "스택", "course_id": "course",
              "concept_ids": ["data_structures.stack"], "slide_number": 1}
    counter = [0]
    def request(stage, path, payload, parse):
        data = json.loads(payload["input"][0]["text"])
        if stage == "quiz_generate_v1":
            counter[0] += 1
            answer = {"stem": f"스택 문항 {counter[0]}", "options": ["가", "나", "다", "라"], "answer_index": 0,
                      "explanation": "스택은 후입선출입니다.", "concept_id": data["concept_id"],
                      "difficulty": data["difficulty"], "difficulty_reason": "테스트 근거", "source_id": "c1",
                      "quote": "스택은 후입선출 구조입니다."}
        elif stage == "quiz_verify_v1":
            answer = {"supported": True, "single_correct": True, "explanation_supported": True,
                      "difficulty_matches": True, "answer_index": 0, "reason": "합성 검증", "explanation": "근거 확인",
                      "source_id": "c1", "quote": "스택은 후입선출 구조입니다."}
        elif stage == "shorts_verify_v1":
            units = json.loads(data["prompt"].split("\n", 1)[1])["units"]
            answer = {"units": [{"target": u["target"], "verdict": "supported",
                "evidence": [{"source_id": "c1", "quote": "스택은 후입선출 구조입니다."}]} for u in units]}
        else:
            assert stage == "grounded_shorts"
            act = {"seconds": "0-20", "visual_cue": "스택", "narration": "스택은 후입선출입니다." * 10}
            answer = {"title": "스택", "target_seconds": 50, "concept": "스택", "hook": act,
                      "body": {**act, "key_takeaways": ["후입선출"]},
                      "outro": {**act, "timestamp_reference": "강의 자료"},
                      "source_id": "c1", "quote": "스택은 후입선출 구조입니다."}
        return parse({"status": "completed", "output_text": json.dumps(answer)})
    engine.client.request = request
    result = engine.generate({"version": 1, "signature": "synthetic", "chunks": [source],
                              "concept_index": {"data_structures.stack": ["c1"]}})
    assert len(result["concept_quizzes"]) == 5 and len(result["shorts_scripts"]) == 1
    assert result["shorts_scripts"][0]["template_variables"]["lecture_script"]
    assert result["concept_quizzes"][0]["answer"]["validation"]["status"] == "model_checked"
