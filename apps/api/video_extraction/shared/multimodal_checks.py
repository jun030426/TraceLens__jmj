"""Deterministic diagnostics. Findings are review signals, never OCR/ASR truth."""
import math
import re
import wave

import numpy as np
from PIL import Image, ImageFilter

from video_extraction.shared.common import bbox_pixels, digest_file
from video_extraction.video.bbox_cutoff import cutoff_evidence
from video_extraction.video.source_coordinate_review import matching_decision

ERROR_REASONS={
    'invalid_bbox','duplicate_region_ids','missing_text_reference','invalid_frame_time',
    'non_increasing_selected_time','invalid_segment_time','word_timestamp_outside_segment',
    'unexpected_resolution','saved_frame_source_mismatch',
}
PENDING_REASONS={
    'extraction_missing','existing_hold','source_uncertainty','unreadable_characters','empty_block',
    'zero_o_requires_source_comparison','long_interval_deferred','api_review_budget',
    'api_review_budget_or_invalid_interval','video_evidence_budget','no_selected_frames',
    'no_decoded_frames',
}
CATEGORY_LABELS={'error':'확인된 구조·시간 오류','warning':'단순 경고 · 원본 대조 필요','pending':'미처리·판독 미확정'}


def classify(reason):
    return 'error' if reason in ERROR_REASONS else 'pending' if reason in PENDING_REASONS else 'warning'


def grouped_findings(rows):
    groups={key:[] for key in CATEGORY_LABELS}
    for row in rows:
        category=classify(row['reason'])
        groups[category].append({**row,'category':category})
    return groups


def finding(modality, reason, **details):
    category=classify(reason)
    return {'modality': modality, 'reason': reason, 'category':category,
            'status':{'error':'confirmed_structure_error','warning':'needs_review','pending':'pending'}[category], **details}


def inspect_frame(image_path, result, expected_size):
    findings = []
    with Image.open(image_path) as im:
        im.load()
        if list(im.size) != list(expected_size):
            findings.append(finding('image', 'unexpected_resolution', actual=list(im.size)))
        gray = np.asarray(im.convert('L').resize((320,180)), dtype=float)
        lap = gray[1:-1,:-2]+gray[1:-1,2:]+gray[:-2,1:-1]+gray[2:,1:-1]-4*gray[1:-1,1:-1]
        metrics = {'gray_std': float(gray.std()), 'laplacian_variance': float(lap.var()),
                   'size': list(im.size)}
        if gray.std() < 3:
            findings.append(finding('image', 'nearly_uniform_frame'))
        elif lap.var() < 8:
            findings.append(finding('image', 'possible_low_detail_or_blur'))
        if result is None:
            findings.append(finding('text', 'extraction_missing'))
            return findings, metrics
        blocks = result.get('final_blocks', result.get('blocks', []))
        visuals = result.get('visuals', [])
        decisions=result.get('source_coordinate_review',{}).get('decisions',[])
        reviewed_image_hash=digest_file(image_path) if decisions else None
        ids = [x['id'] for x in blocks+visuals]
        if len(ids) != len(set(ids)):
            findings.append(finding('text', 'duplicate_region_ids'))
        for b in blocks+visuals:
            modality = 'text' if b in blocks else 'image'
            try: pixel_box=bbox_pixels(b['bbox'], im.size, pad=0)
            except (ValueError, TypeError, KeyError):
                findings.append(finding(modality, 'invalid_bbox', target_id=b['id'])); continue
            if b.get('uncertainties'):
                findings.append(finding(modality, 'source_uncertainty', target_id=b['id'], details=b['uncertainties']))
            text = b.get('text', '')
            if modality == 'text':
                if not text.strip(): findings.append(finding('text', 'empty_block', target_id=b['id']))
                crop=np.asarray(im.convert('L').crop(pixel_box))
                if text.strip() and crop.std()<3:
                    findings.append(finding('image','text_over_nearly_uniform_region',target_id=b['id']))
                elif text.strip() and min(crop.shape)>2:
                    evidence=cutoff_evidence(im,pixel_box)
                    if evidence:
                        alert=finding('image','possible_bbox_cutoff',target_id=b['id'],evidence=evidence)
                        reviewed=matching_decision(b,reviewed_image_hash,decisions)
                        if reviewed:
                            metrics.setdefault('reviewed_cutoff_findings',[]).append({**alert,
                                'status':'resolved_by_source_review','decision':reviewed['decision'],
                                'review_reason':reviewed['reason'],'post_review_note':reviewed.get('post_review_note','')})
                        else:findings.append(alert)
                if '\ufffd' in text or '[ILLEGIBLE]' in text:
                    findings.append(finding('text', 'unreadable_characters', target_id=b['id']))
                if b.get('kind') == 'code' and re.search(r'\[[0o]\]|=\s*[0o]\b', text):
                    findings.append(finding('text', 'zero_o_requires_source_comparison', target_id=b['id']))
                lines = [s.strip() for s in text.splitlines() if len(s.strip()) > 12]
                if len(lines) != len(set(lines)):
                    findings.append(finding('text', 'possible_repeated_line', target_id=b['id']))
            elif any(i not in {x['id'] for x in blocks} for i in b.get('related_block_ids', [])):
                findings.append(finding('image', 'missing_text_reference', target_id=b['id']))
        for i, a in enumerate(blocks):
            for b in blocks[i+1:]:
                if not a.get('text','').strip() or a['text'] != b.get('text'): continue
                try:
                    aa=bbox_pixels(a['bbox'], im.size, pad=0); bb=bbox_pixels(b['bbox'], im.size, pad=0)
                except ValueError: continue
                intersection=max(0,min(aa[2],bb[2])-max(aa[0],bb[0]))*max(0,min(aa[3],bb[3])-max(aa[1],bb[1]))
                if intersection:
                    findings.append(finding('text','possible_duplicate_overlap',target_id=a['id'],other_id=b['id']))
        for h in result.get('holds', []):
            findings.append(finding('image' if h.get('layer')=='visual' else 'text',
                                    'existing_hold', original_hold=h))
    return findings, metrics


