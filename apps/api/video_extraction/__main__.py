from video_extraction._layout import PROJECT_ROOT, PACKAGE_ROOT, source_path
import argparse
from video_extraction.shared import file_lock as fcntl
import json
import os
from pathlib import Path
import sys
import time

from video_extraction import VERSION
from video_extraction.audio.audio_review import review_segment
from video_extraction.shared.common import digest_file, now, read, save, signature
from video_extraction.shared.gemini import Blocked, Gemini
from video_extraction.shared.errors import guidance
from video_extraction.shared.media import prepare_audio, probe, select_frames, transcribe
from video_extraction.shared.output import export
from video_extraction.video.vision import process_frame

ROOT=PROJECT_ROOT


def parser():
    p=argparse.ArgumentParser(description='Local video extraction worker: resumable, immutable source, no DB publication')
    p.add_argument('source',type=Path)
    p.add_argument('--output',type=Path,default=ROOT/'outputs/video-extraction')
    p.add_argument('--stage',choices=['local','vision','all'],default='all')
    p.add_argument('--asr-model',default='turbo')
    p.add_argument('--model-cache',default=str(ROOT/'work/extraction-compare/models'))
    p.add_argument('--language',default='ko')
    p.add_argument('--asr-threads',type=int,default=4)
    p.add_argument('--asr-chunk-seconds',type=int,default=180)
    p.add_argument('--allow-model-download',action='store_true')
    p.add_argument('--normalize-audio',action='store_true')
    p.add_argument('--scan-fps',type=float,default=2)
    p.add_argument('--change-fraction',type=float,default=.025)
    p.add_argument('--min-frame-gap',type=float,default=1)
    p.add_argument('--max-frame-gap',type=float,default=20)
    p.add_argument('--gemini-model',default=os.environ.get('GEMINI_MODEL','gemini-1.5-flash'))
    p.add_argument('--env-file',type=Path,default=ROOT/'.env')
    p.add_argument('--max-api-calls',type=int,default=60)
    p.add_argument('--api-delay',type=float,default=15)
    p.add_argument('--max-regions',type=int,default=6)
    p.add_argument('--max-audio-reviews',type=int,default=20)
    return p


