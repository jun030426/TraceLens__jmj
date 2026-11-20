"""Empty model blocks must be verified or held, never dropped or auto-approved."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from PIL import Image

from video_extraction.shared.common import read
from video_extraction.video.vision import process_frame, validate_blocks
from video_extraction.video.vision_optimized import process_frame_optimized, reuse_blocks


class EmptyClient:
    model='empty-block-fixture'

    def __init__(self, text='', decision='accept', readable=True):
        self.initial={'readable':True,'notes':[],'blocks':[
            {'id':'blank','kind':'annotation','bbox':[0,0,400,1000],
             'text':text,'uncertainties':[]},
            {'id':'keep','kind':'text','bbox':[500,0,1000,1000],
             'text':'Keep this text.','uncertainties':[]}]}
        self.decision=decision;self.readable=readable;self.stages=[]

    def call(self, stage, images, prompt, schema):
        self.stages.append(stage)
        if stage=='extract':return copy.deepcopy(self.initial)
        if stage=='audit':return {'regions':[],'complete_scan':True,'notes':[]}
        reading={'text':'Visible label','readable':self.readable,
                 'uncertainties':[] if self.readable else ['blur'],'source_conflicts':[]}
        verification={'decision':self.decision,'source_clear':True,'all_changes_visible':True,
                      'same_region':True,'source_conflict':False,'reason':'fixture'}
        if stage.startswith('crop_read'):return reading
        if stage=='verify':return verification
        if stage.startswith('optimized_read'):
            rows=json.loads(prompt.split('IMAGE MAP:\n')[1])
            return {'items':[{'region_id':r['region_id'],'reading':reading} for r in rows]}
        if stage=='optimized_verify':
            rows=json.loads(prompt[prompt.index('{"regions"'):])['regions']
            return {'items':[{'region_id':r['region_id'],'verification':verification} for r in rows]}
        raise AssertionError(stage)


class EmptyExtraction(unittest.TestCase):
    pipelines=(process_frame,process_frame_optimized)

    def run_case(self, pipeline, client, max_regions=6):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);Image.new('RGB',(200,100),'white').save(p/'frame.png')
            f={'id':'f','time_seconds':0,'path':'frame.png'}
            result=pipeline(f,[f],[],p,client,max_regions=max_regions)
            self.assertEqual(read(p/'vision/f/original.json'),client.initial)
            self.assertEqual(result['original'],client.initial)
            self.assertEqual(result['final_blocks'][1],client.initial['blocks'][1])
            # A completed result, including its holds, can be resumed without calls.
            stages=list(client.stages)
            self.assertEqual(pipeline(f,[f],[],p,client,max_regions=max_regions),result)
            self.assertEqual(client.stages,stages)
            return result

    def test_empty_and_whitespace_blocks_repaired_only_after_verification(self):
        for pipeline in self.pipelines:
            for text in ('',' \n\t'):
                with self.subTest(pipeline=pipeline.__name__,text=text):
                    c=EmptyClient(text=text);r=self.run_case(pipeline,c)
                    self.assertEqual(r['final_blocks'][0]['text'],'Visible label')
                    self.assertEqual(r['status'],'auto_repaired')
                    self.assertEqual(r['changed_blocks'],1)

    def test_unchanged_hold_unreadable_and_region_budget_preserve_empty_region(self):
        for pipeline in self.pipelines:
            for decision,readable,budget in [('unchanged',True,6),('hold',True,6),
                                             ('accept',False,6),('accept',True,0)]:
                with self.subTest(pipeline=pipeline.__name__,decision=decision,readable=readable,budget=budget):
                    c=EmptyClient(decision=decision,readable=readable)
                    r=self.run_case(pipeline,c,budget)
                    self.assertEqual(r['final_blocks'],c.initial['blocks'])
                    self.assertEqual(r['status'],'needs_review')
                    self.assertEqual(r['changed_blocks'],0)
                    self.assertIn({'target_id':'blank','reason':'empty_extraction_block'},r['holds'])

    def test_structural_errors_still_rejected(self):
        data=EmptyClient().initial
        with self.assertRaisesRegex(ValueError,'empty_extraction_block'):
            validate_blocks(data,(200,100))
        validate_blocks(data,(200,100),allow_empty_text=True)
        for error in ('duplicate','bbox'):
            bad=copy.deepcopy(data)
            if error=='duplicate':bad['blocks'][1]['id']='blank'
            else:bad['blocks'][0]['bbox']=[400,0,0,1000]
            with self.assertRaises(ValueError):
                validate_blocks(bad,(200,100),allow_empty_text=True)

    def test_empty_region_never_reuses_prior_verification(self):
        import numpy as np
        data=EmptyClient().initial
        prior={'frame_id':'old','final_blocks':data['blocks'],
               'corrections':[{'action':'unchanged','target_id':'blank'}],'holds':[]}
        pixels=np.full((100,200,3),255,dtype=np.uint8)
        self.assertEqual(reuse_blocks(data,{'regions':[],'complete_scan':True},prior,pixels,pixels),[])


if __name__=='__main__':unittest.main()
