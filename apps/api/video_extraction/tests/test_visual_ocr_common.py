"""Whole-image OCR through the actual common dispatch; no network/models in unit tests."""
import copy
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from video_extraction.pipeline import visual_ocr as o, connected as c
from video_extraction.shared.common import read,save,signature,digest_file
from video_extraction.tests.test_correction_gate import block,result


class WholeImageOCRTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.image=self.root/'page.png'
        Image.new('RGB',(200,100),'white').save(self.image)
        models=self.root/'models'
        for name in ('PP-OCRv5_mobile_det','korean_PP-OCRv5_mobile_rec'):
            path=models/name;path.mkdir(parents=True)
            for f in ('inference.yml','inference.json','inference.pdiparams'):(path/f).write_text('fixture')
        self.t={'id':'source:visual:0','unit_key':'page','image':str(self.image),'source_id':'source',
                'source_file':str(self.image),'source_kind':'image','modality':'visual','time_seconds':0,'dimensions':[200,100],'location':{'page':1}}
        self.p={'ocr_models':str(models),'ocr_python':'configured-python','ocr_policy':'selective_auxiliary_v1','ocr_available':True,
                'source_plan':{'gemini_model':'fake','config':{'region_budget':10}},'seeds':{},'_output':str(self.root),
                'tasks':[{'id':self.t['id'],'kind':'visual','unit':self.t}]}
        self.words=[{'text':'객체','score':.99,'bbox_pixels':[30,15,100,50]}]
        save(self.root/'native-inventory.json',{'records':[],'pending':[]})

    def worker(self,args,**kw):
        rows=read(args[args.index('--manifest')+1]);folder=Path(args[args.index('--output')+1]).parent
        for r in rows:
            unit={**self.t,'image':r['path']}
            save(folder/(r['id']+'.json'),{**r,'state':'candidate','words':self.words,
                 'model_hashes':o.identity(unit,self.p)['model_hashes']})
        return subprocess.CompletedProcess(args,0)

    def prepare(self):
        with patch.object(o.subprocess,'run',side_effect=self.worker):o.prepare(self.root,self.p)
        return o.load(self.t,self.p,self.root)

    def seed(self,text='객체'):
        v=result(block(text,'text'),block(text,'text'))
        v.update(signature='fixture',image_sha256=digest_file(self.image),audit={})
        path=self.root/'seed.json';save(path,v);self.p['seeds'][self.t['id']]=str(path)
        return v

    def test_shared_cache_and_resume_dont_repeat_inference(self):
        self.p['tasks'].append({'id':'same-bytes','kind':'visual','unit':{**self.t,'id':'same-bytes'}})
        with patch.object(o.subprocess,'run',side_effect=self.worker) as worker:
            first=o.prepare(self.root,self.p);again=o.prepare(self.root,self.p)
        self.assertEqual(worker.call_count,1);self.assertEqual(first['unique_images'],1)
        self.assertEqual(again['cached_units'],2)

    def test_malformed_boxes_fail_before_model_review(self):
        self.words[0]['bbox_pixels']=[100,0,30,20]
        with self.assertRaisesRegex(ValueError,'geometry'):self.prepare()

    def test_cache_tampering_is_rejected(self):
        receipt=self.prepare();path=self.root/'page-ocr'/(signature(receipt['identity'])+'.json')
        receipt['words'][0]['text']='개체';save(path,receipt)
        with self.assertRaisesRegex(ValueError,'evidence_changed'):o.load(self.t,self.p,self.root)

    def test_normal_cases_all_visual_modalities_and_replay(self):
        self.prepare();self.seed()
        for kind in ('ppt','pdf','image','video','ink'):
            # Ink's coarse wrapper invokes its specialist independently; exercise
            # full page OCR before that existing engine rather than bypassing it.
            t={**self.t,'source_kind':kind};folder=self.root/'work'/signature(t['id'])[:24]
            with patch.object(c.ink_workflow,'run',return_value=([],[])),patch.object(o.subprocess,'run',side_effect=self.worker):
                got=c.visual(t,self.p,folder,None,[])
            self.assertEqual(got['records'][0]['observed_text'],'객체')
            self.assertTrue(got['records'][0]['eligible_for_chunking'])
            self.assertIn('selective_auxiliary_ocr',got['executed'])
            c.revalidate_result(self.root,self.p,{'kind':'visual','id':t['id'],'unit':t},got)
            wrong=copy.deepcopy(got);wrong['records'][0]['auxiliary_ocr']['receipt']='bad'
            with self.assertRaisesRegex(ValueError,'selection_changed'):
                c.revalidate_result(self.root,self.p,{'kind':'visual','id':t['id'],'unit':t},wrong)

    def fake(self,decision):
        class Reviewer:
            def call(self,name,media,prompt,schema):
                assert name=='whole-image-ocr-discrepancy-v1'
                issues=json.loads(prompt.split('DATA:\n')[1])['issues']
                return {'checks':[{'id':i['id'],'decision':decision,'source_clear':True,
                    'candidate_complete':decision=='ocr_wrong','reason':'fixture source inspection'} for i in issues]}
        return Reviewer()

    def test_wrong_ocr_never_overwrites_correct_code(self):
        self.words[0]['text']='string';self.prepare();self.seed('String')
        with patch.object(o.subprocess,'run',side_effect=self.worker):
            got=c.visual(self.t,self.p,self.root/'work'/signature(self.t['id'])[:24],self.fake('ocr_wrong'),[])
        self.assertEqual(got['records'][0]['observed_text'],'String')
        self.assertTrue(got['records'][0]['eligible_for_chunking']);self.assertFalse(got['changes'])

    def test_real_discrepancy_holds_only_target_without_editing(self):
        self.words[0]['text']='객체';self.prepare();self.seed('개체')
        with patch.object(o.subprocess,'run',side_effect=self.worker):
            got=c.visual(self.t,self.p,self.root/'work'/signature(self.t['id'])[:24],self.fake('correction_needed'),[])
        row=got['records'][0]
        self.assertEqual(row['observed_text'],'개체');self.assertFalse(row['eligible_for_chunking'])
        self.assertTrue(any(r['kind']=='coverage_issue' for r in got['records']))

    def test_existing_hold_cannot_be_released_by_ocr(self):
        receipt=self.prepare();v=self.seed();rows=[{'id':self.t['id']+':b','observed_text':'객체','eligible_for_chunking':False,'reasons':['prior_hold']}]
        review=o.review(self.t,v,receipt,self.root,None,'fake')
        got=o.apply(self.t,v,rows,receipt,review,'fake')
        self.assertFalse(got[0]['eligible_for_chunking']);self.assertEqual(got[0]['reasons'],['prior_hold'])

    def test_incomplete_or_duplicate_reviews_cannot_publish(self):
        receipt=self.prepare();v=self.seed('개체')
        checked=o.review(self.t,v,receipt,self.root,self.fake('ocr_wrong'),'fake')
        for checks in ([],checked['answer']['checks']*2):
            bad=copy.deepcopy(checked);bad['answer']['checks']=checks
            with self.assertRaisesRegex(ValueError,'mapping_invalid'):
                o.apply(self.t,v,[],receipt,bad,'fake')

    def test_changed_source_requires_new_ocr(self):
        self.prepare();Image.new('RGB',(200,100),'blue').save(self.image)
        with self.assertRaisesRegex(ValueError,'ocr_pending'):o.load(self.t,self.p,self.root)

    def test_native_text_skips_ocr_and_image_text_is_cropped(self):
        v=self.seed();t={**self.t,'source_kind':'pdf','native_text':'객체',
            'pdf_inventory':{'words':[{'text':'객체','bbox':[150,150,500,500],'valid_box':True}]}}
        self.assertEqual(o.select_regions(t,v),[])
        v['final_blocks'].append({**v['final_blocks'][0],'id':'screenshot','bbox':[500,100,900,900]})
        # Native token center does not cover the second region.
        self.assertEqual([r['id'] for r in o.select_regions(t,v)],['screenshot'])
        with patch.object(o.subprocess,'run',side_effect=OSError('missing')) as worker:
            got=o.collect(t,v,self.p,self.root/'selected')
        self.assertEqual(worker.call_count,1);self.assertEqual(got['state'],'unavailable')
        crop=next((self.root/'selected/auxiliary-ocr-crops').glob('*.png'))
        with Image.open(crop) as im:self.assertEqual(im.size,(80,80))

    def test_no_ocr_detection_does_not_hold_normal_multiplication_output(self):
        self.words=[];self.seed('7 * 1 = 7\n7 * 2 = 14\n7 * 9 = 63')
        with patch.object(o.subprocess,'run',side_effect=self.worker):
            got=c.visual(self.t,self.p,self.root/'empty',None,[])
        self.assertTrue(got['records'][0]['eligible_for_chunking'])
        self.assertEqual(got['local_checks']['auxiliary_ocr']['state'],'no_detection')
        self.assertEqual(got['changes'],[])

    def test_unconfirmed_ocr_difference_is_diagnostic_not_new_hold(self):
        self.words[0]['text']='string';self.seed('String')
        with patch.object(o.subprocess,'run',side_effect=self.worker):
            got=c.visual(self.t,self.p,self.root/'unclear',self.fake('unclear'),[])
        self.assertTrue(got['records'][0]['eligible_for_chunking'])
        self.assertTrue(got['records'][0]['auxiliary_ocr']['diagnostics'])
        self.assertEqual(len(got['records']),1)

    def test_optional_worker_failure_preserves_prior_verdict(self):
        self.seed()
        with patch.object(o.subprocess,'run',side_effect=OSError('missing')):
            got=c.visual(self.t,self.p,self.root/'failed',None,[])
        self.assertTrue(got['records'][0]['eligible_for_chunking'])
        self.assertEqual(got['records'][0]['auxiliary_ocr']['state'],'unavailable')

    def test_local_only_does_not_run_whole_page_ocr_or_api(self):
        with patch.object(c,'verify',return_value=self.p),patch.object(c,'done',return_value={}),\
             patch.object(c,'check_ocr_runtime'),patch.object(c.runtime_tools,'audit',return_value={'checks':[]}),\
             patch.object(c,'publish',return_value={'pending':1,'all_tasks_processed':False}),\
             patch.object(o,'prepare') as worker,patch.object(c,'Gemini') as api:
            c.run(self.root,self.root/'missing.env',local_only=True)
        api.assert_not_called();worker.assert_not_called()


if __name__=='__main__':unittest.main()
