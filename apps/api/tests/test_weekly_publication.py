"""Instructor review is the authorization boundary; all fixtures are isolated SQLite."""
import json
from uuid import uuid4
from datetime import date
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from lerny import automatic, team_engine, weekly_content, worker
from lerny.models import (Chunk, ConceptVideo, ContentGeneration, Enrollment, Job, Material,
    MaterialVersion, PracticeExercise, Question, Section)
from lerny.security import COOKIE
from test_gemini_integration import api, configured, integration  # noqa: F401


@pytest.fixture
def weekly(integration, configured, monkeypatch):
    from pydantic import SecretStr
    client, session, tokens = integration
    client.headers["Idempotency-Key"]=str(uuid4())
    monkeypatch.setattr(configured, "automatic_learning_enabled", True)
    # Existing video-publication regressions explicitly exercise enabled video production.
    monkeypatch.setattr(configured, "heygen_rendering_enabled", True)
    monkeypatch.setattr(configured, "heygen_calls_enabled", True)
    monkeypatch.setattr(configured, "heygen_api_key", SecretStr("synthetic-not-a-live-key"))
    material=session.get(Material,"material"); material.kind="lecture"
    session.get(MaterialVersion,"version").extracted_text="Synthetic public stack rule 1. Synthetic public stack rule 2."
    session.add(Section(id="section",course_id="course",title="Section",
        progress_mode="auto",week_schedule=[{"week":1,"date":date.today().isoformat()}]))
    session.add(Enrollment(course_id="course",section_id="section",student_id="student",status="active"))
    session.commit()
    return client,session,tokens


def login(client,tokens,actor):
    client.cookies.set(COOKIE,tokens[actor][0]);client.headers["X-CSRF-Token"]=tokens[actor][1]


def start(client,week=1):
    listing=client.get("/api/v1/courses/course/weekly-content")
    assert listing.status_code==200,listing.text
    item=next(i for i in listing.json()["items"] if i["week"]==week)
    response=client.post(f"/api/v1/courses/course/weeks/{week}/content",json={"source_hash":item["source_hash"]},headers={"Idempotency-Key":str(uuid4())})
    assert response.status_code==202,response.text
    return response.json()["generation_id"]


def test_cross_material_concept_evidence_is_repaired_once_and_revalidated(monkeypatch):
    batch=[{'version_id':'ppt','text':'스택은 후입선출 자료구조입니다.'},
           {'version_id':'video','text':'STACK uses LIFO.'}]
    invalid={'concepts':[{'name':'STACK','quote':'스택은 후입선출 자료구조입니다.','version_id':'ppt'}]}
    valid={'concepts':[{'name':'스택','quote':'스택은 후입선출 자료구조입니다.','version_id':'ppt'}]}
    calls=[]
    def model(prompt,schema):
        calls.append(prompt)
        return invalid if len(calls)==1 else valid
    monkeypatch.setattr(worker,'model_json',model)
    result=weekly_content.concepts_from_batch(batch)
    assert len(calls)==2 and result[0].name=='스택'
    assert 'invalid_indices' in calls[1]
    calls.clear()
    monkeypatch.setattr(worker,'model_json',lambda prompt,schema:(calls.append(prompt) or invalid))
    with pytest.raises(ValueError,match='INVALID_CONCEPT_EVIDENCE'):
        weekly_content.concepts_from_batch(batch)
    assert len(calls)==2


