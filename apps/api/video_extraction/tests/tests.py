"""Offline safety/contract tests plus an actual FFmpeg/PyAV integration fixture."""
from video_extraction._layout import source_path
import copy
import io
import json
import socket
from pathlib import Path
import tempfile
import unittest
import urllib.error
import types
import wave
from unittest.mock import patch

from video_extraction.shared.common import atomic_patches, bbox_pixels, overlap, read, save, validate
from video_extraction.shared.gemini import Blocked, EXTRACT, Gemini, response_text, provider_schema
from video_extraction.shared.media import prepare_audio, probe, run_ffmpeg, select_frames, transcribe
from video_extraction.shared.output import align, export
from video_extraction.video.vision import process_frame
from video_extraction.audio.audio_review import review_segment
from video_extraction.shared.diagnose import diagnose
from video_extraction.shared.errors import http_failure


class Contracts(unittest.TestCase):
    def test_schema_rejects_bool_coordinates(self):
        value={'blocks':[{'id':'b','kind':'code','bbox':[False,0,999,999],'text':'x+1','uncertainties':[]}],
               'readable':True,'notes':[]}
        with self.assertRaises(ValueError):validate(value,EXTRACT)

    def test_schema_rejects_unknown_keys_and_missing(self):
        for value in ({'blocks':[],'readable':True,'notes':[],'unexpected':1},{'blocks':[]}):
            with self.assertRaises(ValueError):validate(value,EXTRACT)

    def test_bbox_clamp_and_invalid_order(self):
        self.assertEqual(bbox_pixels([0,0,1000,1000],(1920,1080)),(0,0,1920,1080))
        with self.assertRaises(ValueError):bbox_pixels([500,0,400,100],(1920,1080))

    def test_overlap_excludes_touching_boundary(self):
        self.assertEqual(overlap(0,10,10,12),0)
        self.assertEqual(overlap(5,12,8,20),4)

    def test_conflicting_edits_all_held(self):
        result,accepted,held=atomic_patches('abcdef',[{'before':'abc','after':'X'},{'before':'bcd','after':'Y'}])
        self.assertEqual(result,'abcdef');self.assertFalse(accepted);self.assertEqual(len(held),2)

    def test_repeated_anchor_cannot_be_changed(self):
        result,accepted,held=atomic_patches('x+x',[{'before':'x','after':'y'}])
        self.assertEqual(result,'x+x');self.assertFalse(accepted);self.assertTrue(held)

    def test_complete_response_required(self):
        with self.assertRaises(ValueError):response_text({'status':'in_progress','output_text':'{}'})
        self.assertEqual(response_text({'status':'completed','output_text':'{}'}),'{}')

    def test_api_cache_and_budget(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'key.env').write_text('GEMINI_API_KEY=test-not-real')
            calls=[]
            def transport(req,timeout):
                body=json.loads(req.data);calls.append(body)
                return io.BytesIO(json.dumps({'status':'completed','output_text':json.dumps({'blocks':[],'readable':True,'notes':[]})}).encode())
            client=Gemini(p/'cache','test-model',p/'key.env',max_calls=1,delay=0,transport=transport)
            a=client.call('test',[],'one',EXTRACT);b=client.call('test',[],'one',EXTRACT)
            self.assertEqual(a,b);self.assertEqual(len(calls),1)
            self.assertEqual(calls[0]['response_format']['schema'],provider_schema(EXTRACT))
            self.assertNotIn('test-not-real',''.join(f.read_text() for f in (p/'cache').iterdir()))
            with self.assertRaisesRegex(Blocked,'budget'):client.call('test',[],'two',EXTRACT)

    def test_network_error_leaves_no_success_cache(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'key.env').write_text('GEMINI_API_KEY=test-not-real')
            def transport(*a,**k):raise urllib.error.URLError('sensitive diagnostics should not escape')
            c=Gemini(p/'cache','test',p/'key.env',delay=0,transport=transport)
            with self.assertRaisesRegex(Blocked,'^gemini_network_unavailable$'):c.call('test',[],'x',EXTRACT)
            self.assertEqual([f.name for f in (p/'cache').iterdir()],['last-error.json'])
            self.assertNotIn('sensitive diagnostics',(p/'cache/last-error.json').read_text())

    def test_http_retry_is_bounded_and_then_cached(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'key.env').write_text('GEMINI_API_KEY=test-not-real');attempts=[]
            def transport(req,timeout):
                attempts.append(1)
                if len(attempts)==1:raise urllib.error.HTTPError(req.full_url,429,'limit',{},None)
                return io.BytesIO(json.dumps({'status':'completed','output_text':json.dumps({'blocks':[],'readable':True,'notes':[]})}).encode())
            c=Gemini(p/'cache','test',p/'key.env',max_calls=2,delay=0,transport=transport,sleeper=lambda _:None)
            c.call('test',[],'x',EXTRACT)
            self.assertEqual(c.stats['requests'],2);self.assertEqual(c.stats['successes'],1)

    def test_incomplete_response_is_never_cached_as_success(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'key.env').write_text('GEMINI_API_KEY=test-not-real')
            c=Gemini(p/'cache','test',p/'key.env',max_calls=3,delay=0,sleeper=lambda _:None,
               transport=lambda *a,**k:io.BytesIO(b'{"status":"in_progress","output_text":"{}"}'))
            with self.assertRaisesRegex(Blocked,'invalid_model_response'):c.call('test',[],'x',EXTRACT)
            self.assertEqual(c.stats['successes'],0)
            self.assertTrue(all('.invalid-' in f.name for f in (p/'cache').iterdir()))

    def test_dns_failure_is_specific_and_not_retried(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'key.env').write_text('GEMINI_API_KEY=test-not-real')
            def transport(*a,**k):raise urllib.error.URLError(socket.gaierror(8,'name unavailable'))
            c=Gemini(p/'cache','test',p/'key.env',transport=transport,delay=0)
            with self.assertRaisesRegex(Blocked,'^gemini_dns_failed$'):c.call('test',[],'x',EXTRACT)
            self.assertEqual(c.stats['requests'],1)
            self.assertEqual(read(p/'cache/last-error.json')['detail']['exception_type'],'gaierror')

    def test_api_error_redacts_key(self):
        payload=json.dumps({'error':{'code':'authentication','message':'API key test-secret is invalid'}}).encode()
        exc=urllib.error.HTTPError('https://example.test',401,'auth',{},io.BytesIO(payload))
        reason,info=http_failure(exc,'test-secret')
        self.assertEqual(reason,'gemini_authentication_failed')
        self.assertNotIn('test-secret',json.dumps(info))
        self.assertIn('[REDACTED]',info['api_message'])

    def test_daily_quota_does_not_retry(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'key.env').write_text('GEMINI_API_KEY=test-not-real');waits=[]
            def transport(req,timeout):
                raise urllib.error.HTTPError(req.full_url,429,'limit',{},
                    io.BytesIO(b'{"error":{"code":"quota_exceeded","message":"Daily quota reached"}}'))
            c=Gemini(p/'cache','test',p/'key.env',transport=transport,delay=0,sleeper=waits.append)
            with self.assertRaisesRegex(Blocked,'daily_quota'):c.call('test',[],'x',EXTRACT)
            self.assertEqual(c.stats['requests'],1);self.assertFalse(waits)

    def test_preflight_is_fresh_on_each_run(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'key.env').write_text('GEMINI_API_KEY=test-not-real');calls=[]
            def transport(*a,**k):
                calls.append(1)
                return io.BytesIO(b'{"status":"completed","output_text":"{\\"ok\\":true}"}')
            reports=[diagnose(p/'key.env','test',transport) for _ in range(2)]
            self.assertEqual(len(calls),2)
            self.assertTrue(all(r['state']=='ready' for r in reports))
            self.assertNotIn('test-not-real',json.dumps(reports))

    def test_compact_provider_schema_keeps_full_local_bounds(self):
        wire=provider_schema(EXTRACT)
        self.assertNotIn('maxLength',json.dumps(wire))
        self.assertNotIn('maxItems',json.dumps(wire))
        self.assertEqual(wire['required'],EXTRACT['required'])
        bad={'blocks':[{'id':'b','kind':'code','bbox':[0,0,1000],
                       'text':'x+1','uncertainties':[]}],'readable':True,'notes':[]}
        validate(bad,wire)
        with self.assertRaises(ValueError):validate(bad,EXTRACT)
        self.assertEqual(EXTRACT['properties']['blocks']['maxItems'],100)

    def test_vision_preflight_really_sends_image_and_extraction_schema(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'key.env').write_text('GEMINI_API_KEY=test-not-real');requests=[]
            def transport(req,timeout):
                body=json.loads(req.data);requests.append(body)
                result={'ok':True} if len(requests)==1 else {
                    'blocks':[{'id':'b','kind':'code','bbox':[0,0,1000,1000],'text':'x + 1','uncertainties':[]}],
                    'readable':True,'notes':[]}
                return io.BytesIO(json.dumps({'status':'completed','output_text':json.dumps(result)}).encode())
            report=diagnose(p/'key.env','test',transport,check_vision=True,sleeper=lambda _:None)
            self.assertEqual(report['state'],'ready');self.assertEqual(len(requests),2)
            self.assertTrue(report['checks']['image_input'])
            self.assertEqual(requests[1]['input'][0]['type'],'text')
            self.assertEqual(requests[1]['input'][1]['mime_type'],'image/png')
            self.assertEqual(requests[1]['response_format']['schema'],provider_schema(EXTRACT))

    def test_vision_preflight_never_reports_ready_for_text_only_success(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'key.env').write_text('GEMINI_API_KEY=test-not-real');calls=[]
            def transport(req,timeout):
                calls.append(1)
                if len(calls)==2:
                    raise urllib.error.HTTPError(req.full_url,400,'invalid',{},
                        io.BytesIO(b'{"error":{"code":"invalid_request","message":"bad schema"}}'))
                return io.BytesIO(b'{"status":"completed","output_text":"{\\"ok\\":true}"}')
            report=diagnose(p/'key.env','test',transport,check_vision=True,sleeper=lambda _:None)
            self.assertEqual(report['state'],'blocked');self.assertEqual(len(calls),3)
            self.assertTrue(report['checks']['image_input_basic'])
            self.assertNotIn('extraction_schema',report['checks'])

    def test_alignment_keeps_both_speech_references(self):
        frames=[{'id':'f1','time_seconds':0,'path':'a.png'},{'id':'f2','time_seconds':5,'path':'b.png'}]
        speech=[{'id':'s','start_seconds':4,'end_seconds':6,'text':'hello','review_reasons':[]}]
        rows=align(frames,speech,10,{})
        self.assertEqual([r['speech_segment_ids'] for r in rows],[['s'],['s']])
        self.assertTrue(all(not r['screen_eligible'] for r in rows))

    def test_unreviewed_content_excluded_from_export(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)
            state={'source_sha256':'a'*64,'source_path':'a.mp4','state':'blocked','metadata':{'duration_seconds':10}}
            speech=[{'id':'s','start_seconds':0,'end_seconds':2,'text':'uncertain','review_reasons':['low_asr_logprob']}]
            export(p,state,[{'id':'f','time_seconds':0,'path':'f.png'}],speech,{})
            self.assertEqual((p/'rag_candidates.jsonl').read_text(),'')
            self.assertEqual(len(read(p/'review_queue.json')),2)


