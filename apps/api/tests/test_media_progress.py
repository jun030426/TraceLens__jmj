from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from lerny import media_progress
from lerny.media_materials import MediaStopped
from lerny.models import Base, Job, now


def test_public_counter_is_version_bound_and_whitelisted():
    job = SimpleNamespace(kind='extract', status='running', payload={'version_id':'v'},
        result={'media_progress':{'version_id':'v', 'stage':'transcribe', 'completed':12,
            'total':64, 'source_text':'private', 'updated_at':'2026-11-16T00:00:00+00:00'}})
    value = media_progress.public_progress(job)
    assert value['percent'] == 18 and value['label'] == '음성 인식'
    assert 'private' not in str(value)
    job.payload['_ai_generation'] = 1
    assert media_progress.public_progress(job) is None
    job.payload['_ai_generation'] = 0
    job.result['media_progress']['version_id'] = 'old'
    assert media_progress.public_progress(job) is None
    job.result['media_progress'].update(version_id='v', completed=float('nan'))
    assert media_progress.public_progress(job) is None
    job.result['media_progress']['completed'] = 64
    job.status = 'succeeded'
    assert media_progress.public_progress(job) is None


def test_progress_cannot_resurrect_cancelled_or_reclaimed_job(tmp_path, monkeypatch):
    engine = create_engine('sqlite:///' + str(tmp_path/'progress.db'))
    Base.metadata.create_all(engine)
    monkeypatch.setattr(media_progress, 'engine', lambda:engine)
    with Session(engine) as db:
        db.add(Job(id='job', owner_id='owner', course_id='course', kind='extract',
            status='running', payload={'version_id':'v'}, lease_token='token',
            lease_until=now()+timedelta(seconds=90)))
        db.commit()
    report = media_progress.reporter('job', 'token', 'v')
    report('transcribe', 1, 8)
    try:
        raise MediaStopped('GEMINI_INPUT_BUDGET_EXCEEDED')
    except MediaStopped:
        report('finalize')
    with Session(engine) as db:
        job = db.get(Job, 'job')
        assert media_progress.public_progress(job)['percent'] == 12
        assert job.result['media_progress']['stage'] == 'transcribe'
        job.status = 'failed'; job.lease_token = None; db.commit()
    with pytest.raises(MediaStopped, match='MEDIA_JOB_CANCELLED'):
        report('audio_review', 0, 10)
    with Session(engine) as db:
        assert db.get(Job, 'job').result['media_progress']['stage'] == 'transcribe'


def test_only_repeated_interrupted_video_is_held():
    version = SimpleNamespace(filename='lecture.mp4', status='queued', error_code=None)
    db = SimpleNamespace(get=lambda *args:version)
    job = SimpleNamespace(kind='extract', status='running', payload={'version_id':'v'},
        lease_token='t', lease_until=now(), error_code=None)
    assert not media_progress.hold_interrupted_video(db, job)
    assert not media_progress.hold_interrupted_video(db, job)
    assert media_progress.hold_interrupted_video(db, job)
    assert job.status == version.status == 'failed'
    assert job.error_code == 'MEDIA_WORKER_INTERRUPTED' and job.lease_token is None
    job.status = 'queued'
    assert not media_progress.hold_interrupted_video(db, job)
    job.status = 'running'; version.filename = 'lecture.pptx'
    assert not media_progress.hold_interrupted_video(db, job)
    version.filename = 'lecture.mp4'; job.payload['_ai_generation'] = 1
    assert not media_progress.hold_interrupted_video(db, job)
    assert job.payload['_media_interruptions'] == 1


def test_restarted_reporter_keeps_saved_high_water_and_other_result_fields(tmp_path, monkeypatch):
    engine = create_engine('sqlite:///' + str(tmp_path/'resume-progress.db'))
    Base.metadata.create_all(engine)
    monkeypatch.setattr(media_progress, 'engine', lambda:engine)
    with Session(engine) as db:
        db.add(Job(id='job', owner_id='owner', course_id='course', kind='extract',
            status='running', payload={'version_id':'v'}, lease_token='token',
            lease_until=now()+timedelta(seconds=90), result={'provider_error': {'http_status':503}}))
        db.commit()
    report = media_progress.reporter('job', 'token', 'v')
    report('audio_review', 80, 490)
    resumed = media_progress.reporter('job', 'token', 'v')
    for stage in ['preparing', 'source_check', 'transcribe', 'speech_check']:
        resumed(stage)
    resumed('audio_review', 0, 490)
    resumed('audio_review', 72, 490)
    with Session(engine) as db:
        row = db.get(Job, 'job')
        assert row.result['media_progress']['completed'] == 80
        assert row.result['provider_error']['http_status'] == 503
    resumed('audio_review', 88, 490)  # Immediate durable increment, even under 5 seconds.
    with Session(engine) as db:
        assert db.get(Job, 'job').result['media_progress']['completed'] == 88
    resumed('audio_coverage', 1, 64)
    resumed('transcribe', 64, 64)  # Cached ASR replay during coverage must not move the phase back.
    with Session(engine) as db:
        row = db.get(Job, 'job')
        assert row.result['media_progress']['stage'] == 'audio_coverage'
        row.payload={'version_id':'v', '_ai_generation':1};db.commit()
    fresh = media_progress.reporter('job', 'token', 'v')
    fresh('preparing')
    with Session(engine) as db:
        assert db.get(Job, 'job').result['media_progress']['generation'] == 1


def test_cached_replay_limits_database_reads_but_still_checks_cancellation(tmp_path, monkeypatch):
    engine = create_engine('sqlite:///' + str(tmp_path/'replay-progress.db'))
    Base.metadata.create_all(engine)
    monkeypatch.setattr(media_progress, 'engine', lambda:engine)
    clock = [100.0]
    monkeypatch.setattr(media_progress.time, 'monotonic', lambda:clock[0])
    with Session(engine) as db:
        db.add(Job(id='job', owner_id='owner', course_id='course', kind='extract',
            status='running', payload={'version_id':'v'}, lease_token='token',
            lease_until=now()+timedelta(seconds=90), result={'media_progress':{
                'stage':'audio_review', 'completed':88, 'total':490, 'version_id':'v', 'generation':0}}))
        db.commit()
    report = media_progress.reporter('job', 'token', 'v')
    reads = []
    def record_sql(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith('SELECT'):
            reads.append(statement)
    event.listen(engine, 'before_cursor_execute', record_sql)
    for completed in range(65):
        report('transcribe', completed, 64)
        report('transcribe', completed, 64)
    for completed in range(89):
        report('audio_review', completed, 490)
    assert len(reads) == 1
    report('audio_review', 96, 490)
    assert len(reads) == 2  # New progress is durable without waiting for the timer.
    with Session(engine) as db:
        job = db.get(Job, 'job')
        assert job.result['media_progress']['completed'] == 96
        job.status = 'failed'; job.lease_token = None; db.commit()
    clock[0] += 6
    with pytest.raises(MediaStopped, match='MEDIA_JOB_CANCELLED'):
        report('transcribe', 64, 64)
