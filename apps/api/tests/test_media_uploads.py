"""MP4 ingestion boundaries with isolated SQL and synthetic Storage/model I/O."""
import io
import json
import struct
import time
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import func, select

from lerny import media_materials, worker
from lerny.config import settings
from lerny.media_validation import validate_mp4
from lerny.models import Job, Material, MaterialVersion, UploadIntent, Chunk
from lerny.gemini_runtime import needs_remote, hold
from test_cloud import cloud_db
from test_identity_courses import login, setup_course
from test_gemini_integration import configured, integration
from test_lecture_specs import api


def box(kind, value):
    return struct.pack('>I4s', 8 + len(value), kind) + value


MP4 = box(b'ftyp', b'isom\x00\x00\x00\x00isommp42') + box(b'moov', b'metadata') + box(b'mdat', b'encoded-video')


@pytest.mark.parametrize('content', [b'', b'not a movie', MP4[:-1], box(b'ftyp', b'isom0000'), box(b'ftyp', b'xxxx0000') + MP4[24:], b'\x00\x00\x00\x01mdat'])
def test_mp4_container_rejects_invalid_or_truncated(content):
    with pytest.raises(ValueError, match='INVALID_MP4'):
        validate_mp4(content)


def test_valid_mp4_container():
    validate_mp4(MP4)


@pytest.mark.asyncio
async def test_cloud_mp4_completion_access_limit_and_idempotency(cloud_db):
    app, isolated, objects = cloud_db
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='https://lerny.example', headers={'Origin':'https://lerny.example'}) as c:
        await login(c,'teacher1'); course_info, _ = await setup_course(c); course=course_info['id']
        cfg=(await c.get('/api/v1/uploads/config')).json()
        assert cfg['limits']['.mp4']==50*1024*1024 and cfg['limits']['.py']==1024*1024
        r=await c.post(f'/api/v1/courses/{course}/uploads',json={'kind':'lecture','filename':'lecture.MP4','size':len(MP4),'week':3})
        assert r.status_code==201,r.text
        ticket=r.json(); objects[ticket['url'].removeprefix('https://storage.example/')]=MP4
        done=await c.post(f"/api/v1/uploads/{ticket['upload_id']}/complete",json={})
        assert done.status_code==201,done.text
        assert (await c.post(f"/api/v1/uploads/{ticket['upload_id']}/complete",json={})).json()==done.json()
        with Session(isolated) as db:
            assert db.scalar(select(func.count()).select_from(Material))==1
            material=db.get(Material,done.json()['material_id']); assert material.week==3
            version=db.get(MaterialVersion,done.json()['version_id']); assert version.object_key.endswith('.mp4')
            assert objects[version.object_key]==MP4
            job=db.get(Job,done.json()['processing_job_id']); assert not needs_remote(db,job)
            assert job.status=='queued'  # Upload extraction does not depend on a content-model key.
        oversized=await c.post(f'/api/v1/courses/{course}/uploads',json={'kind':'lecture','filename':'large.mp4','size':50*1024*1024+1})
        assert oversized.status_code==413
        await login(c,'student1')
        assert (await c.post(f'/api/v1/courses/{course}/uploads',json={'kind':'lecture','filename':'lecture.mp4','size':len(MP4)})).status_code==404
        assert (await c.post(f"/api/v1/uploads/{ticket['upload_id']}/complete",json={})).status_code==404


from sqlalchemy.orm import Session


