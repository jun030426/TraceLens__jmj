"""Freeze a blind annotation set from offline preprocessing; never calls an API.

This lecture has already informed fixes, so these are development samples, not
an independent holdout. Blank reference labels must be filled from the source.
"""
import argparse
import html
import json
import random
import wave
from pathlib import Path

from video_extraction.shared.common import digest_file, now, read, save
from video_extraction.shared.preprocessing import checked


def select_frames(frames, count, seed):
    ordered = sorted(frames, key=lambda f: (f['time_seconds'], f['id']))
    if count <= 0 or count > len(ordered):
        raise ValueError('invalid_frame_sample_count')
    rng = random.Random(seed)
    # Equal-count temporal strata: sampling does not depend on model findings.
    return [rng.choice(ordered[i*len(ordered)//count:(i+1)*len(ordered)//count])
            for i in range(count)]


def select_audio(duration, offset, count, seconds, seed):
    if count <= 0 or seconds <= 0 or duration < count*seconds:
        raise ValueError('insufficient_audio_duration')
    rng = random.Random(seed)
    width = duration/count
    return [{'id': 'audio-sample-%02d' % (i+1),
             'start_seconds': round(offset + i*width + rng.random()*(width-seconds), 3)}
            for i in range(count)]


def blind_frame(frame, source):
    return {'id': frame['id'], 'source_sha256': source,
            'image_path': frame['path'], 'time_seconds': frame['time_seconds'],
            'annotation_status': 'unlabeled', 'reviewer': None, 'reviewed_at': None,
            'reference_text_verbatim': None, 'reference_regions': None,
            'ambiguous_regions': None, 'is_blank': None, 'notes': None}


def prepare(preprocessed, output, seed=20261026, frame_count=24, audio_count=6, clip_seconds=60):
    base, output = Path(preprocessed).resolve(), Path(output).resolve()
    if output.exists():
        raise ValueError('output_exists_choose_new_directory')
    manifest_path = base/'manifest.json'
    manifest_hash = digest_file(manifest_path)
    manifest = read(manifest_path)
    for name, digest in manifest['output_sha256'].items():
        checked(base/name, digest)
    inputs = read(base/'evaluation-inputs.json')
    audio_path = Path(inputs['audio_path'])
    checked(audio_path, manifest['input_sha256'][str(audio_path)])
    frames = select_frames(inputs['frames'], frame_count, seed)
    for frame in frames:
        checked(frame['path'], manifest['input_sha256'][frame['path']])
    with wave.open(str(audio_path), 'rb') as audio:
        rate = audio.getframerate()
        duration = audio.getnframes()/rate
        offset = inputs['audio_offset_seconds']
        clips = select_audio(duration, offset, audio_count, clip_seconds, seed+1)
        output.mkdir(parents=True, exist_ok=False)
        (output/'audio').mkdir()
        for clip in clips:
            begin = round((clip['start_seconds']-offset)*rate)
            amount = round(clip_seconds*rate)
            audio.setpos(begin)
            data = audio.readframes(amount)
            if len(data) != amount*audio.getnchannels()*audio.getsampwidth():
                raise ValueError('incomplete_audio_clip')
            dest = output/'audio'/(clip['id']+'.wav')
            with wave.open(str(dest), 'wb') as out:
                out.setparams(audio.getparams())
                out.writeframes(data)
            clip.update(start_seconds=offset+begin/rate, end_seconds=offset+(begin+amount)/rate,
                        audio_path=str(dest), derived_from=str(audio_path),
                        annotation_status='unlabeled', reviewer=None, reviewed_at=None,
                        reference_text_verbatim=None, ambiguous_spans=None,
                        boundary_partial_words=None, notes=None)
    frame_ids = {f['id'] for f in frames}
    records = [json.loads(line) for line in (base/'records.jsonl').read_text().splitlines()]
    predictions = {'frame_records': [r for r in records if r['location'].get('frame_id') in frame_ids],
                   'audio_segments': []}
    for clip in clips:
        for seg in inputs['speech']:
            if seg['end_seconds'] > clip['start_seconds'] and seg['start_seconds'] < clip['end_seconds']:
                predictions['audio_segments'].append({'sample_id': clip['id'], 'segment': seg,
                    'crosses_clip_boundary': seg['start_seconds'] < clip['start_seconds'] or
                                             seg['end_seconds'] > clip['end_seconds']})
    references = {'schema_version': 1, 'purpose': 'development_sample_not_holdout',
                  'source_sha256': inputs['source_sha256'], 'seed': seed,
                  'instructions': [
                      'Read/listen to source before opening predictions.json; do not copy model outputs as truth.',
                      'Preserve code indentation, spelling, numbers and symbols verbatim.',
                      'For 0/o or illegible content, mark ambiguity with candidates; do not force a correction.',
                      'Record every visible region, including handwriting, figures and tables, with xyxy_0_1000 boxes.',
                      'For clipped audio words, label boundary_partial_words separately from complete words.',
                      'Blank/null labels mean not annotated, never correct or empty source.',
                      'A second reviewer should adjudicate disagreements before scoring.'],
                  'region_template': {'kind': None, 'bbox': None, 'literal_text': None,
                                      'status': 'unlabeled', 'candidates': []},
                  'frames': [blind_frame(f, inputs['source_sha256']) for f in frames], 'audio': clips}
    save(output/'references.blank.json', references)
    save(output/'predictions.json', predictions)
    cards = []
    for f in frames:
        cards.append('<article><h2>%s · %.2f초</h2><img src="%s" alt="원본 화면"></article>' %
                     (html.escape(f['id']), f['time_seconds'], html.escape(Path(f['path']).as_uri(), quote=True)))
    for c in clips:
        cards.append('<article><h2>%s · %.2f–%.2f초</h2><audio controls preload="none" src="audio/%s.wav"></audio></article>' %
                     (c['id'], c['start_seconds'], c['end_seconds'], c['id']))
    page = '''<!doctype html><html lang="ko"><meta charset="utf-8"><title>정답 표본 작성용 원본</title>
<style>body{font-family:system-ui;max-width:1100px;margin:32px auto;padding:0 20px;background:#f5f6f8}
article{background:white;padding:18px;margin:24px 0;border-radius:12px}img{width:100%}audio{width:100%}</style>
<h1>정답 표본 작성용 원본</h1><p>화면 24개와 음성 6개가 기본값입니다. 실제 선택 개수는 아래 항목을 따릅니다.
기존 오류 수정에 사용한 강의에서 고른 개발 표본이며, 별도 평가용 새 강의가 아닙니다.</p>
<p>추출 결과를 열기 전에 원본을 보고 references.blank.json을 복사해 정답을 작성하세요.
모호한 0/o·필기는 보류와 후보를 기록합니다. 아직 정확도는 계산하지 않았습니다.</p>'''
    (output/'원본표본.html').write_text(page+''.join(cards)+'</html>', encoding='utf-8')
    summary = {'created_at': now(), 'purpose': 'development_sample_not_holdout', 'seed': seed,
               'frame_samples': len(frames), 'audio_samples': len(clips),
               'audio_seconds': sum(c['end_seconds']-c['start_seconds'] for c in clips),
               'reference_labels_completed': 0, 'accuracy': None, 'api_requests': 0,
               'coverage_limits': ['Sampled existing keyframes only; short unsampled scenes are not evaluated.',
                                   'PPT and generalization to other lectures are not evaluated.'],
               'future_metrics': ['screen_text_CER', 'code_exact_match', 'region_precision_recall',
                                  'audio_CER_WER', 'ambiguity_and_abstention_rate']}
    save(output/'summary.json', summary)
    checked(manifest_path, manifest_hash)
    for name, digest in manifest['output_sha256'].items():
        checked(base/name, digest)
    checked(audio_path, manifest['input_sha256'][str(audio_path)])
    for frame in frames:
        checked(frame['path'], manifest['input_sha256'][frame['path']])
    save(output/'manifest.json', {'preprocessing_manifest': str(manifest_path),
         'preprocessing_manifest_sha256': manifest_hash, 'implementation_sha256': digest_file(__file__),
         'output_sha256': {str(p.relative_to(output)): digest_file(p) for p in sorted(output.rglob('*')) if p.is_file()}})
    return summary


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--preprocessed', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--seed', type=int, default=20261026)
    a = p.parse_args()
    print(json.dumps(prepare(a.preprocessed, a.output, a.seed), ensure_ascii=False))


if __name__ == '__main__':
    main()
