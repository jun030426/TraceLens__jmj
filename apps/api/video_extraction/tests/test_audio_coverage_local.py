import json
import tempfile
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from video_extraction.audio import audio_coverage_local as local
from video_extraction.shared.common import save, jsonl, read
from video_extraction.shared.gemini import Blocked


class LocalCoverageTests(unittest.TestCase):
    def test_local_cache_reuses_completed_transcription(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            audio = root / 'clip.wav'
            with wave.open(str(audio), 'wb') as wav:
                wav.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
                wav.writeframes(b'\x00\x00' * 160)
            config = {'options': local.OPTIONS}
            t = local.LocalWhisper(config, root / 'cache')
            t.model = Mock()
            t.model.transcribe.return_value = (iter([
                SimpleNamespace(start=0, end=2, text=' 반복 반복', words=[])]), None)
            a = t.transcribe(audio)
            b = t.transcribe(audio)
            self.assertEqual(a, b)
            self.assertEqual(a['text'], '반복 반복')
            self.assertEqual(t.model.transcribe.call_count, 1)
            self.assertEqual(t.model.transcribe.call_args.kwargs['no_repeat_ngram_size'], 0)
            self.assertFalse(t.model.transcribe.call_args.kwargs['vad_filter'])
            self.assertIsNone(t.model.transcribe.call_args.kwargs['initial_prompt'])
            self.assertEqual(t.model.transcribe.call_args.args[0].shape, (160,))

    def test_missing_model_fails_without_download(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaisesRegex(ValueError, 'no_download'):
                local.model_info(d)

    def fixture(self, root):
        jsonl(root / 'full-transcript.frozen.jsonl', [])
        w = {'label': 'W001', 'priority': 0, 'core': [0, 30], 'clip': 'a.wav',
             'clip_meta': {'start_seconds': 0, 'end_seconds': 35}, 'row_ids': []}
        return {'windows': [w], 'local_whisper': {}, 'gemini_model': 'test'}

    def report(self, root, p):
        count = len(list((root / 'results').glob('*.json')))
        return {'completed_windows': count, 'windows': 1, 'remaining_windows': 1-count}

    def test_gemini_failure_resume_does_not_require_openai_or_rewrite_completed(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            p = self.fixture(root)
            with patch.object(local, 'verify', return_value=p), \
                 patch.object(local, 'report', side_effect=self.report), \
                 patch.object(local, 'api_key', return_value='google-key') as key, \
                 patch.object(local, 'LocalWhisper') as whisper, \
                 patch.object(local, 'Gemini') as gemini, \
                 patch('video_extraction.audio.audio_crosscheck.openai_key', side_effect=AssertionError('OpenAI forbidden')), \
                 patch('video_extraction.audio.audio_crosscheck.blind_transcribe', side_effect=AssertionError('OpenAI forbidden')):
                whisper.return_value.transcribe.return_value = {'text': '반복 반복', 'signature': 'local'}
                gemini.return_value.call.side_effect = Blocked('test_interruption')
                with self.assertRaises(Blocked):
                    local.run(root, root / '.env')
                self.assertFalse((root / 'results/W001.json').exists())
                gemini.return_value.call.side_effect = None
                gemini.return_value.call.return_value = {'checked_full_core': True, 'speech_unresolved': False, 'findings': []}
                local.run(root, root / '.env')
                self.assertEqual(gemini.return_value.call.call_count, 2)
                local.run(root, root / '.env')
                self.assertEqual(gemini.return_value.call.call_count, 2)
                saved = read(root / 'results/W001.json')
                self.assertFalse(saved['independent_model'])
                self.assertEqual(saved['transcription_provider'], 'local_whisper')
                self.assertIn('SAME turbo', gemini.return_value.call.call_args.args[2])

    def test_local_only_never_reads_key_or_constructs_api_client(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            p = self.fixture(root)
            with patch.object(local, 'verify', return_value=p), \
                 patch.object(local, 'report', side_effect=self.report), \
                 patch.object(local, 'api_key', side_effect=AssertionError('key forbidden')), \
                 patch.object(local, 'Gemini', side_effect=AssertionError('API forbidden')), \
                 patch.object(local, 'LocalWhisper') as whisper:
                whisper.return_value.transcribe.return_value = {'text': '', 'signature': 'x'}
                local.run(root, root / '.env', local_only=True, limit=1)
                self.assertEqual(read(root / 'local-run-state.json')['api_calls_this_run'], 0)
                self.assertFalse((root / 'results/W001.json').exists())


if __name__ == '__main__':
    unittest.main()
