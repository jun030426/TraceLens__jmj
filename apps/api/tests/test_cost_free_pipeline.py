"""Real worker/storage/retrieval flow with synthetic AI responses and blocked HTTP.

No private environment or shared database is needed. These tests check plumbing,
not the semantic quality of an embedding/model or a rendered HeyGen video.
"""

import json
from contextlib import contextmanager

import pytest
from pydantic import SecretStr
from sqlalchemy import select

from lerny import gemini_provider as provider, video_worker, worker
from lerny.models import Chunk, Concept, ConceptVideo, ContentGeneration, Job, Material, MaterialVersion, Question
from lerny.rag_index import load_vector
from lerny.retrieval import search_public
from test_gemini_integration import (  # noqa: F401 -- isolated DB and HTTP blocker
    api, configured, fake_provider, integration,
)

SOURCE = "stack removes the newest item first.\nqueue removes the oldest item first."


@pytest.fixture
def synthetic_ai(fake_provider, monkeypatch):
    fallback = provider.request

    def request(path, payload, parse):
        if path.endswith(":embedContent"):
            return fallback(path, payload, parse)
        data = json.loads(payload["input"].rsplit("\n", 1)[1])
        properties = payload["response_format"]["schema"].get("properties", {})
        if "assessment_task" in data or "single_correct" in properties:
            from quiz_provider_fixture import quiz_response
            result = quiz_response(data)
        elif "concepts" in properties:
            result = {"concepts": [{"name": name, "quote": line, "version_id":data[0]["version_id"]}
                                   for name, line in zip(("stack", "queue"), SOURCE.splitlines())]}
        elif "programs" in properties:
            result = {"programs": []}
        elif "difficulty" in data and "retrieved_excerpts" in data:
            source = data["retrieved_excerpts"][0]
            result = {"concept_id": data["topic"], "question": f"{data['difficulty']}: What does the source say?",
                      "options": [source["text"], "Unused option A", "Unused option B", "Unused option C"],
                      "correct_index": 0, "explanation": source["text"],
                      "distractor_rationales": ["Source", "Synthetic distractor", "Synthetic distractor", "Synthetic distractor"],
                      "source_id": source["source_id"], "quote": source["text"]}
        elif "criteria" in properties:
            ids = [source["chunk_id"] for source in data["evidence"][:2]]
            result = {"kind": "essay", "prompt": "Explain the two source statements.", "options": [],
                      "answer_index": 0, "explanation": data["evidence"][0]["text"],
                      "criteria": ids, "sources": [{"chunk_id": key} for key in ids]}
        elif "correct_options" in properties:
            result = {"correct_options": [data["options"][0]]}
        elif "supported" in properties:
            result = {"supported": True, "unambiguous": True, "answer_correct": True}
        elif "target_seconds" in data and "retrieved_excerpts" in data:
            # The integrated 50-second profile validates 360-400 characters.
            # Keep the synthetic provider within that real production contract.
            source = data["retrieved_excerpts"][0]
            narration = ((source["text"] + " ") * 20)[:375]
            acts = [{"seconds": span, "visual_cue": "Synthetic graphic", "narration": text}
                    for span, text in zip(("00:00 ~ 00:15", "00:15 ~ 00:35", "00:35 ~ 00:50"),
                                          (narration[:125], narration[125:250], narration[250:]))]
            result = {"title": "Synthetic lesson", "target_seconds": data["target_seconds"],
                      "concept": data["topic"], "hook": acts[0],
                      "body": {**acts[1], "key_takeaways": [source["text"]]},
                      "outro": {**acts[2], "timestamp_reference": ""},
                      "source_id": source["source_id"], "quote": source["text"]}
        else:
            return fallback(path, payload, parse)
        fake_provider.append((path, payload))
        return parse({"status": "completed", "output_text": json.dumps(result)})

    monkeypatch.setattr(provider, "request", request)
    return fake_provider


def run_job(session, job):
    job_id = job.id
    assert worker.run_once(job_id)
    session.expire_all()
    result = session.get(Job, job_id)
    assert result.status == "succeeded", (result.kind, result.status, result.error_code)
    return result