def inspect_timeline(frames, duration, max_gap):
    findings=[]; previous=None
    if not frames: return [finding('video','no_selected_frames')]
    for f in frames:
        t=f['time_seconds']
        if not math.isfinite(t) or not 0 <= t <= duration:
            findings.append(finding('video','invalid_frame_time',frame_id=f['id'],time_seconds=t))
        if previous is not None:
            if t <= previous['time_seconds']:
                findings.append(finding('video','non_increasing_selected_time',frame_id=f['id']))
            if t-previous['time_seconds'] > max_gap+1:
                findings.append(finding('video','selected_frame_gap',start_seconds=previous['time_seconds'],end_seconds=t))
        previous=f
    if frames[0]['time_seconds'] > 1:
        findings.append(finding('video','uncovered_start',start_seconds=0,end_seconds=frames[0]['time_seconds']))
    if duration-frames[-1]['time_seconds'] > max_gap+1:
        findings.append(finding('video','uncovered_end',start_seconds=frames[-1]['time_seconds'],end_seconds=duration))
    return findings


def scan_video(source, frames, metadata, out, scan_fps=2, max_evidence=12, progress=lambda x: None, frame_root=None):
    """Decode all frames; audit scene changes at scan_fps, retaining capped evidence.

    A missed change is a candidate only; a scene may change without changing lesson
    content. Shorter-than-sampling events can still be missed, explicitly reported.
    """
    import av
    events=[]; count=0; sampled=0; previous_pts=None; previous_small=None; previous_image=None
    last_sample=-1e9; previous_sample=0; last_event=-1e9; samples_without_pts=0
    selected=np.array([f['time_seconds'] for f in frames]); folder=out/'evidence/video';folder.mkdir(parents=True,exist_ok=True)
    first=None; last=None;selected_index=0;matched=0
    ordered=sorted(frames,key=lambda f:f['time_seconds'])
    with av.open(str(source)) as container:
        for frame in container.decode(video=0):
            count+=1
            if frame.time is None: samples_without_pts+=1; continue
            t=float(frame.time)-metadata['video_origin_seconds']
            if first is None:first=t
            last=t
            if previous_pts is not None and (t<=previous_pts or t-previous_pts>max(.5,10/max(1,metadata['fps']))):
                events.append(finding('video','decoded_timestamp_gap_or_order',start_seconds=previous_pts,end_seconds=t))
            previous_pts=t
            while frame_root is not None and selected_index<len(ordered) and t>=ordered[selected_index]['time_seconds']-.001:
                saved=ordered[selected_index];selected_index+=1
                if abs(t-saved['time_seconds'])>max(.15,2/max(1,metadata['fps'])):
                    events.append(finding('video','selected_timestamp_not_decoded',frame_id=saved['id']));continue
                with Image.open(frame_root/saved['path']) as cached:
                    actual=frame.to_image()
                    mismatch=actual.size!=cached.size
                    error=None if mismatch else float(np.mean(np.abs(np.asarray(actual,dtype=np.int16)-np.asarray(cached.convert('RGB'),dtype=np.int16))))
                    if mismatch or error>2:
                        events.append(finding('video','saved_frame_source_mismatch',frame_id=saved['id'],mean_pixel_error=error))
                matched+=1
            if t-last_sample < 1/scan_fps-.001: continue
            last_sample=t;sampled+=1
            small=np.asarray(Image.fromarray(frame.reformat(width=320,height=180,format='gray').to_ndarray())
                             .filter(ImageFilter.GaussianBlur(.8)),dtype=np.int16)
            delta=0 if previous_small is None else float(np.mean(np.abs(small-previous_small)>20))
            if delta>.08 and t-last_event>=2 and (not len(selected) or float(np.min(np.abs(selected-t)))>2):
                event=finding('video','possibly_unrepresented_scene_change',start_seconds=previous_sample,
                              end_seconds=t,changed_fraction=delta)
                if sum('images' in e for e in events)<max_evidence:
                    paths=[]
                    for suffix,image in [('before',previous_image),('after',frame.to_image())]:
                        path=folder/f'change-{len(events):05}-{suffix}.png';image.save(path)
                        paths.append(str(path.relative_to(out)))
                    event['images']=paths
                else:event['evidence_deferred']='video_evidence_budget'
                events.append(event);last_event=t
            previous_small=small;previous_image=frame.to_image();previous_sample=t
            if sampled%120==0:progress(round(t,1))
    if not count: events.append(finding('video','no_decoded_frames'))
    if last is not None and metadata['duration_seconds']-last>1:
        events.append(finding('video','decoded_end_short',decoded_end=last,expected_end=metadata['duration_seconds']))
    if samples_without_pts:events.append(finding('video','frames_without_pts',count=samples_without_pts))
    if frame_root is not None:
        events.extend(finding('video','selected_timestamp_not_decoded',frame_id=f['id']) for f in ordered[selected_index:])
    return events,{'decoded_frames':count,'sampled_frames':sampled,'scan_fps':scan_fps,
                   'decoded_start':first,'decoded_end':last,'selected_frames_source_compared':matched,
                   'subsample_events_may_be_missed':True}


