import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw

from video_extraction.shared.common import save, read, signature
from video_extraction.shared.gemini import Blocked
from video_extraction.tests.test_ink_recheck import package
from video_extraction.ink.policy.ink_policy import particle_pair, admin_ids, word_edges, assessment, apply_policy, execute, prepare, run, check_plan, speech_hints


def text_package(root, text='순서가'):
    p = package(root); p['candidate']['items'][0].update(kind='printed_text', text=text)
    p['base'] = copy.deepcopy(p['candidate'])
    w, h = p['view']['size']
    p['ocr'] = {'state': 'candidate', 'words': [{'text': '순서', 'score': .99, 'bbox_pixels': [w*.2, h*.2, w*.8, h*.8]}]}
    return p


def audit(value, required=None):
    return {'checks': [{'id': x['id'], 'content': 'supported', 'geometry': 'supported',
        'meaning': 'supported', 'reason': 'direct source and context', 'full_text': x.get('text', ''),
        'lexical_complete': True, 'meaning_preserved': True, 'role_risk': False,
        'role': 'text' if x.get('text') else 'simple_emphasis', 'split_required': False,
        'critical': False, 'uncertainty_scope': 'none'} for x in value['items']+value['links']
        if required is None or x['id'] in required], 'missing': [], 'complete': True}


class Fake:
    def __init__(self, stop=None): self.calls = []; self.stats = {'requests': 0}; self.stop = stop
    def call(self, name, media, prompt, schema):
        self.calls.append((name, media, prompt)); self.stats['requests'] += 1
        if self.stop and name.endswith(self.stop): raise Blocked('request_budget_exhausted')
        data = json.loads(prompt.split('DATA:\n', 1)[1]); value = data['candidate']
        if name.endswith('whole_word_targeted_repair'):
            value['items'][0]['text'] = '응용 예제'; return value
        result = audit(value, data['required_ids'])
        if value['items'][0]['text'] == '용 예제':
            result['checks'][0]['full_text'] = '응용 예제'
            # Deliberately inconsistent supported response: local comparison must catch it.
        return result


