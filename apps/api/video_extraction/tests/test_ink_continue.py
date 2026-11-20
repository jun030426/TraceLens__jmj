import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from video_extraction.shared.common import read, save, signature
from video_extraction.shared.gemini import Blocked
from video_extraction.tests.test_ink_pipeline import fixture, visual
from video_extraction.tests.test_ink_policy import audit
from video_extraction.ink.runner.ink_continue import prepare, select_batch, execute, run, context_bindings, safe_task, verify_manifest


def setup(root, count=3, batch_size=2):
    source = root/'catalog'; completed = root/'completed'; tasks = []
    for n in range(count):
        task = fixture(root, 't'+str(n))
        task.update(frame_id='f'+str(n), time_seconds=n*20, priority_score=1, asr_context=[], human_feedback='SECRET_GOLD')
        tasks.append(task)
    save(source/'plan.json', {'tasks': tasks, 'selected_ids': ['t0'], 'source_sha256': 'sha', 'model': 'fake', 'input_hashes': {}, 'scope': []})
    save(source/'results/t0.json', {'previous': True})
    save(completed/'prepared/t0.json', {'task': tasks[0]})
    done = {'tasks': [{'id': 't0', 'package': str(completed/'prepared/t0.json')}], 'input_hashes': {}}
    save(completed/'plan.json', done)
    save(completed/'results/t0.json', {'active_coverage_complete': True, 'plan_signature': signature(done), 'administrator_queue': []})
    out = root/'out'; prepare(source, completed, out, batch_size)
    return out, tasks


def local_stub(output, plan, batch, *args):
    tasks = {}
    for t in plan['tasks']:
        if t['id'] not in batch['ids']: continue
        t = copy.deepcopy(t)
        t['evidence'] = {'selected_frame': t['current_image'], 'selected_frame_seconds': t['time_seconds']}
        view = {'path': t['current_image'], 'size': [200, 100], 'crop_in_source': [0, 0, 1, 1]}
        tasks[t['id']] = {'task': t, 'view': view, 'ocr': {'state': 'unavailable', 'words': []},
                         'ocr_coverage': dict(left=0, top=0, right=1000, bottom=1000)}
    return {'tasks': tasks}


class Fake:
    def __init__(self, stop=None): self.stats = {'requests': 0}; self.calls = []; self.stop = stop
    def call(self, name, media, prompt, schema):
        self.calls.append((name, media, prompt)); self.stats['requests'] += 1
        if self.stop and self.stop in name: raise Blocked('request_budget_exhausted')
        if name.endswith('continuation_visual'): return visual()
        data = json.loads(prompt.split('DATA:\n', 1)[1])
        if name.endswith('continuation_asr_context'): return {'bindings': [], 'concepts': [], 'word_candidates': [], 'notes': []}
        return audit(data['candidate'], data['required_ids'])


