import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from video_extraction.shared.common import read, save, signature
from video_extraction.shared.gemini import Blocked
from video_extraction.tests.test_ink_pipeline import fixture, visual
from video_extraction.ink.correction.ink_recheck import ocr_findings, load_ocr, scope_ids, local_check, apply_checked, execute, prepare, run, check_plan, recheck_view
from video_extraction.ink.runner.ink_pipeline import transform_visual
from video_extraction.shared.common import digest_file


def audit(value, status='supported', missing=None):
    return {'checks': [{'id': x['id'], 'content': status, 'geometry': status,
                       'meaning': status, 'reason': 'pixels checked'} for x in value['items']+value['links']],
            'missing': missing or [], 'complete': not missing}


def package(root):
    task = fixture(root); view = task['evidence']['views']['original']
    return {'task': task, 'view': view, 'base': visual(), 'candidate': visual(),
            'ocr': {'state': 'unavailable', 'words': []},
            'ocr_coverage': dict(left=0, top=0, right=1000, bottom=1000), 'audio_context': {}}


class Fake:
    def __init__(self, fail_final=False, stop=None):
        self.stats = {'requests': 0}; self.calls = []; self.fail_final = fail_final; self.stop = stop

    def call(self, name, media, prompt, schema):
        self.stats['requests'] += 1; self.calls.append((name, media, prompt))
        if self.stop and name.endswith(self.stop): raise Blocked('request_budget_exhausted')
        data = json.loads(prompt.split('DATA:\n', 1)[1]); value = data['candidate']
        if name.endswith('targeted_repair'):
            value['items'][0]['box']['left'] = 200
            return value
        result = audit(value)
        if name.endswith('_source_reaudit') and not name.endswith('_final_source_reaudit'):
            result['checks'][0]['geometry'] = 'partial'
        if self.fail_final and name.endswith('_final_source_reaudit'):
            result['checks'][0]['geometry'] = 'unsupported'
        result['checks'] = [c for c in result['checks'] if c['id'] in data['required_ids']]
        return result


