import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PIL import Image

from video_extraction.shared.common import save, read, signature
from video_extraction.shared.gemini import Blocked
from video_extraction.ink.recognition.ink_evidence import similarity, prepare_views, pixel_evidence
from video_extraction.ink.runner.ink_pipeline import inspect_visual, merge_repair, transform_visual, concept_index, concept_key, execute, prepare, run, check_plan, code_hashes, transform_ocr


def visual():
    return {'items':[{'id':'m','kind':'circle','box':{'left':100,'top':100,'right':900,'bottom':900},
        'text':'','uncertainties':[],'cancelled':False,'arrow_points':[]}],
        'links':[],'complete':True,'notes':[]}


def fixture(folder,name='case'):
    rgb=np.full((100,200,3),255,np.uint8);rgb[20:80,50:150]=[200,20,20]
    frame=folder/'frame.png';Image.fromarray(rgb).save(frame)
    audio=folder/'audio.wav';audio.write_bytes(b'fake-audio-for-mocked-client')
    task={'id':name,'source_sha256':'sha','bbox':[100,100,900,900],
          'current_image':str(frame),'before_image':str(frame),'after_image':str(frame),
          'audio_path':str(audio),'audio_interval':[10,20],'asr_context':[{'text':'SECRET_AUDIO_HINT'}]}
    task['evidence']=prepare_views(task,folder/name)
    return task


class Fake:
    def __init__(self,stop=None,missing=False):self.calls=[];self.stats={'requests':0};self.stop=stop;self.missing=missing
    def call(self,name,media,prompt,schema):
        self.calls.append((name,media,prompt));self.stats['requests']+=1
        if self.stop and name.endswith(self.stop):raise Blocked('request_budget_exhausted')
        if name.endswith('audio_focus'):
            return {'importance':'high','events':[{'quote':'중요','start_seconds':11,'end_seconds':12,'role':'emphasis'}], 'keywords':['집합'],'notes':[]}
        if name.endswith('audio_links'):
            return {'bindings':[],'concepts':[{'label':'집합','item_ids':['m'],'evidence':'spoken set'}], 'word_candidates':[],'notes':[]}
        if name.endswith('audit') and not name.endswith('repair_audit'):
            return {'checks':[{'id':'m','status':'supported','reason':'visible'}],
                    'missing':[{'description':'extra','box':visual()['items'][0]['box']}] if self.missing else [],'complete':True}
        return visual()


