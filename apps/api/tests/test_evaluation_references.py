"""Synthetic reference flow: SQLite + stubbed model only; real HTTP is blocked by api."""

import json
from datetime import date

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from lerny import retrieval, worker
from lerny.assessment import generate_job, grade_job
from lerny.auth import COOKIE
from lerny.config import settings
from lerny.evaluation import review_references
from lerny.gemini_provider import available
from lerny.lecture_grounding import grounding_job
from lerny.models import (
    Attempt, ChatMessage, Chunk, Course, Enrollment, Job, LearningSession,
    Material, MaterialVersion, Question, Section,
)
from lerny.narration_lessons import narration_job
from lerny.rag_answers import answer_job
import test_gemini_integration as integration_tests
import test_lecture_grounding as grounding_tests

api = integration_tests.api
configured = integration_tests.configured
fake_provider = integration_tests.fake_provider
integration = integration_tests.integration
index_all = integration_tests.index_all
post_lesson = integration_tests.post_lesson
seed_request = grounding_tests.seed_request
simulated_reviewer = grounding_tests.simulated_reviewer
spec = grounding_tests.spec

SECRET = 'PRIVATE_STACK_RUBRIC_SENTINEL'
SOURCE_IDS = ['src_stack_01', 'src_stack_02']


def add_reference(session, key='ref', **overrides):
    material = Material(
        id=key, course_id=overrides.pop('course_id', 'course'),
        title='stack teacher answer', kind='answer', week=1,
        visibility='private', internal_use='validation_grading',
        active_version_id=key+'-v',
    )
    for field, value in overrides.items():
        setattr(material, field, value)
    session.add(material)
    session.flush()
    session.add(MaterialVersion(
        id=key+'-v', material_id=key, version_no=1, filename='reference.txt',
        object_key='unused-reference', sha256='b'*64, status='ready',
        extracted_text='stack '+SECRET,
    ))
    session.flush()
    session.add(Chunk(id=key+'-chunk', version_id=key+'-v',
                      content='stack '+SECRET, locator={'page': 1}))
    session.commit()
    return material


def enroll(session):
    from publication_fixtures import published
    session.get(Material,"material").kind="lecture"
    published(session,"course")
    session.add(Section(id='section', course_id='course', title='Synthetic section'))
    session.flush()
    session.add(Enrollment(student_id='student', section_id='section',
                           course_id='course', status='active'))
    session.commit()


def student(client, tokens):
    client.cookies.set(COOKIE, tokens['student'][0])
    client.headers['X-CSRF-Token'] = tokens['student'][1]


def private_result(prompt, verdict='consistent'):
    data = json.loads(prompt.rsplit('\n', 1)[1])
    assert SECRET in str(data['private_validation_only'])
    return {'checks': [{'target': u['target'], 'verdict': verdict}
                       for u in data['review_units']]}


def test_gemini_selects_ready_unembedded_reference_without_any_model_call(integration, monkeypatch):
    _, session, _ = integration
    add_reference(session)
    monkeypatch.setattr(retrieval, 'perform', lambda *_: pytest.fail('No embedding request'))
    refs = retrieval.internal_validation_context(session, 'course', 'stack', SOURCE_IDS)
    assert refs == ['stack '+SECRET]
    assert retrieval.internal_validation_context(session, 'course', 'unrelated-topic', SOURCE_IDS) == []
    assert retrieval.internal_validation_context(session, 'other-course', 'stack', SOURCE_IDS) == []
    assert retrieval.internal_validation_context(session, 'course', 'stack', []) == []


@pytest.mark.parametrize('change', ['week', 'kind', 'internal_use', 'deleted', 'active_version_id', 'status'])
def test_reference_filters_unrelated_or_revoked_materials(integration, change):
    _, session, _ = integration
    material = add_reference(session)
    if change == 'status':
        session.get(MaterialVersion, 'ref-v').status = 'extracted'
    else:
        setattr(material, change, {'week': 2, 'kind': 'lecture', 'internal_use': 'none',
                                  'deleted': True, 'active_version_id': None}[change])
    session.commit()
    assert retrieval.internal_validation_context(session, 'course', 'stack', SOURCE_IDS) == []


