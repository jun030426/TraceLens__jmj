from video_extraction._layout import source_path
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import wave

import numpy as np
from PIL import Image,ImageDraw

from video_extraction.shared.common import digest_file, read, save
from video_extraction.shared.gemini import Blocked
from video_extraction.shared.media import probe, run_ffmpeg, prepare_audio
from video_extraction.shared.multimodal_checks import inspect_frame, inspect_timeline, inspect_audio, audio_windows, scan_video
from video_extraction.shared.multimodal_validation import prepare, freeze_check, execute, render, cut_audio


class FakeClient:
    def __init__(self,interrupt=False,bad=False):self.calls=[];self.interrupt=interrupt;self.bad=bad
    def call(self,stage,media,prompt,schema):
        self.calls.append(stage)
        if stage=='multimodal_source_compare':
            if self.interrupt:raise Blocked('request_budget_exhausted')
            return {'decision':'accept','source_clear':True,'all_changes_visible':True,
                    'same_region':True,'source_conflict':False,'reason':'fixture','cross_modal_conflicts':['fixture conflict']}
        if stage=='multimodal_audio_read':
            return {'text':'독립 판독 후보','readable':True,'uncertainties':[],'source_conflicts':[]}
        return {'blocks':[{'id':'b','kind':'text','bbox':[800,0,100,900] if self.bad else [0,0,1000,1000],
                           'text':'candidate','uncertainties':[]}], 'visuals':[],'readable':True,'notes':[]}


class Diagnostics(unittest.TestCase):
    def test_text_image_signals_do_not_mutate_extraction(self):
        with tempfile.TemporaryDirectory() as d:
            image=Path(d)/'i.png';Image.new('RGB',(100,100),'white').save(image)
            b={'id':'b','kind':'code','bbox':[10,10,90,90],'text':'x = student[o]','uncertainties':['unclear']}
            result={'final_blocks':[b,{**b,'id':'b2'},{**b,'id':'bad','bbox':[80,0,20,80]},
                                     {**b,'id':'empty','text':''}],'visuals':[],'holds':[{'reason':'manual_hold'}]}
            original=copy.deepcopy(result)
            rows,metrics=inspect_frame(image,result,[200,100]);reasons={x['reason'] for x in rows}
            self.assertTrue({'unexpected_resolution','nearly_uniform_frame','invalid_bbox','empty_block',
                             'possible_duplicate_overlap','zero_o_requires_source_comparison','existing_hold'}<=reasons)
            self.assertEqual(result,original)

    def test_timeline_does_not_call_gaps_definite_omissions(self):
        rows=inspect_timeline([{'id':'a','time_seconds':4},{'id':'b','time_seconds':2}],40,20)
        self.assertTrue({'uncovered_start','non_increasing_selected_time','uncovered_end'}<={x['reason'] for x in rows})
        self.assertEqual(next(r for r in rows if r['reason']=='non_increasing_selected_time')['category'],'error')
        self.assertEqual(next(r for r in rows if r['reason']=='uncovered_end')['category'],'warning')

    def test_audio_silence_clipping_missing_and_timing(self):
        windows=[{'start':0,'end':.5,'rms_dbfs':-100,'clipped_fraction':0},
                 {'start':.5,'end':1,'rms_dbfs':-100,'clipped_fraction':0},
                 {'start':1,'end':1.5,'rms_dbfs':-10,'clipped_fraction':.1},
                 {'start':1.5,'end':2,'rms_dbfs':-10,'clipped_fraction':0}]
        segments=[{'id':'s','start_seconds':0,'end_seconds':1,'text':'무음인데 전사 10', 'words':[]},
                  {'id':'bad','start_seconds':5,'end_seconds':4,'text':'잘못된 시간','words':[]}]
        findings,by=inspect_audio(segments,windows,0,2)
        self.assertIn('text_over_near_silence',[x['reason'] for x in by['s']])
        self.assertIn('invalid_segment_time',[x['reason'] for x in by['bad']])
        self.assertEqual(findings[0]['reason'],'audible_without_transcript')

    def test_pcm_metrics_and_audio_offset(self):
        with tempfile.TemporaryDirectory() as d:
            raw=Path(d)/'raw.wav';clip=Path(d)/'clip.wav'
            with wave.open(str(raw),'wb') as w:
                w.setparams((1,2,16000,0,'NONE','not compressed'))
                w.writeframes(np.concatenate([np.zeros(16000),np.ones(16000)*32767]).astype('<i2').tobytes())
            windows,duration=audio_windows(raw)
            self.assertEqual(duration,2);self.assertEqual(windows[0]['rms_dbfs'],-200)
            self.assertEqual(windows[-1]['clipped_fraction'],1)
            self.assertEqual(cut_audio(raw,2,3,1,clip),[2,3])
            with wave.open(str(clip)) as w:self.assertEqual(w.getnframes(),16000)


