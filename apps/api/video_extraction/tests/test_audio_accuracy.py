import unittest
from video_extraction.audio.audio_accuracy import edits, compare, evaluate, normalized

class AudioAccuracyTests(unittest.TestCase):
    def pred(self,rid,old,new):
        return {'id':rid,'original_text':old,'observed_text':new}
    def ref(self,rid,text,status='approved',silent=False):
        return {'id':rid,'status':status,'reference_text':text,'no_speech':silent,'listened':True,'reviewed_at':'2026-10-30T00:00:00Z'}
    def submission(self,*rows):
        return {'reviewer':'test-listener','records':list(rows)}
    def test_known_edit_operations(self):
        self.assertEqual(edits('abc','axc')['substitutions'],1)
        self.assertEqual(edits('abc','ac')['deletions'],1)
        self.assertEqual(edits('abc','abbc')['insertions'],1)
        self.assertEqual(edits('','abc')['errors'],3)
    def test_unicode_and_no_semantic_replacement(self):
        self.assertEqual(normalized('튜플,  값!'),'튜플 값')
        self.assertGreater(compare('투풀','튜플')['cer']['errors'],0)
        self.assertEqual(compare('하나 둘','하나둘')['cer']['errors'],0)
        self.assertGreater(compare('하나 둘','하나둘')['wer']['errors'],0)
        self.assertGreater(compare('1.2','12')['cer']['errors'],0)
        self.assertGreater(compare('-1','1')['cer']['errors'],0)
    def test_micro_average_and_regression(self):
        p=[self.pred('a','가','나'),self.pred('b','x','가나다라마바사아자')]
        s=self.submission(self.ref('a','가'),self.ref('b','가나다라마바사아자'))
        r=evaluate(p,s)
        self.assertEqual(r['current_metrics']['cer']['error_rate_pct'],10)
        self.assertEqual(r['paired_before_after']['worsened_by_character_errors'],1)
        self.assertEqual(r['paired_before_after']['improved_by_character_errors'],1)
    def test_partial_coverage_not_perfect(self):
        p=[self.pred('a','가','가'),self.pred('b','나','나')]
        r=evaluate(p,self.submission(self.ref('a','가'),self.ref('b','나','ambiguous')))
        self.assertEqual(r['scored_segments'],1);self.assertEqual(r['coverage_pct'],50)
        self.assertFalse(r['evaluation_complete'])
    def test_silence_insertions_and_zero_denominator(self):
        r=evaluate([self.pred('a','','잘못 생성')],self.submission(self.ref('a','',silent=True)))
        self.assertIsNone(r['current_metrics']['cer']['error_rate_pct'])
        self.assertEqual(r['no_speech_with_false_transcription'],1)
        self.assertGreater(r['current_metrics']['cer']['insertions'],0)
    def test_empty_or_ambiguous_reference_rejected(self):
        for value in ('','[불명료]','[판독불가]'):
            with self.assertRaises(ValueError):evaluate([self.pred('a','','가')],self.submission(self.ref('a',value)))
    def test_duplicate_unknown_and_unlistened_rejected(self):
        p=[self.pred('a','가','가')];a=self.ref('a','가')
        for rows in [(a,a),(self.ref('x','가'),)]:
            with self.assertRaises(ValueError):evaluate(p,self.submission(*rows))
        a['listened']=False
        with self.assertRaises(ValueError):evaluate(p,self.submission(a))
    def test_error_rate_not_clamped(self):
        r=evaluate([self.pred('a','가','나다라')],self.submission(self.ref('a','가')))
        self.assertEqual(r['current_metrics']['cer']['error_rate_pct'],300)
    def test_no_references_no_score(self):
        r=evaluate([self.pred('a','가','가')],self.submission())
        self.assertIsNone(r['current_metrics']['cer']['error_rate_pct'])
        self.assertIsNone(r['normalized_exact_segment_rate_pct'])

if __name__=='__main__':unittest.main()
