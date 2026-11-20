import copy
import unittest
from video_extraction.shared.impact_policy import hold_for_administrator,CONSUMERS


class ImpactPolicyTests(unittest.TestCase):
    def test_all_modalities_hold_and_preserve_original(self):
        for modality in ['ppt','pdf','video_frame','image','audio','handwriting','screen_text']:
            with self.subTest(modality=modality):
                original={'id':'a','modality':modality,'observed_text':'원문 반복 반복',
                          'raw_payload':{'source':'original'},'eligible_for_chunking':True,
                          'approved_for_rag':True,'selection_reasons':['older_hold']}
                before=copy.deepcopy(original)
                result=hold_for_administrator(original,'근거에 따른 낮은 영향 판정',{'source_review':'test'})
                self.assertEqual(original,before)
                self.assertEqual(result['observed_text'],before['observed_text'])
                self.assertEqual(result['raw_payload'],before['raw_payload'])
                self.assertFalse(result['eligible_for_chunking']);self.assertFalse(result['approved_for_rag'])
                self.assertTrue(all(result['eligible_for_generation'][key] is False for key in CONSUMERS))
                self.assertIn('older_hold',result['selection_reasons'])
                self.assertEqual(result['impact_review']['route'],'administrator')
                self.assertEqual(hold_for_administrator(result,'근거에 따른 낮은 영향 판정',{'source_review':'test'}),result)

    def test_no_unsupported_low_impact_claim(self):
        for reason,evidence in [('',{'a':1}),('low',{})]:
            with self.assertRaises(ValueError):hold_for_administrator({},reason,evidence)
