from video_extraction.shared import file_lock as fcntl
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from video_extraction.shared.common import read, digest_file
from video_extraction.shared.gemini import Blocked, Gemini as RealGemini
from video_extraction.ink.runner.ink_auto_continue import run, prepare_runner
from video_extraction.tests.test_ink_continue_v2 import setup, Fake
from video_extraction.tests.test_ink_continue import local_stub
from video_extraction.tests.test_ink_policy import audit
from video_extraction.tests.test_ink_pipeline import visual


class BudgetFake(Fake):
    def __init__(self,limit,interrupt=None):
        super().__init__();self.limit=limit;self.interrupt=interrupt
    def call(self,name,media,prompt,schema):
        if self.stats['requests']>=self.limit:raise Blocked('request_budget_exhausted')
        if self.interrupt and self.interrupt in name:raise KeyboardInterrupt()
        return super().call(name,media,prompt,schema)


class AutoContinuationTests(unittest.TestCase):
    def test_one_client_budget_across_batches_and_mid_task_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            out,p=setup(Path(tmp),5);original=digest_file(out/'plan.json');prepare_runner(out)
            first=BudgetFake(5)
            with patch('video_extraction.ink.runner.ink_auto_continue.local_batch',side_effect=local_stub) as local,patch('video_extraction.ink.runner.ink_auto_continue.Gemini',return_value=first) as create:
                s=run(out,Path('.env'),Path('python'),Path('models'),max_calls=5)
            self.assertEqual(create.call_count,1);self.assertEqual(local.call_count,2)
            self.assertEqual((s['api_requests'],s['processed'],s['stop_reason']),(5,2,'request_budget_exhausted'))
            self.assertFalse((out/'results/t2.json').exists())
            state=read(out/'run-state.json');self.assertEqual(state['current_task_id'],'t2')
            second=BudgetFake(60)
            with patch('video_extraction.ink.runner.ink_auto_continue.local_batch',side_effect=local_stub),patch('video_extraction.ink.runner.ink_auto_continue.Gemini',return_value=second):
                s=run(out,Path('.env'),Path('python'),Path('models'))
            self.assertEqual(s['stop_reason'],'all_tasks_processed');self.assertEqual(s['processed'],5)
            self.assertEqual(s['completed_this_run'],3);self.assertEqual(s['api_requests'],5)
            self.assertFalse(any(n.endswith('t2_continuation_v2_visual') for n,_ in second.calls))
            self.assertFalse(any('t0_' in n or 't1_' in n for n,_ in second.calls))
            self.assertEqual(digest_file(out/'plan.json'),original)

    def test_exact_batch_boundary_no_next_ocr_after_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            out,_=setup(Path(tmp),4);prepare_runner(out)
            with patch('video_extraction.ink.runner.ink_auto_continue.local_batch',side_effect=local_stub) as local,patch('video_extraction.ink.runner.ink_auto_continue.Gemini',return_value=BudgetFake(4)):
                s=run(out,Path('.env'),Path('python'),Path('models'),max_calls=4)
            self.assertEqual(local.call_count,1);self.assertEqual(s['processed'],2)
            self.assertEqual(read(out/'active-batch.json')['ids'],['t2','t3'])

    def test_completed_queue_no_api_or_local_work(self):
        with tempfile.TemporaryDirectory() as tmp:
            out,_=setup(Path(tmp),0);prepare_runner(out)
            with patch('video_extraction.ink.runner.ink_auto_continue.local_batch',side_effect=AssertionError('no OCR')),patch('video_extraction.ink.runner.ink_auto_continue.Gemini',side_effect=AssertionError('no API')):
                s=run(out,Path('.env'),Path('python'),Path('models'))
            self.assertEqual(s['api_requests'],0);self.assertEqual(s['stop_reason'],'all_tasks_processed')

    def test_interrupt_preserves_visual_and_releases_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            out,_=setup(Path(tmp),1);prepare_runner(out)
            with patch('video_extraction.ink.runner.ink_auto_continue.local_batch',side_effect=local_stub),patch('video_extraction.ink.runner.ink_auto_continue.Gemini',return_value=BudgetFake(60,'_source_audit')):
                with self.assertRaises(KeyboardInterrupt):run(out,Path('.env'),Path('python'),Path('models'))
            self.assertEqual(read(out/'run-state.json')['stop_reason'],'interrupted')
            resumed=BudgetFake(60)
            with patch('video_extraction.ink.runner.ink_auto_continue.local_batch',side_effect=local_stub),patch('video_extraction.ink.runner.ink_auto_continue.Gemini',return_value=resumed):
                s=run(out,Path('.env'),Path('python'),Path('models'))
            self.assertEqual(s['api_requests'],1)

    def test_retry_attempts_count_in_real_client_budget_without_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            out,_=setup(Path(tmp),4);prepare_runner(out);attempts=[];clients=[]
            def transport(req,timeout):
                payload=json.loads(req.data);prompt=payload['input'][0]['text'];attempts.append(prompt)
                if len(attempts)<=2:text='invalid json'
                else:
                    d=json.loads(prompt.split('DATA:\n',1)[1])
                    value=audit(d['candidate'],d['required_ids']) if 'required_ids' in d else visual()
                    text=json.dumps(value)
                return io.BytesIO(json.dumps(dict(status='completed',output_text=text)).encode())
            def factory(*args,**kwargs):
                client=RealGemini(*args,**kwargs,transport=transport,sleeper=lambda _:None);clients.append(client);return client
            with patch('video_extraction.shared.gemini.api_key',return_value='test-only'),patch('video_extraction.ink.runner.ink_auto_continue.local_batch',side_effect=local_stub),patch('video_extraction.ink.runner.ink_auto_continue.Gemini',side_effect=factory):
                s=run(out,Path('.env'),Path('python'),Path('models'),max_calls=7)
            self.assertEqual(len(clients),1);self.assertEqual(len(attempts),7)
            self.assertEqual(s['api_requests'],7);self.assertEqual(s['processed'],2)
            self.assertEqual(s['stop_reason'],'request_budget_exhausted')

    def test_parallel_old_runner_lock_blocks_new_runner(self):
        with tempfile.TemporaryDirectory() as tmp:
            out,_=setup(Path(tmp),1);prepare_runner(out)
            with (out/'.run.lock').open('a') as lock:
                fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                with self.assertRaises(BlockingIOError):run(out,Path('.env'),Path('python'),Path('models'))

    def test_prepare_is_offline_and_preserves_extraction_signature(self):
        with tempfile.TemporaryDirectory() as tmp:
            out,_=setup(Path(tmp),1);before=digest_file(out/'plan.json')
            with patch('video_extraction.ink.runner.ink_auto_continue.Gemini',side_effect=AssertionError('no API')):
                prepare_runner(out);prepare_runner(out)
            self.assertEqual(digest_file(out/'plan.json'),before)


if __name__=='__main__':unittest.main()