@pytest.mark.parametrize('internal_use', ['none', 'validation_grading'])
def test_legacy_public_answer_is_not_student_visible(integration, internal_use):
    client, session, tokens = integration
    add_reference(session, visibility='public', internal_use=internal_use)
    enroll(session)
    student(client, tokens)
    response = client.get('/api/v1/courses/course/materials')
    assert response.status_code == 200
    assert 'ref' not in {m['id'] for m in response.json()['items']}
    for suffix in ('/file', '/file?version_id=ref-v', '/transcript'):
        assert client.get('/api/v1/materials/ref'+suffix).status_code == 404
    assert all(m.id != 'ref' for _, m, _ in retrieval.public_rows(session, 'course'))


def test_local_upload_and_access_cannot_publish_answer(integration):
    client, session, _ = integration
    response = client.post('/api/v1/courses/course/materials',
        data={'kind': 'answer', 'week': '1', 'visibility': 'public'},
        files={'file': ('reference.txt', b'Synthetic answer', 'text/plain')})
    assert response.status_code == 201, response.text
    material = session.get(Material, response.json()['material_id'])
    assert material.visibility == 'private'
    changed = client.patch('/api/v1/materials/'+material.id+'/access',
        headers={'If-Match': str(material.revision)}, json={'visibility': 'public'})
    assert changed.status_code == 200 and changed.json()['visibility'] == 'private'


@pytest.mark.parametrize('verdict', ['consistent', 'conflicting', 'uncertain'])
def test_chat_private_check_never_supplies_the_answer(integration, fake_provider, monkeypatch, verdict):
    client, session, tokens = integration
    index_all(session)
    add_reference(session)
    enroll(session)
    message = ChatMessage(student_id='student', section_id='section', thread_id='thread',
                          question='stack rule', access_epoch=1)
    session.add(message)
    session.flush()
    job = Job(owner_id='student', course_id='course', kind='chat', payload={'message_id': message.id})
    session.add(job)
    session.flush()
    original, private_calls = worker.model_json, []

    def generate(prompt, schema):
        if 'private_validation_only' in prompt:
            private_calls.append(prompt)
            return private_result(prompt, verdict)
        assert SECRET not in prompt
        return original(prompt, schema)

    monkeypatch.setattr(worker, 'model_json', generate)
    result = answer_job(session, job)
    assert len(private_calls) == 1
    assert SECRET not in json.dumps(result) and 'teacher answer' not in json.dumps(result)
    assert result['validation'] == ('citation_checked' if verdict == 'consistent' else 'held')
    job.result, job.status = result, 'succeeded'
    session.commit()
    student(client, tokens)
    assert SECRET not in client.get('/api/v1/jobs/'+job.id).text
    assert all(SECRET not in json.dumps(payload) for _, payload in fake_provider)


@pytest.mark.parametrize('verdict', ['consistent', 'conflicting'])
def test_narration_private_check_is_separate_from_draft(integration, fake_provider, monkeypatch, verdict):
    client, session, _ = integration
    index_all(session)
    add_reference(session)
    response = post_lesson(client)
    job = session.get(Job, response.json()['job_id'])
    original, seen = worker.model_json, []

    def generate(prompt, schema):
        if 'private_validation_only' in prompt:
            seen.append(prompt)
            return private_result(prompt, verdict)
        assert SECRET not in prompt
        return original(prompt, schema)

    monkeypatch.setattr(worker, 'model_json', generate)
    result = narration_job(session, job)
    assert seen and SECRET not in json.dumps(result)
    assert result['validation'] == ('model_reviewed' if verdict == 'consistent' else 'held')
    job.result, job.status = result, 'succeeded'
    session.commit()
    response = client.get(response.json()['poll_url']).json()
    assert ('video_plan' in response) == (verdict == 'consistent')
    assert SECRET not in json.dumps(response)


