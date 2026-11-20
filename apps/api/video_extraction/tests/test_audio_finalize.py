import copy
import json
import tempfile
import unittest
import urllib.request
import wave
from pathlib import Path
from unittest.mock import patch

from video_extraction.audio import audio_finalize as mod
from video_extraction.audio import audio_coverage as core
from video_extraction.shared.common import read, save, signature, digest_file
from video_extraction.shared.gemini import Blocked
from video_extraction.tests.test_audio_coverage import finding, WINDOW


def response(text, change=True):
    return {'decision':'accept','literal_text':text,'full_target_checked':True,'content_supported':True,
            'change_needed':change,'all_additions_audible':True,'repetitions_preserved':True,
            'no_neighbor_double_capture':True,'boundaries_supported':True,'no_new_error':True,
            'uncertain':False,'reason':'mock source evidence'}


def outcome(t, passed=True):
    blind = {'text':t['after'],'uncertain':False,'boundary_clear':True,'reason':'mock'}
    review = response(t['after'],t['role']=='repair')
    if not passed:
        review['uncertain']=True
    return {'task_id':t['id'],'blind':blind,'review':review,'gate':mod.decision(t,blind,review)}


def fixture():
    def row(id,a,b,text,selected):
        return {'id':id,'start_seconds':a,'end_seconds':b,'text':text,'baseline_text':text,
                'original_words':[],'prior_selected':selected,'word_alignment_required':False}
    rows=[row('a',1,3,'이름 점수',True),row('b',7,8,'반복 반복',True),row('c',10,11,'보류',False)]
    f=finding(kind='omitted_words',action='replace',target_id='a',before='이름 점수',
              after='이름과 점수',start=1,end=3)
    c=core.check_finding(f,WINDOW,rows,'이름과 점수');c['batch_conflict']=False
    task={'id':'repair-a','role':'repair','target_id':'a','before':f['before'],'after':f['after'],
          'candidate':c,'interval':[1,3],'clip':'a.wav','clip_meta':{'start_seconds':0,'end_seconds':8},'neighbors':[]}
    control={'id':'control-b','role':'control','target_id':'b','before':'반복 반복','after':'반복 반복',
             'interval':[7,8],'clip':'b.wav','clip_meta':{'start_seconds':2,'end_seconds':13},'neighbors':[]}
    previous=[{'id':r['id'],'source_sha256':'source','modality':'audio','eligible_for_chunking':r['prior_selected'],
               'reasons':[] if r['prior_selected'] else ['audio_source_review_unresolved'],
               'observed_text':r['text']} for r in rows]
    snapshot={'rows':rows,'held':[],'previous_records':previous,
              'previous_usable':previous[:2]+[{'id':'image','modality':'image','source_sha256':'other'}],
              'coverage_results':[{'label':'W001','review':{'checked_full_core':True,'speech_unresolved':False}}],
              'source_plan':{'source_sha256':'source','source_audio':'source.wav','duration_seconds':30,
                             'audio_offset_seconds':0,'windows':[{'label':'W001','core':[0,30]}]}}
    return snapshot,[task,control]


