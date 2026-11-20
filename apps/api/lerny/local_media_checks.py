"""Local extraction checks, not semantic approval. Never repair source text."""
import math
import re

POLICY = 'local-media-basic-v3'


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def text_issues(text):
    issues = []
    if not isinstance(text, str) or not text.strip():
        return ['empty_extraction']
    if '\ufffd' in text or any(ord(c) < 32 and c not in '\n\r\t' for c in text):
        issues.append('invalid_text_characters')
    if re.search(r'(.{4,80}?)\1\1', text):
        issues.append('possible_transcript_repetition')
    return issues


def audio_records(transcript, duration, offset, windows, speech):
    """Return each source segment plus local suspicions; no whole-video rejection."""
    from video_extraction.audio.audio_coverage import audit_timeline
    from video_extraction.shared.multimodal_checks import inspect_audio
    rows = []
    for i, segment in enumerate(transcript['segments']):
        text = segment.get('text', '')
        if not isinstance(text,str):text=''
        a, b = segment.get('start'), segment.get('end')
        reasons = text_issues(text)
        if len(text)>1800:reasons.append('oversized_transcript_segment')
        if not finite(a) or not finite(b) or not 0 <= a < b <= duration + .02:
            reasons.append('invalid_segment_time')
            a = a if finite(a) else 0
            b = b if finite(b) else a
        words = []
        for w in segment.get('words', []):
            wa, wb, probability = w.get('start'), w.get('end'), w.get('probability')
            if not finite(wa) or not finite(wb) or not a-.1 <= wa <= wb <= b+.1:
                reasons.append('word_timestamp_outside_segment'); continue
            if probability is not None and (not finite(probability) or not 0 <= probability <= 1):
                reasons.append('invalid_asr_confidence'); continue
            words.append({**w, 'start_seconds':wa, 'end_seconds':wb})
        row = {'id':f'audio-{i+1}', 'modality':'audio', 'text':text,
               'start_seconds':a, 'end_seconds':b, 'words':words, 'review_reasons':reasons}
        if finite(segment.get('avg_logprob')): row['avg_logprob'] = segment['avg_logprob']
        if finite(segment.get('no_speech_prob')): row['no_speech_prob'] = segment['no_speech_prob']
        rows.append(row)
    global_issues, per_segment = inspect_audio(rows, windows, 0, duration)
    timeline = audit_timeline(rows, duration, speech)
    overlap_ids = {sid for issue in global_issues if issue['reason']=='overlapping_transcript_intervals'
                   for sid in issue['segment_ids']}
    records = []
    for row in rows:
        # User-approved local policy: a number alone is not evidence of a defect.
        # Low-confidence numbers remain held by the same confidence checks as other words.
        reasons = sorted(set(row['review_reasons'] + [f['reason'] for f in per_segment.get(row['id'], [])
                         if f['reason'] != 'spoken_number_requires_listening']))
        if row['id'] in overlap_ids: reasons.append('overlapping_transcript_intervals')
        start, end = row['start_seconds']+offset, row['end_seconds']+offset
        record = {'id':row['id'], 'modality':'audio', 'text':row['text'],
            'start_seconds':start, 'end_seconds':end, 'reasons':reasons,
            'source_locator':f'영상 {start:.1f}–{end:.1f}초 · 음성', 'eligible_for_chunking':not reasons}
        from lerny.local_audio_spans import split_uncertain
        records.extend(split_uncertain(row, record))
    for i, (a,b) in enumerate(timeline['vad_gaps_at_least_0_2s']):
        if b-a < 1: continue
        records.append({'id':f'audio-gap-{i+1}', 'modality':'audio', 'text':'',
            'start_seconds':a+offset, 'end_seconds':b+offset,
            'source_locator':f'영상 {a+offset:.1f}–{b+offset:.1f}초 · 음성',
            'reasons':['speech_without_transcript'], 'eligible_for_chunking':False})
    return records, {'timeline':timeline, 'semantic_verified':False,
                     'scope':'source timing, VAD coverage, signal and transcription quality indicators'}


def ocr_records(lines, start, end, frame_id):
    records=[]
    for i, line in enumerate(lines):
        text=line['text'];reasons=text_issues(text)
        if line['min_confidence'] < 55 or line['mean_confidence'] < 80:
            reasons.append('ocr_low_confidence')
        if re.search(r'(^|\s)(def |class |import |public |void |return |for\s*\(|while\s*\()|[{};]|==|!=|<=|>=|[=∑∫√→←]',text):
            reasons.append('ocr_code_or_formula_requires_review')
        if len(text)>1800:reasons.append('oversized_ocr_line')
        records.append({'id':f'{frame_id}-line-{i+1}', 'modality':'visual', 'text':text,
            'start_seconds':start, 'end_seconds':end, 'bbox':line['bbox'],
            'source_locator':f'영상 {start:.1f}초 · 화면 글자', 'reasons':reasons,
            'eligible_for_chunking':not reasons})
    return records


def build_chunks(records, source_sha256):
    """Pack adjacent accepted speech only; a held segment always breaks the group."""
    chunks=[];pending=[];length=0
    def flush():
        nonlocal pending,length
        if not pending:return
        a=min(r['start_seconds'] for r in pending);b=max(r['end_seconds'] for r in pending)
        chunks.append({'text':'\n'.join(r['text'] for r in pending), 'document_type':'mp4',
            'source_sha256':source_sha256, 'source_locator':f'영상 {a:.1f}–{b:.1f}초 · '+('음성' if pending[0]['modality']=='audio' else '화면 글자'),
            'time_interval':{'start_seconds':a,'end_seconds':b},
            'modality':pending[0]['modality'], 'record_ids':[r['id'] for r in pending],
            'quality':POLICY, 'semantic_verified':False, 'eligible_for_chunking':True})
        if len(pending)==1 and pending[0].get('picture_reuse'):
            chunks[-1].update(picture_reuse=pending[0]['picture_reuse'], image_region=pending[0]['bbox'])
        pending=[];length=0
    for r in records:
        if not r['eligible_for_chunking'] or not r['text'].strip():flush();continue
        if r.get('code_block'):
            from lerny.video_code import valid_record
            flush()
            if not valid_record(r):raise ValueError('VIDEO_CODE_PROOF_INVALID')
            chunks.append({'text':r['text'],'document_type':'mp4','source_sha256':source_sha256,
                'source_locator':r['source_locator'],'time_interval':{'start_seconds':r['start_seconds'],'end_seconds':r['end_seconds']},
                'modality':'visual','record_ids':[r['id']],'quality':POLICY,'semantic_verified':False,
                'code_block':r['code_block'],'eligible_for_chunking':True})
            continue
        if r.get('isolated'):flush()
        if pending and (r['modality'] != pending[-1]['modality'] or
                        r['start_seconds']-pending[-1]['end_seconds']>2 or length+len(r['text'])+1>1500):flush()
        if len(r['text'])>1800:raise ValueError('LOCAL_MEDIA_CHUNK_LIMIT')
        pending.append(r);length+=len(r['text'])+1
        if r.get('isolated'):flush()
    flush()
    return chunks
