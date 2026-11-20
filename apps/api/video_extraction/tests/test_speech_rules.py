"""Rule regressions are synthetic; they do not measure real lecture accuracy."""
import unittest
from video_extraction.audio.speech_rules import letters, phonetic_similarity, propose, apply, evidence


LEXICON=[{'term':'객체','importance':3,'anchors':['데이터','파이썬','구조'],'source_refs':['fixture']},
         {'term':'튜플','importance':3,'anchors':['데이터','파이썬','구조'],'source_refs':['fixture']}]


class SpeechRules(unittest.TestCase):
    def test_simple_liaison_not_duum(self):
        self.assertEqual(letters('대답을',True),letters('대다블',True))
        self.assertEqual(phonetic_similarity('대답을','대다블'),1)
        self.assertNotEqual(letters('가능',True),letters('불가능',True))

    def test_context_is_required(self):
        self.assertEqual(propose('객차라고 하는 개념','철도 여행 기차표',LEXICON),[])
        p=propose('객차라고 하는 개념','파이썬 데이터 구조',LEXICON)
        self.assertEqual(p[0]['after'],'객체라고')

    def test_recognized_terms_and_negative_are_preserved(self):
        self.assertFalse(propose('객체와 튜플은 불가능하다','파이썬 데이터 구조',LEXICON))
        self.assertFalse(propose('객체들의 튜플이에요','파이썬 데이터 구조',LEXICON))
        self.assertFalse(propose('인덱싱이라든가 메소드','파이썬 데이터 구조',LEXICON))

    def test_liaison_generates_full_particle_candidate(self):
        lex=[{'term':'대답','importance':2,'anchors':['질문','답변','학생']}]
        self.assertEqual(propose('대다블','학생 질문 답변',lex)[0]['after'],'대답을')

    def test_weight_changes_rank_not_probability(self):
        low=[{**LEXICON[0],'importance':1}]
        high=[{**LEXICON[0],'importance':3}]
        a=propose('객차라고','파이썬 데이터 구조',low)[0]
        b=propose('객차라고','파이썬 데이터 구조',high)[0]
        self.assertGreater(b['rank_score'],a['rank_score'])
        self.assertEqual(b['phonetic_score'],a['phonetic_score'])

    def fixture(self):
        s={'text':'객차라고 했고 객차라고 했다','words':[
            {'word':'객차라고','start_seconds':1,'end_seconds':2},
            {'word':'했고','start_seconds':2,'end_seconds':3},
            {'word':'객차라고','start_seconds':5,'end_seconds':6}]}
        p=propose(s['text'],'파이썬 데이터 구조',LEXICON)
        a={'text':'객체라고','words':[{'word':'객체라고','start_seconds':1,'end_seconds':2}]}
        return s,p,a

    def test_same_term_elsewhere_cannot_support_change(self):
        s,p,a=self.fixture();result,accepted,held=apply(s,p,a,a)
        self.assertEqual(result,'객체라고 했고 객차라고 했다')
        self.assertEqual(len(accepted),1);self.assertEqual(len(held),1)

    def test_hints_alone_cannot_force_change(self):
        s,p,a=self.fixture();result,accepted,held=apply(s,p,{'text':'','words':[]},a)
        self.assertEqual(result,s['text']);self.assertFalse(accepted)
        self.assertEqual(held[0]['reason'],'unhinted_audio_disagrees')

    def test_particle_must_be_supported_not_just_stem(self):
        s,p,a=self.fixture();a['words'][0]['word']='객체라고는'
        self.assertFalse(apply(s,p,a,a)[1])

    def test_exact_liaison_supports_spelling_restoration(self):
        w=[{'word':'튜프를','start_seconds':1,'end_seconds':2}]
        self.assertTrue(evidence('',w,'튜플을',1,2))
        self.assertFalse(evidence('',w,'튜플',1,2))
        w=[{'word':'객차라고','start_seconds':1,'end_seconds':2}]
        self.assertFalse(evidence('',w,'객체라고',1,2))

    def test_second_model_disagreement_holds(self):
        s,p,a=self.fixture()
        self.assertFalse(apply(s,p,a,a,{'words':[]})[1])

    def test_missing_alignment_and_ambiguous_candidates_held(self):
        s,p,a=self.fixture();s['words']=[]
        self.assertFalse(apply(s,p,a,a)[1])
        s,p,a=self.fixture();p[0]['ambiguous']=True
        self.assertFalse(apply(s,p,a,a)[1])

    def test_original_and_other_words_unchanged(self):
        s,p,a=self.fixture();original=s['text']
        result,accepted,_=apply(s,p,a,a)
        self.assertEqual(s['text'],original)
        self.assertEqual(result.replace('객체','객차'),original)


if __name__=='__main__':unittest.main()