def test_question_generation_public_but_validation_uses_answer_reference(integration, monkeypatch):
    _, session, _ = integration
    add_reference(session)
    monkeypatch.setattr('lerny.assessment.search_public', lambda *_, **__: retrieval.public_rows(session, 'course'))
    seen = []

    def generate(prompt, schema):
        data = json.loads(prompt.rsplit('\n', 1)[1])
        if 'topic' in data and 'retrieved_excerpts' in data:
            assert SECRET not in prompt
            source = data['retrieved_excerpts'][0]
            return dict(concept_id='concept_stack', question='Explain stack ' + data['difficulty'],
                        options=['rule', 'wrong1', 'wrong2', 'wrong3'], correct_index=0,
                        explanation=source['text'], distractor_rationales=['supported', 'wrong', 'wrong', 'wrong'],
                        source_id=source['source_id'], quote=source['text'])
        if 'concept' in data:
            assert SECRET not in prompt
            ids = [s['chunk_id'] for s in data['evidence']]
            return [dict(
                kind='mcq' if i < 2 else 'essay', prompt=f'Explain stack rule {i}',
                options=['rule', 'wrong1', 'wrong2', 'wrong3'] if i < 2 else [],
                answer_index=0, explanation='Synthetic public stack rule 1',
                criteria=[] if i < 2 else ids[:2], sources=[{'chunk_id': ids[0]}],
            ) for i in range(3)][-1]
        if 'options' in data:
            assert SECRET not in prompt
            return {'correct_options': [data['options'][0]]}
        assert SECRET in str(data['private_validation_only'])
        seen.append(data)
        return {'supported': True, 'unambiguous': True, 'answer_correct': True}

    monkeypatch.setattr(worker, 'model_json', generate)
    job = Job(owner_id='teacher', course_id='course', kind='questions', payload={'concept_id': 'concept_stack'})
    session.add(job)
    session.flush()
    assert generate_job(session, job)['count'] == 3 and len(seen) == 3
    for q in session.scalars(select(Question)):
        assert SECRET not in json.dumps([q.prompt, q.solution, q.sources])


def seed_grade(session):
    enroll(session)
    question = Question(id='q', course_id='course', concept_id='concept_stack', kind='essay',
        prompt='Explain stack', options=[],
        solution={'criteria': ['Synthetic public stack rule 1']},
        sources=[{'chunk_id': SOURCE_IDS[0], 'quote': 'Synthetic public stack rule 1'}])
    session.add(question)
    from publication_fixtures import published
    published(session,"course")
    session.add(LearningSession(id='daily', student_id='student', section_id='section',
                               day=date(2026, 11, 1), question_ids=['q']))
    session.flush()
    attempt = Attempt(id='attempt', student_id='student', section_id='section',
        learning_session_id='daily', question_id='q', concept_id='concept_stack',
        answer='Synthetic public stack rule 1')
    session.add(attempt)
    session.flush()
    job = Job(owner_id='student', course_id='course', kind='grade', payload={'attempt_id': attempt.id})
    session.add(job)
    session.commit()
    return attempt, job


@pytest.mark.parametrize('certain', [True, False])
def test_both_grading_passes_use_reference_but_student_feedback_cannot_copy_it(integration, monkeypatch, certain):
    client, session, tokens = integration
    add_reference(session)
    attempt, job = seed_grade(session)
    calls = []

    def grade(prompt, schema):
        assert SECRET in prompt
        assert '동일 가중치' in prompt and 'certain=false' in prompt
        calls.append(prompt)
        return {'certain': certain, 'criteria': {'C1': {'score': 100, 'answer_source_ids': ['A1']}}}

    monkeypatch.setattr(worker, 'model_json', grade)
    result = grade_job(session, job)
    assert len(calls) == 2
    assert result['status'] == ('graded' if certain else 'held')
    assert attempt.score == (100 if certain else None)
    assert SECRET not in json.dumps(attempt.feedback)
    session.commit()
    student(client, tokens)
    response = client.get('/api/v1/attempts/attempt')
    assert response.status_code == 200 and SECRET not in response.text


