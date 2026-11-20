"""Whole-audio audit: cached local Whisper + Gemini only; preserve real repetitions."""
from video_extraction._layout import code_hashes_match
import argparse
import copy
import importlib.metadata
import json
import shutil
import wave
from pathlib import Path

from video_extraction.audio import audio_coverage as core
from video_extraction.shared.common import read, save, jsonl, signature, digest_file, now
from video_extraction.audio.audio_crosscheck import Budget, lock
from video_extraction.shared.gemini import Gemini, Blocked, api_key

ROOT = core.ROOT
OUT = ROOT / 'outputs/audio-coverage-v2'
MODEL = ROOT / 'work/extraction-compare/models/models--mobiuslabsgmbh--faster-whisper-large-v3-turbo/snapshots/0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf'
OPTIONS = dict(language='ko', task='transcribe', beam_size=5, temperature=0,
               condition_on_previous_text=False, initial_prompt=None, hotwords=None,
               vad_filter=False, word_timestamps=True, repetition_penalty=1,
               no_repeat_ngram_size=0)
PROMPT = core.PROMPT.replace('Independent transcription', 'Local Whisper retranscription').replace(
    'DATA:\n', 'The local retranscription uses the SAME turbo family as the baseline; it is NOT independent evidence or gold. '
    'Agreement alone does not prove correctness. Inspect the audio even where both transcripts agree or are empty.\nDATA:\n')


def hashes():
    return {**core.hashes(), 'audio_coverage_local.py': digest_file(__file__)}


def model_info(path):
    path = Path(path).resolve()
    names = ['model.bin', 'config.json', 'tokenizer.json']
    vocabulary = next((n for n in ('vocabulary.json', 'vocabulary.txt') if (path / n).is_file()), None)
    if not vocabulary:
        raise ValueError('local_whisper_model_missing_no_download_attempted')
    names.append(vocabulary)
    # Official CTranslate2 Whisper exports may rely on built-in preprocessing defaults.
    if (path / 'preprocessor_config.json').is_file():names.append('preprocessor_config.json')
    if not all((path / n).is_file() for n in names):
        raise ValueError('local_whisper_model_missing_no_download_attempted')
    return {'path': str(path), 'files': {n: digest_file(path / n) for n in names},
            'runtime': {n: importlib.metadata.version(n) for n in ['faster-whisper', 'ctranslate2']},
            'device': 'cpu', 'compute_type': 'int8', 'options': OPTIONS,
            'same_model_family_as_baseline': True}


def prepare(out=OUT, source=core.OUT, model=MODEL):
    out, source = Path(out).resolve(), Path(source).resolve()
    with lock(out):
        if (out / 'plan.json').exists():
            p = verify(out)
            if Path(p['local_whisper']['path']) != Path(model).resolve():
                raise ValueError('model_changed_choose_new_output')
            return p
        # Reuse only verified offline inputs, never old API results or credentials.
        old = core.verify(source)
        local = model_info(model)
        (out / 'clips').mkdir(exist_ok=True)
        for name in ['full-transcript.frozen.jsonl', 'vad.json', 'timeline-audit.json']:
            shutil.copy2(source / name, out / name)
        for w in old['windows']:
            shutil.copy2(source / w['clip'], out / w['clip'])
        p = copy.deepcopy(old)
        p.pop('openai_model', None)
        p.update(version=2, created_at=now(), code_hashes=hashes(), local_whisper=local,
                 nominal_calls=len(p['windows']), transcription_provider='local_whisper',
                 source_plan_signature=signature(old), allowed_api_provider='gemini')
        save(out / 'plan.json', p)
        report(out, p)
        return p