class InkRecheckTests(unittest.TestCase):
    def test_ocr_unavailable_no_detection_and_conflict_are_distinct(self):
        item = visual()['items'][0]; item.update(kind='handwriting', text='0')
        view = {'size': [100, 100]}; coverage = dict(left=0, top=0, right=1000, bottom=1000)
        self.assertEqual(ocr_findings(item, view, {}, coverage)['unprocessed'], ['ocr_unavailable'])
        self.assertEqual(ocr_findings(item, view, {'state': 'candidate', 'words': []}, coverage)['unprocessed'], ['ocr_no_detection'])
        receipt = {'state': 'candidate', 'words': [{'bbox_pixels': [20, 20, 80, 80], 'score': .95, 'text': 'o'}]}
        self.assertEqual(ocr_findings(item, view, receipt, coverage)['blocking'], ['ocr_text_conflict'])

    def test_ocr_variant_change_elsewhere_does_not_flag_good_word(self):
        item = visual()['items'][0]; item.update(kind='printed_text', text='A')
        word = {'bbox_pixels': [20, 20, 80, 80], 'score': .9, 'text': 'A'}
        receipt = {'state': 'candidate', 'words': [word], 'variant_disagreement': True,
            'alternative_words': [word, {'bbox_pixels': [95, 95, 99, 99], 'score': .9, 'text': 'other'}]}
        f = ocr_findings(item, {'size': [100, 100]}, receipt, dict(left=0, top=0, right=1000, bottom=1000))
        self.assertEqual(f, {'blocking': [], 'warnings': [], 'unprocessed': []})

    def test_outside_ocr_crop_is_unprocessed_not_conflict(self):
        item = visual()['items'][0]; item.update(kind='printed_text', text='A')
        f = ocr_findings(item, {'size': [100, 100]}, {'state': 'candidate', 'words': []},
                         dict(left=400, top=400, right=600, bottom=600))
        self.assertEqual(f['unprocessed'], ['ocr_outside_scanned_area']); self.assertFalse(f['blocking'])

    def test_partial_ocr_line_does_not_assert_mismatch(self):
        item = visual()['items'][0]; item.update(kind='printed_text', text='A')
        r = {'state': 'candidate', 'words': [{'text': 'ABCD', 'score': .99, 'bbox_pixels': [0, 0, 100, 100]}]}
        f = ocr_findings(item, {'size': [100, 100]}, r, dict(left=0, top=0, right=1000, bottom=1000))
        self.assertFalse(f['blocking']); self.assertIn('ocr_partial_word_coverage', f['unprocessed'])

    def test_scope_keeps_crossing_mark_and_direct_target_not_padding(self):
        v = visual(); v['items'][0]['box'] = dict(left=100, top=100, right=300, bottom=300)
        v['items'] += [{**copy.deepcopy(v['items'][0]), 'id': 'target', 'box': dict(left=600, top=600, right=800, bottom=800)},
                       {**copy.deepcopy(v['items'][0]), 'id': 'padding', 'box': dict(left=850, top=850, right=1000, bottom=1000)}]
        v['links'] = [dict(id='r', from_ids=['m'], to_ids=['target'], kind='emphasis', direction='not_applicable', evidence='visible')]
        self.assertEqual(scope_ids(v, dict(left=200, top=200, right=500, bottom=500)), {'m', 'r', 'target'})

    def test_independent_good_item_survives_bad_sibling_but_link_does_not(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = package(Path(tmp)); v = p['candidate']
            second = copy.deepcopy(v['items'][0]); second.update(id='bad', box=dict(left=300, top=200, right=700, bottom=800))
            v['items'].append(second)
            v['links'] = [dict(id='r', from_ids=['m'], to_ids=['bad'], kind='emphasis', direction='not_applicable', evidence='visible')]
            a = audit(v); a['checks'][1]['content'] = 'uncertain'
            result = apply_checked(p['base'], v, p['task'], p['view'], p['ocr'], p['ocr_coverage'], a)
            states = {d['id']: d['status'] for d in result['decisions']}
            self.assertEqual(states, {'m': 'model_source_checked', 'bad': 'held', 'r': 'held'})
            self.assertEqual(len(result['records']), 1)

    def test_audit_duplicate_ids_blocks_all_application(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = package(Path(tmp)); a = audit(p['candidate']); a['checks'] *= 2
            result = apply_checked(p['base'], p['candidate'], p['task'], p['view'], p['ocr'], p['ocr_coverage'], a)
            self.assertFalse(result['audit_contract_valid']); self.assertFalse(result['records'])

    def test_ocr_conflict_blocks_even_when_model_agrees(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = package(Path(tmp)); item = p['candidate']['items'][0]; item.update(kind='handwriting', text='0')
            w, h = p['view']['size']
            ocr = {'state': 'candidate', 'words': [{'text': 'o', 'score': .99, 'bbox_pixels': [w*.2, h*.2, w*.8, h*.8]}]}
            r = apply_checked(p['base'], p['candidate'], p['task'], p['view'], ocr, p['ocr_coverage'], audit(p['candidate']))
            self.assertFalse(r['changes']); self.assertFalse(r['records'])
            self.assertIn('ocr_text_conflict', r['decisions'][0]['reasons'])

    def test_new_crop_uses_source_pixels_and_preserves_source_coordinates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); p = package(root); old = p['view']; source_hash = digest_file(p['task']['current_image'])
            new = recheck_view(p['task'], old, root/'wider')
            moved = transform_visual(p['candidate'], old, new)
            back = transform_visual(moved, new, old)
            for k, v in p['candidate']['items'][0]['box'].items():
                self.assertAlmostEqual(back['items'][0]['box'][k], v)
            self.assertEqual(digest_file(p['task']['current_image']), source_hash)
            self.assertTrue(new['core_unchanged'])

    def test_duplicate_new_item_is_not_applied(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = package(Path(tmp)); p['candidate']['items'].append({**copy.deepcopy(p['candidate']['items'][0]), 'id': 'duplicate'})
            r = apply_checked(p['base'], p['candidate'], p['task'], p['view'], p['ocr'], p['ocr_coverage'], audit(p['candidate']))
            self.assertFalse(r['changes']); self.assertFalse(r['records'])
            self.assertTrue(all('possible_duplicate_item' in d['reasons'] for d in r['decisions']))

    def test_unsupported_cancellation_meaning_stays_held(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = package(Path(tmp)); p['candidate']['items'][0]['cancelled'] = True
            a = audit(p['candidate']); a['checks'][0]['meaning'] = 'uncertain'
            r = apply_checked(p['base'], p['candidate'], p['task'], p['view'], p['ocr'], p['ocr_coverage'], a)
            self.assertFalse(r['changes']); self.assertFalse(r['effective_inventory']['items'][0]['cancelled'])

    def test_invalid_missing_box_blocks_application(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = package(Path(tmp)); a = audit(p['candidate'], missing=[dict(description='bad', box=dict(left=-100, top=0, right=2, bottom=3))])
            result = apply_checked(p['base'], p['candidate'], p['task'], p['view'], p['ocr'], p['ocr_coverage'], a)
            self.assertFalse(result['records']); self.assertFalse(result['coverage_complete'])

    def test_repair_then_fresh_audit_applies_new_version_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); p = package(root); before = copy.deepcopy(p); fake = Fake()
            r = execute(p, root, {'model': 'fake'}, fake)
            self.assertEqual(p, before); self.assertEqual(len(r['changes']), 1)
            self.assertEqual(r['effective_inventory']['items'][0]['box']['left'], 200)
            self.assertEqual(len(fake.calls), 3); self.assertTrue(r['coverage_complete'])
            self.assertFalse(r['gold_approved']); self.assertFalse(r['records'][0]['approved_for_rag'])
            self.assertTrue(all(all(m.suffix != '.wav' for m in call[1]) for call in fake.calls))
            self.assertTrue(all('SECRET_AUDIO_HINT' not in call[2] for call in fake.calls))

    def test_failed_final_audit_never_applies_repair(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = package(Path(tmp)); r = execute(p, Path(tmp), {'model': 'fake'}, Fake(fail_final=True))
            self.assertFalse(r['changes']); self.assertEqual(r['effective_inventory'], {**p['base'], 'complete': False})

    def test_interrupted_final_audit_resumes_without_repair_repeat(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = package(Path(tmp)); plan = {'model': 'fake'}
            with self.assertRaises(Blocked): execute(p, Path(tmp), plan, Fake(stop='final_source_reaudit'))
            second = Fake(); execute(p, Path(tmp), plan, second)
            self.assertEqual(len(second.calls), 1); self.assertTrue(second.calls[0][0].endswith('final_source_reaudit'))

    def test_prepare_and_resume_never_construct_api_and_hash_changes_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); p = package(root); source = root/'source'; source.mkdir()
            old = {'model': 'fake', 'input_hashes': {}, 'tasks': [p['task']]}
            save(source/'plan.json', old)
            save(source/'results/case.json', {'plan_signature': signature(old), 'inventory': p['base'], 'final_view': p['view']})
            out = root/'out'
            with patch('video_extraction.ink.correction.ink_recheck.Gemini', side_effect=AssertionError('API forbidden')):
                prepare(source, out)
                plan = check_plan(out); prepared = read(Path(plan['tasks'][0]['package']))
                result = execute(prepared, out, plan, Fake()); save(out/'results/case.json', result)
                self.assertEqual(run(out, root/'.env')['processed'], 1)
            Path(p['view']['path']).write_bytes(b'changed')
            with self.assertRaises(ValueError): check_plan(out)


if __name__ == '__main__': unittest.main()