def test_reference_edit_during_grading_stops_before_second_pass(integration, monkeypatch):
    _, session, _ = integration
    add_reference(session)
    attempt, job = seed_grade(session)
    calls = []

    def grade(prompt, schema):
        calls.append(prompt)
        session.get(Course, 'course').access_epoch += 1
        session.flush()
        return {'certain': True, 'criteria': {'C1': {'score': 100, 'answer_source_ids': ['A1']}}}

    monkeypatch.setattr(worker, 'model_json', grade)
    with pytest.raises(ValueError, match='SOURCE_CHANGED'):
        grade_job(session, job)
    assert len(calls) == 1 and attempt.status == 'pending'


def test_paused_grade_job_never_contacts_gemini(integration, monkeypatch):
    _, session, _ = integration
    add_reference(session)
    _, job = seed_grade(session)
    monkeypatch.setattr(settings(), 'gemini_calls_enabled', False)
    monkeypatch.setattr(worker, 'model_json', lambda *_: pytest.fail('Model must remain paused'))
    assert worker.run_once(job.id) is True  # Moves queued -> waiting_ai without executing.
    session.expire_all()
    assert job.status == 'waiting_ai' and job.attempt == 0
    assert worker.run_once(job.id) is False
    with pytest.raises(ValueError, match='GEMINI_CALLS_DISABLED'):
        available()


@pytest.mark.parametrize('malformed', [
    {'checks': [{'target': 'wrong', 'verdict': 'consistent'}]},
    {'checks': [{'target': 'u', 'verdict': 'consistent'}, {'target': 'u', 'verdict': 'consistent'}]},
    {'checks': [{'target': 'u', 'verdict': 'consistent', 'explanation': SECRET}]},
])
def test_private_reviewer_cannot_return_free_text_or_missing_targets(malformed):
    try:
        result = review_references([{'target': 'u', 'text': 'public'}], [SECRET], lambda *_: malformed)
        assert result is False
    except ValidationError:
        pass


def test_lecture_grounding_uses_reference_verdict_without_private_citations(api, spec, monkeypatch):  # noqa: F811
    _, session, _ = api
    add_reference(session)
    # Match this synthetic Korean lecture while preserving the sentinel.
    session.get(Material, 'ref').title = spec['title']
    session.commit()
    _, queued = seed_request(api, spec)
    job = session.get(Job, queued['job_id'])
    job.status = 'running'
    session.commit()
    seen = []

    def generate(prompt, schema):
        if 'private_validation_only' in prompt:
            seen.append(prompt)
            return private_result(prompt, 'conflicting')
        assert SECRET not in prompt
        return simulated_reviewer(prompt, schema)

    monkeypatch.setattr(worker, 'model_json', generate)
    result = grounding_job(session, job)
    assert seen and result['status'] == 'held'
    assert SECRET not in json.dumps(result)


def test_private_review_reaches_selected_gemini_adapter_with_mock_transport(integration, monkeypatch):
    from lerny import gemini_provider

    requests = []

    def request(path, payload, parse):
        requests.append((path, payload))
        assert path == 'interactions'
        assert payload['model'] == settings().gemini_answer_model
        assert SECRET in payload['input']
        result = private_result(payload['input'])
        return parse({'status': 'completed', 'output_text': json.dumps(result)})

    monkeypatch.setattr(gemini_provider, 'request', request)
    assert review_references([{'target': 'u', 'text': 'public stack rule'}],
                             ['stack '+SECRET], worker.model_json)
    assert len(requests) == 1
