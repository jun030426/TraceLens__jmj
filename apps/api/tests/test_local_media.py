import hashlib
import json
import math
import wave
from pathlib import Path
from types import SimpleNamespace
import pytest
from lerny import local_media_checks as checks, local_ocr, local_media
from lerny.gemini_runtime import needs_remote
from lerny.models import Chunk, Job, MaterialVersion
from lerny.auth import COOKIE
from sqlalchemy import select
from test_gemini_integration import configured, integration
from test_lecture_specs import api


def segment(text,a,b,p=1):
    return {'text':text,'start':a,'end':b,'words':[{'word':text,'start':a,'end':b,'probability':p}]}


def test_local_audio_only_problem_segments_are_held_and_never_bridged():
    transcript={'segments':[segment('정상 앞 문장',0,1),segment('잘못 읽었을 수 있는 내용',1,2,.1),segment('정상 뒤 문장',2,3)]}
    windows=[{'start':i/2,'end':(i+1)/2,'rms_dbfs':-20,'clipped_fraction':0} for i in range(6)]
    rows,evidence=checks.audio_records(transcript,4,0,windows,[[0,4]])
    held=[r for r in rows if not r['eligible_for_chunking']]
    assert 'low_word_probability' in held[0]['reasons']
    assert any('speech_without_transcript' in r['reasons'] for r in held)
    chunks=checks.build_chunks(rows,'source')
    assert [c['text'] for c in chunks]==['정상 앞 문장','정상 뒤 문장']
    assert not evidence['semantic_verified']


def test_silence_overlap_repetition_and_invalid_times_are_not_accepted():
    rows,_=checks.audio_records({'segments':[
        segment('침묵 속 문장',0,1),segment('반복문장반복문장반복문장',.5,2),
        segment('잘못된 시간',float('nan'),3),segment('a'*2000,2,3)]},3,0,
        [{'start':0,'end':3,'rms_dbfs':-80,'clipped_fraction':0}],[])
    assert not any(r['eligible_for_chunking'] for r in rows)
    assert any('invalid_segment_time' in r['reasons'] for r in rows)


def test_ocr_boxes_confidence_and_code_are_checked_without_rewriting():
    tsv='level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n'
    tsv+='5\t1\t1\t1\t1\t1\t10\t10\t100\t30\t96\t자료구조\n'
    lines=local_ocr.parse_tsv(tsv,[200,100])
    assert lines[0]['text']=='자료구조' and lines[0]['bbox']==[50,100,550,400]
    with pytest.raises(ValueError,match='LOCAL_OCR_INVALID_RESULT'):
        local_ocr.parse_tsv(tsv.replace('\t100\t30\t','\t400\t30\t'),[200,100])
    rows=checks.ocr_records(lines+[{'text':'x = 0','bbox':[0,0,10,10],'min_confidence':99,'mean_confidence':99},
         {'text':'흐린 글자','bbox':[0,0,10,10],'min_confidence':30,'mean_confidence':60}],0,5,'frame')
    assert rows[0]['eligible_for_chunking']
    assert not rows[1]['eligible_for_chunking'] and not rows[2]['eligible_for_chunking']
    assert rows[1]['text']=='x = 0'


