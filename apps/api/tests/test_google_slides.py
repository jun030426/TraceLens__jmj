import copy
import io
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from cryptography.fernet import Fernet
from PIL import Image
from pydantic import SecretStr
from sqlalchemy import select

from lerny import google_slides_auth as auth, lecture_slides as slides, video_worker, worker
from lerny.google_slides_client import GoogleSlidesClient, validate_deck
from lerny.lecture_slide_layout import TeachingPlan, TeachingSlide, slide_requests
from lerny.models import ConceptVideo, ContentGeneration, GoogleSlidesConnection, GoogleSlidesServiceConnection, GoogleSlidesOAuthState, Job, now
from test_gemini_integration import api, configured, integration  # noqa: F401
from test_weekly_publication import weekly, start, completed, publish, login  # noqa: F401
from test_heygen_site_video import lesson


@pytest.fixture(autouse=True)
def network(monkeypatch):
    def no_network(*args,**kwargs):raise AssertionError('Live network forbidden')
    monkeypatch.setattr(httpx.HTTPTransport,'handle_request',no_network)
    # The lightweight SQLite fixture does not retain timezone metadata.
    monkeypatch.setattr(auth,'now',lambda:datetime.now(UTC).replace(tzinfo=None))
    monkeypatch.setattr(slides,'now',lambda:datetime.now(UTC).replace(tzinfo=None))


def setup_oauth(configured,monkeypatch):
    for key,value in {'google_slides_client_id':'client.apps.googleusercontent.com',
        'google_slides_client_secret':SecretStr('synthetic-client-secret'),
        'google_slides_token_key':SecretStr(Fernet.generate_key().decode()),
        'google_slides_redirect_uri':'http://localhost:5173/api/v1/google-slides/callback'}.items():
        monkeypatch.setattr(configured,key,value)


def fixture_video(weekly):
    client,session,tokens=weekly;gid=start(client)
    g=completed(session,gid)
    v=session.get(ConceptVideo,gid+'-video')
    v.script={'lesson':lesson()};v.provider_video_id='preserved-receipt'
    j=Job(owner_id='teacher',course_id='course',kind='narration_lesson',status='succeeded',payload={},
          result={'validation':'model_reviewed','draft':v.script})
    session.add(j);session.flush();v.script_job_id=j.id
    session.commit()
    return client,session,tokens,g,v


def plan():
    return TeachingPlan(slides=[TeachingSlide(heading='스택',key_point='마지막에 넣은 값을 먼저 꺼내요',
        kind='steps',items=['push: 맨 위에 추가','pop: 맨 위에서 제거'],caption='후입선출') for _ in range(2)])


def deck(scripts,revision='revision-one'):
    return {'revisionId':revision,'slides':[{'objectId':f'lerny_scene_{i:03d}',
        'slideProperties':{'notesPage':{'notesProperties':{'speakerNotesObjectId':f'note_{i}'},
            'pageElements':[{'objectId':f'note_{i}','shape':{'text':{'textElements':[
                {'textRun':{'content':text+'\n'}}]}}}]}}} for i,text in enumerate(scripts)]}


def test_default_hold_blocks_new_paid_calls_but_not_receipt_poll(weekly,monkeypatch):
    monkeypatch.setattr(video_worker.settings(), 'heygen_rendering_enabled', False)
    _,session,_,g,v=fixture_video(weekly)
    v.status='queued';v.provider_video_id=None;session.commit()
    assert video_worker.claim(session) is None
    updates=[];monkeypatch.setattr(video_worker,'update',lambda item,**kw:updates.append(kw))
    with httpx.Client() as c:video_worker.process({'action':'submit','request':v.request},c)
    assert updates==[{'status':'queued','error_code':'HEYGEN_RENDERING_PAUSED'}]
    v.status='processing';v.provider_video_id='preserved-receipt';session.commit()
    assert video_worker.claim(session)['action']=='poll'