class InkPipelineTests(unittest.TestCase):
    def test_new_or_erased_ink_blocks_frame_substitution(self):
        a=np.full((100,100,3),255,np.uint8);b=a.copy();b[20:50,20:60]=0
        self.assertFalse(similarity(a,b)['eligible']);self.assertFalse(similarity(b,a)['eligible'])
        self.assertTrue(similarity(b,b)['eligible'])

    def test_preprocessing_preserves_original_and_transforms(self):
        with tempfile.TemporaryDirectory() as tmp:
            t=fixture(Path(tmp));e=t['evidence']
            self.assertEqual(set(e['views']),{'original','expanded','contrast','denoise','binary'})
            self.assertEqual(e['selected_frame'],t['current_image'])
            for name,v in e['views'].items():
                self.assertTrue(Path(v['path']).exists())
                with Image.open(v['path']) as im:self.assertEqual(im.size,tuple(v['size']))
                self.assertEqual(len(v['crop_in_source']),4)
            self.assertEqual(e['views']['original']['operation'],'crop_only')

    def test_crop_expansion_preserves_source_geometry_and_endpoints(self):
        v=visual();v['items'][0]['arrow_points']=[{'x':100,'y':100},{'x':900,'y':900}]
        old={'crop_in_source':[.2,.3,.6,.8]};new={'crop_in_source':[0,0,1,1]}
        changed=transform_visual(v,old,new)
        b=changed['items'][0]['box']
        self.assertAlmostEqual(b['left'],240);self.assertAlmostEqual(b['top'],350)
        self.assertAlmostEqual(changed['items'][0]['arrow_points'][1]['y'],750)
        self.assertEqual(v['items'][0]['box']['left'],100)

    def test_ocr_transform_tracks_crop(self):
        old={'crop_in_source':[.2,.2,.4,.4],'size':[100,100]};new={'crop_in_source':[0,0,1,1],'size':[500,500]}
        got=transform_ocr({'words':[{'bbox_pixels':[0,0,100,100],'text':'x'}]},old,new)
        self.assertEqual(got['words'][0]['bbox_pixels'],[100,100,200,200])

    def test_repair_preserves_unaffected_items_and_blocks_unrequested_additions(self):
        original=visual();original['items'].append({**copy.deepcopy(original['items'][0]),'id':'healthy'})
        proposed=copy.deepcopy(original);proposed['items'][0]['box']['left']=200
        proposed['items'][1]['text']='hallucinated';proposed['items'].append({**proposed['items'][0],'id':'new'})
        got=merge_repair(original,proposed,{'m'})
        self.assertEqual(got['items'][1],original['items'][1]);self.assertEqual(len(got['items']),2)
        self.assertEqual(got['items'][0]['box']['left'],200)

    def test_failed_coordinate_does_not_remove_sibling(self):
        with tempfile.TemporaryDirectory() as tmp:
            t=fixture(Path(tmp));v=visual();bad=copy.deepcopy(v['items'][0]);bad['id']='bad';bad['box']['left']=1200;v['items'].append(bad)
            rows,flags=inspect_visual(v,t,t['evidence']['views']['original'],{'state':'unavailable'})
            self.assertEqual(len(rows),2);self.assertIn('bad',flags);self.assertNotIn('m',flags)

    def test_cancellation_and_direction_need_actual_targets_and_endpoints(self):
        with tempfile.TemporaryDirectory() as tmp:
            t=fixture(Path(tmp));v=visual();v['links']=[{'id':'r','from_ids':['m'],'to_ids':['m'],'kind':'sequence','direction':'observed','evidence':'nearby'}]
            _,flags=inspect_visual(v,t,t['evidence']['views']['original'],{'state':'unavailable'})
            self.assertIn('direction_without_endpoints',flags['r'])
            v['links'][0].update(kind='cancellation',direction='not_applicable')
            _,flags=inspect_visual(v,t,t['evidence']['views']['original'],{'state':'unavailable'})
            self.assertIn('missing_cancelled_target',flags['r'])

    def test_ocr_disagreement_never_overwrites_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            t=fixture(Path(tmp));v=visual();v['items'][0].update(kind='handwriting',text='0')
            before=copy.deepcopy(v);view=t['evidence']['views']['original'];w,h=view['size']
            _,flags=inspect_visual(v,t,view,{'state':'candidate','words':[{'text':'o','score':.9,'bbox_pixels':[w*.3,h*.3,w*.7,h*.7]}]})
            self.assertIn('ocr_disagreement_or_no_coverage',flags['m']);self.assertEqual(v,before)

    def test_visual_pass_has_no_audio_hints_and_completed_stages_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);t=fixture(root);plan={'model':'fake'};fake=Fake(stop='audio_links')
            with self.assertRaises(Blocked):execute(t,root,plan,fake)
            first=[x for x in fake.calls if x[0].endswith('visual')][0]
            self.assertNotIn('SECRET_AUDIO_HINT',first[2]);self.assertTrue(all(p.suffix!='.wav' for p in first[1]))
            second=Fake();result=execute(t,root,plan,second)
            self.assertEqual(len(second.calls),2);self.assertFalse(result['approved']);self.assertFalse(result['applied'])

    def test_post_audit_repair_never_silently_approved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);t=fixture(root);result=execute(t,root,{'model':'fake'},Fake(missing=True))
            self.assertEqual(result['status'],'held')
            self.assertFalse(result['repairs'][-1]['applied'])
            self.assertEqual(result['repairs'][-1]['status'],'requires_source_reaudit')

    def test_concept_links_are_real_record_ids_and_cancelled_refs_excluded(self):
        self.assertEqual(concept_key('리스트'),concept_key('list'))
        result={'task_id':'task','inventory':visual(),'records':[{'local_id':'m','id':'actual-record-id'}],
                'audio_record':{'id':'actual-audio-id'},'audio_context':{'concepts':[{'label':'list','item_ids':['m'],'evidence':'explicit'}]}}
        index=concept_index([result],None)
        self.assertEqual({m['record_id'] for m in index[0]['members']},{'actual-record-id','actual-audio-id'})
        result['inventory']['items'][0]['cancelled']=True
        self.assertEqual(concept_index([result],None),[])

    def test_prepared_plan_hashes_and_full_resume_without_api_client(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);t=fixture(root);source=root/'source';source.mkdir()
            t['audio']=t['audio_path'];t['priority_score']=0
            save(source/'plan.json',{'model':'fake','source_sha256':'sha','input_hashes':{},'tasks':[t]})
            out=root/'prepared'
            with patch('video_extraction.ink.runner.ink_pipeline.Gemini',side_effect=AssertionError('no API')):
                prepare(source,out,1,None)
            plan=check_plan(out);task=plan['tasks'][0]
            result=execute(task,out,plan,Fake());save(out/'results'/(task['id']+'.json'),result)
            with patch('video_extraction.ink.runner.ink_pipeline.Gemini',side_effect=AssertionError('no API')):
                self.assertEqual(run(out,root/'.env')['processed'],1)
            Path(task['evidence']['views']['original']['path']).write_bytes(b'changed')
            with self.assertRaises(ValueError):check_plan(out)

    def test_audio_first_order_and_low_priority_is_not_dropped(self):
        class PriorityFake(Fake):
            def call(self,name,media,prompt,schema):
                result=super().call(name,media,prompt,schema)
                if name.endswith('audio_focus'):result['importance']='high' if '_b_' in name else 'low'
                return result
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);a=fixture(root,'a');b=fixture(root,'b');source=root/'source';source.mkdir()
            for t in (a,b):t['audio']=t['audio_path']
            save(source/'plan.json',{'model':'fake','source_sha256':'sha','input_hashes':{},'tasks':[a,b]})
            out=root/'prepared';prepare(source,out,2,None);fake=PriorityFake()
            with patch('video_extraction.ink.runner.ink_pipeline.Gemini',return_value=fake):
                result=run(out,root/'.env')
            names=[c[0] for c in fake.calls]
            self.assertTrue(all(n.endswith('audio_focus') for n in names[:2]))
            self.assertEqual([n for n in names if n.endswith('_visual')],['ink_pipeline_b_visual','ink_pipeline_a_visual'])
            self.assertEqual(result['processed'],2)

    def test_invalid_response_does_not_stop_other_tasks(self):
        class BadFake(Fake):
            def call(self,name,media,prompt,schema):
                if '_a_' in name:raise Blocked('invalid_model_response')
                return super().call(name,media,prompt,schema)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);tasks=[fixture(root,n) for n in ('a','b')];source=root/'source';source.mkdir()
            for t in tasks:t['audio']=t['audio_path']
            save(source/'plan.json',{'model':'fake','source_sha256':'sha','input_hashes':{},'tasks':tasks})
            out=root/'prepared';prepare(source,out,2,None)
            with patch('video_extraction.ink.runner.ink_pipeline.Gemini',return_value=BadFake()):
                result=run(out,root/'.env')
            self.assertEqual(result['processed'],2)
            self.assertEqual(read(out/'results/a.json')['status'],'held')
            self.assertEqual(read(out/'results/b.json')['status'],'model_checked_candidate')


if __name__=='__main__':unittest.main()
