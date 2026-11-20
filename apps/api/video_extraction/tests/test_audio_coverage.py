import copy
import unittest
from video_extraction.audio.audio_coverage import audit_timeline, subtract, merge, check_finding, apply_candidates

def row(id,start,end,text):
    return {'id':id,'start_seconds':start,'end_seconds':end,'text':text}

def finding(**kw):
    f={'kind':'missing_utterance','action':'insert','target_id':'','related_id':'','before':'',
       'after':'설명','start':2,'end':3,'source_clear':True,'same_acoustic_event':False,
       'actual_repeated_speech':False,'uncertain':False,'reason':'test'}
    f.update(kw);return f

WINDOW={'core':[0,30],'clip_meta':{'start_seconds':0,'end_seconds':35}}

class CoverageTests(unittest.TestCase):
    def test_union_and_uncovered_intervals(self):
        self.assertEqual(merge([[0,3],[2,5],[7,9]]),[[0,5],[7,9]])
        self.assertEqual(subtract([[0,10]],[[1,3],[2,4],[6,8]]),[[0,1],[4,6],[8,10]])

    def test_vad_gaps_not_confirmed_errors(self):
        a=audit_timeline([row('a',1,2,'가')],5,[[0,3]])
        self.assertEqual(a['vad_uncovered_seconds'],2)
        self.assertIsNone(a['confirmed_omissions'])

    def test_invalid_times_excluded_but_recorded(self):
        a=audit_timeline([row('bad',-1,2,'가'),row('empty',1,2,'')],5,[[0,3]])
        self.assertEqual(a['invalid_time_ids'],['bad'])
        self.assertEqual(a['vad_uncovered_seconds'],3)

    def test_real_repeated_identical_text_at_different_times_is_not_duplicate(self):
        rows=[row('a',1,2,'반복'),row('b',3,4,'반복')]
        f=finding(kind='duplicate_capture',action='delete',target_id='b',related_id='a',before='반복',after='',start=3,end=4,same_acoustic_event=True)
        c=check_finding(f,WINDOW,rows,'반복 반복')
        self.assertFalse(c['candidate'])
        self.assertIn('not_same_time_exact_duplicate_partial_requires_review',c['reasons'])

    def test_actual_repetition_delete_is_always_preserved(self):
        f=finding(kind='duplicate_capture',action='delete',actual_repeated_speech=True)
        c=check_finding(f,WINDOW,[],'')
        self.assertFalse(c['candidate']);self.assertEqual(c['status'],'preserve_real_repetition')

    def test_restore_missing_real_repetition_allowed(self):
        rows=[row('a',0,1,'설명')]
        c=check_finding(finding(actual_repeated_speech=True),WINDOW,rows,'설명 설명')
        self.assertTrue(c['candidate'])

    def test_exact_double_capture_only_one_removed_after_approval(self):
        rows=[row('a',1,2,'반복'),row('b',1,2,'반복'),row('c',3,4,'반복')]
        f=finding(kind='duplicate_capture',action='delete',target_id='b',related_id='a',before='반복',after='',start=1,end=2,same_acoustic_event=True)
        c=check_finding(f,WINDOW,rows,'반복 반복');self.assertTrue(c['candidate']);c['batch_conflict']=False
        before=copy.deepcopy(rows)
        after,receipt=apply_candidates(rows,[c],[c['candidate_id']],'reviewer')
        self.assertEqual([r['id'] for r in after],['a','c']);self.assertEqual(rows,before)
        self.assertEqual(len(receipt),1)

    def test_partial_overlaps_never_deleted_automatically(self):
        rows=[row('a',1,3,'이름 점수'),row('b',2,4,'점수 출력')]
        f=finding(kind='duplicate_capture',action='delete',target_id='b',related_id='a',before='점수 출력',after='',start=2,end=4,same_acoustic_event=True)
        self.assertFalse(check_finding(f,WINDOW,rows,'이름 점수 출력')['candidate'])

    def test_substantive_rewrite_blocked_but_omitted_words_addition_allowed(self):
        rows=[row('a',1,4,'이름 점수')]
        f=finding(kind='omitted_words',action='replace',target_id='a',before='이름 점수',after='이름과 점수',start=1,end=4)
        self.assertTrue(check_finding(f,WINDOW,rows,'이름과 점수')['candidate'])
        f['after']='이름 가격'
        self.assertFalse(check_finding(f,WINDOW,rows,'이름 가격')['candidate'])

    def test_insertion_overlap_and_context_ownership_block(self):
        self.assertFalse(check_finding(finding(),WINDOW,[row('a',1,4,'다른 말')],'설명')['candidate'])
        w={'core':[0,2],'clip_meta':{'start_seconds':0,'end_seconds':5}}
        self.assertFalse(check_finding(finding(),w,[],'설명')['candidate'])

    def test_next_segment_text_not_reinserted_as_omission(self):
        rows=[row('a',1,3,'이름 점수'),row('b',3,5,'튜플로 만든다')]
        f=finding(kind='omitted_words',action='replace',target_id='a',before='이름 점수',
                  after='이름 점수 튜플로 만든다',start=1,end=3)
        c=check_finding(f,WINDOW,rows,'이름 점수 튜플로 만든다')
        self.assertFalse(c['candidate'])
        self.assertIn('addition_already_in_neighbor_requires_boundary_review',c['reasons'])

    def test_disagreement_uncertainty_and_stale_before_block(self):
        self.assertFalse(check_finding(finding(),WINDOW,[],'무관한말')['candidate'])
        self.assertFalse(check_finding(finding(uncertain=True),WINDOW,[],'설명')['candidate'])
        f=finding(kind='omitted_words',action='replace',target_id='a',before='과거',after='과거 설명')
        self.assertFalse(check_finding(f,WINDOW,[row('a',2,3,'현재')],'과거 설명')['candidate'])

    def test_no_approval_no_changes_and_conflict_blocks_apply(self):
        rows=[row('a',0,1,'설명')]
        c=check_finding(finding(),WINDOW,rows,'설명');c['batch_conflict']=False
        after,receipt=apply_candidates(rows,[c],[],'reviewer');self.assertEqual(after,rows);self.assertFalse(receipt)
        c['batch_conflict']=True
        with self.assertRaises(ValueError):apply_candidates(rows,[c],[c['candidate_id']],'reviewer')
        with self.assertRaises(ValueError):apply_candidates(rows,[c],['unknown'],'reviewer')

if __name__=='__main__':unittest.main()