def service_state(session):
    query=parse_qs(urlparse(auth.begin_service_connection(session)['url']).query)
    assert query['scope']==[auth.SCOPE] and query['access_type']==['offline']
    assert query['code_challenge_method']==['S256']
    state=query['state'][0]
    pending=session.get(GoogleSlidesOAuthState,auth.digest(state))
    assert pending.owner_id is None and pending.state_hash!=state
    assert auth.decrypt(pending.verifier)!=query['code_challenge'][0]
    return state


def test_shared_oauth_cli_state_single_use_without_instructor_login(weekly,configured,monkeypatch):
    client,session,tokens=weekly;setup_oauth(configured,monkeypatch)
    assert client.post('/api/v1/google-slides/connect').status_code==403
    assert session.scalar(select(GoogleSlidesOAuthState)) is None
    for owner in ('teacher','outsider'):
        session.add(Job(owner_id=owner,course_id='course',kind='lecture_slides',status='waiting_google',payload={},result={'plan':'cached'}))
    session.commit();state=service_state(session)
    requests=[]
    def token(payload):
        requests.append(payload)
        return {'refresh_token':'private-refresh','scope':auth.SCOPE}
    monkeypatch.setattr(auth,'token_request',token)
    client.cookies.clear();client.headers.pop('X-CSRF-Token',None)
    assert client.post('/api/v1/google-slides/connect').status_code in {401,403}
    response=client.get('/api/v1/google-slides/callback',params={'state':state,'code':'test'})
    assert response.status_code==200,response.text
    assert response.headers['cache-control']=='no-store'
    assert response.headers['referrer-policy']=='no-referrer'
    assert requests[0]['code_verifier'] and requests[0]['grant_type']=='authorization_code'
    connection=session.get(GoogleSlidesServiceConnection,'lerny')
    assert connection.refresh_token!='private-refresh' and auth.decrypt(connection.refresh_token)=='private-refresh'
    assert session.get(GoogleSlidesConnection,'teacher') is None
    assert all(j.status=='queued' and j.result=={'plan':'cached'} for j in session.scalars(select(Job).where(Job.kind=='lecture_slides')))
    assert client.get('/api/v1/google-slides/callback',params={'state':state,'code':'test'}).status_code==400
    assert len(requests)==1
    for owner in ('teacher','outsider'):
        login(client,tokens,owner)
        status=client.get('/api/v1/google-slides/connection')
        assert status.json()['connected'] and status.json()['mode']=='service'
        assert 'private-refresh' not in status.text and 'secret' not in status.text
    login(client,tokens,'student')
    assert client.get('/api/v1/google-slides/connection').status_code==403
    assert client.post('/api/v1/google-slides/connect').status_code==403


def test_service_oauth_expired_denied_legacy_missing_refresh_and_csrf(weekly,configured,monkeypatch):
    client,session,_=weekly;setup_oauth(configured,monkeypatch)
    assert client.post('/api/v1/google-slides/connect',headers={'X-CSRF-Token':'bad'}).status_code==403
    assert client.get('/api/v1/google-slides/callback',params={'state':'invented','code':'x'}).status_code==400
    state=service_state(session)
    pending=session.get(GoogleSlidesOAuthState,auth.digest(state));pending.expires_at=auth.now()-timedelta(seconds=1);session.commit()
    assert client.get('/api/v1/google-slides/callback',params={'state':state,'code':'x'}).status_code==400
    state=service_state(session)
    pending=session.get(GoogleSlidesOAuthState,auth.digest(state));pending.owner_id='teacher';session.commit()
    assert client.get('/api/v1/google-slides/callback',params={'state':state,'code':'x'}).status_code==400
    state=service_state(session)
    assert client.get('/api/v1/google-slides/callback',params={'state':state,'error':'access_denied'}).status_code==200
    assert client.get('/api/v1/google-slides/callback',params={'state':state,'code':'x'}).status_code==400
    state=service_state(session)
    monkeypatch.setattr(auth,'token_request',lambda payload:{'scope':auth.SCOPE})
    assert client.get('/api/v1/google-slides/callback',params={'state':state,'code':'x'}).status_code==409
    assert client.get('/api/v1/google-slides/callback',params={'state':state,'code':'x'}).status_code==400
    assert session.get(GoogleSlidesServiceConnection,'lerny') is None


