import copy
import io
import json
import tempfile
import unittest
import urllib.request
from pathlib import Path
from unittest.mock import patch

from video_extraction.audio import audio_crosscheck as ac
from video_extraction.shared.common import read, save

def judgment(**kwargs):
    j={k:True for k in ac.BOOLS}
    j.update(current_supported=False,boundary_ambiguous=False,uncertain=False,
             decision='candidate',categories=['terminology'],supported_text='객체',reason='test',
             evidence=[{'start':0.1,'end':0.8,'heard':'객체'}])
    j.update(kwargs);return j

class AudioCrosscheckTests(unittest.TestCase):
    def test_candidate_not_production(self):
        r=ac.gate('개체','객체','그 객체라고',judgment(),1)
        self.assertEqual(r['status'],'correction_candidate')
        self.assertFalse(r['production_applied'])

    def test_conflict_boundary_and_invalid_times_block(self):
        for fields in [dict(uncertain=True),dict(boundary_ambiguous=True),
                       dict(current_supported=True),dict(same_target_interval=False),
                       dict(evidence=[{'start':0,'end':2,'heard':'객체'}]),
                       dict(evidence=[{'start':0,'end':0.8,'heard':'없음'}]),
                       dict(supported_text='새 단어'),dict(evidence=[])]:
            with self.subTest(fields=fields):
                self.assertFalse(ac.gate('개체','객체','객체',judgment(**fields),1)['would_change'])

    def test_context_disagreement_never_auto_candidate(self):
        r=ac.gate('개체','객체','다른 단어',judgment(),1)
        self.assertIn('exact_context_transcription_disagreement',r['reasons'])

    def test_surface_changes_preserve_current(self):
        j=judgment(decision='keep',categories=['equivalent_spelling'],current_supported=True,supported_text='student')
        r=ac.gate('student','스튜던트','스튜던트',j,1)
        self.assertEqual(r['status'],'retained_equivalent')
        self.assertEqual(r['preview_text'],'student')
        j['decision']='candidate';j['supported_text']='스튜던트';j['current_supported']=False
        self.assertFalse(ac.gate('student','스튜던트','스튜던트',j,1)['would_change'])

    def test_negation_and_numbers_not_erased(self):
        for a,b in [('한다','안 한다'),('1.2','12'),('-1','1'),('3','4')]:
            self.assertNotEqual(ac.canonical(a),ac.canonical(b))

    def test_control_measures_would_change_before_protection(self):
        task={'role':'normal_control','current_text':'객체','reference_text':'객체'}
        d={'preview_text':'개체','would_change':True,'status':'correction_candidate'}
        r=ac.control_check(task,'개체',d)
        self.assertTrue(r['potential_regression'])
        self.assertIsNone(r['confirmed_wrong_correction'])
        d.update(preview_text='객체',would_change=False,status='unresolved')
        self.assertFalse(ac.control_check(task,'개체',d)['potential_regression'])

    def test_blind_requests_and_review_do_not_leak_reference(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'reference-secret-A016.wav';path.write_bytes(b'fake wav')
            data,_=ac.multipart('gpt-transcribe',path)
            self.assertNotIn(b'reference-secret',data)
            self.assertNotIn(b'prompt',data)
            task={'role':'normal_control','reference_text':'SECRET_GOLD','current_text':'current',
                  'clip_meta':{'duration_seconds':1},'target_in_context':[5,6]}
            prompt=ac.review_prompt(task,'independent','context')
            self.assertNotIn('SECRET_GOLD',prompt)
            self.assertNotIn('normal_control',prompt)

    def test_global_budget_failed_attempts_and_cached_calls(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp);path=out/'a.wav';path.write_bytes(b'fake wav')
            sent=[]
            def fake(req,timeout):
                sent.append(req.full_url)
                return io.BytesIO(b'{"text":"test"}')
            budget=ac.Budget(out,1,0,transport=fake)
            one=ac.blind_transcribe(path,'model','DUMMY',out/'cache',budget)
            self.assertEqual(ac.blind_transcribe(path,'model','DUMMY',out/'cache',budget),one)
            self.assertEqual(len(sent),1)
            with self.assertRaises(ac.Blocked):
                ac.blind_transcribe(path,'different-model','DUMMY',out/'cache',budget)
            self.assertEqual(len(sent),1)

    def test_runner_resumes_between_providers_without_new_transcription(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp);(out/'clips').mkdir()
            for file in ['A.wav','A-context.wav']:(out/'clips'/file).write_bytes(file.encode())
            task={'label':'A','role':'normal_control','current_text':'객체','original_text':'객체',
                  'reference_text':'객체','clip':'clips/A.wav','context_clip':'clips/A-context.wav',
                  'clip_meta':{'duration_seconds':1},'target_in_context':[5,6]}
            plan={'tasks':[task],'openai_model':'gpt-transcribe','gemini_model':'gemini-test'}
            seen=[]
            def fake(req,timeout):
                seen.append(req.full_url)
                if 'openai.com' in req.full_url:return io.BytesIO(json.dumps({'text':'객체'}).encode())
                j=judgment(decision='keep',current_supported=True,supported_text='객체',categories=[])
                return io.BytesIO(json.dumps({'status':'completed','output_text':json.dumps(j)}).encode())
            real_budget=ac.Budget
            with patch.object(ac,'verify',return_value=plan),patch.object(ac,'openai_key',return_value='DUMMY'),patch.object(ac,'api_key',return_value='DUMMY'),patch('video_extraction.shared.gemini.api_key',return_value='DUMMY'),patch.object(ac,'Budget',side_effect=lambda o,m,d:real_budget(o,m,0,transport=fake)):
                with self.assertRaises(ac.Blocked):ac.run(out,out/'unused.env',maximum=2,delay=0)
                self.assertEqual(len(seen),2)
                self.assertEqual(read(out/'summary.json')['completed'],0)
                s=ac.run(out,out/'unused.env',maximum=1,delay=0)
                self.assertEqual(s['completed'],1)
                self.assertEqual(len(seen),3)
                self.assertFalse(s['candidate_release_blocked'])
                self.assertEqual(s['production_changes'],0)
                ac.run(out,out/'unused.env',maximum=1,delay=0)
                self.assertEqual(len(seen),3)

    def test_control_risk_blocks_batch_candidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)
            task={'label':'A','role':'normal_control','current_text':'객체','original_text':'객체',
                  'reference_text':'객체','clip':'A.wav','context_clip':'C.wav','target_in_context':[5,6]}
            plan={'tasks':[task]}
            decision={'status':'correction_candidate','would_change':True,'preview_text':'개체'}
            save(out/'results/A.json',{'label':'A','plan_signature':ac.signature(plan),'current_text':'객체',
                 'independent_exact':'개체','independent_context':'개체','review':{'reason':'test'},'gate':decision,
                 'control':ac.control_check(task,'개체',decision)})
            s=ac.report(out,plan)
            self.assertTrue(s['candidate_release_blocked'])
            self.assertEqual(s['potential_wrong_corrections'],1)

if __name__=='__main__':unittest.main()
