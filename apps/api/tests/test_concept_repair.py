"""Repair invalid generated evidence without redoing upload or successful AI calls."""
import json

import pytest

from lerny import weekly_content as weekly, worker
from lerny.models import Job
from test_weekly_publication import weekly as fixture_weekly, start  # noqa: F401
from test_gemini_integration import api, configured, integration  # noqa: F401

BATCH=[{'version_id':'ppt','text':'스택은 후입선출 자료구조입니다.'}]
SHORT={'concepts':[{'name':'스택','quote':'스택','version_id':'ppt'}]}
VALID={'concepts':[{'name':'스택','quote':'스택은 후입선출 자료구조입니다.','version_id':'ppt'}]}


def test_short_quote_repaired_with_same_source_and_strict_schema(monkeypatch):
    calls=[]
    def model(prompt,schema):
        calls.append(prompt)
        assert json.loads(prompt.rsplit('\n',1)[1])==BATCH
        assert schema['$defs']['ExtractedConcept']['properties']['quote']['minLength']==5
        return SHORT if len(calls)==1 else VALID
    monkeypatch.setattr(worker,'model_json',model)
    assert weekly.concepts_from_batch(BATCH)[0].quote==VALID['concepts'][0]['quote']
    assert len(calls)==2 and '5~500자' in calls[1]
    assert 'quote_too_short' in calls[1] and 'previous' in calls[1]


@pytest.mark.parametrize('replacement,code',[
    (SHORT,'CONCEPT_QUOTE_TOO_SHORT'),
    ({'concepts':[{'name':'스택','quote':'스택은 새로 지어낸 설명입니다.','version_id':'ppt'}]},'INVALID_CONCEPT_EVIDENCE'),
    ({'concepts':[{'name':'스택','quote':'스택은 후입선출 자료구조입니다.','version_id':'other'}]},'INVALID_CONCEPT_EVIDENCE'),
])
def test_bounded_repair_rejects_short_invented_and_cross_source_quotes(monkeypatch,replacement,code):
    calls=[]
    monkeypatch.setattr(worker,'model_json',lambda prompt,schema:(calls.append(prompt) or (SHORT if len(calls)==1 else replacement)))
    with pytest.raises(weekly.ConceptGenerationError,match=code) as caught:
        weekly.concepts_from_batch(BATCH)
    assert len(calls)==2
    assert caught.value.validation_error['repair_attempts']==1
    assert caught.value.validation_error['issues'][0]['concept_index']==0
    assert '스택' not in json.dumps(caught.value.validation_error,ensure_ascii=False)


def test_retry_changes_only_repair_prompt_and_provider_errors_propagate(monkeypatch):
    calls=[]
    monkeypatch.setattr(worker,'model_json',lambda prompt,schema:(calls.append(prompt) or SHORT))
    for round in [0,1]:
        with pytest.raises(weekly.ConceptGenerationError):
            weekly.concepts_from_batch(BATCH,round)
    assert calls[0]==calls[2] and calls[1]!=calls[3]
    from lerny.gemini_provider import ProviderDeferred
    error=ProviderDeferred('GEMINI_TEMPORARILY_UNAVAILABLE',12345)
    def defer(prompt,schema):
        raise error
    monkeypatch.setattr(worker,'model_json',defer)
    with pytest.raises(ProviderDeferred) as caught:
        weekly.concepts_from_batch(BATCH)
    assert caught.value is error


def test_worker_records_final_validation_reason_then_retry_keeps_completed_cache(fixture_weekly,monkeypatch):
    client,session,_=fixture_weekly
    gid=start(client)
    job=weekly.generation_jobs(session,session.get(weekly.ContentGeneration,gid))[0]
    job.result={'provider_error':{'status':503},'media_progress':{'completed':5}}
    job.payload={**job.payload,'_ai_generation':4}
    session.commit()
    monkeypatch.setattr(worker,'model_json',lambda *args: SHORT)
    assert worker.run_once(job.id)
    session.expire_all();job=session.get(Job,job.id)
    assert job.status=='failed' and job.error_code=='CONCEPT_QUOTE_TOO_SHORT'
    assert job.result['media_progress']=={'completed':5}
    assert 'provider_error' not in job.result
    issues=job.result['validation_error']['issues']
    assert issues==[{'concept_index':0,'reason':'quote_too_short','batch_number':1}]
    listing=client.get('/api/v1/courses/course/weekly-content').json()['items'][0]['draft']
    assert listing['jobs'][0]['validation_issues']==issues
    response=client.post(f'/api/v1/courses/course/content-generations/{gid}/retry',json={})
    assert response.status_code==200,response.text
    session.expire_all();job=session.get(Job,job.id)
    assert job.status=='queued' and job.payload['_ai_generation']==4
    assert job.payload['_concept_retry_round']==0 and job.payload['_concept_repair_rounds']=={'1':1} and job.result is None


