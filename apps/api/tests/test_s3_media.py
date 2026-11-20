"""Large media authorization and publication, using isolated PostgreSQL only."""
import hashlib
import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from lerny import media_storage
from lerny.config import settings
from lerny.models import Material, MaterialVersion, Job, User
from test_cloud import cloud_db
from test_identity_courses import login, setup_course


@pytest.mark.asyncio
async def test_large_media_ticket_auth_completion_and_retry(cloud_db, monkeypatch):
    app, isolated, objects = cloud_db
    with Session(isolated) as db:
        first = db.scalar(select(User).where(User.login_id == 'teacher1'))
        db.add(User(login_id='teacher2',display_name='Other teacher',role='teacher',password_hash=first.password_hash))
        db.commit()
    monkeypatch.setattr(media_storage, 'enabled', lambda: True)
    calls = []
    fail = [True]
    def bridge(action, **body):
        calls.append(action)
        if action == 'begin': return {'upload_id': 's3-multipart'}
        if action == 'parts': return {'complete': False, 'uploaded_bytes': 8*1024*1024, 'parts': []}
        if fail[0]: raise ValueError('MEDIA_UPLOAD_INCOMPLETE')
        return {'size': body['size'], 'sha256': hashlib.sha256(b'synthetic-original').hexdigest()}
    monkeypatch.setattr(media_storage, 'bridge', bridge)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='https://lerny.example',headers={'Origin':'https://lerny.example'}) as c:
        await login(c,'teacher1'); info,_=await setup_course(c); course=info['id']
        limits=(await c.get('/api/v1/uploads/config')).json()['limits']
        assert limits['.mp4']==1024**3 and limits['.pptx']==50*1024**2
        ticket=(await c.post(f'/api/v1/courses/{course}/uploads',json={'kind':'lecture','filename':'lecture.MP4','size':1024**3,'week':4})).json()
        assert ticket['method']=='MULTIPART' and not ticket['url']
        assert (await c.post(f"/api/v1/uploads/{ticket['upload_id']}/parts",json={})).status_code==200
        assert (await c.post(f"/api/v1/uploads/{ticket['upload_id']}/complete",json={})).status_code==422
        with Session(isolated) as db: assert db.scalar(select(func.count()).select_from(Material))==0
        await login(c,'teacher2')
        assert (await c.post(f"/api/v1/uploads/{ticket['upload_id']}/parts",json={})).status_code==404
        assert (await c.post(f"/api/v1/uploads/{ticket['upload_id']}/complete",json={})).status_code==404
        await login(c,'teacher1'); fail[0]=False
        result=await c.post(f"/api/v1/uploads/{ticket['upload_id']}/complete",json={});assert result.status_code==201,result.text
        assert (await c.post(f"/api/v1/uploads/{ticket['upload_id']}/complete",json={})).json()==result.json()
        assert calls.count('begin')==1 and calls.count('complete')==2 and not objects
        with Session(isolated) as db:
            assert db.scalar(select(func.count()).select_from(Material))==1
            version=db.get(MaterialVersion,result.json()['version_id'])
            assert version.object_key=='s3media/'+ticket['upload_id']+'.mp4'
            assert version.sha256==hashlib.sha256(b'synthetic-original').hexdigest()
            assert db.get(Material,version.material_id).week==4
            assert db.get(Job,result.json()['processing_job_id']).kind=='extract'
        assert (await c.post(f'/api/v1/courses/{course}/uploads',json={'kind':'lecture','filename':'too-large.mp4','size':1024**3+1})).status_code==422
        assert (await c.post(f'/api/v1/courses/{course}/uploads',json={'kind':'lecture','filename':'too-large.pdf','size':51*1024**2})).status_code==413
        await login(c,'student1')
        assert (await c.post(f"/api/v1/uploads/{ticket['upload_id']}/parts",json={})).status_code==404


def test_worker_download_is_bounded_and_web_runtime_cannot_read_s3(monkeypatch, tmp_path):
    monkeypatch.setattr(settings(),'dedicated_worker',False)
    with pytest.raises(ValueError,match='MEDIA_DEDICATED_WORKER_REQUIRED'):
        media_storage.download_to('s3media/12345678-1234-1234-1234-123456789abc.mp4',tmp_path/'out',1)
    with pytest.raises(ValueError,match='INVALID_MEDIA_KEY'):
        media_storage.media_id('s3media/../../other')
    # botocore's context manager returns its underlying HTTPResponse, not StreamingBody.
    import io
    from types import SimpleNamespace
    monkeypatch.setattr(settings(),'dedicated_worker',True)
    class Stream:
        def __enter__(self): self.raw=io.BytesIO(b'movie');return self.raw
        def __exit__(self,*args):self.raw.close()
    client=SimpleNamespace(get_object=lambda **kw:{'Body':Stream(),'ContentLength':5})
    monkeypatch.setattr(media_storage.boto3,'Session',lambda **kw:SimpleNamespace(client=lambda *a,**kw:client))
    key='s3media/12345678-1234-1234-1234-123456789abc.mp4'
    media_storage.download_to(key,tmp_path/'out',5)
    assert (tmp_path/'out').read_bytes()==b'movie'
    with pytest.raises(ValueError,match='FILE_TOO_LARGE'):media_storage.download_to(key,tmp_path/'too-large',4)
