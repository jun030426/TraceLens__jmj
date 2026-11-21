"""Real instructor APIs/workers with local files/DB and synthetic model/sandbox responses."""
import copy
import io
import json
import re
from datetime import date
from uuid import uuid4

import pytest
from pptx import Presentation
from sqlalchemy import select

from lerny import assessment, practice, weekly_content, worker, video_worker
from lerny.models import ConceptVideo, ContentGeneration, Job, Material, Section, Question
from test_gemini_integration import api, configured, integration, fake_provider  # noqa: F401
from test_weekly_publication import completed, login, publish, start, weekly  # noqa: F401
from test_ready_video_selection import select_mode
from test_document_materials import site, synthetic_engine  # noqa: F401 -- real document gates, synthetic model/render

CODE = "numbers = [1, 2]\ntotal = sum(numbers)\nprint(total)"


def finish(session, job):
    assert worker.run_once(job.id), job.kind
    session.expire_all()
    assert job.status == "succeeded", (job.kind, job.status, job.error_code, job.result)


def upload(client, week, text, *, kind="lecture", ppt=False):
    raw = text.encode()
    filename = f"week-{week}.txt"
    if ppt:
        deck = Presentation()
        slide = deck.slides.add_slide(deck.slide_layouts[6])
        slide.shapes.add_textbox(0, 0, 8000000, 4000000).text_frame.text = text
        stream = io.BytesIO(); deck.save(stream); raw = stream.getvalue()
        filename = f"week-{week}.pptx"
    result = client.post("/api/v1/courses/course/materials",
        data={"kind":kind,"week":str(week),"visibility":"public"},
        files={"file":(filename,raw,"application/octet-stream")})
    assert result.status_code == 201, result.text
    return result.json()


def synthetic_model(session, *, code=True):
    def generate(prompt, schema):
        data = json.loads(prompt.rsplit("\n", 1)[1])
        props = schema["properties"]
        if "assessment_task" in data or "single_correct" in props:
            from quiz_provider_fixture import quiz_response
            return quiz_response(data)
        if "concepts" in props:
            source = next((s for s in data if "WeekConcept" in s["text"]), None)
            if source is None:
                source = next(s for s in data if CODE in s["text"])
                return {"concepts":[{"name":"numbers","quote":CODE,"version_id":source["version_id"]}]}
            names = list(dict.fromkeys(re.findall(r"WeekConcept\w+", source["text"])))
            return {"concepts":[{"name":name,"quote":f"{name} is a synthetic rule.","version_id":source["version_id"]} for name in names]}
        if "programs" in props:
            sources = [s for s in data["sources"] if CODE in s["text"]]
            if not code or not sources:
                return {"programs":[]}
            return {"programs":[{"source_id":source["source_id"],"concept_id":None,
                "code":source["text"],"title":"합 계산","prompt":"배열의 합을 출력하세요.",
                "input_statement":"numbers = [1, 2]","variants":["numbers = [3, 4]","numbers = [0, 0]"],
                "blank_lines":[3],"full_template":"numbers = [1, 2]\n# 구현"} for source in sources]}
        if "correct_index" in props:
            source = next(s for s in data["retrieved_excerpts"] if "WeekConcept" in s["text"])
            return {"concept_id":"", "question":f"개념을 {data['difficulty']} 관점에서 설명한 것은?",
                "options":["자료의 설명","관계없는 설명1","관계없는 설명2","관계없는 설명3"],
                "correct_index":0,"explanation":source["text"],"distractor_rationales":[],
                "source_id":source["source_id"],"quote":source["text"].split("\n")[0]}
        if "criteria" in props:
            keys = schema["properties"]["criteria"]["items"]["enum"][:2]
            return {"kind":"essay","prompt":"개념의 두 가지 특징을 설명하세요.","options":[],
                "answer_index":0,"explanation":"자료의 특징을 설명해요.","criteria":keys,
                "sources":[{"chunk_id":key} for key in keys]}
        if "correct_options" in props:
            return {"correct_options":[data["options"][0]]}
        if "supported" in props:
            return {"supported":True,"unambiguous":True,"answer_correct":True}
        raise AssertionError(f"Unexpected model request (including video): {list(props)}")
    return generate