def run(args):
    if not args.source.is_file():raise ValueError('source video missing')
    if not (0<args.scan_fps<=10 and 0<args.change_fraction<1 and
            0<args.min_frame_gap<=args.max_frame_gap and args.max_frame_gap>=1 and
            args.asr_chunk_seconds>=10 and args.asr_threads>=1 and args.max_api_calls>=0 and
            args.api_delay>=0 and 1<=args.max_regions<=20 and args.max_audio_reviews>=0):raise ValueError('invalid processing limits')
    source=args.source.resolve();source_hash=digest_file(source)
    # Record code provenance. Bump VERSION when changing persisted stage semantics.
    code_hash=signature({str(p.relative_to(PACKAGE_ROOT)):digest_file(p) for p in sorted(PACKAGE_ROOT.rglob('*.py'))})
    config={'version':VERSION,'asr_model':args.asr_model,'model_cache':args.model_cache,
            'language':args.language,'asr_threads':args.asr_threads,'asr_chunk_seconds':args.asr_chunk_seconds,
            'offline_models':not args.allow_model_download,'normalize_audio':args.normalize_audio,
            'scan_fps':args.scan_fps,'change_fraction':args.change_fraction,'min_frame_gap':args.min_frame_gap,
            'max_frame_gap':args.max_frame_gap,'gemini_model':args.gemini_model,'max_regions':args.max_regions}
    job=source_hash[:16]+'-'+signature(config)[:12]
    out=args.output.resolve()/job;out.mkdir(parents=True,exist_ok=True)
    lock=(out/'.worker.lock').open('a+')
    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:raise RuntimeError('This job already has a running worker') from None
    state_file=out/'state.json'
    state=read(state_file) if state_file.exists() else {
        'job_id':job,'source_path':str(source),'source_sha256':source_hash,'config':config,'created_at':now(),
        'stages':{},'runs':[]}
    state.update(state='running',updated_at=now())
    for key in ('blocked_reason','blocked_detail','next_action'):state.pop(key,None)
    state['runs'].append({'started_at':now(),'stage':args.stage,'max_api_calls':args.max_api_calls,'code_hash':code_hash})
    frames=[];speech=[];vision={};client=None;exit_code=0;started=time.monotonic()
    def progress(stage,done,total):
        state['progress']={'stage':stage,'done':done,'total':total}
        state['updated_at']=now();save(state_file,state)
        print(json.dumps(state['progress'],ensure_ascii=False),flush=True)
    save(state_file,state)
    print('JOB_DIR='+str(out),flush=True)
    try:
        metadata=probe(source);state['metadata']=metadata;save(state_file,state)
        if args.stage=='vision' and not (out/'local_complete.json').exists():
            raise Blocked('run_local_stage_first')
        if metadata['audio_present']:
            progress('audio',0,1);audio=prepare_audio(source,out,args.normalize_audio)
            state['stages']['audio']='complete';progress('audio',1,1)
        else:
            state['stages']['audio']='no_audio_stream';audio=None
        progress('frames',0,metadata['duration_seconds'])
        frames=select_frames(source,out,metadata,config,progress);state['stages']['frames']='complete'
        if audio:
            progress('asr',0,audio['duration_seconds'])
            speech=transcribe(out/audio['asr_audio'],out,metadata,config,progress)
        state['stages']['asr']='complete' if audio else 'no_audio_stream'
        save(out/'local_complete.json',{'completed_at':now(),'source_sha256':source_hash})
        if args.stage!='local':
            client=Gemini(out/'api-cache',args.gemini_model,args.env_file,args.max_api_calls,args.api_delay)
            for i,frame in enumerate(frames):
                progress('vision',i,len(frames))
                try:
                    vision[frame['id']]=process_frame(frame,frames,speech,out,client,args.max_regions)
                except ValueError as exc:
                    # A malformed bbox/block is not grounds to trust or publish partial text.
                    vision[frame['id']]={'text':'','status':'needs_review','changed_blocks':0,
                        'holds':[{'reason':'invalid_extraction_structure','detail':str(exc)}]}
                    save(out/'vision'/frame['id']/'invalid.json',vision[frame['id']])
                progress('vision',i+1,len(frames))
            state['stages']['vision']='complete'
            reviewed=0
            for i,s in enumerate(speech):
                if not s['review_reasons']:continue
                cached=(out/'audio-review'/s['id']/'result.json').exists()
                if not cached and reviewed>=args.max_audio_reviews:continue
                progress('audio_review',reviewed,args.max_audio_reviews)
                speech[i]=review_segment(s,out/'audio-original.wav',out,metadata,client)
                if not cached:reviewed+=1
            state['stages']['audio_review']='complete_with_holds' if any(s['review_reasons'] for s in speech) else 'complete'
        if args.stage=='local':
            state['state']='local_complete_vision_pending'
        else:
            held=any(v['status']=='needs_review' for v in vision.values()) or any(s['review_reasons'] for s in speech)
            state['state']='completed_with_review' if held else 'completed_auto_checked'
    except Blocked as exc:
        state['state']='blocked';state['blocked_reason']=str(exc);exit_code=2
        state['blocked_detail']=exc.detail;state['next_action']=guidance(str(exc))
    except KeyboardInterrupt:
        state['state']='interrupted';state['blocked_reason']='resume_with_same_command';exit_code=130
    except Exception as exc:
        state['state']='failed';state['blocked_reason']=f'{type(exc).__name__}: {str(exc)[:500]}';exit_code=1
    finally:
        state['updated_at']=now();state['runs'][-1].update(ended_at=now(),elapsed_seconds=time.monotonic()-started,
            state=state['state'],api=client.stats if client else {})
        # Retain outputs from previous completed frames if this run stopped earlier.
        for frame in frames:
            p=out/'vision'/frame['id']/'result.json'
            if frame['id'] not in vision and p.exists():vision[frame['id']]=read(p)
        for i,s in enumerate(speech):
            p=out/'audio-review'/s['id']/'result.json'
            if p.exists():speech[i]=read(p)['segment']
        if 'metadata' in state:
            summary=export(out,state,frames,speech,vision)
            state['summary']=summary
        save(state_file,state);fcntl.flock(lock,fcntl.LOCK_UN);lock.close()
        print(json.dumps({'state':state['state'],'output':str(out),'reason':state.get('blocked_reason')},ensure_ascii=False),flush=True)
        if state.get('next_action'):print(state['next_action'],flush=True)
    return exit_code


def main():
    try:return run(parser().parse_args())
    except (ValueError,RuntimeError) as exc:
        print(str(exc),file=sys.stderr);return 1


if __name__=='__main__':
    raise SystemExit(main())
