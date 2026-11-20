import sys
import wave
from types import SimpleNamespace

import pytest
from video_extraction.audio.audio_coverage_local import LocalWhisper
from video_extraction.shared.progress import reporting


def audio(path, seconds):
    with wave.open(str(path), 'wb') as w:
        w.setparams((1,2,16000,0,'NONE','not compressed'))
        for index in range(seconds): w.writeframes((index+1).to_bytes(2,'little')*16000)


def test_long_audio_bounded_model_input_cache_resume_and_absolute_words(tmp_path):
    path = tmp_path/'lecture.wav'; audio(path, 125)
    calls = []; reports = []
    class Model:
        def transcribe(self, samples, **options):
            calls.append(len(samples))
            assert len(samples) <= 40*16000
            # One word each second exercises ownership of overlapped context.
            words = [SimpleNamespace(start=float(i), end=i+.5, word=' 한', probability=.9)
                     for i in range(len(samples)//16000)]
            segments = [SimpleNamespace(start=w.start, end=w.end, text=w.word, words=[w]) for w in words]
            return iter(segments), SimpleNamespace(language='ko')
    transcriber = LocalWhisper({'options':{}}, tmp_path/'cache'); transcriber.model = Model()
    with reporting(lambda *v:reports.append(v)):
        result = transcriber.transcribe(path)
    assert len(calls) == 5 and len(result['segments']) == 125
    assert [s['start'] for s in result['segments']] == list(range(125))
    assert result['segments'][-1]['words'][0]['end'] == 124.5
    assert reports[-1] == ('transcribe',5,5)
    # All clips are source bound; repeat inference uses durable cache.
    transcriber.transcribe(path)
    assert len(calls) == 5
    audio(path, 126)
    transcriber.transcribe(path)
    assert len(calls) > 5


def test_interrupted_transcription_reuses_completed_chunks(tmp_path):
    path=tmp_path/'lecture.wav'; audio(path, 100)
    calls=[]
    class Model:
        def transcribe(self, samples, **kwargs):
            calls.append(len(samples))
            if len(calls)==2: raise RuntimeError('synthetic interruption')
            return iter([]), SimpleNamespace(language='ko')
    transcriber=LocalWhisper({'options':{}},tmp_path/'cache');transcriber.model=Model()
    with pytest.raises(RuntimeError):transcriber.transcribe(path)
    transcriber.transcribe(path)
    assert len(calls)==5  # successful first chunk not recomputed


def test_vad_is_bounded_and_merges_speech_at_chunk_boundaries(tmp_path,monkeypatch):
    from video_extraction.audio.audio_coverage import detect_speech
    path=tmp_path/'lecture.wav';audio(path,181);calls=[]
    def detect(samples, options, sampling_rate):
        calls.append(len(samples));assert len(samples)<=62*16000
        return [{'start':0,'end':len(samples)}]
    monkeypatch.setitem(sys.modules,'faster_whisper.vad',SimpleNamespace(
        get_speech_timestamps=detect,VadOptions=lambda **kwargs:kwargs))
    assert detect_speech(path)==[[0,181]] and len(calls)==4