@pytest.mark.parametrize("week,concept_count,program_count", [(w,1,1) for w in [1,*range(3,16)]] + [(15,18,3)])
def test_upload_through_student_publication_without_video(weekly, configured, fake_provider, site, synthetic_engine, monkeypatch, week, concept_count, program_count):
    client, session, tokens = weekly
    # A published earlier week, its questions and video must remain unchanged.
    session.get(Material, "material").week = 2; session.commit()
    old_id = start(client, 2); completed(session, old_id)
    assert publish(client, old_id).status_code == 200
    old = copy.deepcopy(weekly_content.generation_view(session, session.get(ContentGeneration, old_id), True))
    monkeypatch.setattr(configured, "heygen_rendering_enabled", False)
    monkeypatch.setattr(worker, "model_json", synthetic_model(session))
    # Never execute student code on the host; only the sandbox response is synthetic.
    monkeypatch.setattr(practice, "output_of", lambda lang, source, **kw:
        "3" if "[1, 2]" in source else "7" if "[3, 4]" in source else "0")
    lecture = "\n".join(f"WeekConcept{week}_{i} is a synthetic rule. Its second characteristic is ordering." for i in range(concept_count - (1 if program_count == 3 else 0)))
    synthetic_engine.text = lecture
    uploads = [upload(client, week, lecture, ppt=week % 2 == 1),
               *[upload(client, week, f"# example {i}\n{CODE}", kind="example") for i in range(program_count)]]
    listing = client.get("/api/v1/courses/course/weekly-content").json()
    assert listing["default_video_mode"] == "none"
    item = next(w for w in listing["items"] if w["week"] == week)
    assert not item["sources_ready"]
    assert client.post(f"/api/v1/courses/course/weeks/{week}/content", json={"source_hash":item["source_hash"]},
        headers={"Idempotency-Key":str(uuid4())}).status_code == 409
    for uploaded in uploads:
        finish(session, session.get(Job, uploaded["processing_job_id"]))
        embedding = session.scalar(select(Job).where(Job.kind == "embed",
            Job.payload["version_id"].as_string() == uploaded["version_id"]))
        finish(session, embedding)
    assert session.scalars(select(ContentGeneration)).all() == [session.get(ContentGeneration, old_id)]
    gid = start(client, week)
    assert start(client, week) == gid  # duplicate clicks reuse this draft
    g = session.get(ContentGeneration, gid)
    assert g.options == {"videos":False,"video_mode":"none","practice":True,"mcq_per_concept":5}
    root = next(j for j in weekly_content.generation_jobs(session, g) if j.kind == "weekly_content")
    finish(session, root)
    for job in weekly_content.generation_jobs(session, g):
        if job.status != "succeeded": finish(session, job)
    data = client.get(f"/api/v1/courses/course/content-generations/{gid}").json()
    assert data["can_publish"] and data["state"] == "ready" and data["video_mode"] == "none", data
    assert data["counts"] == {"concepts":concept_count,"questions":5*concept_count,"practice":2*program_count,"videos":0,"videos_ready":0,"videos_deferred":0}
    assert {j["kind"] for j in data["jobs"]} == {"weekly_content","questions","practice_prepare"}
    assert {e["kind"] for e in data["practice"]} == {"blank","full"}
    assert all(len(e["tests"]) == 3 for e in data["practice"])
    assert not session.scalars(select(ConceptVideo).where(ConceptVideo.generation_id == gid)).all()
    assert publish(client, gid, reviewed=False).status_code == 409
    login(client, tokens, "student")
    assert not set(g.concept_ids) & {c["id"] for c in client.get("/api/v1/courses/course/concepts").json()["items"]}
    from lerny.learning import valid_sources
    assert not any(valid_sources(session, session.get(Question, q["id"])) for q in data["questions"])
    login(client, tokens, "teacher")
    session.get(Section, "section").week_schedule = [{"week":week,"date":date.today().isoformat()}]
    session.commit()
    assert publish(client, gid).status_code == 200
    login(client, tokens, "student")
    assert all(valid_sources(session, session.get(Question, q["id"])) for q in data["questions"])
    assigned = client.post("/api/v1/sections/section/daily")
    assert assigned.status_code == 200, assigned.text
    assert assigned.json()["week"] == week and assigned.json()["items"]
    assert {q["id"] for q in assigned.json()["items"]} & {q["id"] for q in data["questions"]}
    exercises = client.post("/api/v1/sections/section/practice/daily")
    assert exercises.status_code == 200, exercises.text
    assert exercises.json()["week"] == week
    assert {e["kind"] for e in exercises.json()["items"]} == {"blank","full"}
    assert all("reference" not in e and "solution" not in e for e in exercises.json()["items"])
    from lerny.retrieval import search_public
    assert search_public(session, "course", f"WeekConcept{week}", version_ids=[u["version_id"] for u in uploads], published_only=True)
    # Switching weeks must not mutate or replace the existing published version/assets.
    assert old == weekly_content.generation_view(session, session.get(ContentGeneration, old_id), True)


def test_no_code_is_explicitly_skipped_not_a_video_blocker(weekly, configured, monkeypatch):
    client, session, _ = weekly
    monkeypatch.setattr(configured, "heygen_rendering_enabled", False)
    gid = start(client); g = completed(session, gid)
    for e in weekly_content.artifacts(session, g)[1]: session.delete(e)
    job = next(j for j in weekly_content.generation_jobs(session, g) if j.kind == "practice_prepare")
    job.payload = {**job.payload, "source_version_id":"version"}
    monkeypatch.setattr(worker, "model_json", lambda *args: {"programs":[]})
    job.result = practice.prepare(session, job); session.commit()
    assert job.result["status"] == "no_verified_source_code"
    assert weekly_content.readiness(session, g)["can_publish"]


