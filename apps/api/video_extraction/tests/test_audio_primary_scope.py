"""Scope-isolation regressions. Synthetic responses/timings, never production gold."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from video_extraction.audio import audio_finalize as mod
from video_extraction.shared.common import read, save
from video_extraction.tests.test_audio_finalize import fixture, response, outcome
from video_extraction.tests.test_audio_target_window import raw_file

FIXTURES=Path(__file__).parents[1]/'fixtures/audio_primary_scope_cases.json'


def scoped(t, text=None, literal=None, issues=None):
    text=t['after'] if text is None else text
    literal=text if literal is None else literal
    duration=t['target_clip_meta']['duration_seconds']
    scope={'audio_index':0,'start_seconds':0,'end_seconds':duration,'boundary_crossing':False}
    def spans(s):return [{'text':s,'start_seconds':0,'end_seconds':duration}] if s else []
    b={'text':text,'uncertain':False,'boundary_clear':True,'reason':'synthetic fixture',
       'target_scope':copy.deepcopy(scope),'target_spans':spans(text)}
    r=response(literal,t['role']=='repair')
    fragments=mod.additions(t['before'],t['after']) if t['role']=='repair' else []
    r.update(target_scope=scope,target_spans=spans(literal),neighbor_issues=issues or [],
             addition_spans=[{'text':f,'start_seconds':i*duration/max(1,len(fragments)),
                              'end_seconds':(i+1)*duration/max(1,len(fragments))} for i,f in enumerate(fragments)])
    return b,r


def v4task(t):
    t=copy.deepcopy(t);t['review_protocol']=4
    t['target_clip_meta']={'duration_seconds':t['interval'][1]-t['interval'][0]}
    return t


def make_files(root,t,source):
    t.update(review_protocol=4,target_clip=t['id']+'-primary.wav',context_clip=t['id']+'-context.wav')
    a,b=t['interval'];lo,hi=max(0,a-1),min(30,b+1)
    t['target_clip_meta']=mod.clip(source,root/t['target_clip'],a,b)
    t['context_clip_meta']=mod.clip(source,root/t['context_clip'],lo,hi)


class PrimaryScopeTests(unittest.TestCase):
    def test_existing_held_cases_scope_only_replay_not_audio_verification(self):
        for case in read(FIXTURES)['cases']:
            with self.subTest(case=case['case']):
                t=v4task(case['task']);texts=case['scope_fixture']
                b,r=scoped(t,texts['blind_text'],texts['review_text'])
                self.assertEqual(mod.decision(t,b,r)['passed'],case['expected_gate_pass'])
                self.assertFalse(case['old_gate']['passed'])

    def test_neighbor_mismatch_is_not_primary_mismatch_and_is_queued(self):
        snap,tasks=fixture();tasks=[v4task(t) for t in tasks]
        tasks[1]['neighbors']=[{'id':'c','start_seconds':10,'end_seconds':11,'text':'보류'}]
        issue={'neighbor_id':'c','kind':'content','observed_text':'이웃 오류','reason':'synthetic'}
        outcomes={}
        for t in tasks:
            b,r=scoped(t,issues=[issue] if t['role']=='control' else [])
            outcomes[t['id']]={'blind':b,'review':r,'gate':mod.decision(t,b,r)}
        result=mod.selection(snap,tasks,outcomes)
        self.assertTrue(result['controls_passed'])
        self.assertEqual(len(result['receipts']),1)
        self.assertIn('b',[r['id'] for r in result['selected']])
        self.assertEqual(result['neighbor_issues'][0]['status'],'needs_own_source_recheck')
        self.assertIn('neighbor_content_needs_own_recheck',next(r for r in result['excluded'] if r['id']=='c')['reasons'])
        self.assertEqual(result['rows'][2]['text'],snap['rows'][2]['text'])

    def test_direct_target_check_supersedes_only_that_neighbors_lead(self):
        _,tasks=fixture();tasks=[v4task(t) for t in tasks]
        tasks[0]['neighbors']=[{'id':'b','start_seconds':7,'end_seconds':8,'text':'반복 반복'}]
        issue={'neighbor_id':'b','kind':'content','observed_text':'반복','reason':'synthetic'}
        outcomes={}
        for t in tasks:
            b,r=scoped(t,issues=[issue] if t['role']=='repair' else [])
            outcomes[t['id']]={'blind':b,'review':r,'gate':mod.decision(t,b,r)}
        self.assertEqual(mod.neighbor_queue(tasks,outcomes)[0]['status'],'superseded_by_direct_target_check')

    def test_fake_neighbor_owner_cannot_hide_primary_error(self):
        _,tasks=fixture();t=v4task(tasks[1])
        b,r=scoped(t,issues=[{'neighbor_id':t['target_id'],'kind':'content','observed_text':'違い','reason':'synthetic'}])
        self.assertIn('invalid_neighbor_issue_owner',mod.decision(t,b,r)['reasons'])

    def test_cross_boundary_and_outside_evidence_never_pass(self):
        _,tasks=fixture();t=v4task(tasks[0])
        b,r=scoped(t);r['target_scope']['boundary_crossing']=True
        self.assertIn('primary_boundary_ownership_unresolved',mod.decision(t,b,r)['reasons'])
        b,r=scoped(t);r['addition_spans'][0]['end_seconds']+=1
        self.assertIn('addition_evidence_outside_or_unordered',mod.decision(t,b,r)['reasons'])
        b,r=scoped(t);b['target_scope']['end_seconds']+=1
        self.assertIn('wrong_primary_scope',mod.decision(t,b,r)['reasons'])

    def test_context_text_cannot_replace_primary_text_or_evidence(self):
        _,tasks=fixture();t=v4task(tasks[0])
        b,r=scoped(t,'이웃 말 '+t['after'])
        self.assertFalse(mod.decision(t,b,r)['passed'])
        b,r=scoped(t);r['addition_spans']=[]
        self.assertIn('addition_evidence_missing_or_different',mod.decision(t,b,r)['reasons'])
        b,r=scoped(t);b['target_spans'][0]['text']='다른 내용'
        self.assertIn('target_evidence_text_mismatch',mod.decision(t,b,r)['reasons'])

    def test_repeated_speech_never_removed_by_scope_policy(self):
        _,tasks=fixture();t=v4task(tasks[1]);b,r=scoped(t,'반복')
        self.assertFalse(mod.decision(t,b,r)['passed'])

    def test_two_files_pcm_mapping_and_mutated_context_fail_closed(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);source=raw_file(root);_,tasks=fixture();t=tasks[0]
            make_files(root,t,source)
            paths,binding,data,_=mod.primary_context_bundle(root,t)
            self.assertEqual(len(paths),2);self.assertEqual(binding['primary_in_context_seconds'],[1,3])
            self.assertEqual(data['scope'],'primary_file_only')
            self.assertEqual(data['target_seconds'],[0,2])
            # Same hash metadata is insufficient: PCM binding must still catch a shifted context.
            t['context_clip_meta']=mod.clip(source,root/t['context_clip'],1,5)
            t['context_clip_meta'].update(start_seconds=0,end_seconds=4)
            with self.assertRaisesRegex(ValueError,'original_samples'):
                mod.primary_context_bundle(root,t)

    def test_v4_fake_end_to_end_uses_only_primary_text_and_separate_queue(self):
        snap,tasks=fixture()
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);source=raw_file(root);save(root/'snapshot.json',snap)
            for t in tasks:make_files(root,t,source)
            p={'version':4,'tasks':tasks,'model':'fake'};calls=[]
            class Fake:
                def __init__(self,*a,**kw):pass
                def call(self,stage,media,prompt,schema):
                    t=next(t for t in tasks if Path(t['target_clip']).name==media[0].name)
                    data=json.loads(prompt.split('DATA:\n',1)[1]);calls.append((t['id'],list(media)))
                    assert len(media)==2 and data['scope']=='primary_file_only'
                    assert data['target_seconds']==[0,t['interval'][1]-t['interval'][0]]
                    b,r=scoped(t)
                    if stage.endswith('blind-v4'):
                        assert 'current_text' not in data
                        return b
                    assert data['current_text']==t['before'] and data['proposed_text']==t['after']
                    return r
            with patch.object(mod,'verify',return_value=p),patch.object(mod,'api_key',return_value='mock'),patch.object(mod,'Gemini',Fake):
                mod.run(root,root/'.env',delay=0)
                mod.run(root,root/'.env',delay=0)
            self.assertEqual(len(calls),4)
            for t in tasks:
                pair=[c for c in calls if c[0]==t['id']];self.assertEqual(pair[0],pair[1])
            manifest=read(read(root/'latest.json')['manifest'])
            self.assertEqual(manifest['applied_repairs'],1)
            self.assertIn('neighbor-review-queue.jsonl',manifest['file_hashes'])


if __name__=='__main__':unittest.main()