class ContinuationTests(unittest.TestCase):
    def test_completed_excluded_and_all_remaining_retained(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch('video_extraction.ink.runner.ink_continue.Gemini', side_effect=AssertionError('No API')):
                out, tasks = setup(Path(tmp), 5)
            plan = read(out/'plan.json')
            self.assertEqual(plan['skipped_completed_ids'], ['t0']); self.assertEqual(len(plan['tasks']), 4)
            self.assertTrue(all('human_feedback' not in t for t in plan['tasks']))
            self.assertEqual(select_batch(out, plan)['ids'], ['t1', 't2'])

    def test_partial_batch_resumes_before_next_batch(self):
        with tempfile.TemporaryDirectory() as tmp:
            out, _ = setup(Path(tmp), 5); plan = read(out/'plan.json')
            save(out/'results/t1.json', {'plan_signature': signature(plan)})
            self.assertEqual(select_batch(out, plan)['ids'], ['t1', 't2'])
            save(out/'results/t2.json', {'plan_signature': signature(plan)})
            self.assertEqual(select_batch(out, plan)['ids'], ['t3', 't4'])

    def test_stale_completed_result_never_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            out, _ = setup(Path(tmp)); plan = read(out/'plan.json')
            save(out/'results/t1.json', {'plan_signature': 'wrong'})
            with self.assertRaises(ValueError): select_batch(out, plan)

    def test_asr_quotes_must_match_actual_supplied_segment(self):
        v = visual(); segments = [dict(text='순서가 없습니다', start_seconds=11, end_seconds=12)]
        b = dict(item_ids=['m'], quote='순서가 없습니다', start_seconds=11, end_seconds=12, relevance='aligned', reason='match')
        result = context_bindings({'bindings': [b, {**b, 'quote': '없는 말'}, {**b, 'end_seconds': 13}]}, segments, v, [10, 20])
        self.assertEqual(result['bindings'], [b]); self.assertEqual(len(result['rejected_bindings']), 2)

    def test_budget_resume_reuses_visual_and_stays_in_same_batch(self):
        with tempfile.TemporaryDirectory() as tmp:
            out, _ = setup(Path(tmp), 4); first = Fake(stop='t1_meaning_source_audit')
            with patch('video_extraction.ink.runner.ink_continue.local_batch', side_effect=local_stub), patch('video_extraction.ink.runner.ink_continue.Gemini', return_value=first):
                with self.assertRaises(Blocked): run(out, Path(tmp)/'.env', Path('python'), Path('models'))
            second = Fake()
            with patch('video_extraction.ink.runner.ink_continue.local_batch', side_effect=local_stub), patch('video_extraction.ink.runner.ink_continue.Gemini', return_value=second):
                summary = run(out, Path(tmp)/'.env', Path('python'), Path('models'))
            self.assertEqual(summary['processed_new_tasks'], 2); self.assertEqual(summary['not_processed'], 1)
            self.assertFalse(any('t1_continuation_visual' in n for n, _, _ in second.calls))
            self.assertFalse(any('SECRET_GOLD' in p for _, _, p in second.calls))

    def test_local_only_never_constructs_api(self):
        with tempfile.TemporaryDirectory() as tmp:
            out, _ = setup(Path(tmp))
            with patch('video_extraction.ink.runner.ink_continue.local_batch', side_effect=local_stub), patch('video_extraction.ink.runner.ink_continue.Gemini', side_effect=AssertionError('No API')):
                r = run(out, Path(tmp)/'.env', Path('python'), Path('models'), local_only=True)
            self.assertEqual(r['api_requests'], 0); self.assertFalse((out/'results').exists())

    def test_empty_extraction_requires_independent_source_scan(self):
        class EmptyFake(Fake):
            def call(self, name, media, prompt, schema):
                self.calls.append((name, media, prompt)); self.stats['requests'] += 1
                if name.endswith('continuation_visual'):
                    return {'items': [], 'links': [], 'complete': True, 'notes': []}
                return {'checks': [], 'missing': [{'description': 'missed ink', 'box': dict(left=200, top=200, right=600, bottom=600)}], 'complete': False}
        with tempfile.TemporaryDirectory() as tmp:
            out, _ = setup(Path(tmp)); plan = read(out/'plan.json'); batch = select_batch(out, plan)
            data = local_stub(out, plan, batch)['tasks']['t1']; fake = EmptyFake()
            r = execute(data, out, plan, fake)
            self.assertFalse(r['active_coverage_complete']); self.assertFalse(r['records'])
            self.assertEqual(len(r['missing_core']), 1)
            self.assertTrue(fake.calls[-1][0].endswith('empty_scope_source_audit'))

    def test_second_invocation_advances_and_noop_after_all_done(self):
        with tempfile.TemporaryDirectory() as tmp:
            out, _ = setup(Path(tmp), 4); fake = Fake()
            with patch('video_extraction.ink.runner.ink_continue.local_batch', side_effect=local_stub), patch('video_extraction.ink.runner.ink_continue.Gemini', return_value=fake):
                self.assertEqual(run(out, Path(tmp)/'.env', Path('python'), Path('models'))['processed_new_tasks'], 2)
                self.assertEqual(run(out, Path(tmp)/'.env', Path('python'), Path('models'))['processed_new_tasks'], 3)
            with patch('video_extraction.ink.runner.ink_continue.Gemini', side_effect=AssertionError('No API')):
                self.assertEqual(run(out, Path(tmp)/'.env', Path('python'), Path('models'))['not_processed'], 0)


if __name__ == '__main__': unittest.main()