def test_access_token_uses_only_operator_connection(weekly,configured,monkeypatch):
    _,session,_=weekly;setup_oauth(configured,monkeypatch)
    session.add(GoogleSlidesConnection(owner_id='teacher',refresh_token=auth.encrypt('legacy'),scopes=auth.SCOPE));session.commit()
    with pytest.raises(ValueError,match='CONNECT_REQUIRED'):auth.access_token(session)
    session.add(GoogleSlidesServiceConnection(id='lerny',refresh_token=auth.encrypt('common'),scopes=auth.SCOPE));session.commit()
    def token(payload):
        assert payload['refresh_token']=='common'
        return {'access_token':'shared-access'}
    monkeypatch.setattr(auth,'token_request',token)
    assert auth.access_token(session)=='shared-access'


def test_prepare_reuses_script_and_published_video_and_denies_students(weekly):
    client,session,tokens,g,v=fixture_video(weekly)
    assert publish(client,g.id).status_code==200
    before=copy.deepcopy((v.script,v.request,v.object_key,v.status,v.provider_video_id,g.published_at))
    url=f'/api/v1/courses/course/content-generations/{g.id}/lecture-slides'
    for _ in range(2):assert client.post(url).json()=={'count':1,'video_submitted':False}
    jobs=list(session.scalars(select(Job).where(Job.kind=='lecture_slides')));assert len(jobs)==1
    assert 'generation_id' not in jobs[0].payload
    assert before==(v.script,v.request,v.object_key,v.status,v.provider_video_id,g.published_at)
    login(client,tokens,'student');assert client.post(url).status_code in {403,404}
    assert client.get(url).status_code in {403,404}


def test_worker_checkpoints_plan_then_waits_for_google_without_new_video(weekly,monkeypatch):
    client,session,_,g,v=fixture_video(weekly)
    job=slides.enqueue(session,v);session.commit();jid=job.id
    calls=[];monkeypatch.setattr(slides,'make_plan',lambda *args:calls.append('plan') or plan())
    assert worker.run_once(jid)
    session.expire_all();job=session.get(Job,jid)
    assert job.status=='waiting_google' and job.result['plan'] and job.error_code=='GOOGLE_SLIDES_SETUP_REQUIRED',job.error_code
    assert v.status=='ready' and v.provider_video_id=='preserved-receipt'
    job.status='queued';session.commit();assert worker.run_once(jid)
    assert calls==['plan']


def test_resume_native_deck_reviews_and_rechecks_before_approval(weekly,monkeypatch):
    client,session,_,g,v=fixture_video(weekly)
    job=slides.enqueue(session,v);session.commit();jid=job.id
    calls=[];saved={};scripts=lesson()['narration'];state={'revision':'revision-one'}
    class Google:
        def __init__(self,token):assert token=='test'
        def find(self,jid):calls.append('find');return None
        def create(self,*args):calls.append('create');return 'presentation-id'
        def populate(self,*args):calls.append('populate');return deck(scripts,state['revision'])
        def get(self,pid):return deck(scripts,state['revision'])
        def thumbnail(self,*args):
            calls.append('thumbnail');output=io.BytesIO();Image.new('RGB',(160,90)).save(output,'PNG');return output.getvalue()
    monkeypatch.setattr(slides,'GoogleSlidesClient',Google)
    monkeypatch.setattr(slides,'access_token',lambda *args:'test')
    monkeypatch.setattr(slides,'make_plan',lambda *args:plan())
    monkeypatch.setattr(slides.storage,'request',lambda method,path,**kw:saved.update({path:kw['content']}))
    assert worker.run_once(jid);session.expire_all();job=session.get(Job,jid)
    assert job.status=='succeeded' and job.result['status']=='review_required',job.error_code
    assert calls.count('create')==1 and len(job.result['previews'])==2
    token=job.result['review_token'];state['revision']='changed'
    assert client.post(f'/api/v1/lecture-slides/{jid}/approve',json={'review_token':token}).status_code==409
    state['revision']='revision-one'
    assert client.post(f'/api/v1/lecture-slides/{jid}/approve',json={'review_token':token}).status_code==200
    session.expire_all();assert job.result['status']=='approved' and v.object_key=='synthetic.mp4'
    assert client.post(f'/api/v1/lecture-slides/{jid}/refresh').status_code==200
    session.expire_all();assert 'approved_at' not in job.result
    assert worker.run_once(jid);assert calls.count('create')==1


