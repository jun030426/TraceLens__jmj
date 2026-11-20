import json
from copy import deepcopy
import pytest
from lerny import media_resume
from lerny.media_materials import MediaStopped


def test_only_same_source_model_observations_are_reused(tmp_path):
    plan={'source_plan':{'sources':[{'source_sha256':'source'}], 'local_whisper':{'model':'small','hash':'abc'}}}
    old=tmp_path/'analysis-old'; old.mkdir()
    (old/'plan.json').write_text(json.dumps(plan))
    cache=old/'whisper-cache';cache.mkdir()
    name='a'*64
    original=json.dumps({'signature':name,'text':'전사','segments':[], 'provider':'local_whisper'})
    (cache/(name+'.json')).write_text(original)
    (old/'results').mkdir();(old/'results/verdict.json').write_text('accepted')
    output=tmp_path/'analysis-new'
    changed=deepcopy(plan);changed['source_plan']['sources'][0]['source_sha256']='other'
    assert media_resume.reuse_asr_cache(output,changed)==0
    changed=deepcopy(plan);changed['source_plan']['local_whisper']['hash']='changed'
    assert media_resume.reuse_asr_cache(output,changed)==0
    assert media_resume.reuse_asr_cache(output,plan)==1
    assert (output/'whisper-cache'/(name+'.json')).read_text()==original
    assert not (output/'results').exists()
    assert media_resume.reuse_asr_cache(output,plan)==0
    assert (cache/(name+'.json')).read_text()==original


def test_time_slice_yields_only_at_call_boundary(monkeypatch):
    monkeypatch.setattr(media_resume.time,'monotonic',lambda:1800)
    monkeypatch.setattr(media_resume.time,'time',lambda:10000)
    media_resume.check_time_slice(1)
    with pytest.raises(MediaStopped,match='MEDIA_CONTINUATION_WAIT') as caught:
        media_resume.check_time_slice(0)
    assert caught.value.retry_at==10005
