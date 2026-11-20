"""Narrow representation equivalence must not erase substantive audio differences."""
import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from video_extraction.audio import audio_meaning_scope as m
from video_extraction.tests.archived_audio import replay_fingerprint


class ExpressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.enterClassContext(replay_fingerprint())
        cls.old=m.verify(m.BODY,archived=True)
        cls.done=m.results(m.BODY,cls.old)
        cls.t=copy.deepcopy(next(t for t in cls.old['tasks'] if t['mode']=='restore'))
        cls.t['expression_policy']=m.EXPRESSION_POLICY
        cls.r=cls.done[cls.t['id']]

    def test_real_two_readings_pass_without_rewriting_evidence(self):
        b,r=copy.deepcopy(self.r['blind']),copy.deepcopy(self.r['review'])
        original=copy.deepcopy((b,r));g=m.gate(self.t,b,r)
        self.assertTrue(g['passed']);self.assertTrue(g['representation_difference_accepted'])
        self.assertEqual((b,r),original)
        self.assertEqual(g['raw_differences']['blind'],'content_or_reading_difference')

    def test_content_repetition_negation_number_and_boundary_still_block(self):
        for text in ['이런 주요 메서드를 사용할 수가 없더라.',
                     '이런 주요 함수를 사용할 수가 있더라.',
                     '이런 주요 메서드 두 개를 사용할 수가 있더라.',
                     '이런 주요 메서드 2개를 사용할 수가 있더라.',
                     '저런 주요 메서드를 사용할 수가 있더라.',
                     '이런 이런 주요 메서드를 사용할 수가 있더라.']:
            b,r=copy.deepcopy(self.r['blind']),copy.deepcopy(self.r['review'])
            b['text']=text;b['target_spans'][0]['text']=text
            self.assertFalse(m.gate(self.t,b,r)['passed'],text)
        for kind in ['boundary','uncertain','scope','unsupported','span_text']:
            b,r=copy.deepcopy(self.r['blind']),copy.deepcopy(self.r['review'])
            if kind=='boundary':b['boundary_clear']=False
            if kind=='uncertain':r['uncertain']=True
            if kind=='scope':r['target_scope']['start_seconds']=0.1
            if kind=='unsupported':r['content_supported']=False
            if kind=='span_text':b['target_spans'][0]['text']='different evidence'
            self.assertFalse(m.gate(self.t,b,r)['passed'],kind)

    def test_projection_is_word_bounded_not_code_or_identifier_rewriting(self):
        expected='요런 주요 메소드를 사용할 수가 있더라'
        self.assertEqual(m.expression_projection('이런 주요 메서드를 사용할 수가 있더라',expected),expected)
        for text in ['안이런 주요 메서드명','"이런" 메서드','이런_method','메서드가아닌함수']:
            self.assertEqual(m.expression_projection(text,expected),text)
        # Neither pair maps to a third demonstrative/concept.
        self.assertEqual(m.expression_projection('저런 함수를 사용',expected),'저런 함수를 사용')

    def test_policy_is_opt_in_and_only_for_restoration(self):
        t=copy.deepcopy(self.t);t.pop('expression_policy')
        self.assertFalse(m.gate(t,self.r['blind'],self.r['review'])['passed'])
        t=copy.deepcopy(self.t);t['before']='existing words'
        self.assertFalse(m.gate(t,self.r['blind'],self.r['review'])['passed'])

    def test_real_offline_publication_one_body_keeps_all_old_text_and_holds(self):
        with tempfile.TemporaryDirectory() as d,patch.object(m.Gemini,'call',side_effect=AssertionError('no API')):
            out=Path(d)/'recheck';s=m.recheck_expressions(out)
            self.assertEqual(s['new_restorations'],1);self.assertEqual(s['released_originals'],1)
            self.assertEqual(s['administrator_holds'],2);self.assertEqual(s['boundary_holds'],1)
            self.assertEqual(s['api_attempts'],0);self.assertEqual(s['usable_audio'],267)
            folder=Path(m.read(out/'latest.json')['manifest']).parent
            added=m.base.load_rows(folder/'new-restorations.jsonl')
            self.assertEqual(added[0]['text'],'요런 주요 메소드를 사용할 수가 있더라')
            self.assertEqual([added[0]['start_seconds'],added[0]['end_seconds']],[359.96,362.8])
            records=m.base.load_rows(folder/'usable-audio.jsonl')
            self.assertIn(added[0]['id'],{r['id'] for r in records})
            oldfolder=Path(m.read(m.BODY/'latest.json')['manifest']).parent
            old=m.base.load_rows(oldfolder/'full-transcript.corrected.jsonl')
            rows=m.base.load_rows(folder/'full-transcript.corrected.jsonl');byid={r['id']:r for r in rows}
            self.assertEqual(len(rows),len(old)+1)
            for r in old:
                for k in ['text','start_seconds','end_seconds']:self.assertEqual(byid[r['id']][k],r[k])
            before=(folder/'manifest.json').read_bytes();m.recheck_expressions(out)
            self.assertEqual((folder/'manifest.json').read_bytes(),before)
            p=m.verify(out);done=m.results(out,p)
            held=[t['id'] for t in p['tasks'] if not done[t['id']]['gate']['passed']]
            self.assertEqual(len(held),3)
            raw=m.results(m.BODY,self.old)
            for key in raw:
                for field in ('blind','review','input_bindings'):self.assertEqual(done[key][field],raw[key][field])

if __name__=='__main__':unittest.main()