def completed(session,gid):
    """Model/video outcomes are synthetic; the real publication API validates them."""
    g=session.get(ContentGeneration,gid)
    g.concept_ids=["concept_stack"]
    g.concept_evidence=[{"id":"concept_stack","name":"stack","description":"Synthetic public stack rule 1","version_id":"version"}]
    for i in range(5):
        kind = "mcq"
        session.add(Question(id=f"{gid}-q{i}",course_id="course",generation_id=gid,concept_id="concept_stack",
            source_version_id="version",kind=kind,prompt=f"Question {i}",options=["A","B","C","D"] if kind=="mcq" else [],
            solution={"answer_index":0,"explanation":"Synthetic explanation","criteria":[],
                      "hint":f"Concept hint {i + 1}","quiz_position":i + 1},
            sources=[{"chunk_id":"src_stack_01","quote":"Synthetic public stack rule 1"}]))
    for kind in ["questions","narration_lesson","practice_prepare"]:
        session.add(Job(owner_id="teacher",course_id="course",kind=kind,status="succeeded",payload={"generation_id":gid},result={"held":[]}))
    for j in weekly_content.generation_jobs(session,g): j.status="succeeded"
    session.add(ConceptVideo(id=f"{gid}-video",course_id="course",generation_id=gid,version_id="version",
        concept_id="concept_stack",owner_id="teacher",position=1,title="Preview",status="ready",object_key="synthetic.mp4"))
    session.add(PracticeExercise(id=f"{gid}-practice",course_id="course",generation_id=gid,version_id="version",
        concept_id="concept_stack",source_key="synthetic",position=1,kind="blank",language="python",title="Example",
        prompt="Synthetic exercise",template="print(1)",reference="print(1)",blanks={},
        tests=[{"input":"x = 1","expected":"1"}],sources=[{"chunk_id":"src_stack_01","quote":"Synthetic public stack rule 1"}],status="ready"))
    session.commit()
    return g


def publish(client,gid,**overrides):
    review=client.get(f"/api/v1/courses/course/content-generations/{gid}")
    assert review.status_code==200,review.text
    return client.post(f"/api/v1/courses/course/content-generations/{gid}/publish",
        json={"review_token":review.json()["review_token"],"reviewed":True,**overrides})


def test_upload_stops_at_indexing_and_legacy_worker_cannot_generate(weekly):
    _,session,_=weekly
    automatic.enqueue_concepts(session,session.get(Material,"material"),session.get(MaterialVersion,"version"),"teacher")
    assert list(session.scalars(select(Job)))==[]
    job=Job(owner_id="teacher",course_id="course",kind="auto_concepts",payload={"source_version_id":"version"})
    session.add(job);session.commit()
    assert worker.run_once(job.id)
    session.expire_all();job=session.get(Job,job.id)
    assert job.status=="failed" and job.error_code=="MANUAL_GENERATION_REQUIRED"


def test_start_uses_whole_week_excludes_private_and_is_idempotent(weekly):
    client,session,_=weekly
    for name,visibility in [("example","public"),("answers","private")]:
        session.add(Material(id=name,course_id="course",title=name,kind="example",week=1,visibility=visibility,active_version_id=name+"-v"))
        session.add(MaterialVersion(id=name+"-v",material_id=name,version_no=1,filename="example.py",object_key="unused",sha256="b"*64,status="ready"))
    session.commit()
    gid=start(client);assert start(client)==gid
    assert {s["material_id"] for s in session.get(ContentGeneration,gid).sources}=={"material","example"}
    assert len(list(session.scalars(select(Job))))==1


@pytest.mark.parametrize("actor",["student","outsider"])
def test_staff_only_generate_review_publish(weekly,actor):
    client,session,tokens=weekly;gid=start(client)
    digest=session.get(ContentGeneration,gid).source_hash
    login(client,tokens,actor)
    assert client.get("/api/v1/courses/course/weekly-content").status_code in (403,404)
    assert client.get(f"/api/v1/courses/course/content-generations/{gid}").status_code in (403,404)
    assert client.post("/api/v1/courses/course/weeks/1/content",json={"source_hash":digest}).status_code in (403,404)
    assert client.post(f"/api/v1/courses/course/content-generations/{gid}/publish",json={"review_token":"a"*64,"reviewed":True}).status_code in (403,404)


def test_publish_requires_ready_reviewed_and_unchanged_review(weekly):
    client,session,_=weekly;gid=start(client)
    assert publish(client,gid).status_code==409
    completed(session,gid)
    assert publish(client,gid,reviewed=False).status_code==409
    old=client.get(f"/api/v1/courses/course/content-generations/{gid}").json()["review_token"]
    q=session.get(Question,gid+"-q0");q.revision+=1;session.commit()
    assert publish(client,gid,review_token=old).status_code==409
    assert publish(client,gid).status_code==200
    assert publish(client,gid).status_code==200


