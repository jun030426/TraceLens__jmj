from video_extraction._layout import PACKAGE_ROOT
import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw

from video_extraction.shared.common import read, signature, digest_file
from video_extraction.ink.correction.ink_discrepancy import ROOT, character_differences, pixel_probe, symbol_context, apply_review, refresh_relations, build

SOURCE=ROOT/'outputs/ink-recovery-v1'
RECEIPTS=PACKAGE_ROOT/'fixtures/ink_discrepancy/source-reviews.json'


def case(tid):
    return read(SOURCE/'prepared'/(tid+'.json')),read(SOURCE/'results'/(tid+'.json')),read(RECEIPTS)[tid]


class InkDiscrepancyTests(unittest.TestCase):
    def test_real_colon_difference_and_span(self):
        differences=character_differences('"김민수":','"김민수".')
        self.assertEqual(len(differences),1)
        self.assertEqual(differences[0]['observed_span'],[5,6])
        self.assertEqual(differences[0]['category'],'punctuation_shape_confusion')

    def test_real_method_differences_are_not_lexical(self):
        diffs=character_differences('union(), intersection(), difference(), symmetric_difference()',
                                   'unionO, intersectionO, differenceO, symmetric differenceO')
        self.assertEqual(len(diffs),5)
        self.assertEqual({d['category'] for d in diffs},{'punctuation_shape_confusion'})

    def test_words_digits_case_not_normalized(self):
        for a,b in [('김민수','김민서'),('0','o'),('O','0'),('x1','x2'),('List','list'),('a-b','a+b')]:
            self.assertIn('lexical_numeric_or_other',[d['category'] for d in character_differences(a,b)])
        self.assertFalse(character_differences('O.foo()','O.foo()'))

    def test_source_pixel_probes(self):
        for tid in ('frame-00094-ink-001','frame-00112-ink-003'):
            p,_,receipt=case(tid)
            for q in receipt['probes']:
                r=pixel_probe(p['task']['evidence']['selected_frame'],q['roi'],q['kind'])
                self.assertEqual(r['state'],'shape_support_only')
                self.assertFalse(r['automatic_release']);self.assertFalse(r['text_rewritten'])
                if q['kind']=='colon': self.assertEqual(r['row_runs'],[[4,7],[10,13]])
                if q['kind']=='underscore': self.assertGreater(r['colored_pixels'],0)

    def test_period_and_letter_o_do_not_pass_other_shape_probe(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'image.png'
            im=Image.new('RGB',(30,30),'white');draw=ImageDraw.Draw(im);draw.rectangle((14,22,16,24),fill='black');im.save(path)
            self.assertEqual(pixel_probe(path,[0,0,30,30],'colon')['state'],'insufficient_pixel_evidence')
            im=Image.new('RGB',(30,30),'white');ImageDraw.Draw(im).ellipse((5,3,24,26),outline='black',width=3);im.save(path)
            self.assertEqual(pixel_probe(path,[0,0,30,30],'parentheses_pair')['state'],'insufficient_pixel_evidence')
            with self.assertRaises(ValueError): pixel_probe(path,[-1,0,30,30],'colon')

    def test_context_suggests_pair_not_symbol_meaning(self):
        p,r,_=case('frame-00007-ink-001');item=r['candidate']['items'][0]
        context=symbol_context(p['task']['evidence']['selected_frame'],item['box'],r['final_view'])
        self.assertEqual(context['suggestion'],'paired_symbol_candidate')
        self.assertTrue(context['aligned_right_components'])
        self.assertIsNone(context['exact_symbol']);self.assertIsNone(context['meaning'])
        self.assertFalse(context['automatic_reclassification'])

    def test_all_five_real_cases_preserve_source_and_admin(self):
        changed=[]
        for tid in read(RECEIPTS):
            p,r,receipt=case(tid);original=copy.deepcopy(r)
            updated=apply_review(p,r,receipt)
            self.assertEqual(r,original)
            self.assertEqual(updated['administrator_queue'],r['administrator_queue'])
            self.assertEqual(updated['final_audit'],r['final_audit']) # Never fabricate an audit.
            changed+=updated['review_changes']
            self.assertEqual(updated['api_requests'],0)
        self.assertEqual(len(changed),5)
        self.assertEqual(sum(c['after_status']=='usable_with_warning' for c in changed),4)
        self.assertEqual(sum(c['after_status']=='symbol_observed_meaning_unresolved' for c in changed),1)

    def test_text_and_relations_released_without_changing_literal(self):
        for tid,iid,lid in [('frame-00094-ink-001','item_11','link_5'),('frame-00112-ink-003','item-8','link-4')]:
            p,r,receipt=case(tid);after=apply_review(p,r,receipt)
            for key in ('items','links'): self.assertEqual(after['candidate'][key],r['candidate'][key])
            decisions={d['id']:d for d in after['decisions']}
            self.assertEqual(decisions[iid]['status'],'usable_with_warning')
            self.assertEqual(decisions[lid]['relation_validation'],dict(own_status='checked',target_status='checked'))
            self.assertTrue(after['active_coverage_complete'])
            self.assertTrue({iid,lid} <= {v['local_id'] for v in after['records']})

    def test_bracket_has_no_invented_character_or_semantic_assertion(self):
        p,r,receipt=case('frame-00007-ink-001');after=apply_review(p,r,receipt)
        item=after['candidate']['items'][0]
        self.assertEqual(item['kind'],'bracket');self.assertEqual(item['text'],'')
        row=next(x for x in after['records'] if x['local_id']==item['id'])
        self.assertIsNone(row['exact_symbol']);self.assertIsNone(row['meaning'])
        self.assertEqual(row['original_observation']['text'],'ㄷ')
        self.assertFalse(row['usable_for_semantic_assertion']);self.assertFalse(row['approved_for_rag'])
        self.assertTrue(after['visual_review_complete']);self.assertFalse(after['active_coverage_complete'])

    def test_receipt_not_reusable_on_other_pixels_or_candidate(self):
        p,r,receipt=case('frame-00094-ink-001')
        r['candidate']['items'][0]['text']='modified'
        with self.assertRaisesRegex(ValueError,'review_result_changed'): apply_review(p,r,receipt)
        p,r,receipt=case('frame-00094-ink-001');receipt['source_sha256']='bad'
        with self.assertRaisesRegex(ValueError,'review_source_changed'): apply_review(p,r,receipt)
        p,r,receipt=case('frame-00094-ink-001');receipt['entries'][0]['item_signature']='bad'
        with self.assertRaisesRegex(ValueError,'review_item_changed'): apply_review(p,r,receipt)

    def test_extra_error_cannot_be_waived_by_ocr_review(self):
        p,r,receipt=case('frame-00094-ink-001')
        next(d for d in r['decisions'] if d['id']=='item_11')['reasons'].append('invalid_crop_box')
        receipt['result_signature']=signature(r)
        with self.assertRaisesRegex(ValueError,'additional_unresolved_reason'): apply_review(p,r,receipt)

    def test_relation_own_fault_survives_target_release(self):
        p,r,receipt=case('frame-00094-ink-001')
        d=next(d for d in r['decisions'] if d['id']=='link_5');d['reasons'].append('direction_without_endpoints')
        receipt['result_signature']=signature(r)
        after=apply_review(p,r,receipt)
        d=next(d for d in after['decisions'] if d['id']=='link_5')
        self.assertEqual(d['status'],'held');self.assertEqual(d['relation_validation']['own_status'],'unresolved')

    def test_relation_keeps_own_check_when_target_held(self):
        _,r,_=case('frame-00094-ink-001');refresh_relations(r)
        d=next(d for d in r['decisions'] if d['id']=='link_5')
        self.assertEqual(d['relation_validation'],dict(own_status='checked',target_status='unresolved'))
        self.assertEqual(d['status'],'held')

    def test_end_to_end_build_offline_and_no_stale_old_record(self):
        before={str(f):digest_file(f) for f in (SOURCE/'results').glob('*.json')}
        with tempfile.TemporaryDirectory() as tmp, patch('video_extraction.shared.gemini.Gemini',side_effect=AssertionError('API forbidden')):
            out=Path(tmp)/'review';summary=build(SOURCE,RECEIPTS,out)
            self.assertEqual(summary['reviewed_items'],5);self.assertEqual(summary['released_false_positive_items'],4)
            self.assertEqual(summary['held_items'],0);self.assertEqual(summary['symbol_meaning_unresolved'],1)
            self.assertEqual(summary['administrator_entries'],9)
            import json
            rows=[json.loads(l) for l in (out/'records.jsonl').read_text().splitlines()]
            keys=[(x['adapter'],x['local_id']) for x in rows]
            self.assertEqual(len(keys),len(set(keys)))
            self.assertEqual((out/'administrator-review.jsonl').read_text(),(SOURCE/'administrator-review.jsonl').read_text())
        self.assertEqual(before,{str(f):digest_file(f) for f in (SOURCE/'results').glob('*.json')})


if __name__=='__main__': unittest.main()