def test_extract_embed_retrieve_review_bank_without_video_jobs(
    integration, configured, synthetic_ai, tmp_path, monkeypatch,
):
    client, session, _ = integration
    monkeypatch.setattr(configured, "automatic_learning_enabled", True)
    monkeypatch.setattr(configured, "heygen_calls_enabled", False)
    # A populated key must not bypass the explicit disabled-call gate.
    monkeypatch.setattr(configured, "heygen_api_key", SecretStr("synthetic-heygen-key"))
    material = session.get(Material, "material")
    material.kind, material.week, material.active_version_id = "lecture", 2, None
    version = session.get(MaterialVersion, "version")
    version.status = "queued"
    path = tmp_path / "source.txt"
    path.write_text(SOURCE, encoding="utf-8")

    @contextmanager
    def source_file(_version):
        yield path

    monkeypatch.setattr(worker, "source_file", source_file)
    extract = Job(owner_id="teacher", course_id="course", kind="extract", payload={"version_id": version.id})
    session.add(extract)
    session.commit()
    run_job(session, extract)
    assert version.status == "extracted"
    assert synthetic_ai == []  # Text extraction cannot charge a model call.
    assert session.scalar(select(Job).where(Job.kind == "auto_concepts")) is None

    run_job(session, session.scalar(select(Job).where(Job.kind == "embed")))
    chunks = list(session.scalars(select(Chunk).where(Chunk.version_id == version.id)))
    assert chunks and all(load_vector(chunk) is not None for chunk in chunks)
    assert version.status == "ready" and material.active_version_id == version.id
    assert any(path.endswith(":embedContent") for path, _ in synthetic_ai)
    hits = search_public(session, "course", "stack", version_id=version.id)
    assert hits and all(hit[2].id == version.id for hit in hits)

    assert session.scalar(select(Job).where(Job.kind == "auto_concepts")) is None
    from test_weekly_publication import start
    generation_id = start(client,2)
    run_job(session, session.scalar(select(Job).where(Job.kind == "weekly_content")))
    videos = list(session.scalars(select(ConceptVideo).order_by(ConceptVideo.position)))
    assert videos == []
    generation = session.get(ContentGeneration, generation_id)
    assert generation.options["video_mode"] == "none"
    assert {session.get(Concept, cid).name for cid in generation.concept_ids} == {"stack", "queue"}
    assert not list(session.scalars(select(Job).where(Job.kind == "narration_lesson")))
    question_jobs = list(session.scalars(select(Job).where(Job.kind == "questions")))
    assert len(question_jobs) == 2
    for job in question_jobs:
        run_job(session, job)
    questions = list(session.scalars(select(Question)))
    assert len(questions) == 10
    assert all(q.kind == "mcq" and q.solution["hint"] for q in questions)
    assert all(q.sources and all(s["chunk_id"] in {c.id for c in chunks} for s in q.sources)
               for q in questions)

    items = client.get("/api/v1/courses/course/concept-videos").json()["items"]
    assert items == []
    run_job(session, session.scalar(select(Job).where(Job.kind == "practice_prepare")))

    def no_claim(_session):
        pytest.fail("Disabled HeyGen must not even claim a queued video")

    monkeypatch.setattr(video_worker, "engine", lambda: session.bind)
    monkeypatch.setattr(video_worker, "claim", no_claim)
    assert video_worker.run_once() is False
    assert session.scalar(select(ConceptVideo)) is None
    assert all(path == "interactions" or path.endswith(":embedContent") for path, _ in synthetic_ai)


def test_question_bank_retrieves_within_upload_before_top_k(integration, synthetic_ai):
    client, session, _ = integration
    session.get(Material,"material").kind="lecture"
    other = Material(id="other", course_id="course", title="stack", kind="lecture", week=3,
                     visibility="public", active_version_id="other-version")
    session.add(other)
    session.add(MaterialVersion(id="other-version", material_id=other.id, version_no=1,
                               filename="other.txt", object_key="unused", sha256="b" * 64, status="ready"))
    session.add_all([Chunk(id=f"a_other_{i}", version_id="other-version", locator={"page": i},
                          content="stack stack stack. This belongs to a different upload.") for i in range(12)])
    session.commit()
    worker.embed_chunks(list(session.scalars(select(Chunk))), session)
    session.commit()
    # Reproduce the original failure: this upload loses every slot in course-wide top-k.
    unscoped = search_public(session, "course", "stack")
    assert unscoped and all(row[2].id == "other-version" for row in unscoped)
    from test_weekly_publication import start
    gid=start(client)
    job = Job(owner_id="teacher", course_id="course", kind="questions",
              payload={"generation_id":gid,"concept_id": "concept_stack", "source_version_id": "version","source_version_ids":["version"]})
    session.add(job)
    session.commit()
    result = run_job(session, job)
    assert len(result.result["question_ids"]) == 5
    assert all(session.get(Question, i).kind == "mcq" for i in result.result["question_ids"])
    for question_id in result.result["question_ids"]:
        question = session.get(Question, question_id)
        assert question.sources
        assert all(session.get(Chunk, source["chunk_id"]).version_id == "version" for source in question.sources)