def audio_windows(path):
    windows=[]
    with wave.open(str(path)) as wav:
        if wav.getsampwidth()!=2 or wav.getnchannels()!=1:
            raise ValueError('audio_validation_requires_pcm16_mono')
        rate=wav.getframerate();total=wav.getnframes();pos=0
        while pos<total:
            data=np.frombuffer(wav.readframes(rate//2),dtype='<i2').astype(float)/32768
            if not len(data): break
            rms=float(np.sqrt(np.mean(data*data)))
            windows.append({'start':pos/rate,'end':(pos+len(data))/rate,
                            'rms_dbfs':20*math.log10(max(rms,1e-10)),
                            'clipped_fraction':float(np.mean(np.abs(data)>=.999))})
            pos+=len(data)
    return windows, total/rate


def inspect_audio(segments, windows, offset, duration):
    findings=[];by_segment={};gaps=[]
    for s in segments:
        a,b=s['start_seconds'],s['end_seconds'];reasons=list(s.get('review_reasons',[]))
        if not (math.isfinite(a) and math.isfinite(b) and 0<=a<b<=duration):reasons.append('invalid_segment_time')
        ws=[w for w in windows if w['end']+offset>a and w['start']+offset<b]
        if ws and s['text'].strip() and all(w['rms_dbfs']<-55 for w in ws):reasons.append('text_over_near_silence')
        if any(w['clipped_fraction']>.001 for w in ws):reasons.append('possible_clipping')
        if s.get('avg_logprob',0)<-1:reasons.append('low_asr_logprob')
        if s.get('no_speech_prob',0)>.6:reasons.append('possible_non_speech')
        if any(w.get('probability',1)<.4 for w in s.get('words',[])):reasons.append('low_word_probability')
        if re.search(r'(.{4,}?)\1\1',s['text']):reasons.append('possible_transcript_repetition')
        if re.search(r'\d',s['text']):reasons.append('spoken_number_requires_listening')
        for w in s.get('words',[]):
            if not a-.1<=w['start_seconds']<w['end_seconds']<=b+.1:reasons.append('word_timestamp_outside_segment');break
        if reasons:by_segment[s['id']]=[finding('audio',r,segment_id=s['id']) for r in sorted(set(reasons))]
    ordered=sorted(segments,key=lambda s:s['start_seconds'])
    for a,b in zip(ordered,ordered[1:]):
        if a['end_seconds']>b['start_seconds']+.2:
            findings.append(finding('audio','overlapping_transcript_intervals',segment_ids=[a['id'],b['id']]))
    active=[]
    for w in windows:
        a=max(0,w['start']+offset);b=min(duration,w['end']+offset)
        covered=any(s['start_seconds']<b and s['end_seconds']>a for s in ordered)
        if a<b and w['rms_dbfs']>-35 and not covered:
            if active and abs(active[-1]['end_seconds']-a)<.01:active[-1]['end_seconds']=b
            else:active.append({'start_seconds':a,'end_seconds':b})
    for x in active:
        if x['end_seconds']-x['start_seconds']>=1:
            gaps.append(finding('audio','audible_without_transcript',**x,
                                note='Energy is not speech detection; music/noise may trigger this.'))
    findings.extend(gaps)
    return findings, by_segment
