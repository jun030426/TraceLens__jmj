"""Explicit published fixtures for tests whose subject is downstream learning, not approval."""
from sqlalchemy import select
from lerny.models import ContentGeneration, Course, Concept, Question, PracticeExercise, ConceptVideo
from lerny.weekly_content import source_snapshot, source_hash


def published(session, course_id, week=1, concept_ids=None):
    session.flush()
    generation=session.scalar(select(ContentGeneration).where(ContentGeneration.course_id==course_id,
        ContentGeneration.week==week,ContentGeneration.status=="published"))
    if not generation:
        sources=source_snapshot(session,course_id,week)
        assert sources and all(s["ready"] for s in sources)
        generation=ContentGeneration(course_id=course_id,week=week,
            owner_id=session.get(Course,course_id).lead_teacher_id,status="published",
            sources=sources,source_hash=source_hash(sources),
            concept_ids=concept_ids or list(session.scalars(select(Concept.id).where(Concept.course_id==course_id))))
        session.add(generation);session.flush()
        generation.concept_evidence=[{"id":cid,"name":session.get(Concept,cid).name,
            "description":session.get(Concept,cid).description,"version_id":sources[0]["version_id"]} for cid in generation.concept_ids]
    for model in (Question,PracticeExercise,ConceptVideo):
        for item in session.scalars(select(model).where(model.course_id==course_id,model.generation_id.is_(None))):
            item.generation_id=generation.id
    session.flush()
    return generation
