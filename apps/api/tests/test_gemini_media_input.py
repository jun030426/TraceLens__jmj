import base64
import copy
import io
import json
import wave
from types import SimpleNamespace

import httpx
import pytest
from PIL import Image
from sqlalchemy.orm import Session
from lerny.gemini_input import input_units
from lerny import gemini_provider as provider, gemini_quota as quota
from lerny.inference import job_context
from lerny.models import GeminiQuota
from test_gemini_quota import paced, fake_http, BODY, PATH  # noqa: F401


def audio(seconds, rate=16000):
    stream=io.BytesIO()
    with wave.open(stream,'wb') as w:
        w.setparams((1,2,rate,0,'NONE','not compressed'))
        w.writeframes(b'\0\0'*int(seconds*rate))
    return {'type':'audio','mime_type':'audio/wav','data':base64.b64encode(stream.getvalue()).decode()}


def test_audio_units_use_duration_not_base64_or_pcm_sample_rate():
    a={**BODY,'input':[audio(6.52),audio(14.04),{'type':'text','text':'원음 검토'}]}
    original=copy.deepcopy(a)
    assert len(json.dumps(a).encode())>800000
    assert input_units(a)<2000 and a==original
    # Equivalent recording duration has the same admission cost at another rate.
    b={**a,'input':[audio(6.52,48000),audio(14.04,48000),a['input'][2]]}
    assert input_units(a)==input_units(b)


def test_images_text_and_nested_multimodal_sum_without_mutating_payload():
    f=io.BytesIO();Image.new('RGB',(1920,1080)).save(f,format='PNG')
    part={'type':'image','mime_type':'image/png','resolution':'high','data':base64.b64encode(f.getvalue()).decode()}
    a={**BODY,'input':[{'role':'user','content':[part,audio(10),{'type':'text','text':'한글'}]}]}
    assert 2560<input_units(a)<4000
    plain={'model':'x','input':'한글'*200}
    assert input_units(plain)==len(json.dumps(plain,ensure_ascii=False).encode())


@pytest.mark.parametrize('part',[
    {'type':'audio','mime_type':'audio/wav','data':'not base64'},
    {'type':'audio','mime_type':'audio/wav','data':base64.b64encode(b'broken wav').decode()},
    {'type':'image','mime_type':'image/png','data':base64.b64encode(b'broken png').decode()},
    {'type':'video','mime_type':'video/mp4','data':base64.b64encode(b'video').decode()},
    {'type':'audio','mime_type':'audio/wav','uri':'https://example.test/a.wav'},
])
def test_unreadable_or_unsupported_media_never_gets_zero_cost(part):
    with pytest.raises(ValueError,match='GEMINI_MEDIA_INPUT_'):
        input_units({**BODY,'input':[part]})


def test_media_admission_still_enforces_shared_minute_budget(paced):
    config,clock,db=paced
    body={**BODY,'input':[audio(14)]}
    size=input_units(body);config.gemini_content_tokens_per_minute=size+1
    lease=quota.reserve_slot(PATH,body);quota.release_slot(lease)
    with Session(db) as session:
        assert session.get(GeminiQuota,lease[0]).recent==[[clock[0],size]]
    clock[0]+=5
    with pytest.raises(quota.ProviderDeferred,match='GEMINI_PACING_WAIT'):
        quota.reserve_slot(PATH,body)
    with pytest.raises(ValueError,match='GEMINI_INPUT_BUDGET_EXCEEDED'):
        quota.reserve_slot(PATH,{**BODY,'input':[audio(28)]})


def test_media_lifetime_budget_is_scoped_and_still_finite(paced,monkeypatch):
    config,clock,_=paced;config.gemini_max_calls_per_job=1;config.gemini_max_calls_per_media_job=2
    calls=fake_http(monkeypatch,httpx.Response(200,json={'ok':True}))
    with job_context(SimpleNamespace(id='media',payload={})),provider.media_call_budget():
        provider.request(PATH,BODY,lambda x:x);clock[0]+=5
        provider.request(PATH,{**BODY,'input':'second'},lambda x:x);clock[0]+=5
        with pytest.raises(ValueError,match='GEMINI_CALL_BUDGET_EXCEEDED'):
            provider.request(PATH,{**BODY,'input':'third'},lambda x:x)
        assert provider.request(PATH,BODY,lambda x:x)=={'ok':True}
    with job_context(SimpleNamespace(id='text',payload={})):
        provider.request(PATH,BODY,lambda x:x);clock[0]+=5
        with pytest.raises(ValueError,match='GEMINI_CALL_BUDGET_EXCEEDED'):
            provider.request(PATH,{**BODY,'input':'second'},lambda x:x)
    assert len(calls)==3
