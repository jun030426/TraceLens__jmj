import copy
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
from PIL import Image

from video_extraction.shared.common import validate
from video_extraction.video.vision_optimized import READ_BATCH, compare_pixels, process_frame_optimized, reuse_blocks, unpack_batch, verified_ids


def block(text='x + 1', bid='b', box=None):
    return {'id':bid,'kind':'code','bbox':box or [100,100,800,800],
            'text':text,'uncertainties':[]}


def prior_result(b=None):
    b=b or block()
    return {'frame_id':'old','final_blocks':[b],
            'corrections':[{'action':'unchanged','target_id':b['id']}],'holds':[]}


class PixelGates(unittest.TestCase):
    def setUp(self):
        self.a=np.full((100,200,3),255,dtype=np.uint8)
        self.current={'blocks':[block()]}
        self.audit={'regions':[],'complete_scan':True,'notes':[]}
        self.prior=prior_result()

    def reuse(self,b,**kw):
        return reuse_blocks(kw.get('current',self.current),kw.get('audit',self.audit),
                            kw.get('prior',self.prior),self.a,b)

    def test_verified_unchanged_region_can_reuse(self):
        b=self.a.copy();b[20,40]=250
        self.assertEqual(len(self.reuse(b)),1)

    def test_one_pixel_operator_change_blocks_reuse(self):
        b=self.a.copy();b[20,40]=0
        self.assertTrue(compare_pixels(self.a,b)['same_scene'])
        self.assertFalse(self.reuse(b))

    def test_new_handwriting_blocks_reuse(self):
        b=self.a.copy();b[40:43,40:70]=[255,0,0]
        self.assertFalse(self.reuse(b))

    def test_spatial_audit_omission_overrides_stable_pixels(self):
        audit={**self.audit,'regions':[{'target_id':'NEW','bbox':[795,400,900,500]}]}
        self.assertFalse(self.reuse(self.a.copy(),audit=audit))

    def test_incomplete_audit_never_reuses(self):
        self.assertFalse(self.reuse(self.a.copy(),audit={**self.audit,'complete_scan':False}))

    def test_text_change_and_indentation_change_not_reused(self):
        for text in ('x * 1','    x + 1'):
            self.assertFalse(self.reuse(self.a.copy(),current={'blocks':[block(text)]}))

    def test_unverified_or_unresolved_block_never_reused(self):
        p=copy.deepcopy(self.prior);p['corrections']=[]
        self.assertFalse(self.reuse(self.a.copy(),prior=p))
        p=copy.deepcopy(self.prior);p['holds']=[{'region':{'target_id':'b'}}]
        self.assertFalse(verified_ids(p));self.assertFalse(self.reuse(self.a.copy(),prior=p))

    def test_different_image_dimensions_not_same_scene(self):
        self.assertFalse(compare_pixels(self.a,self.a[:50])['same_scene'])


class BatchClient:
    model='test-only'
    def __init__(self,bad_mapping=False,uncertain=False,hold=False):
        self.stages=[];self.bad_mapping=bad_mapping;self.uncertain=uncertain;self.hold=hold
    def call(self,stage,images,prompt,schema):
        self.stages.append(stage)
        if stage=='extract':
            return {'blocks':[block('x * 1',f'b{i}',[i*300,100,i*300+250,800]) for i in range(3)],
                    'readable':True,'notes':[]}
        if stage=='audit':return {'regions':[],'complete_scan':True,'notes':[]}
        if stage.startswith('optimized_read'):
            mapping=json.loads(prompt.split('IMAGE MAP:\n')[1])
            rows=[{'region_id':m['region_id'],'reading':{'text':'x + 1','readable':not self.uncertain,
                   'uncertainties':['blur'] if self.uncertain else [],'source_conflicts':[]}} for m in mapping]
            if self.bad_mapping:rows[0]['region_id']='not-requested'
        else:
            data=json.loads(prompt[prompt.index('{"regions"'):])
            rows=[{'region_id':r['region_id'],'verification':{'decision':'hold' if self.hold else 'accept',
                   'source_clear':not self.hold,'same_region':True,'all_changes_visible':True,
                   'source_conflict':False,'reason':'synthetic fixture'}} for r in data['regions']]
        result={'items':list(reversed(rows))};validate(result,schema);return result


