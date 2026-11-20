"""Versioned local MP4 ingestion. No Gemini client, key check or generation calls."""
import os
import subprocess
import time
import wave
from pathlib import Path

from lerny import local_media_checks as checks, local_ocr, local_audio_spans
from video_extraction.shared import media
from video_extraction.shared.common import digest_file, read, save, signature


def reuse_observations(output, plan, root):
    from lerny.media_resume import reuse_asr_cache
    # The same source/model can have older job generations; only immutable ASR
    # observations are reusable. Old AI decisions and output datasets are untouched.
    copied=0
    for folder in Path(root).iterdir() if Path(root).is_dir() else []:
        if folder.is_dir():copied+=reuse_asr_cache(output,plan,search_root=folder)
    return copied


def process(path, base, source_sha, check_lease, report, *, references=()):
    from lerny.config import settings
    from lerny.media_resume import check_time_slice
    from video_extraction.audio.audio_coverage_local import LocalWhisper, model_info
    from video_extraction.audio.audio_coverage import detect_speech
    from video_extraction.shared.multimodal_checks import audio_windows
    from video_extraction.shared.progress import reporting
    from lerny import picture_ocr, ppt_pictures, media_picture_reuse, video_code
    if digest_file(path)!=source_sha:raise ValueError('SOURCE_CHANGED')
    try:metadata=media.probe(path)
    except Exception:raise ValueError('INVALID_MP4') from None
    if metadata['duration_seconds']>7200 or metadata['width']*metadata['height']>3840*2160:
        raise ValueError('MEDIA_VIDEO_LIMIT')
    model=None
    if metadata['audio_present']:
        model_path=Path(os.environ.get('LERNY_INGESTION_WHISPER_MODEL',str(settings().runtime_root/'models/faster-whisper-small')))
        if not (model_path/'model.bin').is_file():raise ValueError('MEDIA_WHISPER_NOT_READY')
        model=model_info(model_path)
        # Match the deployed uploader's auto-detected language configuration,
        # including its cache signature; never rerun already completed speech.
        model={**model,'options':{**model['options'],'language':None}}
    identity={'policy':checks.POLICY,'source_sha256':source_sha,'model':model,
              'references':[{k:r[k] for k in ('material_id','version_id','sha256')} for r in references],
              'picture_code':{n:digest_file(p) for n,p in [('ocr',picture_ocr.__file__),('ppt',ppt_pictures.__file__),('reuse',media_picture_reuse.__file__)]},
              'code':{n:digest_file(p) for n,p in [('adapter',__file__),('checks',checks.__file__),('audio_spans',local_audio_spans.__file__),('ocr',local_ocr.__file__),('media',media.__file__),('video_code',video_code.__file__)]}}
    output=Path(base)/('analysis-local-'+signature(identity)[:16]);output.mkdir(parents=True,exist_ok=True)
    plan={'source_plan':{'sources':[{'source_sha256':source_sha}],'local_whisper':model},'identity':identity}
    if (output/'plan.json').exists() and read(output/'plan.json')!=plan:raise ValueError('SOURCE_CHANGED')
    save(output/'plan.json',plan)
    copied=reuse_observations(output,plan,Path(base).parent) if model else 0
    started=time.monotonic();records=[];audio_evidence={};last_lease=[-1e9]
    def progress(stage, completed=0, total=None):
        if time.monotonic()-last_lease[0]>=5:
            check_lease();last_lease[0]=time.monotonic()
        check_time_slice(started)
        report('local_transcribe' if stage=='transcribe' else stage,completed,total)
    progress('local_preparing')
    if model:
        audio_meta=media.prepare_audio(path,output,normalize=False)
        audio=output/audio_meta['original_audio']
        asr=LocalWhisper(model,output/'whisper-cache')
        with reporting(progress):transcript=asr.transcribe(audio)
        save(output/'transcript.json',transcript)
        with wave.open(str(audio)) as wav:duration=wav.getnframes()/wav.getframerate()
        progress('local_checks',0,1)
        windows,_=audio_windows(audio)
        speech=detect_speech(audio)
        records,audio_evidence=checks.audio_records(transcript,duration,metadata['audio_offset_seconds'],windows,speech)
        for r in records:
            if r['start_seconds']<0 or r['end_seconds']>metadata['duration_seconds']+.05:
                r['reasons'].append('audio_outside_video');r['eligible_for_chunking']=False
        progress('local_checks',1,1)
        # Release model memory before OCR, including long new uploads on small EC2.
        asr.model=None
    frames=media.select_frames(path,output,metadata,
        {'scan_fps':1,'change_fraction':.035,'min_frame_gap':2,'max_frame_gap':30},
        progress=lambda stage, at, total:progress('local_frames',at,total))
    progress('local_frames',metadata['duration_seconds'],metadata['duration_seconds'])
    try:ocr_config=local_ocr.runtime()
    except (ValueError,OSError,subprocess.SubprocessError):ocr_config=None
    pictures=media_picture_reuse.prepare(references,settings().runtime_root/'picture-text',
                                         lambda:progress('local_ocr',0,len(frames)))
    prior_text=None;duplicates=0;seen_pictures=set();picture_proofs=[];code_proofs=[];seen_codes=set()
    for i,frame in enumerate(frames):
        progress('local_ocr',i,len(frames))
        at=frame['time_seconds'];end=frames[i+1]['time_seconds'] if i+1<len(frames) else metadata['duration_seconds']
        reason=None
        reused,covered,proofs=media_picture_reuse.reuse(output/frame['path'],pictures,at,end,seen_pictures,
                                                       lambda:progress('local_ocr',i,len(frames)))
        records.extend(reused);picture_proofs.extend(proofs)
        if ocr_config is None:reason='local_ocr_unavailable';lines=[]
        else:
            try:lines=local_ocr.recognize(output/frame['path'],output/'local-ocr',ocr_config)
            except (ValueError,OSError,subprocess.SubprocessError):reason='local_ocr_failed';lines=[]
        if covered:lines=[line for line in lines if not any(media_picture_reuse.inside(line,box) for box in covered)]
        if lines and ocr_config:
            blocks,consumed=video_code.verify_frame(output/frame['path'],output/'code-ocr',ocr_config,lines,at,end,frame['id'],
                                                  check=lambda:progress('local_ocr',i,len(frames)))
            for block in blocks:
                key=block['code_block']['code_sha256'];code_proofs.append(block['code_block'])
                if key not in seen_codes:records.append(block);seen_codes.add(key)
            if consumed:lines=[line for index,line in enumerate(lines) if index not in consumed]
            if consumed and not lines:prior_text=None;continue
        if not lines and covered:
            prior_text=None
        elif not lines:
            reason=reason or 'screen_no_text_detected'
            records.append({'id':frame['id'],'modality':'visual','text':'','start_seconds':at,'end_seconds':end,
                'source_locator':f'영상 {at:.1f}초 · 화면','reasons':[reason],'eligible_for_chunking':False})
            prior_text=None
        else:
            # Skip only consecutively identical observed screens. Original OCR
            # receipts/frames retain every timestamp; never fuzzy-merge or repair.
            identity_text=signature([(l['text'],l['bbox'],l['min_confidence'],l['mean_confidence']) for l in lines])
            if prior_text==identity_text:duplicates+=1
            else:records.extend(checks.ocr_records(lines,at,end,frame['id']))
            prior_text=identity_text
        progress('local_ocr',i+1,len(frames))
    progress('local_finalize',0,1)
    if digest_file(path)!=source_sha:raise ValueError('SOURCE_CHANGED')
    check_lease()
    chunks=checks.build_chunks(records,source_sha)
    held=[{**r,'status':'held'} for r in records if not r['eligible_for_chunking']]
    result={'source_sha256':source_sha,'chunks':chunks,'held':held,'evidence':{
        'pipeline':checks.POLICY,'api_calls':0,'semantic_verified':False,
        'video_metadata':metadata,'reused_asr_files':copied,'audio':audio_evidence,
        'ocr_runtime':{k:v for k,v in (ocr_config or {}).items() if k!='executable'},
        'frames':len(frames),'consecutive_duplicate_screens':duplicates,
        'picture_reuse':{'unique_pictures':len({p['image_sha256'] for p in picture_proofs}),'matched_occurrences':len(picture_proofs),'proofs':picture_proofs},
        'accepted_records':sum(r['eligible_for_chunking'] for r in records),
        'code_blocks':{'policy':video_code.POLICY,'unique_blocks':len(seen_codes),'proofs':code_proofs,'execution_verified':False},
        'limitations':['기초 검사 통과는 전사·OCR의 의미 정확성을 보증하지 않습니다.',
                       '화면은 장면 변화와 최대 30초 간격으로 추출하므로 짧은 장면은 누락될 수 있습니다.',
                       '그림·도표의 의미와 필기 구조는 해석하지 않으며 화면 글자만 추출합니다.']}}
    save(output/'records.json',records);save(output/'selected.json',result)
    # Preserve a policy-specific result before the existing queue adapter reads it.
    selected=Path(base)/'selected.json'
    if selected.exists():
        previous=Path(base)/('selected-preserved-'+digest_file(selected)+'.json')
        if not previous.exists():previous.write_bytes(selected.read_bytes())
    save(selected,result)
    progress('local_finalize',1,1)
    return result
