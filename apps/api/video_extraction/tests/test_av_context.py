"""Offline routing/safety tests. Synthetic API responses are not accuracy labels."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from video_extraction.pipeline import av_context as av, audio_workflow as aw, connected
from video_extraction.video.vision import speech_context
from video_extraction.shared.common import read, signature
from video_extraction.tests.test_audio_target_window import raw_file
from video_extraction.tests.test_audio_primary_scope import scoped
from video_extraction.tests.test_audio_batch import batch_fixture
from video_extraction.tests.test_audio_coverage import finding


class AVTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.image=self.root/'frame.png'
        Image.new('RGB',(80,60),'white').save(self.image)
        self.frame={'id':'v1','unit_key':'v1','source_id':'same','source_kind':'video','modality':'visual',
                    'time_seconds':12.,'image':str(self.image)}
        self.unit={'id':'a1','unit_key':'a1','source_id':'same','source_file':'video.mp4',
                   'source_kind':'video','modality':'audio','location':{'audio_offset_seconds':10}}
        self.window={'interval':[0,10],'review_interval':[0,15]}

    def test_same_source_half_open_time_and_positive_offset(self):
        frames=[self.frame,{**self.frame,'id':'foreign','source_id':'other'},
                {**self.frame,'id':'before','time_seconds':9.},
                {**self.frame,'id':'after','time_seconds':25.}]
        b=av.frame_bundle(self.unit,frames,self.window)
        self.assertEqual([r['id'] for r in b['frames']],['v1'])
        self.assertEqual(b['frames'][0]['audio_seconds'],2.)
        self.assertFalse(b['complete_video_coverage'])

    def test_negative_offset_and_no_keyframe_carry_forward(self):
        u={**self.unit,'location':{'audio_offset_seconds':-2}}
        self.assertEqual(av.frame_bundle(u,[self.frame],self.window)['frames'][0]['audio_seconds'],14)
        self.assertEqual(av.frame_bundle(u,[self.frame],{'interval':[20,30],'review_interval':[18,30]})['frames'],[])

    def test_sampling_is_bounded_deterministic_and_omissions_visible(self):
        frames=[{**self.frame,'id':str(i),'time_seconds':10+i/2} for i in range(20)]
        b=av.frame_bundle(self.unit,frames,self.window)
        self.assertEqual(len(b['frames']),6);self.assertEqual(len(b['omitted_frame_ids']),14)
        self.assertEqual(b,av.frame_bundle(self.unit,list(reversed(frames)),self.window))

    def test_nonfinite_timestamps_rejected(self):
        for value in (float('nan'),float('inf'),True):
            with self.assertRaises(ValueError):av.frame_bundle(self.unit,[{**self.frame,'time_seconds':value}],self.window)

    def test_decode_failures_and_pending_video_check_supply_no_hint(self):
        p={'tasks':[{'id':'check','kind':'video_coverage','source':{'source_sha256':'same'}}],
           'source_plan':{'units':[self.frame]}}
        self.assertEqual(av.usable_frames(p,{},'same'),[])
        r={'check':{'records':[{'raw_payload':{'reason':'saved_frame_source_mismatch','category':'error','frame_id':'v1'}}]}}
        self.assertEqual(av.usable_frames(p,r,'same'),[])
        self.assertEqual(av.usable_frames(p,{'check':{'records':[]}},'same'),[self.frame])

    def audio_records(self):
        r={'id':'near','source_id':'same','modality':'audio','eligible_for_chunking':True,
           'start_seconds':5,'end_seconds':8,'observed_text':'설명','judgment':'previously_verified_retained'}
        return [r,{**r,'id':'far','start_seconds':30,'end_seconds':32},
                {**r,'id':'held','eligible_for_chunking':False},{**r,'id':'foreign','source_id':'other'}]

    def test_audio_to_visual_scope_before_frame_and_status_adapter(self):
        rows=self.audio_records();original=copy.deepcopy(rows)
        context,receipt=av.audio_for_frame(self.frame,rows)
        self.assertEqual(receipt['record_ids'],['near']);self.assertEqual(rows,original)
        frame={'id':'v1','time_seconds':12,'context_interval':receipt['source_interval']}
        speech=speech_context(frame,[frame],context)
        self.assertEqual(speech[0]['text'],'설명')
        self.assertEqual(speech[0]['status'],'previously_verified_retained')
        self.assertEqual(av.audio_for_frame({**self.frame,'source_kind':'pdf'},rows)[0],[])

    def test_common_visual_dispatch_receives_only_timed_verified_audio(self):
        task={**self.frame,'source_file':'video.mp4'}
        plan={'av_context_policy':av.POLICY,'source_plan':{'units':[task]},'seeds':{}}
        folder=self.root/'visual';calls=[]
        def processor(out,source_plan,t,client,context,candidate):
            calls.append((t,context))
            return {'records':[],'changes':[],'evidence':{}}
        with patch.object(connected.base,'process_visual',side_effect=processor):
            connected.visual(task,plan,folder,None,self.audio_records())
        t,context=calls[0]
        self.assertEqual(t['audio_context_interval'],[2,22])
        self.assertEqual([r['id'] for r in context],['near'])
        self.assertIn('status',context[0])
        self.assertEqual(read(folder/'audio-context-binding.json')['record_ids'],['near'])

    def setup_window(self):
        source=raw_file(self.root)
        unit={**self.unit,'source_audio':str(source),'location':{'audio_offset_seconds':0},
              'interval':[0,30],'review_interval':[0,30]}
        clip=self.root/'window.wav';meta=aw.final.clip(source,clip,0,30)
        unit.update(target_clip=str(clip),context_clip=str(clip),target_clip_meta=meta,context_clip_meta=meta)
        return unit

    def test_receipt_resume_change_detection_and_no_frame_fallback(self):
        unit=self.setup_window();payload={'existing_segments':[]}
        class Client:
            def __init__(self):self.calls=0
            def call(self,name,media,prompt,schema):
                self.calls+=1
                return {'checked_full_core':True,'speech_unresolved':False,'findings':[],**({'comparisons':[]} if len(media)>1 else {})}
        client=Client();out=self.root/'av-context'/'w.json'
        reply,r=av.inspect_window(unit,[self.frame],unit,payload,client,out,{})
        av.inspect_window(unit,[self.frame],unit,payload,client,out,{})
        self.assertEqual(client.calls,1);av.validate_receipts(self.root)
        Image.new('RGB',(80,60),'blue').save(self.image)
        with self.assertRaisesRegex(ValueError,'source_frame_changed'):av.validate_receipts(self.root)
        with self.assertRaisesRegex(ValueError,'binding_changed'):av.inspect_window(unit,[self.frame],unit,payload,client,out,{})
        _,r=av.inspect_window(unit,[],unit,payload,client,self.root/'no-frame.json',{})
        self.assertEqual(r['request']['visual_context']['state'],'no_matching_frame')

    def run_audio(self, proposed=False, hallucinated=False):
        unit=self.setup_window();calls=[]
        class ASR:
            def transcribe(self,path):
                return {'text':'이름과 점수 반복 반복' if proposed else '이름 점수 반복 반복',
                        'segments':[{'start':1.,'end':3.,'text':'이름 점수'},
                                    {'start':7.,'end':8.,'text':'반복 반복'}]}
        class Client:
            @batch_fixture
            def call(self,name,media,prompt,schema):
                calls.append((name,media,prompt))
                if 'coverage' in name:
                    return {'checked_full_core':True,'speech_unresolved':False,
                        'findings':[finding(kind='omitted_words',action='replace',target_id='same:speech:0',
                            before='이름 점수',after='이름과 점수',start=1,end=3)] if proposed else [],
                        'comparisons':[{'target_id':'same:speech:0','frame_ids':['v1'],'kind':'term_difference','reason':'synthetic hint'}]}
                data=json.loads(prompt.split('DATA:\n',1)[1]);duration=data['target_seconds'][1]
                text=('이름과 점수' if proposed and not hallucinated else '이름 점수') if duration==2 else '반복 반복'
                repair=data.get('proposed_text')=='이름과 점수'
                t={'role':'repair' if repair else 'control','before':'이름 점수' if repair else text,
                   'after':'이름과 점수' if repair else text,'target_clip_meta':{'duration_seconds':duration}}
                b,r=scoped(t,text=text,literal=text)
                if 'impact' in name:
                    return {'literal_text':text,'target_scope':r['target_scope'],'target_spans':r['target_spans'],
                            'impact':'unknown','uncertain':False,'full_target_checked':True,
                            'no_unique_concept_or_step':False,'no_number_negation_or_condition_change':False,
                            'core_instruction_preserved_without_target':False,'context_preserves_relation':False,'reason':'synthetic hold'}
                return b if 'blind' in name else r
        with patch.object(aw.core,'detect_speech',return_value=[[1,3],[7,8]]):
            got=aw.run(unit,[unit],self.root/'work',{'av_context_policy':av.POLICY},Client(),ASR(),[self.frame])
        aw.validate_saved(unit,self.root/'work',got)
        return got,calls

    def test_screen_difference_alone_does_not_change_normal_audio(self):
        got,calls=self.run_audio()
        self.assertEqual(got['changes'],[])
        self.assertEqual([r['observed_text'] for r in got['records']],['이름 점수','반복 반복'])
        self.assertTrue(all(r['eligible_for_chunking'] for r in got['records']))
        self.assertEqual(got['av_context']['comparisons'][0]['status'],'audio_supported_original_preserved')

    def test_visual_hint_restoration_still_requires_audio_only_rechecks(self):
        got,calls=self.run_audio(proposed=True)
        self.assertEqual(len(got['changes']),1)
        self.assertEqual([r['observed_text'] for r in got['records']],['이름과 점수','반복 반복'])
        coverage=next(c for c in calls if 'coverage' in c[0]);self.assertEqual(len(coverage[1]),2)
        for name,media,prompt in calls:
            if 'blind' in name or 'review' in name:
                self.assertTrue(all(Path(p).suffix=='.wav' for p in media))
                self.assertNotIn('visual_context',prompt)

    def test_screen_only_word_cannot_override_blind_audio(self):
        got,_=self.run_audio(proposed=True,hallucinated=True)
        self.assertEqual(got['changes'],[])
        self.assertEqual(next(r for r in got['records'] if r['id']=='same:speech:0')['observed_text'],'이름 점수')
        self.assertTrue(next(r for r in got['records'] if r['id']=='same:speech:1')['eligible_for_chunking'])

    def test_wrong_frame_or_neighbor_reference_is_rejected(self):
        unit=self.setup_window();unit['interval']=[0,10]
        payload={'existing_segments':[{'id':'neighbor','start_seconds':20,'end_seconds':22,'text':'설명'}]}
        class Client:
            def call(self,*args):return {'checked_full_core':True,'speech_unresolved':False,'findings':[],
                'comparisons':[{'target_id':'neighbor','frame_ids':['v1'],'kind':'unclear','reason':'test'}]}
        with self.assertRaisesRegex(ValueError,'owned_by_neighbor'):
            av.inspect_window(unit,[self.frame],unit,payload,Client(),self.root/'bad.json',{})


if __name__=='__main__':unittest.main()