class BatchGates(unittest.TestCase):
    def run_frame(self,p,client):
        Image.new('RGB',(300,100),'white').save(p/'frame.png')
        f={'id':'f','time_seconds':0,'path':'frame.png'}
        return process_frame_optimized(f,[f],[],p,client),f

    def test_region_order_is_resolved_by_id_not_response_position(self):
        value={'items':[{'region_id':'b','reading':2},{'region_id':'a','reading':1}]}
        self.assertEqual(unpack_batch(value,['a','b'],'reading'),{'a':1,'b':2})

    def test_missing_duplicate_and_extra_ids_rejected(self):
        for ids in (['a'],['a','a'],['a','b','c']):
            with self.assertRaises(ValueError):
                unpack_batch({'items':[{'region_id':i,'reading':{}} for i in ids]},['a','b'],'reading')

    def test_schema_keeps_boolean_types_strict(self):
        bad={'items':[{'region_id':'r','reading':{'text':'x','readable':'true','uncertainties':[],'source_conflicts':[]}}]}
        with self.assertRaises(ValueError):validate(bad,READ_BATCH)

    def test_three_regions_use_four_requests_and_keep_three_results(self):
        with tempfile.TemporaryDirectory() as d:
            c=BatchClient();r,_=self.run_frame(Path(d),c)
            self.assertEqual(c.stages,['extract','audit','optimized_read','optimized_verify'])
            self.assertEqual(len(r['final_blocks']),3);self.assertEqual(r['changed_blocks'],3)
            self.assertTrue(all(b['text']=='x + 1' for b in r['final_blocks']))

    def test_bad_mapping_preserves_original_and_holds_all(self):
        with tempfile.TemporaryDirectory() as d:
            r,_=self.run_frame(Path(d),BatchClient(bad_mapping=True))
            self.assertTrue(all(b['text']=='x * 1' for b in r['final_blocks']))
            self.assertEqual(len(r['holds']),3);self.assertEqual(r['changed_blocks'],0)

    def test_blur_and_verifier_hold_do_not_change_source(self):
        for c in (BatchClient(uncertain=True),BatchClient(hold=True)):
            with tempfile.TemporaryDirectory() as d:
                r,_=self.run_frame(Path(d),c)
                self.assertEqual(r['status'],'needs_review');self.assertEqual(r['changed_blocks'],0)
                self.assertTrue(all(b['text']=='x * 1' for b in r['final_blocks']))

    def test_exact_frame_retains_holds_and_timeline_without_new_calls(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);c=BatchClient(hold=True);r,f=self.run_frame(p,c)
            Image.open(p/'frame.png').save(p/'second.png')
            f2={'id':'next','time_seconds':20,'path':'second.png'};before=len(c.stages)
            r2=process_frame_optimized(f2,[f,f2],[],p,c,prior=r,prior_image=p/'frame.png')
            self.assertEqual(len(c.stages),before);self.assertEqual(r2['frame_time_seconds'],20)
            self.assertEqual(r2['holds'],r['holds']);self.assertEqual(r2['changed_blocks'],0)

    def test_new_content_outside_old_blocks_still_gets_whole_frame_audit(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);c=BatchClient();r,f=self.run_frame(p,c)
            im=Image.open(p/'frame.png');im.putpixel((299,99),(255,0,0));im.save(p/'second.png')
            f2={'id':'next','time_seconds':20,'path':'second.png'};before=len(c.stages)
            process_frame_optimized(f2,[f,f2],[],p,c,prior=r,prior_image=p/'frame.png')
            self.assertEqual(c.stages[before:before+2],['extract','audit'])


if __name__=='__main__':unittest.main()
