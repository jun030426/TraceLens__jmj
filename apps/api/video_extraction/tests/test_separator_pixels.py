import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw

from video_extraction.shared.common import digest_file, signature
from video_extraction.video.separator_pixels import count_dashes, apply_review


def fixture(count):
    image = Image.new('L', (count * 6 + 4, 9), 255)
    draw = ImageDraw.Draw(image)
    for i in range(count):
        draw.rectangle((3+i*6, 3, 6+i*6, 4), fill=20)
    return image


class PixelTests(unittest.TestCase):
    def count(self, image):
        return count_dashes(image, (0, 0, image.width, image.height), (80, 100, 120, 140, 160))

    def test_counts_are_measured_not_fixed_to_sixteen(self):
        for n in (2, 7, 13, 16, 19):
            result = self.count(fixture(n))
            self.assertEqual(result['status'], 'verified')
            self.assertEqual(result['count'], n)

    def test_blank_solid_clipped_and_joined_are_not_approved(self):
        blank = Image.new('L', (50, 9), 255)
        solid = blank.copy(); ImageDraw.Draw(solid).rectangle((3, 3, 45, 4), fill=20)
        clipped = fixture(7).crop((3, 0, 46, 9))
        joined = fixture(7); ImageDraw.Draw(joined).rectangle((6, 3, 9, 4), fill=20)
        for image in (blank, solid, clipped, joined):
            self.assertEqual(self.count(image)['status'], 'needs_review')

    def test_threshold_sensitive_gaps_are_not_approved(self):
        image = fixture(7)
        ImageDraw.Draw(image).rectangle((7, 3, 8, 4), fill=110)
        self.assertEqual(self.count(image)['status'], 'needs_review')

    def test_invalid_rois_and_thresholds_rejected(self):
        with self.assertRaises(ValueError): count_dashes(fixture(5), (-1, 0, 20, 8), (90,100,110))
        with self.assertRaises(ValueError): count_dashes(fixture(5), (0, 0, 20, 8), (100,100,100))

    def test_merge_is_narrow_preserves_history_and_other_holds(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp); (out/'frames').mkdir()
            image = out/'frames/frame-00030.png'; fixture(16).save(image)
            evidence = {'frame_id': 'frame-00030', 'region_id': 'code_separator',
                        'image_sha256': digest_file(image), **self.count(fixture(16))}
            config = {'test': True}; review = {'plan_signature': signature(config), 'outcomes': [evidence]}
            check = {'region_id': 'code_separator', 'target_id': 'c', 'status': 'needs_review'}
            hold = {'layer': 'text', 'target_id': 'c', 'region_id': 'text-1', 'reason': 'verification_hold'}
            source = {'frame_id':'frame-00030', 'signature':'base', 'status':'needs_review',
                      'final_blocks':[{'id':'c','kind':'code','text':'  name = student[o]\n  print("---")\nend'}],
                      'holds':[hold, {**hold, 'region_id':'code_separator'}],
                      'followup':{'symbol_checks':[check], 'corrections':[]}}
            snapshot = copy.deepcopy(source)
            actual = apply_review(source,review,config,out)
            self.assertEqual(actual['final_blocks'][0]['text'], '  name = student[o]\n  print("'+'-'*16+'")\nend')
            self.assertEqual(actual['holds'],[hold])
            self.assertEqual(actual['followup']['symbol_checks'][0]['model_check'],check)
            self.assertEqual(source,snapshot)
            self.assertEqual(actual,apply_review(source,review,config,out))
            fixture(13).save(image)
            with self.assertRaisesRegex(ValueError,'image_changed'): apply_review(source,review,config,out)

    def test_real_frames_offline_and_api_construction_forbidden(self):
        from video_extraction.video.layer_followup import OUTPUT
        from video_extraction.video.separator_pixels import inspect, load_frozen_plan
        if not (OUTPUT/'plan.json').exists(): self.skipTest('local review data unavailable')
        with patch('video_extraction.video.layer_followup.Gemini',side_effect=AssertionError('API forbidden')):
            result = inspect(OUTPUT,load_frozen_plan(OUTPUT))
        self.assertEqual(len(result['outcomes']),6)
        self.assertTrue(all(x['status']=='verified' and x['count']==16 for x in result['outcomes']))


if __name__ == '__main__': unittest.main()