class FinalizeTests(unittest.TestCase):
    def test_blind_and_final_reading_must_match_and_be_certain(self):
        _,tasks=fixture();t=tasks[0];r=outcome(t)
        self.assertTrue(r['gate']['passed'])
        r['blind']['text']='이름 가격'
        self.assertFalse(mod.decision(t,r['blind'],r['review'])['passed'])
        r=outcome(t);r['review']['uncertain']=True
        self.assertFalse(mod.decision(t,r['blind'],r['review'])['passed'])

    def test_no_neighbor_duplication_or_boundary_guessing(self):
        _,tasks=fixture();t=tasks[0]
        for key in ['no_neighbor_double_capture','boundaries_supported','no_new_error','repetitions_preserved']:
            r=outcome(t);r['review'][key]=False
            self.assertFalse(mod.decision(t,r['blind'],r['review'])['passed'])

    def test_deletion_and_substitution_blocked_even_with_model_agreement(self):
        _,tasks=fixture();t=tasks[0]
        t['after']='이름 가격'
        self.assertFalse(outcome(t)['gate']['passed'])
        t['candidate']['finding']['action']='delete'
        self.assertFalse(outcome(t)['gate']['passed'])

    def test_one_failed_control_blocks_all_repairs_and_flags_control(self):
        snap,tasks=fixture();outcomes={t['id']:outcome(t,t['role']=='repair') for t in tasks}
        result=mod.selection(snap,tasks,outcomes)
        self.assertEqual(result['rows'],snap['rows'])
        self.assertFalse(result['receipts']);self.assertFalse(result['controls_passed'])
        self.assertIn('existing_text_control_needs_review',next(r for r in result['excluded'] if r['id']=='b')['reasons'])

    def test_approved_addition_selected_but_unrelated_hold_preserved(self):
        snap,tasks=fixture();before=copy.deepcopy(snap)
        result=mod.selection(snap,tasks,{t['id']:outcome(t) for t in tasks})
        self.assertEqual(snap,before)
        self.assertEqual(result['rows'][0]['text'],'이름과 점수')
        self.assertEqual(result['rows'][1]['text'],'반복 반복')
        self.assertEqual(len(result['receipts']),1)
        fixed=next(r for r in result['selected'] if r['id']=='a')
        self.assertTrue(fixed['word_alignment_required']);self.assertEqual(fixed['words'],[])
        self.assertFalse(fixed['gold_approved'])
        self.assertEqual([r['id'] for r in result['excluded']],['c'])
        self.assertEqual(result['combined'][0],{'id':'image','modality':'image','source_sha256':'other'})

    def test_failed_repair_excluded_and_original_not_overwritten(self):
        snap,tasks=fixture();outcomes={t['id']:outcome(t,t['role']=='control') for t in tasks}
        result=mod.selection(snap,tasks,outcomes)
        self.assertEqual(result['rows'],snap['rows'])
        self.assertNotIn('a',[r['id'] for r in result['selected']])

    def test_prior_timing_hold_not_cleared_by_content_success(self):
        snap,tasks=fixture()
        snap['previous_records'][0].update(eligible_for_chunking=False,reasons=['audio_source_review_unresolved','asr_chunk_boundary'])
        result=mod.selection(snap,tasks,{t['id']:outcome(t) for t in tasks})
        excluded=next(r for r in result['excluded'] if r['id']=='a')
        self.assertIn('asr_chunk_boundary',excluded['reasons'])
        self.assertNotIn('audio_source_review_unresolved',excluded['reasons'])

    def test_unresolved_window_or_other_finding_blocks_selection(self):
        snap,tasks=fixture()
        snap['coverage_results'][0]['review']['speech_unresolved']=True
        result=mod.selection(snap,tasks,{t['id']:outcome(t) for t in tasks})
        self.assertFalse(result['selected'])
        snap,tasks=fixture()
        snap['held']=[{'finding':finding(target_id='b',start=7,end=8)}]
        result=mod.selection(snap,tasks,{t['id']:outcome(t) for t in tasks})
        self.assertNotIn('b',[r['id'] for r in result['selected']])

    def test_new_utterance_can_be_selected_with_provenance(self):
        snap,tasks=fixture()
        f=finding(after='새 발화',start=4,end=5)
        c=core.check_finding(f,WINDOW,snap['rows'],'새 발화');c['batch_conflict']=False
        tasks[0].update(candidate=c,target_id='',before='',after='새 발화',interval=[4,5])
        result=mod.selection(snap,tasks,{t['id']:outcome(t) for t in tasks})
        new=next(r for r in result['selected'] if r['id'].startswith('audio-repair-'))
        self.assertEqual(new['observed_text'],'새 발화');self.assertTrue(new['word_alignment_required'])

    def test_resume_budget_atomic_publish_and_idempotence_without_network(self):
        snap,tasks=fixture()
        p={'version':2,'tasks':tasks,'model':'fake','code_hashes':{},'inputs':{}}
        class FakeGemini:
            def __init__(self, cache,model,env_file,max_calls,delay,transport):
                self.cache=cache;self.budget=transport
                self.budget.transport=lambda *a,**kw: None
            def call(self,stage,media,prompt,schema):
                sig=signature([stage,prompt]);path=self.cache/(sig+'.json')
                if path.exists():return read(path)
                self.budget(urllib.request.Request('https://generativelanguage.googleapis.com/test'))
                data=json.loads(prompt.split('DATA:\n',1)[1])
                t=next(t for t in tasks if Path(t['target_clip']).name==Path(media[0]).name)
                assert len(media)==1 and data['target_seconds'][0]==0
                assert 'audio_start_seconds' not in data
                r=outcome(t)['blind' if stage.endswith('blind-v2') else 'review']
                save(path,r);return r
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);save(root/'snapshot.json',snap)
            source=root/'raw.wav'
            with wave.open(str(source),'wb') as w:
                w.setparams((1,2,16000,0,'NONE','not compressed'))
                w.writeframes(b'\x01\x00'*(30*16000))
            for t in tasks:
                t['target_clip']=t['id']+'-target.wav'
                t['target_clip_meta']=mod.clip(source,root/t['target_clip'],*t['interval'])
            with patch.object(mod,'verify',return_value=p),patch.object(mod,'api_key',return_value='mock'),patch.object(mod,'Gemini',FakeGemini):
                with self.assertRaises(Blocked):mod.run(root,root/'.env',maximum=1,delay=0)
                self.assertFalse((root/'latest.json').exists())
                self.assertEqual(len(list((root/'gemini-cache').glob('*.json'))),1)
                mod.run(root,root/'.env',maximum=10,delay=0)
                latest=read(root/'latest.json');manifest=read(latest['manifest'])
                self.assertEqual(manifest['applied_repairs'],1)
                self.assertEqual(manifest['usable_audio'],2)
                self.assertEqual(read(root/'summary.json')['api_attempts'],4)
                before=(root/'latest.json').read_bytes()
                mod.run(root,root/'.env',maximum=10,delay=0)
                self.assertEqual((root/'latest.json').read_bytes(),before)
                self.assertEqual(read(root/'run-state.json')['api_calls_this_run'],0)
                Path(latest['usable_audio']).write_text('tampered')
                with self.assertRaisesRegex(ValueError,'published_revision_changed'):
                    mod.run(root,root/'.env',maximum=10,delay=0)

    def test_missing_task_never_publishes(self):
        _,tasks=fixture()
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaisesRegex(ValueError,'incomplete'):
                mod.finalize(Path(d),{'tasks':tasks})
            self.assertFalse((Path(d)/'latest.json').exists())

    def test_stale_result_is_rejected(self):
        _,tasks=fixture();p={'tasks':tasks}
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);r=outcome(tasks[0]);r['plan_signature']='old'
            save(root/'results'/(tasks[0]['id']+'.json'),r)
            with self.assertRaisesRegex(ValueError,'stale'):
                mod.results(root,p)


if __name__=='__main__':
    unittest.main()
