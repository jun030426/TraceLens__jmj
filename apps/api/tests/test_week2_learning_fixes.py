"""Regression coverage for the four student-week findings; isolated SQLite only."""
from datetime import date, timedelta
from types import SimpleNamespace
import pytest
from sqlalchemy import select
from lerny import personalized, team_engine, weekly_content
from lerny.learning_signals import weakness
from lerny.models import Attempt, Chunk, Concept, ContentGeneration, Enrollment, LearningSession, Question, Section, User
from test_lecture_specs import api
from test_gemini_integration import configured, integration
from test_weekly_publication import weekly, start, completed, login, publish

def test_rotation_continues_past_seven_and_covers_all_concepts(api, monkeypatch):
    _, db, _ = api
    ids = [f"concept-{i}" for i in range(18)]
    for cid in ids: db.add(Concept(id=cid, course_id="course", name=cid))
    section = Section(id="rotation", course_id="course", title="rotation", progress=ids, progress_mode="manual", progress_week=2)
    db.add(section); db.flush()
    monkeypatch.setattr(personalized, "weekly_content", lambda *a: {2: ids, 3: ["future"]})
    monkeypatch.setattr(personalized, "section_schedule", lambda *a: [{"week":2,"date":"2026-09-07"}])
    days = [personalized.learning_context(db, section, "student", date(2026,11,18)+timedelta(days=i)) for i in range(18)]
    assert all(d["day_index"]==7 and d["review_enabled"] and d["week"]==2 for d in days)
    assert days[0]["concept_slots"] != days[1]["concept_slots"]
    assert set(cid for d in days for cid in d["concept_slots"]) == set(ids)
    assert not list(db.scalars(select(LearningSession)))

def test_selected_summary_uses_concept_and_preserves_raw_evidence(weekly):
    client, db, tokens = weekly
    gid=start(client); g=completed(db,gid)
    chunk=db.get(Chunk,"src_stack_01")
    chunk.content='len(email) email.upper() email.lower()'
    g.concept_ids=["len","upper","lower"]
    g.concept_evidence=[]
    for name,expression in [("len","len(email)"),("upper","email.upper()"),("lower","email.lower()")]:
        db.add(Concept(id=name,course_id="course",name=name,description=expression))
        g.concept_evidence.append({"id":name,"name":name,"description":name+"의 검토된 설명",
                                  "source_description":expression,"version_id":"version"})
    g.status="published"
    db.commit()
    login(client,tokens,"student")
    for name in ("len","upper","lower"):
        response=client.get("/api/v1/materials/material/lecture-summary",params={"concept_id":name})
        assert response.status_code==200
        assert [i["concept_id"] for i in response.json()["items"]]==[name]
        assert response.json()["items"][0]["points"]==[name+"의 검토된 설명"]
    assert client.get("/api/v1/materials/material/lecture-summary?concept_id=unpublished").json()["items"]==[]
    assert chunk.content=='len(email) email.upper() email.lower()'
    login(client,tokens,"outsider")
    assert client.get("/api/v1/materials/material/lecture-summary?concept_id=lower").status_code==404

def test_new_bank_requires_five_mcqs(weekly):
    client, db, _ = weekly
    gid=start(client); g=completed(db,gid)
    assert g.options["mcq_per_concept"]==5
    assert weekly_content.readiness(db,g)["can_publish"]
    q=next(q for q in db.scalars(select(Question).where(Question.generation_id==gid)) if q.kind=="mcq")
    db.delete(q); db.commit()
    assert not weekly_content.readiness(db,g)["can_publish"]

def test_three_distinct_questions_reach_existing_score_threshold(api):
    _,db,_=api
    db.add(Section(id="s",course_id="course",title="s")); db.flush()
    for i in range(3):
        q=Question(id=f"q{i}",course_id="course",concept_id="concept_stack",kind="mcq",prompt=f"Question {i}",options=[],solution={},sources=[])
        plan=LearningSession(id=f"p{i}",student_id="student",section_id="s",day=date(2026,11,1)+timedelta(days=i),question_ids=[q.id])
        db.add_all([q,plan]);db.flush()
        db.add(Attempt(student_id="student",section_id="s",learning_session_id=plan.id,question_id=q.id,
                       concept_id="concept_stack",answer="0",status="graded",correct=True,independent=True))
        db.flush()
        result=weakness(db,"student","s",["concept_stack"])["concept_stack"]
        assert result["quiz"]==(0 if i==2 else 50)
    assert result["samples"]==3 and result["tier"]=="mastery"
    repeat=LearningSession(id="repeat",student_id="student",section_id="s",day=date(2026,11,4),question_ids=["q0"])
    db.add(repeat);db.flush()
    db.add(Attempt(student_id="student",section_id="s",learning_session_id="repeat",question_id="q0",concept_id="concept_stack",
                   answer="1",status="graded",correct=False,independent=True));db.flush()
    assert weakness(db,"student","s",["concept_stack"])["concept_stack"]["samples"]==3

def test_adapter_generates_three_perspectives_and_rejects_duplicate_stems(monkeypatch):
    source=SimpleNamespace(id="chunk",content="First source fact. Second source fact.")
    topics=[]
    class Engine:
        def generate_quiz(self,topic,difficulty,top_k):
            topics.append(topic)
            return dict(source_id="chunk",quote=source.content,question="Question "+difficulty,
                        options=["one","two","three","four"],correct_index=0,explanation="First source fact.")
    monkeypatch.setattr(team_engine,"make_engine",lambda *a,**k:Engine())
    def essay(*a): return dict(kind="essay",prompt="Explain both facts",options=[],answer_index=0,
                              explanation="Both facts.",criteria=["S1","S2"],sources=[{"chunk_id":"S1"}])
    def run():
        return team_engine.generate_questions([(source,None,None)],"course",SimpleNamespace(name="facts",description="facts"),
            {"S1":(source,"First source fact."),"S2":(source,"Second source fact.")},[],essay,mcq_count=3)
    assert [q.kind for q in run().questions]==["mcq","mcq","mcq","essay"]
    assert "앞 문항" in topics[-1] and "Question easy" in topics[-1]
    def duplicate(self,topic,difficulty,top_k):
        return dict(source_id="chunk",quote=source.content,question="Same question?",options=[difficulty,"two","three","four"],correct_index=0,explanation="First fact.")
    monkeypatch.setattr(Engine,"generate_quiz",duplicate)
    with pytest.raises(ValueError,match="DUPLICATE_QUESTION"):run()

