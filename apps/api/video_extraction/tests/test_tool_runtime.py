"""Actual native reading plus mocked inference handoff; never execute models/API."""
import copy
import json
import subprocess
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch
from video_extraction.pipeline import runtime_tools as rt,alignment_bridge as ab,document_workflow as dw,connected
from video_extraction.shared.common import read,save,jsonl,signature,digest_file
from video_extraction._layout import PROJECT_ROOT
from video_extraction.tests.test_pdf_alignment_admin import aligned
from video_extraction.audio import word_alignment
from video_extraction.pipeline import ink_workflow as iw
from PIL import Image


class RuntimeTests(unittest.TestCase):
    def test_wrong_runtime_and_missing_weights_block_core(self):
        report={'checks':[{'tool':'PaddleOCR','required':True,'ok':False},{'tool':'WhisperX','required':False,'ok':False}]}
        with self.assertRaisesRegex(ValueError,'PaddleOCR'):rt.require_core(report)
        rt.require_core({'checks':[report['checks'][1]]})
        self.assertFalse(rt.assets(None,['inference.pdiparams'])['ok'])

    def test_missing_python_is_not_reported_as_model_success(self):
        self.assertFalse(rt.imports('/nonexistent/ocr-python',[('paddleocr','paddleocr')])['ok'])

    def test_real_native_ppt_reader_connected_without_changes_to_source(self):
        source=next(s for s in read(PROJECT_ROOT/'outputs/common-connected-v6/plan.json')['source_plan']['sources'] if s['kind']=='ppt')
        before=digest_file(source['source_file'])
        with tempfile.TemporaryDirectory() as tmp:
            out=dw.native_inventory([source],rt.defaults()['native_python'],tmp)
            self.assertTrue(out['native_reader_receipts'])
            self.assertEqual(out['native_reader_receipts'][0]['tool'],'python-pptx')
            self.assertTrue(any('native_reader_agreement' in r for r in out['records']))
            self.assertFalse(any(p['reason']=='native_ppt_parsers_disagree' for p in out['pending']))
        self.assertEqual(before,digest_file(source['source_file']))

    def test_native_parser_disagreement_keeps_both_values(self):
        source=next(s for s in read(PROJECT_ROOT/'outputs/common-connected-v6/plan.json')['source_plan']['sources'] if s['kind']=='ppt')
        actual=dw.native_documents
        def changed(*args):
            records,changes,assets,pending=actual(*args)
            records[0]['observed_text']='WRONG'
            return records,changes,assets,pending
        with tempfile.TemporaryDirectory() as tmp,patch.object(dw,'native_documents',side_effect=changed):
            out=dw.native_inventory([source],rt.defaults()['native_python'],tmp)
            problem=next(p for p in out['pending'] if p['reason']=='native_ppt_parsers_disagree')
            self.assertEqual(problem['xml_value'],'WRONG');self.assertNotEqual(problem['python_pptx_value'],'WRONG')


class AlignmentBridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.wav=self.root/'audio.wav'
        with wave.open(str(self.wav),'wb') as wav:
            wav.setparams((1,2,16000,0,'NONE','NONE'));wav.writeframes(b'\0\0'*32000)
        self.rows=[dict(id='a',modality='audio',kind='speech',eligible_for_chunking=True,word_alignment_required=True,
             observed_text='가 가',source_audio=str(self.wav),audio_offset_seconds=0,start_seconds=0,end_seconds=2)]
        self.records=self.root/'approved.jsonl';jsonl(self.records,self.rows)
        save(self.root/'latest.json',{'usable_records':str(self.records)})
        self.plan={'source_plan':{'config':{'language':'ko'}},'tool_runtime':{**rt.defaults(),'alignment_allow_download':False}}

    def test_prepare_does_not_execute_model_and_exposes_pending_timing(self):
        with patch.object(ab.subprocess,'run',side_effect=AssertionError('model execution forbidden')):
            r=ab.prepare(self.root,self.plan,self.records)
        self.assertEqual(r['targets'],1);self.assertEqual(r['state'],'pending')
        row=json.loads(Path(r['records_with_timing']).read_text())
        self.assertEqual(row['observed_text'],'가 가');self.assertTrue(row['eligible_for_chunking'])
        self.assertFalse(row['eligible_for_word_timed_use'])

    def test_missing_environment_is_explicit_not_silent_success(self):
        with patch.object(rt,'imports',return_value={'ok':False,'reason':'python_missing'}):r=ab.run(self.root,self.plan)
        self.assertEqual(r['state'],'environment_missing')
        self.assertEqual(ab.prepare(self.root,self.plan,self.records)['state'],'environment_missing')

    def test_user_run_handoff_publishes_timing_and_resumes_without_reinfer(self):
        def fake_run(args,**kw):
            folder=Path(args[args.index('--output')+1]);plan=read(folder/'plan.json');job=plan['jobs'][0];raw=aligned()
            save(folder/'results'/(signature(job['id'])[:24]+'.json'),{'binding':signature({'plan':plan,'job':job}),
                 'raw':raw,'gate':word_alignment.inspect_alignment(job['text'],[0,2],raw,{'가'}),'supported_chars':['가']})
            return subprocess.CompletedProcess(args,0)
        with patch.object(rt,'imports',return_value={'ok':True}),patch('video_extraction.pipeline.runtime_setup.ensure_alignment',return_value={}),patch.object(ab.subprocess,'run',side_effect=fake_run) as worker:
            r=ab.run(self.root,self.plan);again=ab.run(self.root,self.plan)
        self.assertEqual(worker.call_count,1);self.assertEqual(r['state'],'complete');self.assertEqual(again['state'],'complete')
        row=json.loads(Path(r['records_with_timing']).read_text())
        self.assertEqual(row['observed_text'],self.rows[0]['observed_text']);self.assertTrue(row['eligible_for_chunking'])
        self.assertTrue(row['eligible_for_word_timed_use']);self.assertFalse(row['word_timestamps_verified'])

    def test_new_selection_gets_new_alignment_version(self):
        first=ab.prepare(self.root,self.plan,self.records)
        rows=copy.deepcopy(self.rows);rows[0]['observed_text']='다 다';jsonl(self.records,rows)
        second=ab.prepare(self.root,self.plan,self.records)
        self.assertNotEqual(first['output'],second['output']);self.assertEqual(second['state'],'pending')


class OCRFailureTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.image=self.root/'image.png';Image.new('RGB',(20,20),'white').save(self.image)
        self.package={'view':{'path':str(self.image)},'task':{'id':'target'}}
        self.folder=self.root/'ocr';self.folder.mkdir()

    def test_failed_worker_is_not_completed_or_selected(self):
        with patch.object(iw.subprocess,'run',return_value=subprocess.CompletedProcess([],1)):
            with self.assertRaisesRegex(RuntimeError,'local_ocr_worker_failed'):
                iw.local_ocr(self.package,self.folder,'models','configured-venv/bin/python')

    def test_failed_cached_receipt_is_preserved_and_retried(self):
        save(self.folder/'target.json',{'state':'unavailable','reason':'old_import_failure'})
        def worker(args,**kwargs):
            self.assertEqual(args[0],'configured-venv/bin/python')
            self.assertFalse((self.folder/'target.json').exists())
            save(self.folder/'target.json',{'state':'candidate','words':[],'image_sha256':digest_file(self.image)})
            return subprocess.CompletedProcess(args,0)
        with patch.object(iw.subprocess,'run',side_effect=worker):
            result=iw.local_ocr(self.package,self.folder,'models','configured-venv/bin/python')
        self.assertEqual(result['ocr']['state'],'candidate')
        archived=list(self.folder.glob('failed-before-retry-*.json'))
        self.assertEqual(len(archived),1);self.assertEqual(read(archived[0])['reason'],'old_import_failure')

    def test_worker_reports_inference_failure_without_crash_still_blocks(self):
        def worker(args,**kwargs):
            save(self.folder/'target.json',{'state':'unavailable','image_sha256':digest_file(self.image)})
            return subprocess.CompletedProcess(args,0)
        with patch.object(iw.subprocess,'run',side_effect=worker):
            with self.assertRaisesRegex(RuntimeError,'local_ocr_inference_failed'):
                iw.local_ocr(self.package,self.folder,'models','configured-venv/bin/python')


if __name__=='__main__':unittest.main()
