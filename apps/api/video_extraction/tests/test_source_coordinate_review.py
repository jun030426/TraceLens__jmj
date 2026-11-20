import copy
from pathlib import Path
import tempfile
import unittest

from PIL import Image,ImageDraw

from video_extraction.shared.common import digest_file, save
from video_extraction.shared.multimodal_checks import inspect_frame
from video_extraction.video.source_coordinate_review import apply_decisions, load_reviewed


class CoordinateReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.image=self.root/'image.png'
        im=Image.new('RGB',(100,70),'white');ImageDraw.Draw(im).rectangle((20,20,30,36),outline='black',width=2)
        im.save(self.image)
        self.original={'frame_id':'frame-1','final_blocks':[{'id':'a','kind':'annotation','text':'red mark',
            'bbox':[250,142,500,715]}],'visuals':[],'holds':[{'reason':'uncertain'}],'text':'red mark'}
        self.row={'index':0,'frame_id':'frame-1','target_id':'a','kind':'annotation','text':'red mark',
            'before':[250,142,500,715],'after':[250,142,500,715],'decision':'false_positive',
            'reason':'Crossing belongs to another layer.','image_sha256':digest_file(self.image)}

    def apply(self):
        return apply_decisions(self.original,[self.row],digest_file(self.image),(100,70))

    def test_reviewed_false_positive_retains_raw_evidence(self):
        result=self.apply();findings,metrics=inspect_frame(self.image,result,[100,70])
        self.assertFalse(any(f['reason']=='possible_bbox_cutoff' for f in findings))
        self.assertEqual(len(metrics['reviewed_cutoff_findings']),1)
        self.assertEqual(result['holds'],self.original['holds'])
        self.assertNotIn('source_coordinate_review',self.original)

    def test_changed_image_text_or_bbox_revokes_resolution(self):
        result=self.apply()
        for field,value in [('text','changed'),('bbox',[240,142,500,715]),('kind','text')]:
            changed=copy.deepcopy(result);changed['final_blocks'][0][field]=value
            findings,_=inspect_frame(self.image,changed,[100,70])
            self.assertTrue(any(f['reason']=='possible_bbox_cutoff' for f in findings))
        with Image.open(self.image) as im:
            im.putpixel((90,60),(240,240,240));im.save(self.image)
        findings,_=inspect_frame(self.image,result,[100,70])
        self.assertTrue(any(f['reason']=='possible_bbox_cutoff' for f in findings))

    def test_corrected_coordinates_preserve_content_and_holds(self):
        self.row.update(after=[180,240,330,560],decision='corrected')
        result=self.apply()
        self.assertEqual(result['final_blocks'][0]['bbox'],self.row['after'])
        for field in ('text','holds','visuals'):self.assertEqual(result[field],self.original[field])
        changed=copy.deepcopy(result['final_blocks']);changed[0]['bbox']=self.row['before']
        self.assertEqual(changed,self.original['final_blocks'])

    def test_invalid_anchors_and_duplicate_decisions_rejected(self):
        row=copy.deepcopy(self.row);row['text']='different'
        with self.assertRaises(ValueError):apply_decisions(self.original,[row],digest_file(self.image),(100,70))
        with self.assertRaises(ValueError):apply_decisions(self.original,[self.row,self.row],digest_file(self.image),(100,70))
        with self.assertRaises(ValueError):apply_decisions(self.original,[self.row],'wrong-image',(100,70))

    def test_overlay_requires_original_baseline_and_intact_result(self):
        baseline=self.root/'baseline/vision/frame-1/result.json';save(baseline,self.original)
        out=self.root/'review';result=out/'vision/frame-1/result.json';save(result,self.apply())
        save(out/'manifest.json',{'results':{'frame-1':{'baseline':str(baseline.resolve()),
            'baseline_sha256':digest_file(baseline),'image_sha256':digest_file(self.image),'result_sha256':digest_file(result)}}})
        self.assertIn('source_coordinate_review',load_reviewed(out,baseline,self.image))
        save(result,{'tampered':True})
        with self.assertRaises(ValueError):load_reviewed(out,baseline,self.image)
        save(result,self.apply());save(baseline,{'changed':True})
        with self.assertRaises(ValueError):load_reviewed(out,baseline,self.image)


if __name__=='__main__':unittest.main()