def verify(out):
    p = read(out / 'plan.json')
    if not code_hashes_match(p['code_hashes'], hashes()):
        raise ValueError('code_changed_choose_new_output')
    if p['local_whisper'] != model_info(p['local_whisper']['path']):
        raise ValueError('local_model_or_runtime_changed')
    for path, expected in p['inputs'].items():
        if digest_file(path) != expected:
            raise ValueError('input_changed_choose_new_output')
    for name, key in [('full-transcript.frozen.jsonl', 'frozen_sha256'), ('vad.json', 'vad_sha256'), ('timeline-audit.json', 'timeline_sha256')]:
        if digest_file(out / name) != p[key]:
            raise ValueError('frozen_audit_changed')
    for w in p['windows']:
        if digest_file(out / w['clip']) != w['clip_meta']['sha256']:
            raise ValueError('clip_changed')
    return p


class LocalWhisper:
    def __init__(self, config, cache):
        self.config, self.cache, self.model = config, Path(cache), None

    def transcribe(self, path):
        # Keep the feature extractor's working set independent of lecture length.
        # Short clips retain the existing inference and mandatory review path.
        with wave.open(str(path)) as wav:
            rate, count = wav.getframerate(), wav.getnframes()
            if (rate, wav.getnchannels(), wav.getsampwidth()) != (16000, 1, 2):
                raise ValueError('local_transcription_requires_pcm16_mono_16k')
        if count > rate * 60:
            return self.transcribe_long(path, count, rate)
        return self.transcribe_clip(path)

    def transcribe_long(self, path, count, rate):
        import math
        from video_extraction.shared.progress import report
        binding = signature({'stage':'bounded-whisper-v1', 'config':self.config,
                             'audio':digest_file(path), 'window':30, 'context':5})
        root = self.cache / binding
        rows = []; language = None; total = math.ceil(count / (30 * rate))
        with wave.open(str(path)) as wav:
            for index in range(total):
                report('transcribe', index, total)
                start = index * 30 * rate; end = min(count, start + 30 * rate)
                lo = max(0, start - 5 * rate); hi = min(count, end + 5 * rate)
                clip = root / f'{index:05}.wav'
                root.mkdir(parents=True, exist_ok=True)
                wav.setpos(lo)
                # At most 40 seconds of PCM; retain source-bound clips and caches.
                with wave.open(str(clip), 'wb') as target:
                    target.setparams((1, 2, rate, 0, 'NONE', 'not compressed'))
                    target.writeframes(wav.readframes(hi - lo))
                result = self.transcribe_clip(clip)
                language = language or result.get('language')
                for segment in result['segments']:
                    words = segment.get('words', [])
                    if words:
                        # Each word has one owning core; preserve its complete
                        # timestamp (including boundary context), never clip words.
                        owned = [{**w, 'start':float(w['start']) + lo/rate,
                                  'end':float(w['end']) + lo/rate} for w in words
                                 if start <= lo + (float(w['start']) + float(w['end']))/2*rate < end]
                        if not owned: continue
                        row = {**segment, 'start':owned[0]['start'], 'end':owned[-1]['end'],
                               'text':''.join(w['word'] for w in owned), 'words':owned}
                    else:
                        a, b = float(segment['start']) + lo/rate, float(segment['end']) + lo/rate
                        if not start/rate <= (a+b)/2 < end/rate: continue
                        row = {**segment, 'start':a, 'end':b, 'words':[]}
                    rows.append(row)
                report('transcribe', index + 1, total)
        result = {'signature':binding, 'text':''.join(s['text'] for s in rows).strip(),
                  'language':language, 'segments':rows, 'time_basis':'clip_relative_seconds',
                  'provider':'local_whisper', 'same_model_family_as_baseline':True,
                  'api_calls':0, 'at':now(), 'window_seconds':30, 'context_seconds':5}
        save(root / 'complete.json', result)
        return result

    def transcribe_clip(self, path):
        sig = signature({'stage': 'local-blind-v2-language', 'config': self.config, 'audio': digest_file(path)})
        dest = self.cache / (sig + '.json')
        if dest.exists():
            result = read(dest)
            if result.get('signature') != sig or not isinstance(result.get('text'), str):
                raise ValueError('invalid_local_cache')
            return result
        if self.model is None:
            from faster_whisper import WhisperModel
            self.model = WhisperModel(self.config['path'], device='cpu', compute_type='int8',
                                      cpu_threads=4, local_files_only=True)
        # Prepared PCM WAVs need no PyAV decoder (installed PyAV has an incompatible API).
        import numpy as np
        with wave.open(str(path)) as wav:
            if (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) != (16000, 1, 2):
                raise ValueError('local_transcription_requires_pcm16_mono_16k')
            audio = np.frombuffer(wav.readframes(wav.getnframes()), dtype='<i2').astype(np.float32) / 32768
        segments, info = self.model.transcribe(audio, **self.config['options'])
        rows = [{'start': s.start, 'end': s.end, 'text': s.text,
                 'words': [{'start': w.start, 'end': w.end, 'word': w.word, 'probability': w.probability}
                           for w in (s.words or [])]} for s in segments]
        result = {'signature': sig, 'text': ''.join(s['text'] for s in rows).strip(),
                  'language':getattr(info,'language',None) or self.config['options'].get('language'),
                  'segments': rows, 'time_basis': 'clip_relative_seconds', 'provider': 'local_whisper',
                  'same_model_family_as_baseline': True, 'api_calls': 0, 'at': now()}
        save(dest, result)
        return result


