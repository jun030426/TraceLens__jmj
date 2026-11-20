"""Regression tests through the actual common processing/selection entry point.

Includes retained source-bound failures, not just isolated guard unit tests.
No test may instantiate an external API client.
"""
import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from video_extraction._layout import PROJECT_ROOT
from video_extraction.pipeline import runner as m, visual_gate
from video_extraction.shared.common import read, save, signature, digest_file
from video_extraction.tests.test_correction_gate import block, result
from video_extraction.tests.test_audio_primary_scope import scoped


class MandatoryGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.out=Path(self.tmp.name);self.image=self.out/'source.png'
        Image.new('RGB',(300,200),'white').save(self.image)
        self.t={'id':'new-source:visual:1','unit_key':'u','source_id':'new-source',
                'source_file':str(self.image),'source_kind':'pdf','modality':'visual',
                'image':str(self.image),'time_seconds':0,'dimensions':[300,200],'location':{'page':1}}
        self.p={'config':{'region_budget':20}}
        self.addCleanup(patch.stopall)
        patch('video_extraction.shared.gemini.Gemini.call',side_effect=AssertionError('API forbidden')).start()

    def candidate(self,b,a):
        v=result(b,a);v.update(signature='fixture',image_sha256=digest_file(self.image),audit={})
        return v

    def process(self,v,kind='pdf'):
        t={**self.t,'source_kind':kind}
        with patch.object(m.visual,'process_frame_layers',return_value=copy.deepcopy(v)):
            return t,m.process_visual(self.out,self.p,t,None,[])

    def test_prior_failure_rules_apply_to_every_image_input_type(self):
        cases=[(block('a[0]'),block('a[o]'),'zero_or_o_unresolved'),
            (block('| A | B |\n| | X |','table'),block('| A | B |\n| X | |','table'),'table_structure_change_unverified'),
            (block('    f(x)\n    g()'),block('f(x)\ng()'),'code_nesting_change_unverified'),
            (block('----------'),block('-------------'),'separator_requires_pixel_evidence'),
            (block('도시','text',[100,200,180,240]),block('ok','text',[100,100,900,900]),'geometry_change_requires_source_evidence')]
        for kind in ['ppt','pdf','image','video','ink']:
            for before,after,reason in cases:
                with self.subTest(kind=kind,reason=reason):
                    _,r=self.process(self.candidate(before,after),kind)
                    row=r['records'][0]
                    self.assertFalse(row['eligible_for_chunking'])
                    self.assertEqual(row['observed_text'],before['text'])
                    self.assertIn(reason,row['safety_findings']);self.assertFalse(r['changes'])

    def test_normal_controls_are_not_held_or_rewritten(self):
        for b in [block('x = 0'),block('| A | B |\n| | X |','table'),block('객체','text')]:
            _,r=self.process(self.candidate(b,copy.deepcopy(b)))
            self.assertTrue(r['records'][0]['eligible_for_chunking']);self.assertEqual(r['changes'],[])

    def test_supported_content_change_at_same_target_survives(self):
        _,r=self.process(self.candidate(block('VR TOUR','text'),block('MR TOUR','text')))
        self.assertEqual(r['records'][0]['observed_text'],'MR TOUR');self.assertTrue(r['records'][0]['eligible_for_chunking'])

    def test_valid_range_axis_swap_is_not_assumed_valid_identity(self):
        b=block('도시','text',[100,400,180,450]);v=self.candidate(b,block('ok','text',b['bbox']))
        v['audit']={'text_regions':[{'target_id':'b','bbox':[400,100,450,180]}]}
        _,r=self.process(v)
        self.assertFalse(r['records'][0]['eligible_for_chunking'])
        self.assertEqual(r['records'][0]['observed_text'],'도시')

    def test_repair_created_duplicate_restores_both_targets(self):
        a=block('title','text',[10,10,200,80]);a['id']='a'
        b=block('label','text',[600,600,800,800]);b['id']='b'
        v=self.candidate(a,a);v['original']['blocks'].append(b)
        v['corrections']=[{'action':'merge_identical_overlap','target_id':'a','removed_id':'b'}]
        _,r=self.process(v)
        rows=[x for x in r['records'] if x['kind']!='coverage_issue']
        self.assertEqual({x['observed_text'] for x in rows},{'title','label'})
        self.assertFalse(any(x['eligible_for_chunking'] for x in rows))

    def test_missing_gate_and_rehashed_bad_selection_both_rejected(self):
        b=block('a[0]');v=self.candidate(b,block('a[o]'));t,r=self.process(v)
        r.update(plan_signature=signature(self.p),unit_id=t['id'])
        r['visual_result_sha256']=digest_file(r['evidence']['visual_result'])
        r['result_payload_sha256']=signature(r)
        m.validate_result(self.out,self.p,t,r)
        r['records'][0]['eligible_for_chunking']=True
        r.pop('result_payload_sha256');r['result_payload_sha256']=signature(r)
        with self.assertRaisesRegex(ValueError,'visual_selection'):
            m.validate_result(self.out,self.p,t,r)
        guarded=read(r['evidence']['visual_result']);guarded.pop('common_gate')
        with self.assertRaisesRegex(ValueError,'common_visual_gate'):visual_gate.records(t,guarded,m.base_record)

    def test_agreeing_models_cannot_delete_actual_repetition(self):
        t={'id':'t','target_id':'t','before':'반복 반복','after':'반복','role':'repair',
           'neighbors':[],'interval':[0,5],'target_clip_meta':{'duration_seconds':5}}
        b,r=scoped(t,text='반복',literal='반복')
        self.assertIn('original_content_removed',m.audio_gate(t,b,r)['reasons'])

    def test_current_real_pdf_regressions_through_common_entrypoint(self):
        root=PROJECT_ROOT/'outputs/common-pipeline-new-source-v1'
        p=read(root/'plan.json')
        for page in (32,41):
            t=next(t for t in p['units'] if t['source_kind']=='pdf' and t['location'].get('page')==page)
            old=read(root/'results'/(t['unit_key']+'.json'));v=read(old['evidence']['visual_result'])
            with patch.object(m.visual,'process_frame_layers',return_value=v):
                # No additional impact requests in an offline regression run.
                class NoClassification:
                    def call(self,stage,images,prompt,schema):
                        import json
                        data=json.loads(prompt.split('DATA:\n')[1])
                        return {'record_id':data['record_id'],'impact':'unknown','same_region':False,
                            'source_clear':False,'uncertain':True,'core_instruction_preserved_without_region':False,
                            'no_unique_concept_or_step':False,'no_number_negation_condition_or_code_change':False,
                            'reason':'Offline replay: no new impact assessment'}
                r=m.process_visual(self.out,p,t,NoClassification(),[])
            rows={x['id'].rsplit(':',1)[-1]:x for x in r['records']}
            if page==32:
                for iid,text in [('b8','도시'),('b9','행정'),('b10','메타버스')]:
                    self.assertEqual(rows[iid]['observed_text'],text)
                    self.assertFalse(rows[iid]['eligible_for_chunking'])
            else:
                original=v['original']['blocks'][0]
                self.assertEqual(rows['b1']['bbox'],original['bbox'])
                self.assertFalse(rows['b1']['eligible_for_chunking'])


if __name__=='__main__':unittest.main()