def test_complete_local_pipeline_reuses_source_bound_asr_and_never_calls_gemini(tmp_path,monkeypatch):
    from lerny import gemini_provider
    from lerny.config import settings
    from video_extraction.audio import audio_coverage_local, audio_coverage
    import urllib.request
    def prohibited(*a,**kw):pytest.fail('Ingestion must not contact a model/API or check Gemini availability')
    monkeypatch.setattr(gemini_provider,'request',prohibited)
    monkeypatch.setattr(gemini_provider,'available',prohibited)
    monkeypatch.setattr(urllib.request,'urlopen',prohibited)
    model=tmp_path/'models';model.mkdir();(model/'model.bin').write_bytes(b'model')
    monkeypatch.setenv('LERNY_INGESTION_WHISPER_MODEL',str(model))
    monkeypatch.setattr(settings(),'gemini_calls_enabled',False)
    source=tmp_path/'job/source.mp4';source.parent.mkdir();source.write_bytes(b'original')
    sha=hashlib.sha256(source.read_bytes()).hexdigest();config={'model':'test-source-bound','options':{'language':None}}
    old=source.parent/'analysis-previous';(old/'whisper-cache').mkdir(parents=True)
    (old/'plan.json').write_text(json.dumps({'source_plan':{'sources':[{'source_sha256':sha}],'local_whisper':config}}))
    cache=old/'whisper-cache'/('a'*64+'.json')
    cache.write_text(json.dumps({'signature':'a'*64,'provider':'local_whisper','text':'기존 전사','segments':[]}))
    preserved=cache.read_bytes()
    previous_selected=source.parent/'selected.json';previous_selected.write_bytes(b'{"historical":true}')
    monkeypatch.setattr(audio_coverage_local,'model_info',lambda path:{**config,'options':{'language':'ko'}})
    class CachedASR:
        def __init__(self,model,folder):assert (folder/cache.name).read_bytes()==preserved
        def transcribe(self,path):return {'segments':[segment('정상 음성',0,1),segment('보류 음성',1,2,.1)]}
    monkeypatch.setattr(audio_coverage_local,'LocalWhisper',CachedASR)
    monkeypatch.setattr(local_media.media,'probe',lambda p:{'duration_seconds':2,'width':200,'height':100,'audio_present':True,'audio_offset_seconds':0})
    def audio(path,out,normalize):
        import struct
        with wave.open(str(out/'audio.wav'),'wb') as f:
            f.setparams((1,2,16000,0,'NONE','not compressed'))
            f.writeframes(b''.join(struct.pack('<h',int(4000*math.sin(i/10))) for i in range(32000)))
        return {'original_audio':'audio.wav'}
    monkeypatch.setattr(local_media.media,'prepare_audio',audio)
    monkeypatch.setattr(audio_coverage,'detect_speech',lambda path:[[0,2]])
    monkeypatch.setattr(local_media.media,'select_frames',lambda *a,**kw:[{'id':'frame-1','time_seconds':0,'path':'frame.png'}])
    monkeypatch.setattr(local_ocr,'runtime',lambda:{'version':'offline-test'})
    monkeypatch.setattr(local_ocr,'recognize',lambda *a:[{'text':'정상 화면 글자','bbox':[0,0,100,100],'min_confidence':99,'mean_confidence':99}])
    stages=[]
    result=local_media.process(source,source.parent,sha,lambda:None,lambda stage,*a:stages.append(stage))
    assert result['evidence']['api_calls']==0 and result['evidence']['reused_asr_files']==1
    assert cache.read_bytes()==preserved and source.read_bytes()==b'original'
    assert any(p.read_bytes()==b'{"historical":true}' for p in source.parent.glob('selected-preserved-*.json'))
    assert '정상 음성' in str(result['chunks']) and '정상 화면 글자' in str(result['chunks'])
    assert '보류 음성' not in str(result['chunks']) and '보류 음성' in str(result['held'])
    assert stages[-1]=='local_finalize'
    from lerny.models import MaterialVersion
    version = SimpleNamespace(filename='source.mp4', material_id='material')
    material = SimpleNamespace(deleted=False, visibility='public', internal_use='none', kind='lecture')
    database = SimpleNamespace(get=lambda model, key: version if model is MaterialVersion else material)
    assert not needs_remote(database, SimpleNamespace(kind='extract', payload={'version_id':'version'}))


def test_held_review_is_paginated_staff_only_and_not_embedded(integration):
    from lerny.team_ingestion import publish_extraction
    client,db,tokens=integration
    version=db.get(MaterialVersion,'version');version.filename='lecture.mp4'
    from lerny.models import Material
    material=db.get(Material,'material')
    job=Job(owner_id='teacher',course_id='course',kind='extract',payload={'version_id':version.id})
    db.add(job);db.flush()
    held=[{'id':str(i),'text':'PRIVATE_HELD_'+str(i),'source_context':'PRIVATE_CONTEXT_'+str(i),'modality':'audio','start_seconds':i,'end_seconds':i+1,
           'reasons':['low_word_probability'],'runtime_path':'/private/path','original_xml':'secret-xml'} for i in range(23)]
    publish_extraction(db,job,version,material,{'source_sha256':version.sha256},
        [{'text':'정상 근거','document_type':'mp4','source_locator':'영상 0초'}],held,{'pipeline':checks.POLICY})
    db.commit()
    assert [c.content for c in db.scalars(select(Chunk).where(Chunk.version_id==version.id))]==['정상 근거']
    assert db.scalar(select(Job).where(Job.kind=='embed')) is not None
    response=client.get('/api/v1/materials/material/extraction-review?offset=10&limit=10&modality=audio')
    assert response.status_code==200
    body=response.json();assert body['held_count']==23 and len(body['review_queue'])==10 and body['has_more']
    assert body['review_queue'][0]['id']=='10'
    assert body['review_queue'][0]['context']=='PRIVATE_CONTEXT_10'
    assert 'runtime_path' not in response.text and 'secret-xml' not in response.text
    assert client.get('/api/v1/materials/material/extraction-review?version_id=old').status_code==409
    for role in ('student','outsider'):
        client.cookies.set(COOKIE,tokens[role][0])
        assert client.get('/api/v1/materials/material/extraction-review').status_code==404