class InkPolicyTests(unittest.TestCase):
    def test_particle_eligibility_is_narrow(self):
        self.assertTrue(particle_pair('순서가', '순서'))
        self.assertTrue(particle_pair('집합은 순서가 없다', '집합은 순서 없다'))
        for a, b in [('응용', '용'), ('사과', '사'), ('변수 0', '변수 o'), ('x가', 'x'),
                     ('나는 너를', '나 너'), ('순서 없음', '순서 있음'), ('순서가', '순서를')]:
            self.assertFalse(particle_pair(a, b), (a, b))

    def test_particle_ocr_conflict_requires_semantic_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = text_package(Path(tmp)); a = audit(p['candidate']); before = copy.deepcopy(p)
            r = apply_policy(p, p['candidate'], a)
            self.assertEqual(r['decisions'][0]['status'], 'usable_with_warning')
            self.assertIn('meaning_preserving_particle_ocr_difference', r['decisions'][0]['warnings'])
            self.assertEqual(p, before); self.assertFalse(r['changes'])
            a['checks'][0]['role_risk'] = True
            r = apply_policy(p, p['candidate'], a)
            self.assertEqual(r['decisions'][0]['status'], 'held')

    def test_missing_particle_preserved_as_observation_not_invented(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = text_package(Path(tmp), '순서'); a = audit(p['candidate'])
            a['checks'][0].update(full_text='순서가', content='partial')
            r = apply_policy(p, p['candidate'], a)
            self.assertEqual(r['records'][0]['raw_payload']['raw']['text'], '순서')
            self.assertEqual(r['records'][0]['source_complete_text_candidate'], '순서가')
            self.assertEqual(r['decisions'][0]['status'], 'usable_with_warning')

    def test_code_particle_like_suffix_never_waived(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = text_package(Path(tmp)); p['candidate']['items'][0]['kind'] = 'code'
            r = apply_policy(p, p['candidate'], audit(p['candidate']))
            self.assertEqual(r['decisions'][0]['status'], 'held')

    def test_admin_writing_does_not_block_healthy_sibling(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = package(Path(tmp)); deleted = copy.deepcopy(p['candidate']['items'][0])
            deleted.update(id='deleted', kind='handwriting', text='', cancelled=True, uncertainties=['text'])
            p['candidate']['items'].append(deleted)
            a = audit(p['candidate'], {'m'}); r = apply_policy(p, p['candidate'], a)
            self.assertTrue(r['active_coverage_complete']); self.assertFalse(r['all_review_resolved'])
            self.assertEqual([r['local_id'] for r in r['records']], ['m'])
            self.assertEqual(len(r['administrator_queue']), 1)
            self.assertFalse(r['administrator_queue'][0]['usable_as_active_knowledge'])
            self.assertIn('source_image', r['administrator_queue'][0])

    def test_cancellation_relations_also_go_to_admin(self):
        v = {'items': [dict(id='text', cancelled=True), dict(id='cross', cancelled=False)],
             'links': [dict(id='cancel', from_ids=['cross'], to_ids=['text'], kind='cancellation')]}
        self.assertEqual(admin_ids(v), {'text', 'cross', 'cancel'})

    def emphasis_package(self, root):
        p = package(root); target = copy.deepcopy(p['candidate']['items'][0])
        target.update(id='text', kind='printed_text', text='중복 허용', box=dict(left=300, top=250, right=700, bottom=750))
        p['candidate']['items'].append(target)
        p['candidate']['items'][0]['uncertainties'] = ['overlapping circles']
        p['candidate']['links'] = [dict(id='r', from_ids=['m'], to_ids=['text'], kind='emphasis', direction='not_applicable', evidence='visible target')]
        return p

    def test_overlap_only_simple_emphasis_becomes_group_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = self.emphasis_package(Path(tmp)); a = audit(p['candidate'])
            a['checks'][0].update(content='partial', uncertainty_scope='segmentation_only')
            r = apply_policy(p, p['candidate'], a)
            d = r['decisions'][0]
            self.assertEqual(d['status'], 'usable_with_warning'); self.assertEqual(d['representation'], 'emphasis_region')
            self.assertFalse(d['reasons'])

    def test_critical_emphasis_and_unknown_target_are_not_waived(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = self.emphasis_package(Path(tmp)); a = audit(p['candidate'])
            a['checks'][0].update(content='partial', uncertainty_scope='segmentation_only', critical=True)
            self.assertEqual(apply_policy(p, p['candidate'], a)['decisions'][0]['status'], 'held')
            a['checks'][0].update(critical=False, meaning='uncertain')
            self.assertEqual(apply_policy(p, p['candidate'], a)['decisions'][0]['status'], 'held')

    def test_process_arrow_cannot_be_disguised_as_simple_emphasis(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = self.emphasis_package(Path(tmp)); p['candidate']['items'][0]['kind'] = 'arrow'
            a = audit(p['candidate']); a['checks'][0].update(content='partial', uncertainty_scope='segmentation_only')
            self.assertEqual(apply_policy(p, p['candidate'], a)['decisions'][0]['status'], 'held')

    def test_complete_word_mismatch_overrides_supported_model_vote(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = text_package(Path(tmp), '용 예제'); p['ocr'] = {'state': 'unavailable', 'words': []}
            a = audit(p['candidate']); a['checks'][0]['full_text'] = '응용 예제'
            r = apply_policy(p, p['candidate'], a)
            self.assertEqual(r['decisions'][0]['status'], 'held')
            self.assertIn('partial_word_or_expression_omission', r['decisions'][0]['reasons'])

    def test_pixel_detector_sees_glyph_before_old_box(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'glyphs.png'; im = Image.new('RGB', (100, 40), 'white'); d = ImageDraw.Draw(im)
            d.rectangle((20, 10, 29, 25), fill='black'); d.rectangle((35, 10, 44, 25), fill='black'); im.save(path)
            v = {'items': [dict(id='word', kind='printed_text', text='용', box=dict(left=350, top=200, right=450, bottom=700))]}
            result = word_edges(v, {'path': str(path)})
            self.assertIn('adjacent_glyph_requires_word_review', result['word'])

    def test_omission_repaired_then_reaudited_before_apply(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); p = text_package(root, '용 예제'); p['ocr'] = {'state': 'unavailable', 'words': []}
            fake = Fake(); r = execute(p, root, {'model': 'fake'}, fake)
            self.assertEqual(len(fake.calls), 3); self.assertEqual(r['changes'][0]['after']['text'], '응용 예제')
            self.assertTrue(fake.calls[-1][0].endswith('final_meaning_source_audit'))
            self.assertTrue(all(all(m.suffix != '.wav' for m in call[1]) for call in fake.calls))

    def test_budget_interruption_reuses_audit_and_repair(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); p = text_package(root, '용 예제'); p['ocr'] = {'state': 'unavailable', 'words': []}; plan = {'model': 'fake'}
            with self.assertRaises(Blocked): execute(p, root, plan, Fake(stop='final_meaning_source_audit'))
            fake = Fake(); r = execute(p, root, plan, fake)
            self.assertEqual(len(fake.calls), 1); self.assertEqual(len(r['changes']), 1)

    def test_malformed_audit_cannot_downgrade_conflict(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = text_package(Path(tmp)); a = audit(p['candidate']); a['checks'] *= 2
            r = apply_policy(p, p['candidate'], a)
            self.assertFalse(r['records']); self.assertFalse(r['audit_contract_valid'])

    def test_only_valid_timed_hints_are_sent(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = text_package(Path(tmp)); b = dict(item_ids=['m'], quote='test', start_seconds=11, end_seconds=12, relevance='aligned')
            p['audio_context'] = {'bindings': [b, {**b, 'end_seconds': 40}, {**b, 'item_ids': ['unknown']}]}
            self.assertEqual(speech_hints(p, p['candidate']), [b])

    def test_prepare_admin_queue_and_resume_are_offline(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); p = package(root); p['candidate']['items'][0].update(cancelled=True)
            source = root/'source'; source.mkdir(); save(source/'prepared/case.json', p)
            old = {'tasks': [{'id': 'case', 'package': str(source/'prepared/case.json')}], 'model': 'fake', 'input_hashes': {}}
            save(source/'plan.json', old)
            save(source/'results/case.json', {'plan_signature': signature(old), 'candidate': p['candidate'], 'effective_inventory': p['base']})
            out = root/'out'
            with patch('video_extraction.ink.policy.ink_policy.Gemini', side_effect=AssertionError('No API allowed')):
                summary = prepare(source, out); self.assertEqual(summary['administrator_entries'], 1)
                self.assertEqual(run(out, root/'.env')['processed'], 1)
                self.assertEqual(run(out, root/'.env')['processed'], 1)
                self.assertFalse(read(out/'results/case.json')['records'])
            Path(read(out/'plan.json')['tasks'][0]['package']).write_text('{}')
            with self.assertRaises(ValueError): check_plan(out)


if __name__ == '__main__': unittest.main()