def test_draft_hidden_then_publication_enables_students_and_retrieval(weekly,monkeypatch):
    from lerny.learning import valid_sources
    from lerny.practice import current_source
    from lerny.retrieval import public_rows
    client,session,tokens=weekly;gid=start(client);completed(session,gid)
    assert not valid_sources(session,session.get(Question,gid+"-q0"))
    assert current_source(session,session.get(PracticeExercise,gid+"-practice")) is None
    assert public_rows(session,"course",published_only=True)==[]
    login(client,tokens,"student")
    assert client.get("/api/v1/courses/course/concepts").json()["items"]==[]
    assert client.get("/api/v1/sections/section/my-learning").json()["items"]==[]
    assert client.get("/api/v1/materials/material/lecture-summary").json()["items"]==[]
    assert client.get("/api/v1/sections/section/concept-videos").json()["items"]==[]
    assert client.get(f"/api/v1/concept-videos/{gid}-video/file").status_code==404
    before = client.post("/api/v1/sections/section/daily")
    assert before.status_code == 200 and before.json()["status"] == "empty" and before.json()["items"] == []
    login(client,tokens,"teacher");assert publish(client,gid).status_code==200
    assert valid_sources(session,session.get(Question,gid+"-q0"))
    assert current_source(session,session.get(PracticeExercise,gid+"-practice")) is not None
    assert len(public_rows(session,"course",published_only=True))==2
    login(client,tokens,"student")
    assert len(client.get("/api/v1/courses/course/concepts").json()["items"])==1
    assert len(client.get("/api/v1/sections/section/concept-videos").json()["items"])==1
    def no_ai(*args,**kwargs):pytest.fail("Student assignment must never generate unreviewed questions")
    monkeypatch.setattr(worker,"model_json",no_ai)
    response=client.post("/api/v1/sections/section/daily")
    assert response.status_code==200,response.text
    assert [q["id"] for q in response.json()["items"]] == [f"{gid}-q{i}" for i in range(5)]
    assert response.json()["target_count"] == 5
    first = response.json()["items"][0]
    assert "explanation" not in first and "solution" not in first
    route = f"/api/v1/learning-sessions/{response.json()['id']}/questions/{first['id']}"
    assert client.post(route + "/help").json()["hint"] == "Concept hint 1"
    assert client.post(route + "/submit", json={"answer": "0"}).status_code == 202
    assert client.post("/api/v1/sections/section/daily").json()["items"][0]["explanation"] == "Synthetic explanation"
    assert client.post("/api/v1/sections/section/daily").json()["id"]==response.json()["id"]
    assert not any(j.kind=="daily_theory" for j in session.scalars(select(Job)))


def test_source_change_requires_new_generation_keeps_previous_until_publish(weekly):
    from lerny.learning import valid_sources
    client,session,_=weekly;first=start(client);completed(session,first);assert publish(client,first).status_code==200
    second=start(client);completed(session,second)
    assert valid_sources(session,session.get(Question,first+"-q0"))
    material=session.get(Material,"material");material.revision+=1;session.commit()
    assert publish(client,second).status_code==409
    third=start(client);assert third!=second
    assert session.get(ContentGeneration,second).status=="cancelled"
    completed(session,third);assert publish(client,third).status_code==200
    assert not valid_sources(session,session.get(Question,first+"-q0"))
    assert valid_sources(session,session.get(Question,third+"-q0"))
    material.visibility="private";session.commit()
    assert not valid_sources(session,session.get(Question,third+"-q0"))
    assert weekly_content.published_version_ids(session,"course")==set()


def test_new_upload_or_failed_index_blocks_generation(weekly):
    client,session,_=weekly
    session.get(MaterialVersion,"version").status="failed";session.commit()
    data=client.get("/api/v1/courses/course/weekly-content").json()["items"][0]
    assert not data["sources_ready"]
    assert client.post("/api/v1/courses/course/weeks/1/content",json={"source_hash":data["source_hash"]}).status_code==409