class Workflow(unittest.TestCase):
    def fixture(self,root):
        job=root/'job';job.mkdir();source=root/'source.mp4'
        run_ffmpeg(['-loglevel','error','-f','lavfi','-i','color=c=white:s=160x90:r=10:d=3',
                    '-f','lavfi','-i','color=c=black:s=160x90:r=10:d=3',
                    '-f','lavfi','-i','sine=frequency=400:sample_rate=16000:duration=6',
                    '-filter_complex','[0:v][1:v]concat=n=2:v=1:a=0[v]',
                    '-map','[v]','-map','2:a','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac',source])
        metadata=probe(source);prepare_audio(source,job)
        (job/'frames').mkdir();Image.new('RGB',(160,90),'white').save(job/'frames/f.png')
        save(job/'frames.json',[{'id':'f','path':'frames/f.png','time_seconds':0}])
        save(job/'asr.json',{'segments':[{'id':'s','start_seconds':0,'end_seconds':1,'text':'원래 말 1','words':[]} ]})
        save(job/'state.json',{'source_path':str(source),'source_sha256':digest_file(source),
                              'config':{'max_frame_gap':20,'gemini_model':'fixture'}})
        return job

    def test_end_to_end_prepare_run_report_without_network(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);job=self.fixture(root);out=root/'review';out.mkdir()
            originals={p:digest_file(p) for p in job.rglob('*') if p.is_file()}
            with patch('video_extraction.shared.multimodal_validation.Gemini',side_effect=AssertionError('API forbidden')):
                plan=prepare(job,out,[],1,2,1,2)
                summary=render(out,plan,read(out/'state.json'))
                self.assertEqual(summary['api_completed'],0)
                self.assertFalse((out/'api-cache').exists())
                self.assertEqual(prepare(job,out,[],1,2,1,2),plan)
            self.assertTrue(any(t['kind']=='video' for t in plan['tasks']))
            for task in plan['tasks']:
                client=FakeClient();r=execute(task,out,plan,client)
                self.assertFalse(r['applied']);self.assertFalse(r['approved'])
                self.assertEqual(r['status'],'needs_source_review')
                self.assertEqual(len(client.calls),2)
                self.assertEqual(execute(task,out,plan,None),r)
            summary=render(out,plan,{'state':'completed_with_review'})
            self.assertEqual(summary['api_completed'],len(plan['tasks']))
            self.assertIsNone(summary['accuracy'])
            self.assertTrue(all(digest_file(p)==h for p,h in originals.items()))
            (out/plan['tasks'][0]['media'][0]).write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'evidence_changed'):freeze_check(out)

    def test_interruption_invalid_bbox_and_existing_holds_never_approve(self):
        with tempfile.TemporaryDirectory() as d:
            out=Path(d);image=out/'image.png';Image.new('RGB',(100,100),'white').save(image)
            task={'id':'screen-x','kind':'screen','media':['image.png'],'baseline':{'holds':[{'reason':'original'}]},
                  'findings':[{'reason':'original'}],'cross_modal_context':[]}
            plan={'metadata':{'width':100,'height':100}}
            with self.assertRaises(Blocked):execute(task,out,plan,FakeClient(interrupt=True))
            self.assertFalse((out/'receipts/screen-x.json').exists())
            with self.assertRaises(ValueError):execute(task,out,plan,FakeClient(bad=True))
            self.assertFalse((out/'receipts/screen-x.json').exists())
            result=execute(task,out,plan,FakeClient())
            self.assertFalse(result['approved']);self.assertEqual(task['baseline']['holds'],[{'reason':'original'}])

    def test_output_cannot_overwrite_sources(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)
            with self.assertRaisesRegex(ValueError,'output_must_be_separate'):prepare(p,p,[])


if __name__=='__main__':unittest.main()
