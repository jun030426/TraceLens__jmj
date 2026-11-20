import copy
import unittest

from video_extraction.video.annotation_duplicate_review import apply_decisions
from video_extraction.video.vision import duplicate_addition
from video_extraction.shared.common import signature
from video_extraction.video.source_coordinate_review import matching_decision


class AnnotationReviewTests(unittest.TestCase):
    def setUp(self):
        self.block={'id':'text-1','kind':'code','text':'[10, 20]','bbox':[100,100,300,300],'uncertainties':[]}
        self.hold={'reason':'duplicate_addition','region':{'target_id':'NEW','bbox':[100,100,300,300],
                   'kind':'annotation','issue':'omission','reason':'Red circle around bracket'}}
        self.original={'frame_id':'frame-1','final_blocks':[self.block],'holds':[self.hold,{'reason':'unrelated'}],
                       'text':self.block['text']}
        self.row={'index':0,'frame_id':'frame-1','image_sha256':'hash','hold':self.hold,
                  'decision':'missing_annotation','reason':'Ink was omitted',
                  'visual':{'id':'ink-1','kind':'annotation','bbox':[100,100,300,300],
                    'description':'Red circle around the printed bracket','literal_text':'',
                    'related_block_ids':['text-1'],'uncertainties':[]}}

    def test_printed_text_and_overlapping_ink_are_not_duplicates(self):
        ink={**self.block,'id':'ink','kind':'annotation','text':'Red circle'}
        self.assertFalse(duplicate_addition(ink,[self.block]))
        # Even equal strings in distinct layers must not be conflated.
        self.assertFalse(duplicate_addition({**ink,'text':self.block['text']},[self.block]))

    def test_same_text_elsewhere_must_not_be_discarded(self):
        self.assertFalse(duplicate_addition({**self.block,'bbox':[500,500,700,700]},[self.block]))
        self.assertFalse(duplicate_addition({**self.block,'text':'[30, 40]'},[self.block]))

    def test_exact_same_kind_content_and_region_is_duplicate(self):
        self.assertTrue(duplicate_addition({**self.block,'id':'another'},[self.block]))

    def test_missing_mark_added_without_copying_printed_text_or_clearing_other_holds(self):
        result=apply_decisions(self.original,[self.row],'hash')
        self.assertEqual(result['final_blocks'],self.original['final_blocks'])
        self.assertEqual(result['visuals'][0]['literal_text'],'')
        self.assertEqual(result['holds'],[{'reason':'unrelated'}])
        self.assertEqual(result['annotation_duplicate_review']['archived_holds'],[self.hold])
        self.assertNotIn('visuals',self.original)
        with self.assertRaises(ValueError):apply_decisions(result,[self.row],'hash')

    def test_uncertain_handwriting_is_preserved_as_pending(self):
        row=copy.deepcopy(self.row);row['decision']='partial_coverage_unresolved_literal'
        row['visual'].update(literal_text='[ILLEGIBLE]',uncertainties=['Cannot read handwritten word'])
        result=apply_decisions(self.original,[row],'hash')
        self.assertEqual(result['holds'][-1]['reason'],'manual_handwriting_unresolved')
        self.assertEqual(result['holds'][-1]['target_id'],'ink-1')
        self.assertEqual(result['visuals'][0]['literal_text'],'[ILLEGIBLE]')

    def test_source_hold_and_ids_must_match(self):
        with self.assertRaises(ValueError):apply_decisions(self.original,[self.row],'other-hash')
        changed=copy.deepcopy(self.original);changed['holds']=[]
        with self.assertRaises(ValueError):apply_decisions(changed,[self.row],'hash')
        row=copy.deepcopy(self.row);row['visual']['id']='text-1'
        with self.assertRaises(ValueError):apply_decisions(self.original,[row],'hash')

    def test_summary_correction_preserves_reviewed_bounds(self):
        original=copy.deepcopy(self.original);block=original['final_blocks'][0]
        original['source_coordinate_review']={'decisions':[{'target_id':block['id'],'decision':'corrected',
            'image_sha256':'hash','reviewed_block_signature':signature(block)}]}
        row=copy.deepcopy(self.row);row['text_patch']={'target_id':block['id'],'before':block['text'],
                                                    'after':'Summary; exact handwriting is pending in ink-1.'}
        result=apply_decisions(original,[row],'hash')
        after=result['final_blocks'][0];self.assertEqual(after['bbox'],block['bbox'])
        self.assertIsNotNone(matching_decision(after,'hash',result['source_coordinate_review']['decisions']))
        self.assertIn('previous_block_signature',result['source_coordinate_review']['decisions'][0])
        row=copy.deepcopy(self.row);row['visual']['related_block_ids']=['missing']
        with self.assertRaises(ValueError):apply_decisions(self.original,[row],'hash')


if __name__=='__main__':unittest.main()
