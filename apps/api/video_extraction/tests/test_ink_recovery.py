"""Regression cases from the two failed real batches; never calls an API."""
from video_extraction._layout import PROJECT_ROOT, PACKAGE_ROOT
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from video_extraction.shared.common import read, signature, save
from video_extraction.shared.gemini import Blocked
from video_extraction.ink.correction.ink_recovery import evaluate, normalize_emphasis, required_ids, safe_audit, source_audit, widen_to_source, execute, prepare, check_plan, run
from video_extraction.ink.correction.ink_recheck import local_check, core_box
from video_extraction.tests.test_ink_policy import audit
from video_extraction.tests.test_ink_recheck import package

FIXTURES = PACKAGE_ROOT/'fixtures/ink_recovery'


def fixture(name):
    return read(FIXTURES/(name+'.json'))


class Fake:
    def __init__(self, responses):
        self.responses = iter(responses); self.calls = []; self.stats = {'requests': 0}

    def call(self, name, media, prompt, schema):
        payload = json.loads(prompt.split('DATA:\n', 1)[1])
        self.calls.append((name, media, payload)); self.stats['requests'] += 1
        response = next(self.responses)
        if isinstance(response, Exception): raise response
        return response(payload) if callable(response) else copy.deepcopy(response)


class InkRecoveryTests(unittest.TestCase):
    def test_all_real_failures_no_source_mutation(self):
        before_count = after_count = normalizations = 0; complete = []
        for path in sorted(FIXTURES.glob('*.json')):
            f = read(path); before = copy.deepcopy(f); p = f['package']
            r = evaluate(p, p['candidate'], f['audit'])
            before_count += sum(d['status']=='held' for d in f['previous_decisions'])
            after_count += sum(d['status']=='held' for d in r['decisions'])
            normalizations += len(r['format_normalizations'])
            if r['active_coverage_complete']: complete.append(path.stem)
            self.assertEqual(f, before)
            self.assertFalse(r['gold_approved']); self.assertIsNone(r['accuracy'])
        self.assertEqual((before_count, after_count, normalizations), (33,22,8))
        self.assertEqual(complete, ['frame-00003-ink-003','frame-00004-ink-000','frame-00013-ink-000'])

    def test_missing_four_relations_preserves_four_healthy_items(self):
        f = fixture('frame-00006-ink-004'); p = f['package']
        r = evaluate(p, p['candidate'], f['audit'])
        self.assertEqual(r['unresolved_audit_ids'], ['link_2','link_3','link_4','link_5'])
        states = {d['id']: d['status'] for d in r['decisions']}
        for i in ('item_3','item_4','item_5','item_6'): self.assertNotEqual(states[i], 'held')
        self.assertEqual(states['item_7'], 'held')  # Unknown handwriting not waved through.
        self.assertFalse(r['active_coverage_complete'])

    def test_normalization_never_changes_arrows_process_unknown_or_admin(self):
        f = fixture('frame-00004-ink-000'); p = f['package']; v = p['candidate']
        for mutation in ('sequence','arrow','cancelled','unknown','critical','target_missing'):
            value = copy.deepcopy(v); a = copy.deepcopy(f['audit']); link = value['links'][0]
            iid = link['id']; source = next(x for x in value['items'] if x['id']==link['from_ids'][0])
            c = next(c for c in a['checks'] if c['id']==iid)
            if mutation=='sequence': link['kind']='sequence'
            if mutation=='arrow': source.update(kind='arrow', arrow_points=[{'x':100,'y':100},{'x':200,'y':200}])
            if mutation=='cancelled': source['cancelled']=True
            if mutation=='unknown': c['role']='unknown'
            if mutation=='critical': c['critical']=True
            if mutation=='target_missing': link['to_ids']=['absent']
            result, edits = normalize_emphasis(value,a,required_ids(p,value))
            self.assertNotIn(iid, [e['id'] for e in edits], mutation)
            self.assertEqual(result['links'][0]['direction'], 'observed')

    def test_duplicate_check_not_last_wins_and_extra_ignored(self):
        f = fixture('frame-00006-ink-004'); p = f['package']; a = copy.deepcopy(f['audit'])
        a['checks'].append(copy.deepcopy(a['checks'][0])); a['checks'].append({**a['checks'][1], 'id':'foreign'})
        safe, unresolved, extra = safe_audit(a, required_ids(p,p['candidate']))
        self.assertIn('item_3',unresolved); self.assertEqual(extra, {'foreign'})
        self.assertEqual(next(c for c in safe['checks'] if c['id']=='item_3')['content'],'uncertain')

    def test_fill_only_missing_ids_and_keep_good_checks(self):
        f = fixture('frame-00006-ink-004'); p = f['package']
        fake = Fake([f['audit'], lambda d:audit(d['candidate'], set(d['required_ids']))])
        with tempfile.TemporaryDirectory() as tmp:
            a, trace = source_audit(p,p['candidate'],Path(tmp),{'test':1},fake,'test')
        self.assertEqual(set(fake.calls[1][2]['required_ids']), {'link_2','link_3','link_4','link_5'})
        self.assertEqual(trace['unresolved_ids'], [])
        for old in f['audit']['checks']: self.assertIn(old,a['checks'])

    def test_fill_missing_again_stops_after_two_calls(self):
        f = fixture('frame-00006-ink-004'); p = f['package']
        fake = Fake([f['audit'],dict(checks=[],missing=[],complete=True)])
        with tempfile.TemporaryDirectory() as tmp:
            a, trace = source_audit(p,p['candidate'],Path(tmp),{'test':1},fake,'test')
        self.assertEqual(len(fake.calls),2); self.assertEqual(len(trace['unresolved_ids']),4)
        self.assertEqual(len(evaluate(p,p['candidate'],a)['unresolved_audit_ids']),4)

    def test_resume_uses_saved_first_audit_no_repeat(self):
        f = fixture('frame-00006-ink-004'); p = f['package']
        with tempfile.TemporaryDirectory() as tmp:
            fake=Fake([f['audit'],Blocked('request_budget_exhausted')])
            with self.assertRaises(Blocked): source_audit(p,p['candidate'],Path(tmp),{'test':1},fake,'test')
            resumed=Fake([lambda d:audit(d['candidate'],set(d['required_ids']))])
            source_audit(p,p['candidate'],Path(tmp),{'test':1},resumed,'test')
            self.assertEqual(len(resumed.calls),1)
            self.assertTrue(resumed.calls[0][0].endswith('_fill_ids'))

    def test_wider_source_transforms_pixels_scope_and_both_ocr_variants(self):
        for name in ('frame-00011-ink-001','frame-00094-ink-001'):
            p=fixture(name)['package']; old=copy.deepcopy(p); wide=widen_to_source(p)
            self.assertEqual(p,old); self.assertEqual(wide['view']['crop_in_source'],[0,0,1,1])
            self.assertEqual(required_ids(p,p['candidate']),required_ids(wide,wide['candidate']))
            a,b,c,d=p['view']['crop_in_source']; w,h=wide['view']['size']
            for x,y in zip(p['candidate']['items'],wide['candidate']['items']):
                self.assertAlmostEqual(y['box']['left']/1000*w,(a+x['box']['left']/1000*(c-a))*w)
            for key in ('words','alternative_words'):
                for x,y in zip(p['ocr'].get(key,[]),wide['ocr'].get(key,[])):
                    self.assertAlmostEqual(y['bbox_pixels'][0],(a+x['bbox_pixels'][0]/p['view']['size'][0]*(c-a))*w)
            _,local,_=local_check(wide['candidate'],wide['task'],wide['view'],wide['ocr'],wide['ocr_coverage'])
            self.assertFalse(any('required_item_touches_crop_boundary' in f['blocking'] for f in local.values()))
            self.assertLess(wide['ocr_coverage']['right']-wide['ocr_coverage']['left'],1000)

    def test_direction_only_execute_no_semantic_repair(self):
        f=fixture('frame-00004-ink-000'); p=f['package']; fake=Fake([f['audit']])
        with tempfile.TemporaryDirectory() as tmp: result=execute(p,Path(tmp),{'test':1},fake)
        self.assertEqual(len(fake.calls),1); self.assertFalse(result['repair_used'])
        self.assertTrue(result['active_coverage_complete'])
        self.assertEqual({c['change_type'] for c in result['changes']},{'format_normalization'})

    def test_zero_o_cannot_be_fixed_by_context_vote(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=package(Path(tmp)); p['candidate']['items'][0].update(kind='handwriting',text='0')
            p['base']=copy.deepcopy(p['candidate']); a=audit(p['candidate'])
            a['checks'][0]['full_text']='o'
            r=evaluate(p,p['candidate'],a)
        self.assertEqual(r['decisions'][0]['status'],'held')
        self.assertFalse(r['changes']); self.assertEqual(r['effective_inventory']['items'][0]['text'],'0')

    def test_failed_final_audit_does_not_apply_patch(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=package(Path(tmp)); p['candidate']['items'][0].update(kind='handwriting',text='용')
            p['base']=copy.deepcopy(p['candidate']); p['failed_ids']=['m']
            first=audit(p['candidate']); first['checks'][0]['full_text']='응용'
            def repair(d):
                v=copy.deepcopy(d['candidate']); v['items'][0]['text']='응용'; return v
            def final(d):
                a=audit(d['candidate']); a['checks'][0]['content']='uncertain'; return a
            r=execute(p,Path(tmp),{'test':1},Fake([first,repair,final]))
        self.assertFalse(r['changes']); self.assertEqual(r['effective_inventory']['items'][0]['text'],'용')
        self.assertEqual(r['candidate']['items'][0]['text'],'응용')

    def test_saved_audit_cannot_attach_to_changed_candidate(self):
        f=fixture('frame-00004-ink-000'); p=f['package']
        with tempfile.TemporaryDirectory() as tmp:
            source_audit(p,p['candidate'],Path(tmp),{'test':1},Fake([f['audit']]),'test')
            changed=copy.deepcopy(p['candidate']); changed['items'][0]['text']='changed'
            with self.assertRaisesRegex(ValueError,'stale_stage'):
                source_audit(p,changed,Path(tmp),{'test':1},Fake([]),'test')

    def test_repair_requires_final_audit_and_cannot_overwrite_healthy_item(self):
        f=fixture('frame-00006-ink-000'); p=f['package']
        healthy=next(x for x in p['candidate']['items'] if x['id'] not in p['failed_ids'])
        def malicious_patch(d):
            v=copy.deepcopy(d['candidate'])
            next(x for x in v['items'] if x['id']==healthy['id'])['text']='UNAUTHORIZED'
            return v
        fake=Fake([f['audit'],malicious_patch,lambda d:audit(d['candidate'],set(d['required_ids']))])
        with tempfile.TemporaryDirectory() as tmp: r=execute(p,Path(tmp),{'test':1},fake)
        self.assertEqual(len(fake.calls),3); self.assertTrue(r['repair_used'])
        self.assertEqual(next(x for x in r['candidate']['items'] if x['id']==healthy['id']),healthy)
        self.assertTrue(fake.calls[-1][0].endswith('recovery_final_audit'))

    def test_prepare_offline_only_and_input_tampering_detected(self):
        # Use immutable production receipts, not annotations or a fabricated success.
        source=PROJECT_ROOT/'outputs/ink-continuation-v1'
        with tempfile.TemporaryDirectory() as tmp, patch('video_extraction.ink.correction.ink_recovery.Gemini',side_effect=AssertionError('API forbidden')):
            out=Path(tmp)/'new'; summary=prepare(source,out); plan=check_plan(out)
            self.assertEqual((summary['failed_regions'],summary['api_regions'],summary['complete_regions']),(9,6,3))
            self.assertEqual(summary['format_changes'],5)
            package=Path(plan['tasks'][0]['package']); package.write_text(package.read_text()+' ')
            with self.assertRaisesRegex(ValueError,'changed_input'): check_plan(out)


if __name__=='__main__': unittest.main()