def report(out, p=None):
    p = p or verify(out)
    s = core.report(out, p)
    s.update(transcription_provider='local_whisper', allowed_api_provider='gemini',
             same_model_family_as_baseline=True)
    save(out / 'summary.json', s)
    path = out / '전체음성_중복누락검사.html'
    page = path.read_text().replace('독립 전사 — 문맥 포함', '로컬 Whisper 재전사 — 문맥 포함')
    page = page.replace('</h1>', '</h1><p class="notice">구글 키만 사용: 로컬 Whisper turbo 재전사 → Gemini 원음 검사 → 계산 검사. 최초 전사도 turbo이므로 모델 간 독립 검증이나 정답으로 취급하지 않습니다. 실제 수정 전 후보 검토가 필요합니다.</p>', 1)
    path.write_text(page, encoding='utf-8')
    return s


def run(out, env_file, maximum=200, delay=15, local_only=False, limit=None):
    with lock(out):
        p = verify(out)
        if not local_only:
            api_key(env_file)  # Google only; OpenAI credentials are never read.
        rows = list(map(json.loads, (out / 'full-transcript.frozen.jsonl').read_text().splitlines()))
        transcriber = LocalWhisper(p['local_whisper'], out / 'whisper-cache')
        budget = Budget(out, maximum, delay)
        client = None if local_only else Gemini(out / 'gemini-cache', p['gemini_model'], env_file,
                                                max_calls=maximum, delay=0, transport=budget)
        error = None
        processed = 0
        try:
            for w in sorted(p['windows'], key=lambda w: (w['priority'], w['core'][0])):
                dest = out / 'results' / (w['label'] + '.json')
                if dest.exists():
                    continue
                if limit is not None and processed >= limit:
                    break
                print(json.dumps({'window': w['label'], 'stage': 'local_whisper', 'api_calls': budget.used}), flush=True)
                local = transcriber.transcribe(out / w['clip'])
                processed += 1
                if local_only:
                    continue
                current = [{k: r[k] for k in ['id', 'start_seconds', 'end_seconds', 'text']}
                           for r in rows if r['id'] in w['row_ids']]
                prompt = PROMPT + json.dumps({'audio_start_seconds': w['clip_meta']['start_seconds'],
                    'audio_end_seconds': w['clip_meta']['end_seconds'], 'owned_core': w['core'],
                    'existing_segments': current, 'local_context_transcript': local['text']}, ensure_ascii=False)
                j = client.call('whole-audio-local-coverage-v2', [out / w['clip']], prompt, core.SCHEMA)
                checks = [core.check_finding(f, w, rows, local['text']) for f in j['findings']]
                if not j['checked_full_core'] or j['speech_unresolved']:
                    for c in checks:
                        if c['candidate']:
                            c.update(candidate=False, status='held')
                            c['reasons'].append('window_not_fully_resolved')
                save(dest, {'label': w['label'], 'plan_signature': signature(p),
                    'independent_text': local['text'],  # shared report schema; provenance below is explicit
                    'transcription_provider': 'local_whisper', 'independent_model': False,
                    'local_signature': local['signature'], 'review': j, 'checks': checks, 'at': now()})
                s = report(out, p)
                print(json.dumps({'completed': s['completed_windows'], 'total': s['windows'], 'calls': budget.used}), flush=True)
        except Blocked as ex:
            error = str(ex)
        except KeyboardInterrupt:
            error = 'interrupted'
        except Exception:
            error = 'local_or_validation_failure'
            raise
        finally:
            s = report(out, p)
            save(out / ('local-run-state.json' if local_only else 'run-state.json'), {
                'stop_reason': error or ('local_only' if local_only else 'complete' if not s['remaining_windows'] else 'partial'),
                'summary': s, 'api_calls_this_run': budget.used})
        if error:
            raise Blocked(error)
        return s


