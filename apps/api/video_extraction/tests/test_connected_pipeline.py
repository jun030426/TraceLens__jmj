"""Actual specialist dispatch with synthetic responses and frozen failure evidence.

No API, model download, or claim of measured extraction accuracy.
"""
import copy
import json
import tempfile
import subprocess
import sys
import numpy as np
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image, ImageDraw
from video_extraction.pipeline import connected as m, audio_workflow as aw, ink_workflow as iw
from video_extraction.pipeline import document_workflow as dw
from video_extraction.shared.common import save, read, signature, digest_file
from video_extraction.tests.test_correction_gate import block, result
from video_extraction.tests.test_ink_pipeline import visual
from video_extraction.tests.test_ink_policy import audit
from video_extraction.tests.test_audio_primary_scope import scoped
from video_extraction.tests.test_audio_batch import batch_fixture
from video_extraction.tests.test_audio_selective_application import setup
from video_extraction.tests.test_audio_target_window import raw_file
from video_extraction.tests.test_audio_coverage import finding
from video_extraction.shared.gemini import Blocked
from video_extraction._layout import PROJECT_ROOT


class FakeInk:
    def __init__(self, text=None):self.calls=[];self.text=text
    def call(self, name, media, prompt, schema):
        self.calls.append(name)
        data=json.loads(prompt.split('DATA:\n',1)[1])
        if name.endswith('visual'):
            v=visual()
            if self.text:v['items'][0].update(kind='handwriting',text=self.text)
            return v
        return audit(data['candidate'],set(data['required_ids'])) if 'required_ids' in data else data['candidate']


class ConnectedTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.image=self.root/'image.png'
        im=Image.new('RGB',(300,200),'white');ImageDraw.Draw(im).rectangle((30,30,250,180),outline='red',width=3);im.save(self.image)
        self.t={'id':'new:visual:1','unit_key':'frame','source_id':'new','source_file':str(self.image),
                'source_kind':'pdf','modality':'visual','image':str(self.image),'time_seconds':0,
                'dimensions':[300,200],'location':{'page':1}}
        save(self.root/'native-inventory.json',{'records':[],'pending':[]})
        self.p={'source_plan':{'config':{'region_budget':20},'gemini_model':'fake'},'seeds':{},
                '_output':str(self.root),'ocr_models':None,'ocr_python':None}
        self.addCleanup(patch.stopall)
        patch('video_extraction.shared.gemini.Gemini.call',side_effect=AssertionError('API forbidden')).start()

    def test_ocr_venv_symlink_path_survives_prepare_and_resume(self):
        python=self.root/'ocr-env/bin/python';python.parent.mkdir(parents=True);python.symlink_to(sys.executable)
        output=self.root/'with-ocr'
        with patch.object(m,'model_hashes',return_value={}),patch.object(m,'check_ocr_runtime') as probe,patch.object(m.runtime_tools,'audit',return_value={'checks':[]}):
            plan=m.prepare(output,[self.image],model='fake',ocr_models=self.root/'models',ocr_python=python)
            self.assertEqual(plan['ocr_python'],str(python.absolute()))
            self.assertNotEqual(plan['ocr_python'],str(python.resolve()))
            self.assertEqual(m.prepare(output,ocr_python=python),plan)
            probe.assert_not_called()

    def test_missing_optional_ocr_does_not_block_local_common_run(self):
        with patch.object(m.subprocess,'run',return_value=subprocess.CompletedProcess([],1,'','')):
            with self.assertRaisesRegex(ValueError,'PaddleOCR'):
                m.check_ocr_runtime(sys.executable)
        output=self.root/'preflight';m.prepare(output,[self.image],model='fake')
        plan=read(output/'plan.json');plan['ocr_models']='configured';plan['ocr_python']='broken-python'
        with patch.object(m,'verify',return_value=plan),patch.object(m,'done',return_value={}),patch.object(m,'check_ocr_runtime',side_effect=ValueError('missing OCR')),patch.object(m,'Gemini') as api:
            m.run(output,self.root/'unused.env',local_only=True)
            api.assert_not_called()

    def seed(self,b,a,annotation=False):
        r=result(b,a);r.update(signature='synthetic',image_sha256=digest_file(self.image),audit={})
        if annotation:
            r['original']['visuals']=[{'id':'ink','kind':'annotation','bbox':[100,100,900,900],
                                      'description':'mark','literal_text':'','uncertainties':[],'related_block_ids':[],'labels':[]}]
            r['visuals']=copy.deepcopy(r['original']['visuals'])
        f=self.root/'candidate.json';save(f,r);self.p['seeds'][self.t['id']]=str(f)
        return r

    def test_every_visual_route_keeps_existing_error_gates(self):
        for kind in ('ppt','pdf','image','video','ink'):
            for before,after in ((block('x[0]'),block('x[o]')),
                    (block('도시','text',[100,200,180,240]),block('ok','text',[100,100,900,900])),
                    (block('------'),block('---------'))):
                with self.subTest(kind=kind,before=before):
                    self.seed(before,after)
                    # The explicit ink route still invokes its real engine below.
                    got=m.visual({**self.t,'source_kind':kind},self.p,self.root/'work',FakeInk(),[])
                    target=next(r for r in got['records'] if r['id']==self.t['id']+':b')
                    self.assertFalse(target['eligible_for_chunking']);self.assertEqual(target['observed_text'],before['text'])

    def test_normal_visual_not_rewritten_or_held_by_common_dispatch(self):
        self.seed(block('객체','text'),block('객체','text'))
        got=m.visual(self.t,self.p,self.root/'work',None,[])
        self.assertTrue(got['records'][0]['eligible_for_chunking']);self.assertFalse(got['changes'])
        self.assertIn('frame_checks',got['executed'])

    def test_pdf_structure_review_is_mandatory_and_replayed(self):
        self.seed(block('객체','text'),block('객체','text'))
        self.t['pdf_inventory']={'route':'scan_or_graphics_render','words':[]}
        class PDFAPI:
            def call(self,name,media,prompt,schema):
                assert name=='pdf-source-structure-v1'
                return {'complete':True,'reading_order':['b'],'checks':[{'id':'b','source_supported':True,
                    'structure_supported':True,'order_clear':True,'reason':'source'}],
                    'relations':[],'missing':[],'cross_page_uncertain':[]}
        task={'id':self.t['id'],'kind':'visual','unit':self.t}
        folder=self.root/'work'/signature(task['id'])[:24]
        got=m.visual(self.t,self.p,folder,PDFAPI(),[])
        self.assertTrue(got['records'][0]['eligible_for_chunking'])
        self.assertTrue(got['records'][0]['document_structure']['verified'])
        m.revalidate_result(self.root,self.p,task,got)
        got['records'][0]['document_structure']['reading_order']=4
        with self.assertRaisesRegex(ValueError,'specialist_selection_changed'):
            m.revalidate_result(self.root,self.p,task,got)

    def test_real_ink_engine_and_final_selection_reused_on_resume(self):
        fake=FakeInk();folder=self.root/'ink'
        got,changes=iw.run(self.t,{'id':'ink','bbox':[100,100,900,900]},[],folder,{'fake':1},fake)
        count=len(fake.calls);self.assertGreaterEqual(count,2)
        self.assertEqual(len(got),1);self.assertTrue(got[0]['eligible_for_chunking'])
        self.assertEqual(got[0]['specialist'],'ink_continue_v2')
        again,_=iw.run(self.t,{'id':'ink','bbox':[100,100,900,900]},[],folder,{'fake':1},fake)
        self.assertEqual(again,got);self.assertEqual(len(fake.calls),count)

    def test_ink_text_without_ocr_never_selected_despite_model_agreement(self):
        got,_=iw.run(self.t,{'id':'ink','bbox':[100,100,900,900]},[],self.root/'ink',{},FakeInk('단어'))
        self.assertFalse(got[0]['eligible_for_chunking'])

    def test_new_auxiliary_ink_policy_requires_fresh_exact_source_support(self):
        policy={'ocr_policy':'selective_auxiliary_v1'}
        got,_=iw.run(self.t,{'id':'ink','bbox':[100,100,900,900]},[],self.root/'ink-aux',policy,FakeInk('단어'))
        self.assertTrue(got[0]['eligible_for_chunking'])
        class Unclear(FakeInk):
            def call(self,*args):
                r=super().call(*args)
                if 'checks' in r:
                    for c in r['checks']:c.update(content='uncertain',lexical_complete=False)
                return r
        got,_=iw.run(self.t,{'id':'ink','bbox':[100,100,900,900]},[],self.root/'ink-unclear',policy,Unclear('단어'))
        self.assertFalse(got[0]['eligible_for_chunking'])

    def test_annotation_dispatch_and_saved_selection_replay(self):
        self.seed(block('객체','text'),block('객체','text'),annotation=True)
        task={'id':self.t['id'],'kind':'visual','unit':self.t}
        folder=self.root/'work'/signature(task['id'])[:24]
        got=m.visual(self.t,self.p,folder,FakeInk(),[])
        self.assertIn('ink_continue_v2',got['executed'])
        coarse=next(r for r in got['records'] if r['id'].endswith(':ink'))
        self.assertEqual(coarse['judgment'],'superseded_observation')
        fine=next(r for r in got['records'] if r.get('specialist')=='ink_continue_v2')
        self.assertTrue(fine['eligible_for_chunking'])
        m.revalidate_result(self.root,self.p,task,got)
        fine['eligible_for_chunking']=False
        with self.assertRaisesRegex(ValueError,'specialist_selection_changed'):m.revalidate_result(self.root,self.p,task,got)

    def test_video_source_error_blocks_only_affected_frame_at_publication(self):
        row=m.base.base_record(self.t,'b','text','text','객체');row.update(eligible_for_chunking=True,judgment='source_rechecked')
        check={'kind':'video_coverage','id':'video','source':{'source_sha256':'new'}}
        frame={'kind':'visual','id':self.t['id'],'unit':self.t}
        p={'tasks':[check,frame],'source_plan':{'units':[self.t]}}
        results={frame['id']:{'records':[row],'changes':[]},'video':{'changes':[],'records':[
            {'raw_payload':{'reason':'saved_frame_source_mismatch','category':'error','frame_id':'frame'},
             **m.base.base_record(self.t,'diagnostic','video','coverage_issue','')}]}}
        with patch.object(m,'done',return_value=results):summary=m.publish(self.root,p)
        self.assertEqual(summary['usable_records'],0)
        selected=Path(read(self.root/'latest.json')['usable_records']).read_text()
        self.assertEqual(selected,'')

    def test_new_input_rejects_configuration_change_on_resume(self):
        output=self.root/'pipeline';m.prepare(output,[self.image],model='fake')
        with self.assertRaisesRegex(ValueError,'different_model'):m.prepare(output,[self.image],model='different')

    def test_terminal_and_import_entrypoints_share_implementation_signature(self):
        output=self.root/'cli'
        subprocess.run([sys.executable,'-m','video_extraction.pipeline.connected','prepare',
                        '--input',str(self.image),'--output',str(output),'--gemini-model','fake'],
                        check=True,capture_output=True,text=True)
        self.assertEqual(m.verify(output)['code_hashes'],m.hashes())

    def test_ppt_native_missing_content_is_retained_for_recheck(self):
        self.seed(block('제목','text'),block('제목','text'))
        save(self.root/'native-inventory.json',{'records':[{'id':'native','source_sha256':'new',
            'slide_number':1,'hidden':False,'shape_id':'3','observed_text':'설명 누락','table_rows':None}],'pending':[]})
        got=m.visual({**self.t,'source_kind':'ppt'},self.p,self.root/'work',None,[])
        missing=next(r for r in got['records'] if 'native-missing' in r['id'])
        self.assertFalse(missing['eligible_for_chunking']);self.assertEqual(missing['missing_fragments'],['설명 누락'])

    def test_selective_audio_uses_existing_error_and_normal_cases(self):
        snap,tasks,outcomes=setup();old=copy.deepcopy(snap)
        got=aw.choose(snap,tasks,outcomes)
        self.assertEqual(len(got['receipts']),1)
        self.assertEqual(got['rows'][0]['text'],'이름과 점수')
        self.assertEqual(got['rows'][1]['text'],'반복 반복')
        self.assertEqual(snap,old)
        outcomes[tasks[1]['id']]['gate']['passed']=True
        with self.assertRaisesRegex(ValueError,'gate_mismatch'):aw.choose(snap,tasks,outcomes)

    def test_frozen_ink_failures_recomputed_without_mutating_fixtures(self):
        folder=Path(iw.engine.__file__).parents[2]/'fixtures/ink_recovery'
        count=0
        for f in folder.glob('*.json'):
            evidence=read(f);old=copy.deepcopy(evidence);p=evidence['package']
            actual=iw.ink_recovery.evaluate(p,p['candidate'],evidence['audit'])
            iw.ink_discrepancy.refresh_relations(actual)
            replay=iw.replay(p,actual)
            self.assertEqual(replay['decisions'],actual['decisions'])
            self.assertEqual(evidence,old);count+=1
        self.assertGreater(count,5)

    def test_audio_whole_source_real_pipeline_normal_repetition_and_cache(self):
        source=raw_file(self.root)
        u={**self.t,'id':'new:audio:0','source_kind':'audio','modality':'audio','source_audio':str(source),
           'interval':[0,30],'review_interval':[0,30],'location':{'audio_offset_seconds':10}}
        u['context_clip']=str(self.root/'window.wav');u['context_clip_meta']=aw.final.clip(source,Path(u['context_clip']),0,30)
        u.update(target_clip=u['context_clip'],target_clip_meta=u['context_clip_meta'])
        class ASR:
            def transcribe(self,path):return {'text':'반복 반복 정상','segments':[{'start':np.float64(1),'end':np.float64(3),'text':'반복 반복'},
                                                                         {'start':np.float64(7),'end':np.float64(8),'text':'정상'}]}
        calls=[]
        class API:
            @batch_fixture
            def call(self,name,media,prompt,schema):
                calls.append(name)
                if 'coverage' in name:return {'checked_full_core':True,'speech_unresolved':False,'findings':[]}
                data=json.loads(prompt.split('DATA:\n',1)[1]);duration=data['target_seconds'][1]
                text='반복 반복' if duration==2 else '정상'
                task={'role':'control','before':text,'after':text,'target_clip_meta':{'duration_seconds':duration}}
                b,r=scoped(task)
                return b if 'blind' in name else r
        with patch.object(aw.core,'detect_speech',return_value=[[1,3],[7,8]]):
            got=aw.run(u,[u],self.root/'audio',{},API(),ASR())
            count=len(calls);again=aw.run(u,[u],self.root/'audio',{},API(),ASR())
        self.assertEqual([r['observed_text'] for r in got['records']],['반복 반복','정상'])
        self.assertTrue(all(r['eligible_for_chunking'] for r in got['records']))
        self.assertEqual(got['records'][0]['start_seconds'],11)
        self.assertEqual(got['records'],again['records'])
        self.assertEqual(len(calls)-count,1) # coverage calls rely on the client's bound cache
        aw.validate_saved(u,self.root/'audio',got)
        corrupted=copy.deepcopy(got);corrupted['records'][0]['observed_text']='반복'
        with self.assertRaisesRegex(ValueError,'audio_selected_content_changed'):aw.validate_saved(u,self.root/'audio',corrupted)

    def test_full_audio_repair_keeps_healthy_repetition_and_source_scope(self):
        source=raw_file(self.root)
        u={**self.t,'id':'new:audio:0','source_kind':'audio','modality':'audio','source_audio':str(source),
           'interval':[0,30],'review_interval':[0,30],'location':{'audio_offset_seconds':0}}
        u['context_clip']=str(self.root/'window.wav');u['context_clip_meta']=aw.final.clip(source,Path(u['context_clip']),0,30)
        u.update(target_clip=u['context_clip'],target_clip_meta=u['context_clip_meta'])
        class ASR:
            def transcribe(self,path):
                return {'text':'이름과 점수 반복 반복','segments':[{'start':1,'end':3,'text':'이름 점수'},
                                                             {'start':7,'end':8,'text':'반복 반복'}]}
        class API:
            @batch_fixture
            def call(self,name,media,prompt,schema):
                if 'coverage' in name:return {'checked_full_core':True,'speech_unresolved':False,'findings':[
                    finding(kind='omitted_words',action='replace',target_id='new:speech:0',before='이름 점수',after='이름과 점수',start=1,end=3)]}
                data=json.loads(prompt.split('DATA:\n',1)[1]);duration=data['target_seconds'][1]
                text='이름과 점수' if duration==2 else '반복 반복'
                repair=data.get('proposed_text')=='이름과 점수'
                task={'role':'repair' if repair else 'control','before':'이름 점수' if repair else text,
                      'after':text,'target_clip_meta':{'duration_seconds':duration}}
                b,r=scoped(task);return b if 'blind' in name else r
        with patch.object(aw.core,'detect_speech',return_value=[[1,3],[7,8]]):
            got=aw.run(u,[u],self.root/'audio',{},API(),ASR())
        self.assertEqual(len(got['changes']),1)
        self.assertEqual([r['observed_text'] for r in got['records']],['이름과 점수','반복 반복'])
        self.assertTrue(all(r['eligible_for_chunking'] for r in got['records']))
        aw.validate_saved(u,self.root/'audio',got)

    def test_dispatcher_stop_resume_and_rehashed_flag_rejection(self):
        # Exercise optional-OCR-unavailable routing, never launch local models in
        # this dispatcher regression. Dedicated OCR tests supply worker fixtures.
        patch.object(m.visual_ocr,'prepare',side_effect=ValueError('whole_image_ocr_failed_see_worker_log')).start()
        other=self.root/'second.png';Image.new('RGB',(300,200),'blue').save(other)
        output=self.root/'pipeline';p=m.prepare(output,[self.image,other],model='fake')
        calls=[];interrupted=[False]
        class OCRReviewer:
            def call(self,name,media,prompt,schema):
                if name.startswith('source-followup-'):
                    issues=json.loads(prompt.split('DATA:\n',1)[1])['issues']
                    return {'complete_scan':True,'regions':[],'checks':[{'id':i['id'],
                        'decision':'existing_supported','source_clear':True,'reason':'synthetic source fixture'} for i in issues]}
                if name!='whole-image-ocr-discrepancy-v1':raise AssertionError(name)
                issues=json.loads(prompt.split('DATA:\n',1)[1])['issues']
                return {'checks':[{'id':i['id'],'decision':'extraction_supported',
                    'source_clear':True,'candidate_complete':True,'reason':'synthetic dispatch fixture'} for i in issues]}
        def extract(frame,*args,**kwargs):
            calls.append(frame['path'])
            if len(calls)==2 and not interrupted[0]:interrupted[0]=True;raise Blocked('test_budget')
            b=block('객체','text');v=result(b,b);v.update(signature='fake',image_sha256=digest_file(frame['path']),audit={});return v
        with patch.object(m.base.visual,'process_frame_layers',side_effect=extract),patch.object(m,'api_key',return_value='fake'),patch.object(m,'Gemini',return_value=OCRReviewer()):
            with self.assertRaises(Blocked):m.run(output,self.root/'.env',delay=0)
            self.assertEqual(read(output/'summary.json')['completed'],1)
            first=next((output/'results').glob('*.json'));first_hash=digest_file(first)
            m.run(output,self.root/'.env',delay=0)
            self.assertEqual(read(output/'summary.json')['completed'],2)
            self.assertEqual(digest_file(first),first_hash);self.assertEqual(len(calls),3)
            m.run(output,self.root/'.env',delay=0);self.assertEqual(len(calls),3)
        got=read(first);got['records'][0]['eligible_for_chunking']=not got['records'][0]['eligible_for_chunking']
        got.pop('payload_hash');got['payload_hash']=signature(got);save(first,got)
        with self.assertRaisesRegex(ValueError,'specialist_selection_changed'):m.publish(output,p)

    def test_real_pdf_misrepairs_through_new_dispatcher(self):
        old=PROJECT_ROOT/'outputs/common-pipeline-new-source-v1';p=read(old/'plan.json')
        class NoClassification:
            def call(self,stage,images,prompt,schema):
                data=json.loads(prompt.split('DATA:\n')[1])
                return {'record_id':data['record_id'],'impact':'unknown','same_region':False,
                    'source_clear':False,'uncertain':True,'core_instruction_preserved_without_region':False,
                    'no_unique_concept_or_step':False,'no_number_negation_condition_or_code_change':False,
                    'reason':'offline replay, no new impact evidence'}
        for page in (32,41):
            t=next(t for t in p['units'] if t['source_kind']=='pdf' and t['location'].get('page')==page)
            before=read(old/'results'/(t['unit_key']+'.json'));raw=before['evidence']['visual_result']
            plan={**self.p,'source_plan':p,'seeds':{t['id']:raw}}
            got=m.visual(t,plan,self.root/str(page),NoClassification(),[])
            rows={r['id'].rsplit(':',1)[-1]:r for r in got['records']}
            if page==32:
                for iid,text in [('b8','도시'),('b9','행정'),('b10','메타버스')]:
                    self.assertEqual(rows[iid]['observed_text'],text);self.assertFalse(rows[iid]['eligible_for_chunking'])
            else:self.assertFalse(rows['b1']['eligible_for_chunking'])

    def test_video_dispatch_calls_timeline_and_decoded_pixel_checks(self):
        source={'source_sha256':'new','source_file':str(self.image),'video_metadata':{'duration_seconds':30}}
        p={'source_plan':{'units':[self.t],'config':{'max_frame_gap':15,'scan_fps':2}}}
        with patch.object(m.multimodal_checks,'inspect_timeline',return_value=[]) as timeline,patch.object(m.multimodal_checks,'scan_video',return_value=([],{'decoded':True})) as scan:
            got=m.video({'id':'video','source':source},p,self.root)
        timeline.assert_called_once();scan.assert_called_once();self.assertTrue(got['metrics']['decoded'])


    def test_real_whisper_numpy_times_and_cached_times_have_identical_signatures(self):
        old=PROJECT_ROOT/'outputs/common-connected-v2'
        p=read(old/'plan.json');u=next(t['unit'] for t in p['tasks'] if t['kind']=='audio')
        evidence=read(old/'work/b810cd7f8f99fdc4890ec4dd/initial.json')
        rows=[dict(id=str(i),text=s['text'],start_seconds=np.float64(s['start']),end_seconds=np.float64(s['end']))
              for i,s in enumerate(evidence['segments'])]
        t={'id':'repro','target_id':'0','role':'control','before':rows[0]['text'],'after':rows[0]['text'],
           'interval':[rows[0]['start_seconds'],rows[0]['end_seconds']]}
        fresh=aw.bound_task(t,rows,Path(u['source_audio']),self.root/'clips',u['interval'][1])
        self.assertIs(type(fresh['boundary_expanded']),bool)
        self.assertEqual(signature(fresh),signature(json.loads(json.dumps(fresh))))
        cached=aw.bound_task(json.loads(json.dumps(t)),json.loads(json.dumps(rows)),Path(u['source_audio']),self.root/'clips',u['interval'][1])
        self.assertEqual(signature(fresh),signature(cached))

    def test_unexpected_failure_is_not_reported_as_plain_pending(self):
        out=self.root/'failed';m.prepare(out,[self.image],model='fake')
        with patch.object(m,'api_key',return_value='fake'),patch.object(m,'Gemini',return_value=None),patch.object(m,'visual',side_effect=TypeError('sensitive-test-value')):
            with self.assertRaises(TypeError):m.run(out,self.root/'.env',delay=0)
        state=read(out/'run-state.json');failure=read(out/'last-failure.json')
        self.assertEqual(state['stop_reason'],'unexpected_error')
        self.assertEqual(failure['exception_type'],'TypeError')
        self.assertNotIn('sensitive-test-value',json.dumps(failure))
        self.assertEqual(read(out/'summary.json')['completed'],0)

    def test_post_recheck_low_impact_warning_policy_and_strict_safety_guards(self):
        from video_extraction.shared.impact_policy import hold_for_administrator
        low_text=hold_for_administrator(m.base.base_record(self.t,'low-text','handwriting','handwriting','스택은'),
                                        '조사 차이로 의미 보존',{'source':'test'})
        low_empty=hold_for_administrator(m.base.base_record(self.t,'low-empty','audio','coverage_issue',''),
                                         '추임새 구간으로 핵심 설명 보존',{'source':'test'})
        unreadable=hold_for_administrator(m.base.base_record(self.t,'unreadable','handwriting','handwriting','?'),
                                          '판독 불가',{'source':'test'})
        unreadable['impact_review']['impact']='unknown'
        unreadable['reasons'].append('source_interpretation_administrator_review')
        safety_gate=hold_for_administrator(m.base.base_record(self.t,'safety','text','text','x[0]'),
                                           '0/o 안전선',{'source':'test'})
        safety_gate['reasons'].append('common_safety_gate')
        task={'kind':'visual','id':self.t['id'],'unit':self.t}
        p={'tasks':[task],'source_plan':{'units':[self.t]},'low_impact_policy':m.LOW_IMPACT_POLICY}
        out=self.root/'low-impact-out'
        with patch.object(m,'done',return_value={task['id']:{'records':[low_text,low_empty],'changes':[]}}):
            s=m.publish(out,p)
        self.assertEqual(s['usable_records'],1);self.assertEqual(s['low_impact_warning_records'],1)
        self.assertEqual(s['low_impact_omissions_resolved'],1);self.assertEqual(s['held_records'],0)
        self.assertTrue(s['review_finished'])
        usable=[json.loads(l) for l in Path(read(out/'latest.json')['usable_records']).read_text().splitlines()]
        self.assertEqual(usable[0]['observed_text'],'스택은')
        self.assertEqual(usable[0]['judgment'],'accepted_with_low_impact_warning')
        self.assertIn('low_impact_warning_accepted',usable[0]['warnings'])
        out_strict=self.root/'strict-out'
        with patch.object(m,'done',return_value={task['id']:{'records':[unreadable,safety_gate],'changes':[]}}):
            s_strict=m.publish(out_strict,p)
        self.assertEqual(s_strict['usable_records'],0);self.assertEqual(s_strict['held_records'],2)
        self.assertFalse(s_strict['review_finished'])


if __name__=='__main__':unittest.main()