def test_uncertain_create_never_posts_again_and_changed_source_denies(weekly,monkeypatch):
    _,session,_,g,v=fixture_video(weekly)
    job=slides.enqueue(session,v);job.result={'plan':plan().model_dump(),'scripts':lesson()['narration'],'creating':True};session.commit()
    monkeypatch.setattr(slides,'access_token',lambda *args:'test')
    monkeypatch.setattr(GoogleSlidesClient,'find',lambda *args:None)
    assert worker.run_once(job.id);session.expire_all()
    assert job.error_code=='GOOGLE_SLIDES_CREATION_UNCERTAIN'
    v.script={**v.script,'changed':True};session.commit()
    with pytest.raises(ValueError,match='SCRIPT_VALIDATION_REQUIRED'):slides.valid_video(session,v)


def test_layout_preserves_safe_areas_and_rejects_overflow():
    requests=slide_requests(plan().slides[0],'page_one',1,2)
    for item in requests:
        shape=item.get('createShape')
        if shape:
            e=shape['elementProperties'];assert e['transform']['translateX']>=398
            assert e['transform']['translateY']+e['size']['height']['magnitude']<=460
    with pytest.raises(ValueError):TeachingSlide(heading='x',key_point='y',kind='code',items=['x'],code='x\n'*7,caption='z')
    with pytest.raises(ValueError):TeachingSlide(heading='x',key_point='y',kind='compare',items=['one'],caption='z')
    scripts=lesson()['narration'];d=deck(scripts)
    assert len(validate_deck(d,scripts))==2
    d['slides'][0]['slideProperties']['isSkipped']=True
    with pytest.raises(ValueError,match='SCRIPT_MISMATCH'):validate_deck(d,scripts)


def test_thumbnail_uses_trusted_origin_without_bearer_and_bounds(monkeypatch):
    google=GoogleSlidesClient('private');monkeypatch.setattr(google,'request',lambda *args,**kw:{'contentUrl':'https://evil.example/p.png'})
    with pytest.raises(ValueError,match='INVALID_THUMBNAIL'):google.thumbnail('presentation','page_one')
    monkeypatch.setattr(google,'request',lambda *args,**kw:{'contentUrl':'https://lh7.googleusercontent.com/p.png'})
    out=io.BytesIO();Image.new('RGB',(160,90)).save(out,'PNG');raw=out.getvalue();real=httpx.Client
    def check(req):
        assert 'authorization' not in req.headers
        return httpx.Response(200,content=raw)
    monkeypatch.setattr(httpx,'Client',lambda **kw:real(transport=httpx.MockTransport(check),**kw))
    assert google.thumbnail('presentation','page_one')==raw


def test_populate_initial_notes_inserts_without_deleting_absent_shape(monkeypatch):
    scripts=lesson()['narration'];d=deck(scripts)
    d['pageSize']={'width':{'magnitude':960,'unit':'PT'},'height':{'magnitude':540,'unit':'PT'}}
    for p in d['slides']:p['slideProperties']['notesPage']['pageElements']=[]
    google=GoogleSlidesClient('test');batches=[]
    monkeypatch.setattr(google,'get',lambda pid:d)
    monkeypatch.setattr(google,'batch',lambda pid,requests,revision:batches.extend(requests))
    google.populate('presentation',plan(),scripts)
    assert len(batches)==2 and all('insertText' in r for r in batches)