def test_existing_draft_can_exclude_video_without_changing_assets_or_retrying_narration(weekly, configured, monkeypatch):
    client, session, tokens = weekly
    gid = start(client); g = completed(session, gid)
    video = session.get(ConceptVideo, gid + "-video")
    narration = next(j for j in weekly_content.generation_jobs(session, g) if j.kind == "narration_lesson")
    video.script_job_id = narration.id
    video.status = "queued"; video.script = {"preserved":"script"}; video.request = {"preserved":"request"}
    narration.status = "failed"; narration.error_code = "GEMINI_QUOTA_EXCEEDED"; session.commit()
    before = copy.deepcopy((video.script, video.request, video.object_key, narration.result))
    response = select_mode(client, gid, "none")
    assert response.status_code == 200 and response.json()["can_publish"]
    assert before == (video.script, video.request, video.object_key, narration.result)
    assert client.post(f"/api/v1/courses/course/content-generations/{gid}/retry").status_code == 409
    assert video_worker.claim(session) is None  # even when the global rendering flag is on
    narration.status = "queued"; session.commit()
    assert not worker.run_once(narration.id)
    slides = Job(owner_id="teacher",course_id="course",kind="lecture_slides",
        payload={"content_generation_id":gid,"video_id":video.id})
    session.add(slides); session.commit()
    assert not worker.run_once(slides.id)
    assert client.post(f"/api/v1/courses/course/concept-videos/{video.id}/retry").status_code == 409
    assert publish(client, gid).status_code == 200
    login(client, tokens, "student")
    assert client.get("/api/v1/sections/section/concept-videos").json()["items"] == []
    assert client.get(f"/api/v1/concept-videos/{video.id}/file").status_code == 404


@pytest.mark.parametrize("problem", ["question_failed","practice_held","source_changed","student","stale_token"])
def test_excluding_video_never_bypasses_other_checks(weekly, configured, monkeypatch, problem):
    client, session, tokens = weekly
    monkeypatch.setattr(configured, "heygen_rendering_enabled", False)
    gid = start(client); g = completed(session, gid)
    if problem == "question_failed":
        next(j for j in weekly_content.generation_jobs(session, g) if j.kind == "questions").status = "failed"
    if problem == "practice_held":
        next(j for j in weekly_content.generation_jobs(session, g) if j.kind == "practice_prepare").result = {"held":[{"reason":"UNVERIFIED"}]}
    if problem == "source_changed": session.get(Material, "material").revision += 1
    session.commit()
    if problem == "student":
        login(client, tokens, "student")
        assert client.post(f"/api/v1/courses/course/content-generations/{gid}/publish", json={"review_token":"a"*64,"reviewed":True}).status_code in (403,404)
    else:
        assert publish(client, gid, **({"review_token":"a"*64} if problem == "stale_token" else {})).status_code == 409


def test_known_credit_failure_automatically_excludes_new_videos(weekly):
    client, session, _ = weekly
    gid = start(client); completed(session, gid)
    video = session.get(ConceptVideo, gid + "-video")
    video.status = "failed"; video.error_code = "HEYGEN_API_CREDITS_REQUIRED"; session.commit()
    assert client.get("/api/v1/courses/course/weekly-content").json()["default_video_mode"] == "none"


def test_video_feature_disabled_does_not_block_text_generation(weekly):
    from lerny.operations import state
    client, session, _ = weekly
    control = state(session); control.features = {"content":True,"videos":False}; session.commit()
    gid = start(client)
    assert session.get(ContentGeneration, gid).options["video_mode"] == "none"


def test_reenabling_video_is_explicit_and_reuses_content(weekly, configured, monkeypatch):
    client, session, _ = weekly
    monkeypatch.setattr(configured, "heygen_rendering_enabled", False)
    gid = start(client); g = completed(session, gid)
    # Emulate new no-video generation, with no video/narration rows at all.
    for v in weekly_content.artifacts(session, g)[2]: session.delete(v)
    for j in weekly_content.generation_jobs(session, g):
        if j.kind == "narration_lesson": session.delete(j)
    session.commit()
    questions = [q.id for q in weekly_content.artifacts(session, g)[0]]
    assert select_mode(client, gid, "all").status_code == 409
    monkeypatch.setattr(configured, "heygen_rendering_enabled", True)
    assert weekly_content.readiness(session, g)["can_publish"]  # no silent policy flip
    assert select_mode(client, gid, "all").status_code == 200
    assert select_mode(client, gid, "all").status_code == 200
    assert len(weekly_content.artifacts(session, g)[2]) == 1
    assert questions == [q.id for q in weekly_content.artifacts(session, g)[0]]
    assert not weekly_content.readiness(session, g)["can_publish"]


def test_exclusion_after_claim_prevents_submission(weekly, monkeypatch):
    client, session, _ = weekly
    gid = start(client); completed(session, gid)
    video = session.get(ConceptVideo, gid + "-video")
    video.status = "queued"; video.request = {"keep":"original"}; session.commit()
    item = video_worker.claim(session)
    assert item["action"] == "submit"
    assert select_mode(client, gid, "none").status_code == 200
    monkeypatch.setattr(video_worker, "engine", lambda: session.bind)
    assert not video_worker.persist_prepared(item, {"do_not":"submit"})
    session.expire_all()
    assert video.status == "queued" and video.request == {"keep":"original"}