@pytest.mark.asyncio
async def test_invalid_cloud_mp4_never_publishes_and_web_scheduler_does_not_decode(cloud_db, monkeypatch):
    app, isolated, objects = cloud_db
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='https://lerny.example',headers={'Origin':'https://lerny.example'}) as c:
        await login(c,'teacher1');course_info,_=await setup_course(c);course=course_info['id']
        ticket=(await c.post(f'/api/v1/courses/{course}/uploads',json={'kind':'lecture','filename':'wrong.mp4','size':4})).json()
        key=ticket['url'].removeprefix('https://storage.example/');objects[key]=b'nope'
        assert (await c.post(f"/api/v1/uploads/{ticket['upload_id']}/complete",json={})).status_code==422
        with Session(isolated) as db:
            assert db.scalar(select(func.count()).select_from(Material))==0
            intent=db.get(UploadIntent,ticket['upload_id']);intent.size=len(MP4);db.commit()
        objects[key]=MP4
        result=(await c.post(f"/api/v1/uploads/{ticket['upload_id']}/complete",json={})).json()
        monkeypatch.setattr(worker,'extract_job',lambda *a: pytest.fail('Video claimed by web scheduler'))
        assert worker.run_once(result['processing_job_id']) is False
        # Existing text embeddings suffered the same web-worker claim race.
        monkeypatch.setattr(settings(),'ai_provider','gemini')
        with Session(isolated) as db:
            teacher=db.get(Job,result['processing_job_id']).owner_id
            embed=Job(owner_id=teacher,course_id=course,kind='embed',payload={'version_id':result['version_id'],'_ai_provider':'gemini'})
            db.add(embed);db.commit();embed_id=embed.id
        assert worker.run_once(embed_id) is False
        with Session(isolated) as db:
            assert db.get(Job,embed_id).status=='queued'


def test_media_selected_source_and_existing_publication(integration, monkeypatch):
    _,db,_=integration
    version=db.get(MaterialVersion,'version');version.filename='lecture.mp4'
    job=Job(owner_id='teacher',course_id='course',kind='extract',payload={'version_id':version.id});db.add(job);db.flush()
    monkeypatch.setattr(media_materials,'run_media',lambda v,j:{'source_sha256':v.sha256,'chunks':[{'id':'video-segment','text':'큐는 선입선출입니다.','source_locator':'영상 0~5초','time_interval':{'start':0,'end':5},'document_type':'mp4'}],'held':[{'text':'HELD_NOT_FOR_RAG','reason':'uncertain'}],'evidence':{'pipeline':'connected'}})
    result=worker.extract_job(db,job)
    assert result['status']=='extracted' and result['held_count']==1
    chunks=list(db.scalars(select(Chunk).where(Chunk.version_id==version.id)))
    assert len(chunks)==1 and chunks[0].locator['engine']['time_interval']=={'start':0,'end':5}
    assert 'HELD_NOT_FOR_RAG' not in version.extracted_text
    assert db.scalar(select(Job).where(Job.kind=='embed')) is not None


def test_media_transport_reuses_service_quota_and_propagates_deferred(monkeypatch):
    from urllib.request import Request
    from lerny import gemini_provider
    from lerny.gemini_quota import ProviderDeferred
    req=Request('https://generativelanguage.googleapis.com/v1beta/interactions',data=json.dumps({'model':settings().gemini_answer_model,'store':False}).encode())
    calls=[]
    monkeypatch.setattr(gemini_provider,'request',lambda path,payload,parse: calls.append(path) or parse({'status':'completed','output_text':'{}'}))
    assert json.load(media_materials.service_transport(req))['status']=='completed' and calls==['interactions']
    def defer(*args): raise ProviderDeferred('GEMINI_DAILY_WAIT',123456)
    monkeypatch.setattr(gemini_provider,'request',defer)
    with pytest.raises(media_materials.MediaStopped) as err: media_materials.service_transport(req)
    assert err.value.retry_at==123456 and not isinstance(err.value,ValueError)
    with pytest.raises(media_materials.MediaStopped,match='UNSUPPORTED_MODEL_PROVIDER'):
        media_materials.service_transport(Request('https://example.com',data=b'{}'))


def test_media_bundle_requires_exact_source_and_no_unapproved_warning():
    with pytest.raises(ValueError,match='SOURCE_CHANGED'):
        media_materials.selected_chunks([{'source_sha256':'wrong'}],'expected')
    with pytest.raises(ValueError,match='UNAPPROVED_SOURCE_WARNING'):
        media_materials.selected_chunks([{'source_sha256':'expected','provenance':{'has_low_impact_warnings':True}}],'expected')


def test_official_whisper_export_vocabulary_txt_is_supported(tmp_path):
    from video_extraction.audio.audio_coverage_local import model_info
    for name in ['model.bin','config.json','tokenizer.json','vocabulary.txt']:(tmp_path/name).write_text('{}')
    assert 'vocabulary.txt' in model_info(tmp_path)['files']
    (tmp_path/'vocabulary.txt').unlink()
    with pytest.raises(ValueError,match='local_whisper_model_missing'):model_info(tmp_path)
