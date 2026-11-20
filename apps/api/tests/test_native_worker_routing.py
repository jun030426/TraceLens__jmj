"""Web status polling cannot consume jobs requiring installed native OCR/ASR."""
import pytest
from lerny import worker
from lerny.models import Job,MaterialVersion
from test_gemini_integration import integration,configured  # noqa: F401
from test_lecture_specs import api  # noqa: F401


@pytest.mark.parametrize('filename',['lecture.pptx','LECTURE.PPTX','lecture.mp4'])
def test_native_extraction_waits_for_aws_worker(integration,configured,monkeypatch,filename):
    _,session,_=integration
    configured.deployment='cloud';configured.dedicated_worker=False
    session.get(MaterialVersion,'version').filename=filename
    job=Job(owner_id='teacher',course_id='course',kind='extract',
            payload={'version_id':'version','_ai_provider':'gemini'})
    session.add(job);session.commit();jid=job.id
    calls=[]
    monkeypatch.setattr(worker,'extract_job',lambda *_:calls.append(filename) or {'version_id':'version'})
    monkeypatch.setattr(worker,'heartbeat',lambda *_:None)
    assert worker.run_once(jid) is False
    session.expire_all()
    assert session.get(Job,jid).status=='queued' and not calls
    configured.dedicated_worker=True
    assert worker.run_once(jid) is True
    session.expire_all()
    assert calls==[filename] and session.get(Job,jid).status=='succeeded'
