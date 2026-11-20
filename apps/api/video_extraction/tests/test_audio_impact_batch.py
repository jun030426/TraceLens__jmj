import copy
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch
from video_extraction.audio import audio_impact_batch as m
from video_extraction.tests.test_audio_primary_scope import scoped


class GenericAudioImpactTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        for name,rate,channels in [('a',8000,1),('b',44100,2)]:
            with wave.open(str(self.root/(name+'.wav')),'wb') as w:
                w.setnchannels(channels);w.setsampwidth(2);w.setframerate(rate);w.writeframes(b'\0\0'*rate*6*channels)
        self.rows=[self.row('A','a.wav',1,2,'사과를 분류한다'),self.row('B','b.wav',1,2,'온도 20도에서 시작한다'),
                   self.row('N','a.wav',2,3,'다음 단계는 보관이다',True)]
    def tearDown(self):self.tmp.cleanup()
    def row(self,id,src,a,b,text,eligible=False):
        return dict(id=id,source_audio=src,start_seconds=a,end_seconds=b,observed_text=text,modality='audio',eligible_for_chunking=eligible)
    def prepare(self,rows=None):
        f=self.root/'input.jsonl';m.jsonl(f,rows if rows is not None else self.rows)
        with patch.object(m.Gemini,'call',side_effect=AssertionError('no API')),patch.dict(m.policy.LOCAL,{'NEW':'must never be used'},clear=True):
            p=m.prepare(f,self.root/'out','test-model')
        return p
    def evidence(self,t):
        b,r=scoped(t,text=t['before'],literal=t['before'])
        review={k:r[k] for k in ('literal_text','target_scope','target_spans','uncertain','full_target_checked')}
        review.update(impact='low',no_unique_concept_or_step=True,no_number_negation_or_condition_change=True,
                      core_instruction_preserved_without_target=True,context_preserves_relation=True,reason='synthetic low-impact test')
        return b,review
    def test_distinct_sources_rates_and_new_content_have_no_old_verdict(self):
        p=self.prepare();self.assertEqual(len(p['tasks']),2);m.verify(self.root/'out')
        self.assertFalse(p['manual_case_verdicts_used'])
        for t in p['tasks']:
            self.assertNotIn(t['id'],m.policy.LOCAL)
            self.assertTrue(all(n['id']=='N' for n in t['neighbors']))
            if t['target_id']=='B':self.assertEqual(t['neighbors'],[])
        s=m.read(self.root/'out/summary.json');self.assertEqual(s['pending'],2)
        self.assertEqual(s['new_administrator_holds'],0)
    def test_absolute_offset_explicit_and_invalid_rows_do_not_block_others(self):
        rows=copy.deepcopy(self.rows)
        rows[0].update(start_seconds=101,end_seconds=102,audio_offset_seconds=100,time_basis='media_absolute')
        rows.append(self.row('bad','a.wav',-1,1,'bad'))
        rows.append(self.row('ambiguous','a.wav',1,2,'unknown'));rows[-1]['audio_offset_seconds']=100
        p=self.prepare(rows)
        self.assertEqual(len(p['tasks']),2);self.assertEqual(len(p['input_issues']),2)
        self.assertEqual(p['tasks'][0]['interval'],[1,2])
    def test_same_ids_in_different_sources_do_not_collide(self):
        rows=copy.deepcopy(self.rows);rows[1]['id']='A'
        p=self.prepare(rows);self.assertEqual(len({t['id'] for t in p['tasks']}),2)
    def test_duplicate_same_source_invalidates_both(self):
        rows=[self.rows[0],copy.deepcopy(self.rows[0]),self.rows[1]]
        p=self.prepare(rows);self.assertEqual(len(p['tasks']),1);self.assertEqual(len(p['input_issues']),2)
    def test_long_tiny_and_unknown_selection_stay_explicit_holds(self):
        rows=copy.deepcopy(self.rows)
        rows.append(self.row('tiny','a.wav',1,1.000001,'tiny'))
        rows.append(self.row('unknown','a.wav',1,2,'unknown'));rows[-1].pop('eligible_for_chunking')
        f=self.root/'input.jsonl';m.jsonl(f,rows)
        p=m.prepare(f,self.root/'out','test-model',max_target_seconds=.5)
        self.assertEqual(len(p['tasks']),0)
        self.assertEqual(len(p['input_issues']),4)
    def test_changed_input_is_not_reused(self):
        self.prepare();f=self.root/'input.jsonl';f.write_text(f.read_text()+'\n')
        with self.assertRaisesRegex(ValueError,'input_changed'):m.verify(self.root/'out')
    def test_routing_never_rewrites_releases_or_reuses_another_target(self):
        p=self.prepare();out=self.root/'out';t=p['tasks'][0];b,r=self.evidence(t)
        binding=m.base.primary_context_bundle(out,t)[1]
        v={'task_id':t['id'],'plan_signature':m.signature(p),'blind':b,'review':r,
           'gate':m.policy.impact_gate(t,b,r),'input_bindings':{'blind':binding,'review':binding}}
        m.save(out/'results'/(t['id']+'.json'),v)
        summary=m.publish(out,p);self.assertEqual(summary['new_administrator_holds'],1)
        self.assertEqual(summary['pending'],1)
        rows=m.base.load_rows(m.Path(m.read(out/'latest.json')['records']))
        self.assertEqual(rows[0]['observed_text'],self.rows[0]['observed_text'])
        self.assertFalse(rows[0]['eligible_for_chunking']);self.assertTrue(rows[2]['eligible_for_chunking'])
        other=p['tasks'][1];m.save(out/'results'/(other['id']+'.json'),v)
        with self.assertRaisesRegex(ValueError,'stale_or_mismatched'):m.results(out,p)

if __name__=='__main__':unittest.main()
