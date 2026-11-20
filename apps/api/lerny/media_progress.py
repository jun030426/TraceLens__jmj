"""Lease-bound public counters. Source text, paths and model replies never leave here."""
import math
import sys
import time
from sqlalchemy import select
from sqlalchemy.orm import Session
from lerny.db import engine
from lerny.models import Job, now

STAGES = {
    'preparing': ('영상 준비', '구간'),
    'frames': ('화면 구간 준비', '초'),
    'prepare_audio': ('음성 파일 준비', '구간'),
    'audio_clips': ('음성 구간 준비', '구간'),
    'transcribe': ('음성 인식', '구간'),
    'speech_check': ('음성 누락 점검', '구간'),
    'audio_review': ('원음·전사 대조', '구간'),
    'audio_coverage': ('음성 전체 구간 검토', '구간'),
    'audio_finalize': ('음성 검토 결과 정리', '구간'),
    'source_check': ('영상 원본 점검', '작업'),
    'video_review': ('화면·음성 분석', '작업'),
    'finalize': ('분석 결과 검증', '구간'),
    'alignment': ('음성 시점 확인', '구간'),
}

# Execution order, including preparation replayed before every resumed attempt.
STAGE_ORDER = {name: i for i, name in enumerate((
    'preparing', 'frames', 'prepare_audio', 'audio_clips', 'source_check',
    'transcribe', 'speech_check', 'audio_review', 'audio_coverage',
    'audio_finalize', 'video_review', 'finalize', 'alignment'))}

LOCAL_STAGES = {'local_preparing':('로컬 처리 준비','작업'),
    'local_transcribe':('음성 인식·저장된 전사 재사용','구간'),
    'local_checks':('음성 기초 검사','작업'), 'local_frames':('화면 구간 추출','초'),
    'local_ocr':('로컬 OCR·화면 글자 검사','화면'), 'local_finalize':('정상·보류 구간 분리','작업')}
STAGES.update(LOCAL_STAGES)
STAGE_ORDER.update({name:len(STAGE_ORDER)+i for i,name in enumerate(LOCAL_STAGES)})

DOCUMENT_STAGES = {'document_preparing': ('문서 페이지·원문 준비', '작업'),
                   'document_review': ('Gemini 판독·계산 검증', '작업'),
                   'document_finalize': ('검증된 문서 근거 정리', '작업')}
STAGES.update(DOCUMENT_STAGES)
STAGE_ORDER.update({name:len(STAGE_ORDER)+i for i,name in enumerate(DOCUMENT_STAGES)})

def public_progress(job):
    if job.kind != 'extract' or job.status not in {'running', 'queued', 'failed'}:
        return None
    value = (job.result or {}).get('media_progress')
    if not isinstance(value, dict) or value.get('stage') not in STAGES:
        return None
    if value.get('version_id') != job.payload.get('version_id'):
        return None
    if value.get('generation', 0) != job.payload.get('_ai_generation', 0):
        return None
    completed, total = value.get('completed'), value.get('total')
    if type(completed) not in (int, float) or not math.isfinite(completed) or completed < 0:
        return None
    if total is not None and (type(total) not in (int, float) or not math.isfinite(total) or total <= 0 or completed > total):
        return None
    label, unit = STAGES[value['stage']]
    return {'stage':value['stage'], 'label':label, 'unit':unit,
            'completed':int(completed), 'total':math.ceil(total) if total is not None else None,
            'percent':min(100, int(completed / total * 100)) if total else None,
            'updated_at':value.get('updated_at')}

def reporter(job_id, token, version_id):
    with Session(engine()) as db:
        job = db.get(Job, job_id)
        generation = job.payload.get('_ai_generation', 0) if job else 0
        observed = [public_progress(job) if job else None]
    last = [None, -1e9]
    checked = [-1e9]
    def already_saved(old, stage, completed, total):
        return old and (STAGE_ORDER[old['stage']] > STAGE_ORDER[stage] or
                       (old['stage'] == stage and (completed < old['completed'] or
                        (completed == old['completed'] and (total is None or total == old['total'])))))
    def report(stage, completed=0, total=None):
        if stage == 'finalize' and sys.exc_info()[0] is not None:
            return
        tick = time.monotonic()
        if stage not in STAGES or (stage not in {'audio_review', 'audio_coverage', 'transcribe','local_transcribe','local_ocr'} and stage == last[0] and tick-last[1] < 5 and completed != total):
            return
        if not math.isfinite(completed) or completed < 0 or (total is not None and (not math.isfinite(total) or total <= 0 or completed > total)):
            return
        # Resuming replays hundreds of cached callbacks. Check the lease periodically,
        # but persist every genuinely new audio checkpoint immediately.
        if already_saved(observed[0], stage, completed, total) and tick-checked[0] < 5:
            return
        stamp = now()
        value = {'stage':stage, 'completed':float(completed),
                 'total':float(total) if total else None, 'version_id':version_id, 'generation':generation,
                 'updated_at':stamp.isoformat()}
        with Session(engine()) as db:
            job = db.scalar(select(Job).where(Job.id==job_id, Job.status=='running',
                Job.lease_token==token, Job.lease_until>stamp).with_for_update())
            if job is None:
                from lerny.media_materials import MediaStopped
                raise MediaStopped('MEDIA_JOB_CANCELLED')
            old = public_progress(job)
            observed[0], checked[0] = old, tick
            if already_saved(old, stage, completed, total):
                return
            job.result = {**(job.result or {}), 'media_progress': value}
            observed[0] = public_progress(job)
            db.commit()
        last[:] = [stage, tick]
    return report

def hold_interrupted_video(session, job):
    """Bound retries after a killed process; scheduled quota waits are not crashes."""
    from lerny.models import MaterialVersion
    if job.kind != 'extract' or job.status != 'running':
        return False
    version = session.get(MaterialVersion, job.payload.get('version_id'))
    if not version or not version.filename.lower().endswith('.mp4'):
        return False
    generation = job.payload.get('_ai_generation', 0)
    previous = job.payload.get('_media_interruptions', 0) if job.payload.get('_media_interruptions_generation', 0) == generation else 0
    count = int(previous) + 1
    job.payload = {**job.payload, '_media_interruptions':count, '_media_interruptions_generation':generation}
    if count < 3:
        return False
    job.status = version.status = 'failed'
    job.error_code = version.error_code = 'MEDIA_WORKER_INTERRUPTED'
    job.lease_token = job.lease_until = None
    return True