@pytest.mark.parametrize("model_blank", [2, 3], ids=["calculation", "print-line"])
def test_weekly_worker_combines_files_and_tags_verified_practice(weekly,monkeypatch,model_blank):
    from lerny import practice
    client,session,_=weekly
    code="numbers = [1, 2]\ntotal = sum(numbers)\nprint(total)"
    session.add(Material(id="code",course_id="course",title="example.py",kind="example",week=1,visibility="public",active_version_id="code-v"))
    session.add(MaterialVersion(id="code-v",material_id="code",version_no=1,filename="example.py",object_key="unused",sha256="b"*64,status="ready",extracted_text=code))
    session.add(Chunk(id="code-chunk",version_id="code-v",content=code,locator={"line":1}));session.commit()
    gid=start(client)
    def model(prompt,schema):
        if "concepts" in schema["properties"]:
            data=json.loads(prompt.rsplit("\n",1)[1]);assert {s["version_id"] for s in data}=={"version","code-v"}
            return {"concepts":[{"name":"stack","quote":"Synthetic public stack rule 1.","version_id":"version"}]}
        assert "programs" in schema["properties"]
        assert code in {s["text"] for s in json.loads(prompt.rsplit("\n",1)[1])["sources"]}
        return {"programs":[{"source_id":"code-chunk","concept_id":"concept_stack","code":code,"title":"합 구하기",
            "prompt":"배열 숫자의 합을 계산해 출력하세요.","input_statement":"numbers = [1, 2]","variants":["numbers = [3, 4]","numbers = [0, 0]"],
            "blank_lines":[model_blank],"full_template":"numbers = [1, 2]\n# 구현하세요"}]}
    monkeypatch.setattr(worker,"model_json",model)
    root=session.scalar(select(Job).where(Job.kind=="weekly_content"))
    weekly_content.generate_job(session,root);session.flush()
    jobs=weekly_content.generation_jobs(session,session.get(ContentGeneration,gid))
    assert all(set(j.payload["source_version_ids"])=={"version","code-v"} for j in jobs if j.kind!="weekly_content")
    monkeypatch.setattr(practice,"output_of",lambda lang,source,**kwargs:"3" if "[1, 2]" in source else "7" if "[3, 4]" in source else "0")
    result=practice.prepare(session,next(j for j in jobs if j.kind=="practice_prepare"))
    assert len(result["exercise_ids"])==2 and result["held"]==[]
    for eid in result["exercise_ids"]:
        exercise=session.get(PracticeExercise,eid)
        if exercise.kind == "blank":
            assert exercise.blanks == {"1": "total = sum(numbers)"}
            assert "print(total)" in exercise.template
        assert exercise.generation_id==gid and exercise.version_id=="code-v" and len(exercise.tests)==3


def test_stale_draft_does_not_start_paid_video_render(weekly):
    from lerny.video_worker import generation_active
    client,session,_=weekly;gid=start(client);completed(session,gid)
    video=session.get(ConceptVideo,gid+"-video")
    assert generation_active(session,video)
    material=session.get(Material,"material");material.revision+=1;session.commit()
    assert not generation_active(session,video)


@pytest.mark.parametrize("repaired",[True,False])
def test_narration_length_has_bounded_repair_without_cutting_or_padding(monkeypatch,repaired):
    text="강의 자료의 근거 문장입니다."
    script={"target_seconds":50,"source_id":"source","quote":text,
        "hook":{"narration":"짧은 도입"},"body":{"narration":"짧은 설명","key_takeaways":[text]},"outro":{"narration":"짧은 마무리"}}
    monkeypatch.setattr(team_engine,"make_engine",lambda *a,**k:SimpleNamespace(generate_shorts_script=lambda *a,**k:script))
    calls=[]
    def generate(prompt,schema):
        calls.append(json.loads(prompt.rsplit("\n",1)[1]))
        assert schema['properties']['candidates']['items']['properties']['body']['minLength']==290
        short={'hook':'여전히','body':'너무','outro':'짧아요'}
        candidate=dict(zip(('hook','body','outro'),["가"*40,"나"*295,"다"*40])) if repaired else short
        return {'candidates':[short,candidate,{'hook':'길게'*100,'body':'길게'*300,'outro':'길게'*100}]}
    job=SimpleNamespace(id="job",course_id="course",payload={"learning_objective":"학습","target_duration_seconds":50,"source_snapshot_id":"snapshot"})
    args=([(SimpleNamespace(id="source",content=text),None,None)],job,SimpleNamespace(name="개념"),generate)
    if repaired:
        result=team_engine.narration_draft(*args)
        assert len(" ".join(result.lesson.narration))==377 and len(calls)==1
        assert result.citations[0].quote==text
    else:
        with pytest.raises(ValueError,match="SHORTS_NARRATION_LENGTH"):team_engine.narration_draft(*args)
        assert len(calls)==2