class FakeVision:
    model='fixture-model'
    def __init__(self,hold=False,uncertain=False):self.hold=hold;self.uncertain=uncertain;self.stages=[]
    def call(self,stage,images,prompt,schema):
        self.stages.append(stage)
        if stage=='extract':
            return {'readable':True,'notes':[],'blocks':[{'id':'b1','kind':'code','bbox':[0,0,1000,1000],
                    'text':'x * 1','uncertainties':[]}]}
        if stage=='audit':return {'regions':[],'complete_scan':True,'notes':[]}
        if stage.startswith('crop_read'):
            return {'text':'x + 1','readable':not self.uncertain,'uncertainties':['blur'] if self.uncertain else [],'source_conflicts':[]}
        return {'decision':'hold' if self.hold else 'accept','source_clear':not self.hold,
                'all_changes_visible':True,'same_region':True,'source_conflict':False,'reason':'fixture'}


class RepairGates(unittest.TestCase):
    def sample(self,p):
        from PIL import Image
        Image.new('RGB',(300,100),'white').save(p/'frame.png')
        return {'id':'f','time_seconds':0,'path':'frame.png'}

    def test_critical_block_checked_even_if_auditor_misses_it(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);f=self.sample(p);c=FakeVision()
            r=process_frame(f,[f],[],p,c)
            self.assertIn('crop_read',c.stages)
            self.assertEqual(r['text'],'x + 1');self.assertEqual(r['original']['blocks'][0]['text'],'x * 1')
            self.assertEqual(r['status'],'auto_repaired')

    def test_verifier_hold_never_replaces_text(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);f=self.sample(p)
            r=process_frame(f,[f],[],p,FakeVision(hold=True))
            self.assertEqual(r['text'],'x * 1');self.assertEqual(r['status'],'needs_review')

    def test_enhancement_disagreement_stays_held(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);f=self.sample(p);c=FakeVision(uncertain=True)
            r=process_frame(f,[f],[],p,c)
            self.assertEqual(r['status'],'needs_review');self.assertNotIn('verify',c.stages)
            self.assertIn('crop_read_enhanced',c.stages)

    def test_audio_correction_preserves_original_word_alignment(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);audio=p/'original.wav'
            with wave.open(str(audio),'wb') as w:
                w.setparams((1,2,16000,0,'NONE','not compressed'));w.writeframes(b'\0\0'*16000)
            seg={'id':'s','start_seconds':0,'end_seconds':1,'text':'wrong','words':[{'word':'wrong'}],
                 'review_reasons':['low_asr_logprob'],'status':'needs_review'}
            class Client:
                model='test'
                def call(self,stage,*a):
                    if stage=='audio_reread':return {'text':'heard','readable':True,'uncertainties':[],'source_conflicts':[]}
                    return {'decision':'accept','source_clear':True,'all_changes_visible':True,'same_region':True,'source_conflict':False,'reason':'fixture'}
            final=review_segment(seg,audio,p,{'audio_offset_seconds':0},Client())
            self.assertEqual(final['text'],'heard');self.assertEqual(final['original_text'],'wrong')
            self.assertFalse(final['words']);self.assertEqual(final['original_words'],seg['words'])
            self.assertEqual(seg['text'],'wrong')

    def test_asr_midpoint_ownership_and_resume(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);audio=p/'original.wav';calls=[]
            with wave.open(str(audio),'wb') as w:
                w.setparams((1,2,16000,0,'NONE','not compressed'));w.writeframes(b'\0\0'*(16000*20))
            class Model:
                def __init__(self,*a,**k):pass
                def transcribe(self,data,**kwargs):
                    calls.append(1)
                    def s(start,end,text):return types.SimpleNamespace(start=start,end=end,text=text,
                       avg_logprob=-.2,no_speech_prob=0,compression_ratio=1,words=[])
                    return iter([s(0,1,'before'),s(3,5,'central'),s(11,12,'after')]),None
            cfg={'asr_model':'fixture','asr_threads':1,'offline_models':True,'asr_chunk_seconds':10,'language':'ko'}
            with patch.dict('sys.modules',{'faster_whisper':types.SimpleNamespace(WhisperModel=Model)}):
                rows=transcribe(audio,p,{'audio_offset_seconds':-.1,'duration_seconds':20},cfg)
                self.assertTrue(all(0<=s['start_seconds']<s['end_seconds']<=20 for s in rows))
                self.assertEqual(len(rows),4)
                transcribe(audio,p,{'audio_offset_seconds':-.1,'duration_seconds':20},cfg)
                self.assertEqual(len(calls),2)


