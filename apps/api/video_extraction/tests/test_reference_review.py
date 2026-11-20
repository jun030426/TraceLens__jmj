import copy
import unittest

from video_extraction.review.reference_review import region, render, validate_draft


def draft():
    return {'frames': [{'id':'frame-1', 'time_seconds':0, 'image_path':'/tmp/original.png',
             'reference_regions':[region('code','code',[1,1,100,40],'student[⟦index⟧]')],
             'ambiguous_regions':[{'id':'index','region_id':'code','reason':'0/o'}],
             'gold_approved':False, 'annotation_status':'assistant_source_reviewed_pending_adjudication'}],
            'audio':[{'id':'audio-1','start_seconds':0,'end_seconds':60,'audio_path':'/tmp/audio.wav',
                      'reference_text_verbatim':None,'reviewer':None}]}


class ReferenceReviewTests(unittest.TestCase):
    def test_untracked_unknown_character_is_not_silently_scored(self):
        d=draft(); validate_draft(d)
        d['frames'][0]['ambiguous_regions']=[]
        with self.assertRaisesRegex(ValueError,'untracked_ambiguity'):
            validate_draft(d)

    def test_assistant_review_cannot_be_promoted_to_gold(self):
        d=draft();d['frames'][0]['gold_approved']=True
        with self.assertRaisesRegex(ValueError,'cannot_be_gold'):
            validate_draft(d)

    def test_unheard_audio_cannot_inherit_model_transcription(self):
        d=draft();d['audio'][0]['reference_text_verbatim']='model prediction'
        with self.assertRaisesRegex(ValueError,'unheard_audio'):
            validate_draft(d)

    def test_geometry_bounds_and_duplicate_regions(self):
        with self.assertRaisesRegex(ValueError,'invalid_reference_box'):
            region('bad','text',[0,0,1300,20],'x')
        d=draft();d['frames'][0]['reference_regions']*=2
        with self.assertRaisesRegex(ValueError,'duplicate_reference_region'):
            validate_draft(d)

    def test_source_text_cannot_escape_html_or_embedded_json(self):
        d=draft();text='</script><script>alert(1)</script>'
        d['frames'][0]['reference_regions'][0]['literal_text']=text
        original=copy.deepcopy(d)
        page=render(d)
        self.assertNotIn(text,page)
        self.assertIn('&lt;/script&gt;',page)
        self.assertIn('\\u003c/script>',page)
        self.assertEqual(d,original)


if __name__=='__main__':
    unittest.main()
