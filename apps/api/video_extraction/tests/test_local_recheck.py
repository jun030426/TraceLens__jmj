from pathlib import Path
import tempfile
import unittest

from PIL import Image,ImageDraw

from video_extraction.video.bbox_cutoff import cutoff_evidence
from video_extraction.shared.multimodal_checks import finding, grouped_findings, inspect_frame
from video_extraction.video.local_recheck import check_output


class LocalCheckTests(unittest.TestCase):
    def test_recheck_output_cannot_overlap_original_data(self):
        root=Path('/tmp/recheck-protected')
        for out in [root,root/'nested',root.parent]:
            with self.assertRaises(ValueError):check_output(out,[root])
        check_output(Path('/tmp/recheck-separate'),[root])

    def glyph(self,color='black'):
        im=Image.new('RGB',(100,70),'white')
        ImageDraw.Draw(im).rectangle((20,20,30,36),outline=color,width=2)
        return im

    def test_cut_letter_is_still_flagged_on_each_edge(self):
        for box in [(25,10,50,50),(10,10,25,50),(10,27,50,50),(10,10,50,27)]:
            evidence=cutoff_evidence(self.glyph(),box)
            self.assertIsNotNone(evidence)
            self.assertEqual(evidence['thresholds'],[110,160])

    def test_tight_but_complete_letter_and_neighbors_not_flagged(self):
        self.assertIsNone(cutoff_evidence(self.glyph(),(20,20,31,37)))
        self.assertIsNone(cutoff_evidence(self.glyph(),(33,10,70,50)))

    def test_red_annotation_crossing_boundary_not_text_evidence(self):
        self.assertIsNone(cutoff_evidence(self.glyph('red'),(25,10,50,50)))

    def test_table_border_and_underline_do_not_trigger_cutoff(self):
        im=self.glyph();draw=ImageDraw.Draw(im)
        draw.rectangle((10,10,80,55),outline='black',width=2)
        draw.line((5,40,90,40),fill='black',width=2)
        self.assertIsNone(cutoff_evidence(im,(10,10,81,41)))

    def test_low_contrast_single_threshold_stroke_not_confirmed(self):
        self.assertIsNone(cutoff_evidence(self.glyph((130,130,130)),(25,10,50,50)))

    def test_classification_keeps_uncertain_content_out_of_errors(self):
        self.assertEqual(finding('text','invalid_bbox')['category'],'error')
        for reason in ['possible_bbox_cutoff','possible_clipping','possible_duplicate_overlap','unknown_future_reason']:
            self.assertEqual(finding('text',reason)['category'],'warning')
        for reason in ['extraction_missing','existing_hold','source_uncertainty','zero_o_requires_source_comparison']:
            self.assertEqual(finding('text',reason)['category'],'pending')
        groups=grouped_findings([{'reason':'invalid_bbox'},{'reason':'extraction_missing'},{'reason':'possible_bbox_cutoff'}])
        self.assertEqual({k:len(v) for k,v in groups.items()},{'error':1,'warning':1,'pending':1})

    def test_integration_uses_new_evidence_and_does_not_mutate_blocks(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'im.png';self.glyph().save(p)
            result={'final_blocks':[{'id':'a','kind':'text','bbox':[250,142,500,715],
                                     'text':'test','uncertainties':[]}],'visuals':[]}
            findings,_=inspect_frame(p,result,[100,70])
            alerts=[x for x in findings if x['reason']=='possible_bbox_cutoff']
            self.assertEqual(len(alerts),1)
            self.assertEqual(alerts[0]['category'],'warning')
            self.assertIn('supported_crossings',alerts[0]['evidence'])
            self.assertEqual(result['final_blocks'][0]['bbox'],[250,142,500,715])


if __name__=='__main__':unittest.main()