class RealMedia(unittest.TestCase):
    def test_real_video_audio_frames_and_resume(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);src=p/'fixture.mp4';out=p/'out';out.mkdir()
            run_ffmpeg(['-loglevel','error','-f','lavfi','-i','color=white:s=640x360:r=10:d=2',
              '-f','lavfi','-i','color=black:s=640x360:r=10:d=2','-f','lavfi','-i','sine=frequency=440:duration=4',
              '-filter_complex','[0:v][1:v]concat=n=2:v=1:a=0[v]','-map','[v]','-map','2:a',
              '-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac','-shortest',src])
            meta=probe(src);self.assertAlmostEqual(meta['duration_seconds'],4,delta=.2)
            audio=prepare_audio(src,out,normalize=True);self.assertTrue((out/audio['asr_audio']).exists())
            rows=select_frames(src,out,meta,{'scan_fps':2,'change_fraction':.025,'min_frame_gap':1,'max_frame_gap':20})
            self.assertEqual(len(rows),2);self.assertAlmostEqual(rows[1]['time_seconds'],2,delta=.2)
            self.assertEqual(rows,select_frames(src,out,meta,{'scan_fps':2,'change_fraction':.025,'min_frame_gap':1,'max_frame_gap':20}))


if __name__=='__main__':unittest.main()
