import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from video_extraction.ink.context.ink_context import detect_change, align_speech, select_tasks, validate_context, execute, run
from video_extraction.shared.common import save, read, signature
from video_extraction.shared.gemini import Blocked


def slide(seed=1):
    rng=np.random.default_rng(seed);im=np.full((360,640,3),255,np.uint8)
    for y in range(35,290,30):
        for x in range(110,500,30):
            value=int(rng.integers(10,160));cv2.rectangle(im,(x,y),(x+int(rng.integers(5,20)),y+7),(value,)*3,-1)
    return im


class InkContextTests(unittest.TestCase):
    def test_added_colored_mark_is_localized_and_existing_color_cancels(self):
        before=slide();cv2.line(before,(170,100),(300,100),(210,0,0),3)
        current=before.copy();cv2.line(current,(180,200),(330,200),(210,0,0),3)
        result=detect_change(before,current,current)
        self.assertEqual(result['status'],'same_slide_candidate')
        self.assertEqual(len(result['regions']),1)
        r=result['regions'][0]
        self.assertLess(r['bbox_pixels'][1],200);self.assertGreater(r['bbox_pixels'][3],200)
        self.assertEqual(r['shape_hint'],'horizontal_mark_candidate')
        self.assertFalse(r['transient_or_cursor_risk'])

    def test_erased_ink_is_not_transcribed_as_new_ink(self):
        before=slide();cv2.line(before,(180,200),(330,200),(210,0,0),3)
        r=detect_change(before,slide(),slide())
        self.assertEqual(r['regions'],[])
        self.assertGreater(r['erased_color_pixels'],100)

    def test_different_slide_is_not_ink_and_shift_is_registered(self):
        a=slide();b=slide(24)
        r=detect_change(a,b,b)
        self.assertNotEqual(r['status'],'same_slide_candidate')
        shifted=cv2.warpAffine(a,np.float32([[1,0,3],[0,1,2]]),(640,360),borderValue=(255,255,255))
        self.assertEqual(detect_change(a,shifted,shifted)['regions'],[])

    def test_transient_mark_remains_but_is_not_selected_by_default(self):
        a=slide();b=a.copy();cv2.line(b,(180,200),(240,200),(210,0,0),3)
        regions=detect_change(a,b,a)['regions']
        self.assertTrue(regions[0]['transient_or_cursor_risk'])
        t={**regions[0],'id':'a','frame_id':'f','priority_score':8,'time_seconds':1}
        self.assertEqual(select_tasks([t],12),[])

    def test_speech_overlap_and_batch_cap_preserve_inputs(self):
        speech=[{'start_seconds':0,'end_seconds':3},{'start_seconds':3,'end_seconds':6}]
        self.assertEqual(align_speech(speech,3,5),[speech[1]])
        tasks=[{'id':str(i),'frame_id':str(i//3),'priority_score':10-i,'time_seconds':i,
                'transient_or_cursor_risk':False} for i in range(8)]
        before=copy.deepcopy(tasks)
        self.assertEqual(len(select_tasks(tasks,4)),4)
        self.assertEqual(tasks,before)
        self.assertEqual(select_tasks(tasks,0),[])

    def test_invalid_speech_evidence_and_invented_targets_rejected(self):
        task={'anchor_candidates':[{'id':'b1'}],'audio_interval':[10,20]}
        c={'importance':'high','speech_relevance':'aligned','speech_quote':'중요',
           'speech_start_seconds':11,'speech_end_seconds':12,'relation':'emphasis',
           'from_target_id':'','to_target_id':'b1','visual_relation_evidence':'underline',
           'context_word_candidates':[],'reason':'spoken and marked','conflicts':[]}
        validate_context(c,task)
        with self.assertRaises(ValueError):validate_context({**c,'to_target_id':'invented'},task)
        with self.assertRaises(ValueError):validate_context({**c,'speech_end_seconds':30},task)
        with self.assertRaises(ValueError):validate_context({**c,'visual_relation_evidence':''},task)

    def test_audio_hints_cannot_replace_visual_text_and_first_pass_is_blind(self):
        class Fake:
            def __init__(self):self.calls=[]
            def call(self,stage,images,prompt,schema):
                self.calls.append((images,prompt))
                if len(self.calls)==1:
                    return {'literal_text':'[ILLEGIBLE]','readable':False,'mark_type':'handwriting',
                            'visible_description':'unclear word','uncertainties':['0/o']}
                return {'importance':'high','speech_relevance':'uncertain','speech_quote':'',
                    'speech_start_seconds':10,'speech_end_seconds':10,'relation':'uncertain',
                    'from_target_id':'','to_target_id':'','visual_relation_evidence':'',
                    'context_word_candidates':['튜플'],'reason':'speech hint only','conflicts':['unclear visual']}
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);task={'id':'x','bbox':[1,1,20,20],'onset_interval_seconds':[8,12],
                'audio_interval':[10,20],'before_image':'a.png','current_image':'b.png','after_image':'c.png',
                'crop':'crop.png','audio':'clip.wav','asr_context':[{'text':'SECRET_ASR'}],
                'human_feedback':[],'anchor_candidates':[]}
            client=Fake();result=execute(task,root,{},client)
            self.assertNotIn('SECRET_ASR',client.calls[0][1])
            self.assertTrue(all(p.suffix!='.wav' for p in client.calls[0][0]))
            self.assertEqual(client.calls[1][0][-1].suffix,'.wav')
            self.assertEqual(result['visual_observation']['literal_text'],'[ILLEGIBLE]')
            self.assertEqual(result['audio_context_candidate']['context_word_candidates'],['튜플'])
            self.assertFalse(result['applied']);self.assertFalse(result['approved'])

    def test_resume_completed_results_does_not_create_api_client(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);plan={'model':'fake','tasks':[{'id':'done','selected':True}]}
            save(root/'results/done.json',{'plan_signature':signature(plan)})
            with patch('video_extraction.ink.context.ink_context.frozen_plan',return_value=plan), \
                 patch('video_extraction.ink.context.ink_context.report',return_value={}), \
                 patch('video_extraction.ink.context.ink_context.Gemini',side_effect=AssertionError('API forbidden')):
                run(root,root/'unused.env')
            self.assertEqual(read(root/'run-state.json')['api_stats']['requests'],0)

    def test_budget_stop_leaves_unfinished_region_pending(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);plan={'model':'fake','tasks':[{'id':'todo','selected':True}]}
            class Fake:
                stats={'requests':1}
            with patch('video_extraction.ink.context.ink_context.frozen_plan',return_value=plan), \
                 patch('video_extraction.ink.context.ink_context.report',return_value={}), \
                 patch('video_extraction.ink.context.ink_context.Gemini',return_value=Fake()), \
                 patch('video_extraction.ink.context.ink_context.execute',side_effect=Blocked('request_budget_exhausted')):
                with self.assertRaises(Blocked):run(root,root/'unused.env')
            self.assertFalse((root/'results/todo.json').exists())
            self.assertTrue((root/'run-state.json').exists())

    def test_invalid_grounding_is_recorded_and_other_tasks_continue(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);plan={'model':'fake','tasks':[{'id':x,'selected':True} for x in ['bad','good']]}
            class Fake:
                stats={'requests':4}
            good={'plan_signature':signature(plan),'approved':False,'applied':False}
            with patch('video_extraction.ink.context.ink_context.frozen_plan',return_value=plan), \
                 patch('video_extraction.ink.context.ink_context.report',return_value={}), \
                 patch('video_extraction.ink.context.ink_context.Gemini',return_value=Fake()), \
                 patch('video_extraction.ink.context.ink_context.execute',side_effect=[ValueError('invented_anchor_id'),good]):
                run(root,root/'unused.env')
            self.assertEqual(read(root/'results/bad.json')['status'],'rejected_requires_review')
            self.assertEqual(read(root/'results/good.json'),good)


if __name__=='__main__':unittest.main()
