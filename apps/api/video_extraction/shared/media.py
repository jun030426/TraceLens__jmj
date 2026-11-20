import json
import math
import os
from pathlib import Path
import subprocess
import time
import wave

from video_extraction.shared.common import read, save, signature


def ffmpeg():
    import imageio_ffmpeg
    return os.environ.get('FFMPEG_BINARY') or imageio_ffmpeg.get_ffmpeg_exe()


def run_ffmpeg(args):
    r = subprocess.run([ffmpeg(), '-nostdin', '-hide_banner', '-y', *map(str, args)],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if r.returncode:
        raise RuntimeError('FFmpeg failed: ' + r.stderr.decode(errors='replace')[-1000:])
    return r.stderr.decode(errors='replace')


def probe(source):
    import av
    with av.open(str(source)) as c:
        if not c.streams.video:
            raise ValueError('Video stream missing')
        v = c.streams.video[0]
        origin = float((v.start_time or 0) * v.time_base)
        duration = float(v.duration * v.time_base) if v.duration else float(c.duration or 0)/1e6
        if duration <= 0:
            raise ValueError('Video duration unavailable')
        a = c.streams.audio[0] if c.streams.audio else None
        return {'duration_seconds': duration, 'width': v.width, 'height': v.height,
                'fps': float(v.average_rate or 0), 'video_origin_seconds': origin,
                'audio_present': a is not None,
                'audio_offset_seconds': float((a.start_time or 0)*a.time_base)-origin if a else 0.0}


def prepare_audio(source, out, normalize=False):
    raw = out/'audio-original.wav'
    meta = out/'audio.json'
    if meta.exists():
        m = read(meta)
        if (out/m['asr_audio']).exists():
            return m
    started = time.monotonic()
    temp = out/'audio-original.tmp.wav'
    run_ffmpeg(['-loglevel','error','-i',source,'-map','0:a:0','-vn','-ac','1','-ar','16000',
                '-c:a','pcm_s16le',temp])
    temp.replace(raw)
    target = raw
    measurements = None
    if normalize:
        log = run_ffmpeg(['-i',raw,'-af','loudnorm=I=-20:LRA=11:TP=-2:print_format=json','-f','null','-'])
        measurements = json.loads(log[log.rfind('{'):log.rfind('}')+1])
        vals = [float(measurements[k]) for k in ['input_i','input_lra','input_tp','input_thresh','target_offset']]
        # Silence yields -inf. Leave silent input untouched instead of failing normalization.
        if all(math.isfinite(v) for v in vals):
            filt = ('loudnorm=I=-20:LRA=11:TP=-2:linear=true:'
                    f'measured_I={vals[0]}:measured_LRA={vals[1]}:measured_TP={vals[2]}:'
                    f'measured_thresh={vals[3]}:offset={vals[4]}')
            target = out/'audio-normalized.wav'
            tmp = out/'audio-normalized.tmp.wav'
            run_ffmpeg(['-loglevel','error','-i',raw,'-af',filt,'-ac','1','-ar','16000','-c:a','pcm_s16le',tmp])
            tmp.replace(target)
    with wave.open(str(target)) as f:
        duration = f.getnframes()/f.getframerate()
    m = {'original_audio':raw.name,'asr_audio':target.name,'rate':16000,'channels':1,
         'duration_seconds':duration,'normalization_requested':normalize,
         'normalization_applied':target != raw,'normalization_measurements':measurements,
         'elapsed_seconds':time.monotonic()-started}
    save(meta,m)
    return m


def select_frames(source, out, metadata, config, progress=lambda *a: None):
    import av
    import numpy as np
    from PIL import Image, ImageFilter
    cached = out/'frames.json'
    if cached.exists():
        rows=read(cached)
        if all((out/r['path']).is_file() for r in rows):
            return rows
    folder=out/'frames';folder.mkdir(exist_ok=True)
    started=time.monotonic()
    origin=metadata['video_origin_seconds']
    interval=1/config['scan_fps'];last_sample=-1e9;last_selected=-1e9
    reference=None;rows=[];sampled=0
    # Decode sequentially; timestamps are actual decoded PTS, never frame_index/fps.
    with av.open(str(source)) as c:
        stream=c.streams.video[0]
        for frame in c.decode(stream):
            if frame.time is None:
                continue
            t=max(0.0,float(frame.time)-origin)
            if t-last_sample < interval-0.001:
                continue
            last_sample=t;sampled+=1
            small=frame.reformat(width=480,height=270,format='gray').to_ndarray()
            # Blurring avoids compression/cursor noise; no hard-coded slide crop.
            smooth=np.asarray(Image.fromarray(small).filter(ImageFilter.GaussianBlur(radius=.8)))
            delta=1.0 if reference is None else float(np.mean(np.abs(smooth.astype(np.int16)-reference.astype(np.int16))>20))
            changed=delta>=config['change_fraction'] and t-last_selected>=config['min_frame_gap']
            periodic=t-last_selected>=config['max_frame_gap']
            if reference is None or changed or periodic:
                identifier=f'frame-{len(rows)+1:05}'
                path=folder/(identifier+'.png')
                frame.to_image().save(path)
                reason='first' if reference is None else 'change' if changed else 'periodic'
                pixels=small.astype(float)
                lap=pixels[1:-1,:-2]+pixels[1:-1,2:]+pixels[:-2,1:-1]+pixels[2:,1:-1]-4*pixels[1:-1,1:-1]
                rows.append({'id':identifier,'time_seconds':round(t,6),'path':str(path.relative_to(out)),
                             'reason':reason,'changed_fraction':delta,
                             'sharpness':float(lap.var())})
                reference=smooth.copy();last_selected=t
            if sampled%120==0:
                progress('frames',round(t,1),metadata['duration_seconds'])
    if not rows:
        raise ValueError('No decodable video frame')
    save(cached,rows)
    save(out/'frames-metrics.json',{'elapsed_seconds':time.monotonic()-started,'samples':sampled,
        'frames':len(rows),'scan_fps':config['scan_fps'],'max_frame_gap':config['max_frame_gap'],
        'coverage':'sampled change detection; brief states may be missed; intervals are approximate'})
    return rows


def transcribe(audio, out, meta, config, progress=lambda *a:None):
    import numpy as np
    from faster_whisper import WhisperModel
    manifest=out/'asr.json'
    if manifest.exists():
        return read(manifest)['segments']
    model=WhisperModel(config['asr_model'],device='cpu',compute_type='int8',
                       cpu_threads=config['asr_threads'],local_files_only=config['offline_models'],
                       download_root=config.get('model_cache'))
    started=time.monotonic();all_segments=[];part_seconds=config['asr_chunk_seconds']
    with wave.open(str(audio)) as wav:
        rate=wav.getframerate();duration=wav.getnframes()/rate
        if wav.getnchannels()!=1 or wav.getsampwidth()!=2 or rate!=16000:
            raise ValueError('ASR requires PCM16 mono 16kHz')
        for number,start in enumerate(range(0,math.ceil(duration),part_seconds)):
            end=min(duration,start+part_seconds);left=max(0,start-3);right=min(duration,end+3)
            p=out/'asr-parts'/f'{number:04}.json'
            sig=signature({'start':start,'end':end,'model':config['asr_model'],'language':config['language'],
                           'beam':5,'version':1})
            if p.exists() and read(p).get('signature')==sig:
                records=read(p)['segments']
            else:
                wav.setpos(round(left*rate))
                arr=np.frombuffer(wav.readframes(round((right-left)*rate)),dtype=np.int16).astype(np.float32)/32768
                segments,info=model.transcribe(arr,language=config['language'],beam_size=5,
                    vad_filter=True,condition_on_previous_text=False,word_timestamps=True)
                records=[]
                for s in segments:
                    a=left+s.start;b=left+s.end
                    if not start <= (a+b)/2 < end or not s.text.strip():
                        continue
                    offset=meta['audio_offset_seconds'];duration_video=meta['duration_seconds']
                    va=max(0,a+offset);vb=min(duration_video,b+offset)
                    if vb<=va:
                        continue
                    reasons=[]
                    if s.avg_logprob < -1.0:reasons.append('low_asr_logprob')
                    if s.no_speech_prob > .6:reasons.append('possible_non_speech')
                    if s.compression_ratio > 2.4:reasons.append('possible_repetition')
                    if a < start or b > end:reasons.append('asr_chunk_boundary')
                    words=[{'start_seconds':max(0,left+w.start+offset),
                            'end_seconds':min(duration_video,left+w.end+offset),
                            'word':w.word,'probability':w.probability} for w in (s.words or [])
                           if min(duration_video,left+w.end+offset)>max(0,left+w.start+offset)]
                    records.append({'id':f'asr-{number:04}-{len(records):04}',
                       'start_seconds':round(va,6),'end_seconds':round(vb,6),'text':s.text.strip(),
                       'avg_logprob':s.avg_logprob,'no_speech_prob':s.no_speech_prob,
                       'words':words,'review_reasons':reasons,
                       'status':'needs_review' if reasons else 'machine_transcribed'})
                save(p,{'signature':sig,'segments':records,'audio_window':[left,right]})
            all_segments.extend(records);progress('asr',round(end,1),duration)
    all_segments.sort(key=lambda s:(s['start_seconds'],s['end_seconds']))
    save(manifest,{'model':config['asr_model'],'language':config['language'],'segments':all_segments,
                   'elapsed_seconds':time.monotonic()-started,'complete':True,
                   'note':'Confidence gates are heuristics, not measured transcription accuracy.'})
    return all_segments