def test_legacy_failure_retry_preserves_successful_batch_cache(fixture_weekly):
    client,session,_=fixture_weekly;gid=start(client)
    job=weekly.generation_jobs(session,session.get(weekly.ContentGeneration,gid))[0]
    job.status='failed';job.error_code='PROCESSING_FAILED';session.commit()
    assert client.post(f'/api/v1/courses/course/content-generations/{gid}/retry',json={}).status_code==200
    session.expire_all();job=session.get(Job,job.id)
    assert job.payload.get('_ai_generation',0)==0
    assert job.payload['_concept_retry_round']==1


def test_line_break_only_quote_is_restored_to_exact_original(monkeypatch):
    batch=[{'version_id':'ppt','text':'트리 구조는 계층\n 형식을 가지고 있습니다.'}]
    output={'concepts':[{'version_id':'ppt','name':'트리','quote':'트리 구조는 계층 형식을 가지고 있습니다.'}]}
    calls=[]
    monkeypatch.setattr(worker,'model_json',lambda prompt,schema:(calls.append(prompt) or output))
    assert weekly.concepts_from_batch(batch)[0].quote==batch[0]['text']
    assert len(calls)==1


@pytest.mark.parametrize('quote',['트리 구조는 계층형식을 가지고 있습니다.','트리 구조는 계층 형식을 가지고 있지요.'])
def test_word_boundary_and_word_changes_are_not_whitespace_repairs(quote):
    batch=[{'version_id':'ppt','text':'트리 구조는 계층\n 형식을 가지고 있습니다.'}]
    item=weekly.ExtractedConcept(name='트리',quote=quote,version_id='ppt')
    assert weekly.restore_quote_whitespace(item,batch).quote==quote
    assert quote not in batch[0]['text']


def test_repair_options_are_exact_same_source_context():
    issues=[{'concept_index':0,'reason':'quote_too_short'}]
    options=weekly.repair_source_options(SHORT,issues,BATCH)
    assert options[0]['exact_source_options'][0]=={'version_id':'ppt','quote':BATCH[0]['text']}
    assert weekly.repair_source_options(SHORT,issues,[{'version_id':'other','text':BATCH[0]['text']}])[0]['exact_source_options']==[]


@pytest.mark.parametrize('code,http_status,attached',[
    ('GEMINI_RATE_LIMITED',503,False),('GEMINI_RATE_LIMITED',429,True),
    ('GEMINI_REQUEST_REJECTED',409,True),('GEMINI_PACING_WAIT',503,False)])
def test_quota_wait_does_not_present_an_earlier_service_error(fixture_weekly,monkeypatch,code,http_status,attached):
    from lerny import gemini_failures
    from lerny.gemini_quota import ProviderDeferred
    from lerny.models import now
    client,session,_=fixture_weekly;gid=start(client)
    job=weekly.generation_jobs(session,session.get(weekly.ContentGeneration,gid))[0]
    monkeypatch.setattr(gemini_failures,'latest_error',lambda job:{'http_status':http_status})
    def quota(*args):
        if code=='GEMINI_REQUEST_REJECTED':raise ValueError(code)
        raise ProviderDeferred(code,now().timestamp()+3600)
    monkeypatch.setattr(worker,'model_json',quota)
    assert worker.run_once(job.id)
    session.expire_all();job=session.get(Job,job.id)
    assert job.status==('failed' if code=='GEMINI_REQUEST_REJECTED' else 'queued') and job.error_code==code
    assert ('provider_error' in (job.result or {})) is attached