def test_generation_uses_small_schema_but_rejects_overflow_and_repairs_once(monkeypatch):
    import json
    from lerny.lecture_slide_layout import generation_schema
    from lerny.heygen_lecture_profile import NarrationLesson
    schema=json.dumps(generation_schema())
    assert not any(key in schema for key in ('$ref','maxItems','minItems','maxLength'))
    invalid=plan().model_dump();invalid['slides'][0]['heading']='가'*29
    responses=[invalid,plan().model_dump(),{'approved':True,'issues':[]}];calls=[]
    def fake(prompt,schema):calls.append(prompt);return responses.pop(0)
    monkeypatch.setattr(worker,'model_json',fake)
    result=slides.make_plan(NarrationLesson.model_validate(lesson()),lesson()['narration'])
    assert result==plan() and len(calls)==3 and '이전 구성안' in calls[1]
    monkeypatch.setattr(worker,'model_json',lambda *args:invalid)
    with pytest.raises(ValueError,match='SLIDES_LAYOUT_REVIEW_REQUIRED'):
        slides.make_plan(NarrationLesson.model_validate(lesson()),lesson()['narration'])


def default_drive_deck():
    page=deck([''])['slides'][0];page['objectId']='p'
    page['pageElements']=[{'objectId':oid,'shape':{'shapeType':'TEXT_BOX','placeholder':{'type':kind}}}
                          for oid,kind in [('i0','CENTERED_TITLE'),('i1','SUBTITLE')]]
    return {'revisionId':'initial-revision','pageSize':{'width':{'magnitude':9144000,'unit':'EMU'},
        'height':{'magnitude':5143500,'unit':'EMU'}},'slides':[page]}


def test_populate_reuses_drive_created_empty_title_atomically(monkeypatch):
    scripts=lesson()['narration'];initial=default_drive_deck();built=deck(scripts)
    views=iter([initial,built,built]);batches=[];google=GoogleSlidesClient('test')
    monkeypatch.setattr(google,'get',lambda pid:next(views))
    monkeypatch.setattr(google,'request',lambda *args,**kw:{'appProperties':{'lerny_slide_job':'owned-job'}})
    monkeypatch.setattr(google,'batch',lambda pid,requests,revision:batches.append((requests,revision)))
    assert google.populate('presentation-id',plan(),scripts,'owned-job')==built
    requests,revision=batches[0]
    assert revision=='initial-revision' and requests[0]=={'deleteObject':{'objectId':'p'}}
    assert [x['createSlide']['objectId'] for x in requests if 'createSlide' in x]==['lerny_scene_000','lerny_scene_001']
    assert len(batches)==2


@pytest.mark.parametrize('change',['text','notes','extra_shape','placeholder','wrong_job','no_job','renamed_page'])
def test_populate_never_replaces_content_or_another_jobs_file(monkeypatch,change):
    initial=default_drive_deck();page=initial['slides'][0];job='owned-job'
    if change=='text':page['pageElements'][0]['shape']['text']={'textElements':[{'textRun':{'content':'User edit'}}]}
    elif change=='notes':page['slideProperties']['notesPage']['pageElements'][0]['shape']['text']['textElements'][0]['textRun']['content']='User notes'
    elif change=='extra_shape':page['pageElements'].append({'objectId':'drawn','shape':{'shapeType':'ELLIPSE'}})
    elif change=='placeholder':page['pageElements'][0]['shape']['placeholder']['type']='BODY'
    elif change=='no_job':job=None
    elif change=='renamed_page':page['objectId']='user-page'
    google=GoogleSlidesClient('test')
    monkeypatch.setattr(google,'get',lambda pid:initial)
    monkeypatch.setattr(google,'request',lambda *args,**kw:{'appProperties':{'lerny_slide_job':'other-job' if change=='wrong_job' else 'owned-job'}})
    def no_mutation(*args,**kwargs):raise AssertionError('Must preserve edited/foreign slides')
    monkeypatch.setattr(google,'batch',no_mutation)
    with pytest.raises(ValueError,match='CHANGED_REVIEW_REQUIRED'):
        google.populate('presentation-id',plan(),lesson()['narration'],job)
