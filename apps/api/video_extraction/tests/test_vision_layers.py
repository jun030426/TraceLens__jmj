import copy
import json
from pathlib import Path
import tempfile
import unittest
from PIL import Image

from video_extraction.shared.common import read, validate
from video_extraction.video.vision_layers import EXTRACT, deduplicate_text, plan_regions, process_frame_layers, validate_extraction, visual_problems


def block(bid='b1',text='객체(Object)',box=None,kind='text'):
    return {'id':bid,'kind':kind,'bbox':box or [100,100,800,800],'text':text,'uncertainties':[]}


def visual(vid='v1'):
    return {'id':vid,'kind':'diagram','bbox':[100,100,800,800],
            'description':'파란 자동차 그림','literal_text':'','related_block_ids':['b1'],'uncertainties':[]}


def region(tid='b1',box=None,reason='check cell'):
    return {'target_id':tid,'bbox':box or [100,100,800,800],'reason':reason,'issue':'omission'}


class Fixture:
    model='fixture'
    def __init__(self,decision='accept',new_annotation=False,uncertain=False,bad_mapping=False):
        self.stages=[];self.decision=decision;self.new_annotation=new_annotation
        self.uncertain=uncertain;self.bad_mapping=bad_mapping
        self.initial={'blocks':[block(kind='table')],'visuals':[visual()],'readable':True,'notes':[]}
    def call(self,stage,images,prompt,schema):
        self.stages.append(stage)
        if stage=='layers_extract':return copy.deepcopy(self.initial)
        if stage=='layers_audit':
            return {'text_regions':[region(reason='label missing'),region(box=[200,200,900,900],reason='other cell')],
                    'visual_regions':[region('NEW',reason='red circle')] if self.new_annotation else [],'complete_scan':True,'notes':[]}
        data=json.loads(prompt.split('DATA:\n')[1]);rows=[]
        for row in data['regions']:
            if stage.endswith('verify'):
                value={'decision':self.decision,'source_clear':True,'all_changes_visible':True,
                       'same_region':True,'source_conflict':False,'reason':'fixture'};field='verification'
            else:
                value={'readable':not self.uncertain,'uncertainties':['unclear'] if self.uncertain else [],'source_conflicts':[]}
                if data['layer']=='text':value.update(text='딕셔너리(Dictionary)',kind='table')
                else:value.update(description='본문을 둘러싼 붉은 원' if row['target_id']=='NEW' else '파란 자동차 그림',
                                  literal_text='',related_block_ids=['b1'],kind='annotation' if row['target_id']=='NEW' else 'diagram')
                field='reading'
            rows.append({'region_id':row['region_id'],'__field':field,'value':value})
        result={'items':[{'region_id':r['region_id'],r['__field']:r['value']} for r in reversed(rows)]}
        if self.bad_mapping:result['items'][0]['region_id']='wrong'
        validate(result,schema);return result


class LayerTests(unittest.TestCase):
    def run_frame(self,client,**kw):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);Image.new('RGB',(300,200),'white').save(p/'f.png')
            f={'id':'f','path':'f.png','time_seconds':0}
            r=process_frame_layers(f,[f],[],p,client,**kw)
            self.assertEqual(read(p/'vision/f/original.json'),client.initial)
            before=list(client.stages)
            self.assertEqual(process_frame_layers(f,[f],[],p,client,**kw),r)
            self.assertEqual(client.stages,before)
            return r

    def test_textless_car_is_preserved_without_empty_text_hold(self):
        r=self.run_frame(Fixture())
        self.assertEqual(r['visuals'][0]['literal_text'],'')
        self.assertEqual(r['visuals'][0]['description'],'파란 자동차 그림')
        self.assertFalse(r['holds']);self.assertNotIn('자동차',r['text'])

    def test_overlaid_annotation_survives_separate_from_same_bbox_text(self):
        r=self.run_frame(Fixture(new_annotation=True))
        self.assertEqual(len(r['visuals']),2);self.assertEqual(len(r['final_blocks']),1)
        self.assertEqual(r['text'],'딕셔너리(Dictionary)');self.assertFalse(r['holds'])

    def test_repeated_target_reviews_all_issues_once(self):
        c=Fixture();r=self.run_frame(c)
        self.assertEqual(c.stages.count('layers_text_read'),1)
        self.assertEqual(r['final_blocks'][0]['bbox'],[100,100,900,900])
        plan,_,_=plan_regions([block()], [region(),region(box=[200,0,900,800])],'text',1)
        self.assertEqual(len(plan),1);self.assertEqual(len(plan[0]['issues']),2)

    def test_separate_budget_retains_every_unreviewed_visual(self):
        r=self.run_frame(Fixture(),max_visual_regions=0)
        self.assertEqual(r['text'],'딕셔너리(Dictionary)')
        self.assertEqual(len(r['deferred_regions']),1)
        self.assertEqual(r['deferred_regions'][0]['target_id'],'v1')
        self.assertEqual(r['status'],'needs_review')

    def test_failed_mapping_or_unclear_or_hold_never_applies_guess(self):
        for c in [Fixture(uncertain=True),Fixture(decision='hold'),Fixture(bad_mapping=True)]:
            with self.subTest(c=c):
                r=self.run_frame(c);self.assertEqual(r['final_blocks'],c.initial['blocks'])
                self.assertEqual(r['status'],'needs_review')

    def test_empty_original_text_unchanged_cannot_pass(self):
        c=Fixture(decision='unchanged');c.initial['blocks'][0]['text']=''
        r=self.run_frame(c);self.assertEqual(r['status'],'needs_review')
        self.assertTrue(any(h['reason']=='unchanged_but_unresolved' for h in r['holds']))

    def test_exact_overlapping_duplicate_merges_and_preserves_uncertainty(self):
        a=block();b=block('b2');b['uncertainties']=['blur']
        kept,log,aliases=deduplicate_text([a,b])
        self.assertEqual(len(kept),1);self.assertEqual(kept[0]['uncertainties'],['blur'])
        self.assertEqual(aliases,{'b2':'b1'});self.assertEqual(len(log),1)
        other=block('other',box=[850,850,1000,1000])
        self.assertEqual(len(deduplicate_text([a,other])[0]),2)

    def test_alias_target_and_visual_reference_are_remapped(self):
        c=Fixture();c.initial['blocks'].append(block('copy',kind='table'))
        c.initial['visuals'][0]['related_block_ids']=['copy']
        r=self.run_frame(c);self.assertEqual(r['visuals'][0]['related_block_ids'],['b1'])
        plan,_,_=plan_regions([block()],[region('copy')],'text',1,{'copy':'b1'})
        self.assertEqual(plan[0]['target_id'],'b1')

    def test_schema_and_references_do_not_let_printed_text_become_visual_text(self):
        v=visual();v['literal_text']='객체(Object)'
        self.assertIn('printed_text_in_visual_literal',visual_problems(v,[block()]))
        v['related_block_ids']=['unknown']
        self.assertIn('unknown_visual_text_reference',visual_problems(v,[block()]))
        data=Fixture().initial;data['visuals'][0]['id']='b1'
        with self.assertRaises(ValueError):validate_extraction(data,(300,200))

    def test_unknown_and_bad_bbox_do_not_consume_valid_target_budget(self):
        planned,deferred,holds=plan_regions([block(kind='code')],[region('missing'),region(box=[5,0,0,1])],'text',1)
        self.assertEqual(planned[0]['target_id'],'b1');self.assertFalse(deferred);self.assertEqual(len(holds),2)


if __name__=='__main__':unittest.main()
