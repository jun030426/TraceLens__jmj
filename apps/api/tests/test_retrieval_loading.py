"""Source joins must not multiply full-video OCR reports by the chunk count."""
from sqlalchemy import event, inspect
from types import SimpleNamespace
import pytest

from lerny import retrieval
from lerny.lecture_specs import source_snapshot
from lerny.models import MaterialVersion, Chunk
from lerny.team_engine import source_item
from test_evaluation_references import add_reference
from test_lecture_specs import api  # noqa: F401


def test_public_retrieval_keeps_citations_without_loading_version_payloads(api):
    _, session, _ = api
    version = session.get(MaterialVersion, 'version')
    version.extraction_report = {'held': [{'text': 'OCR report ' * 1000}] * 50}
    session.commit()
    session.expunge_all()
    statements = []
    def capture(_conn, _cursor, statement, _params, _context, _many):
        statements.append(statement)
    event.listen(session.bind, 'before_cursor_execute', capture)
    try:
        rows = retrieval.public_rows(session, 'course')
        assert len(rows) == 2
        assert {'extraction_report', 'extracted_text'} <= inspect(rows[0][2]).unloaded
        sources = [source_item(row, 'course') for row in rows]
        assert all(item['text'] and item['source_sha256'] for item in sources)
        snapshot, evidence = source_snapshot(session, 'course', rows[0][0].id)
        assert snapshot['version_id'] == rows[0][2].id
        assert evidence['text'] == rows[0][0].content
        assert not any('material_versions.extraction_report' in sql or
                       'material_versions.extracted_text' in sql for sql in statements)
    finally:
        event.remove(session.bind, 'before_cursor_execute', capture)


def test_version_lookup_defers_large_payloads_until_accessed(api):
    _, session, _ = api
    version = session.get(MaterialVersion, 'version')
    version.extraction_report = {'held_count': 3, 'native_evidence': {'pipeline': 'ocr'}}
    session.commit()
    session.expunge_all()
    statements = []
    def capture(_conn, _cursor, statement, _params, _context, _many):
        statements.append(statement)
    event.listen(session.bind, 'before_cursor_execute', capture)
    try:
        version = session.get(MaterialVersion, 'version')
        assert version.status and {'extraction_report', 'extracted_text'} <= inspect(version).unloaded
        assert not any('material_versions.extraction_report' in sql or
                       'material_versions.extracted_text' in sql for sql in statements)
        assert version.extraction_report['held_count'] == 3
    finally:
        event.remove(session.bind, 'before_cursor_execute', capture)


def test_private_validation_reads_only_bounded_chunk_evidence(api):
    _, session, _ = api
    add_reference(session)
    session.expunge_all()
    statements = []
    def capture(_conn, _cursor, statement, _params, _context, _many):
        statements.append(statement)
    event.listen(session.bind, 'before_cursor_execute', capture)
    try:
        refs = retrieval.internal_validation_context(session, 'course', 'stack', ['src_stack_01'])
        assert len(refs) == 1 and 'PRIVATE_STACK_RUBRIC_SENTINEL' in refs[0]
        assert not any('material_versions.extraction_report' in sql or
                       'material_versions.extracted_text' in sql for sql in statements)
    finally:
        event.remove(session.bind, 'before_cursor_execute', capture)


def test_longer_lesson_evidence_keeps_week_scope_and_private_exclusion(api, monkeypatch):
    """Short matching labels must not consume the entire lesson evidence budget."""
    _, session, _ = api
    add_reference(session)
    for i in range(12):
        session.add(Chunk(id=f'heading-{i:02}', version_id='version',
            content='STACK' if i < 4 else '스택은 맨 위에서 값을 넣고 꺼내는 자료구조입니다.', locator={}))
    session.commit()
    from lerny import rag_index, team_engine
    monkeypatch.setattr(retrieval, 'settings', lambda:SimpleNamespace(ai_provider='gemini',rag_storage='supabase'))
    monkeypatch.setattr(rag_index, 'indexed_ids', lambda chunks:{c.id for c in chunks})
    def engine(rows, course_id, **_):
        # Model-independent ranking: reproduce several short labels preceding prose.
        assert all(m.kind!='answer' and m.visibility=='public' and v.id=='version' for c,m,v in rows)
        return SimpleNamespace(retrieve=lambda query,top_k:[{'id':r[0].id} for r in rows[:top_k]])
    monkeypatch.setattr(team_engine, 'make_engine', engine)
    short=retrieval.search_public(session,'course','STACK',version_ids=['version','ref-v'])
    lesson=retrieval.search_public(session,'course','STACK',version_ids=['version','ref-v'],limit=12)
    assert len(short)==4 and all(r[0].content=='STACK' for r in short)
    assert len(lesson)==12 and any('자료구조입니다' in r[0].content for r in lesson)
    assert not retrieval.search_public(session,'course','STACK',version_ids=[],limit=12)
    for invalid in (0,13,True):
        with pytest.raises(ValueError,match='INVALID_RETRIEVAL_LIMIT'):
            retrieval.search_public(session,'course','STACK',limit=invalid)
