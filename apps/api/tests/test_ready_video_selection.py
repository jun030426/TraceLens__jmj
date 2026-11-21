"""Ready-only review preserves deferred assets and the explicit publication boundary."""
import pytest
from sqlalchemy import select
from lerny import course_videos, video_worker, weekly_content
from lerny.models import Concept, ConceptVideo, ContentGeneration, Job, Question
from test_gemini_integration import api, configured, integration  # noqa: F401
from test_weekly_publication import completed, login, publish, start, weekly  # noqa: F401


def draft(weekly):
    client, session, tokens = weekly
    gid = start(client)
    g = completed(session, gid)
    session.add(Concept(id='other', course_id='course', name='Other'))
    session.flush()
    g.concept_ids = [*g.concept_ids, 'other']
    g.concept_evidence = [*g.concept_evidence, {'id':'other','name':'Other','description':'Synthetic public stack rule 1','version_id':'version'}]
    for i in range(g.options["mcq_per_concept"]):
        source = session.get(Question, f'{gid}-q{i}')
        session.add(Question(id=f'other-q{i}', course_id='course', generation_id=gid,
            concept_id='other', source_version_id='version', kind=source.kind, prompt=f'Other {i}',
            options=source.options, solution=source.solution, sources=source.sources))
    job = Job(course_id='course', owner_id='teacher', kind='narration_lesson', status='succeeded',
              payload={'generation_id':gid,'concept_id':'other'}, result={'validation':'model_reviewed'})
    session.add(job); session.flush()
    session.add(ConceptVideo(id='deferred', course_id='course', generation_id=gid, version_id='version',
        concept_id='other', owner_id='teacher', position=2, title='Later', status='queued',
        script_job_id=job.id, script={'keep':'script'}, request={'keep':'request'}))
    session.commit()
    return client, session, tokens, gid


def select_mode(client, gid, mode='ready_only', token=None):
    token = token or client.get(f'/api/v1/courses/course/content-generations/{gid}').json()['review_token']
    return client.post(f'/api/v1/courses/course/content-generations/{gid}/video-selection',
                       json={'mode':mode,'review_token':token})


def test_ready_selection_preserves_assets_and_requires_separate_publication(weekly):
    client, session, tokens, gid = draft(weekly)
    assert publish(client, gid).status_code == 409
    before = [(v.id,v.status,v.script,v.request,v.provider_video_id) for v in session.scalars(select(ConceptVideo))]
    response = select_mode(client, gid)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data['can_publish'] and data['state']=='ready' and data['status']=='draft'
    assert data['counts']['videos']==1 and data['counts']['videos_deferred']==1
    assert {v['id'] for v in data['videos'] if v['included']}=={gid+'-video'}
    session.expire_all()
    assert session.get(ContentGeneration,gid).published_at is None
    assert before == [(v.id,v.status,v.script,v.request,v.provider_video_id) for v in session.scalars(select(ConceptVideo))]
    # Later completion of an excluded receipt does not silently add it to the reviewed set.
    row=session.get(ConceptVideo,'deferred');row.status='ready';row.object_key='later.mp4';session.commit()
    login(client,tokens,'student')
    assert client.get('/api/v1/sections/section/concept-videos').json()['items']==[]
    login(client,tokens,'teacher')
    assert publish(client,gid).status_code==200
    login(client,tokens,'student')
    assert [v['id'] for v in client.get('/api/v1/sections/section/concept-videos').json()['items']]==[gid+'-video']
    assert client.get('/api/v1/concept-videos/deferred/file').status_code==404


def test_deferred_queue_never_submits_and_explicit_full_mode_restores_it(weekly, monkeypatch):
    client, session, _, gid = draft(weekly)
    monkeypatch.setattr(video_worker.settings(), 'heygen_rendering_enabled', False)
    assert select_mode(client,gid).status_code==200
    assert video_worker.claim(session) is None
    row=session.get(ConceptVideo,'deferred');assert row.status=='queued' and row.request=={'keep':'request'}
    assert client.post('/api/v1/courses/course/concept-videos/deferred/retry').status_code==409
    assert select_mode(client,gid,'all').status_code==200
    assert video_worker.claim(session) is None
    monkeypatch.setattr(video_worker.settings(), 'heygen_rendering_enabled', True)
    assert video_worker.claim(session)['action']=='submit'


def test_accepted_receipt_can_still_poll_while_new_renders_are_deferred(weekly):
    client, session, _, gid = draft(weekly)
    assert select_mode(client,gid).status_code==200
    row=session.get(ConceptVideo,'deferred');row.status='processing';row.provider_video_id='accepted';session.commit()
    assert video_worker.claim(session)['action']=='poll'


@pytest.mark.parametrize('actor',['student','outsider'])
def test_selection_is_staff_only(weekly,actor):
    client, session, tokens, gid = draft(weekly)
    login(client,tokens,actor)
    assert select_mode(client,gid,token='a'*64).status_code in (403,404)
    assert session.get(ContentGeneration,gid).options.get('video_mode') == 'all'


def test_stale_review_and_source_changes_cannot_change_selection(weekly):
    from lerny.models import Material
    client, session, _, gid = draft(weekly)
    old=client.get(f'/api/v1/courses/course/content-generations/{gid}').json()['review_token']
    assert select_mode(client,gid).status_code==200
    assert select_mode(client,gid,'all',old).status_code==409
    session.get(Material,'material').revision+=1;session.commit()
    assert select_mode(client,gid,'all').status_code==409


def test_no_ready_video_and_missing_selected_file_block_approval(weekly):
    client, session, _, gid = draft(weekly)
    row=session.get(ConceptVideo,gid+'-video');row.object_key=None;session.commit()
    assert select_mode(client,gid).status_code==409
    row.object_key='synthetic.mp4';session.commit()
    assert select_mode(client,gid).status_code==200
    row.object_key=None;session.commit()
    assert publish(client,gid).status_code==409


def test_failed_question_is_not_hidden_by_video_selection(weekly):
    client, session, _, gid = draft(weekly)
    job=session.scalar(select(Job).where(Job.kind=='questions'));job.status='failed';session.commit()
    response=select_mode(client,gid)
    assert response.status_code==200 and not response.json()['can_publish']