def apply(out, approval_file):
    with lock(out):
        p = verify(out)
        approval = read(approval_file)
        if approval['plan_signature'] != signature(p):
            raise ValueError('approval_plan_changed')
        results, candidates, _ = core.collect(out, p)
        if len(results) != len(p['windows']):
            raise ValueError('finish_all_windows_before_apply')
        rows = list(map(json.loads, (out / 'full-transcript.frozen.jsonl').read_text().splitlines()))
        after, receipt = core.apply_candidates(rows, candidates, approval['approved_candidate_ids'], approval['reviewer'])
        if not receipt:
            raise ValueError('no_explicitly_approved_candidates')
        dest = out / 'revisions' / signature(approval)[:16]
        jsonl(dest / 'full-transcript.corrected.jsonl', after)
        save(dest / 'repair-receipt.json', {'plan_signature': signature(p), 'approved': receipt,
            'production_changes': 0, 'rows_before': len(rows), 'rows_after': len(after),
            'all_content_verified': False, 'api_calls': 0})
        return {'new_version': str(dest / 'full-transcript.corrected.jsonl'), 'approved_repairs': len(receipt)}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('mode', choices=['prepare', 'run', 'report', 'apply'])
    ap.add_argument('--output', type=Path, default=OUT)
    ap.add_argument('--source-output', type=Path, default=core.OUT)
    ap.add_argument('--model-path', type=Path, default=MODEL)
    ap.add_argument('--env-file', type=Path, default=ROOT / '.env')
    ap.add_argument('--max-api-calls', type=int, default=200)
    ap.add_argument('--delay', type=float, default=15)
    ap.add_argument('--local-only', action='store_true')
    ap.add_argument('--limit', type=int)
    ap.add_argument('--approval-file', type=Path)
    a = ap.parse_args()
    out = a.output.resolve()
    try:
        if a.mode == 'prepare':
            p = prepare(out, a.source_output, a.model_path)
            result = {'segments': p['baseline_segments'], 'windows': len(p['windows']), 'nominal_gemini_calls': p['nominal_calls'], 'api_calls': 0}
        elif a.mode == 'run':
            result = run(out, a.env_file, a.max_api_calls, a.delay, a.local_only, a.limit)
        elif a.mode == 'apply':
            if not a.approval_file:
                ap.error('--approval-file is required')
            result = apply(out, a.approval_file)
        else:
            with lock(out):
                result = report(out)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (Blocked, ValueError, BlockingIOError, ImportError, OSError) as ex:
        print(json.dumps({'stopped': str(ex)}, ensure_ascii=False))
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
