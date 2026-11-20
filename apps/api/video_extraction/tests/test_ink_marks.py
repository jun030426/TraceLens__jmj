import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from video_extraction.shared.common import read, save, signature
from video_extraction.shared.gemini import Blocked
from video_extraction.ink.recognition.ink_marks import validate_inventory, validate_context, validate_audit, coverage_findings, execute, run, freeze_check


def task():
    return {'id':'sample','source_sha256':'source','bbox':[100,100,600,500],
        'anchor_candidates':[],'onset_interval_seconds':[8,15],'audio_interval':[5,20],
        'before_image':'before.png','current_image':'current.png','after_image':'after.png',
        'crop':'crop.png','audio':'clip.wav','asr_context':[{'text':'SECRET_SPEECH'}],'human_feedback':[]}


def inventory():
    return {'marks':[{'id':'m'+str(i),'kind':'circle','bbox':[100+i*50,110,140+i*50,160],
        'literal_text':'','description':'circle','visibility':'clear','lifecycle':'active',
        'arrow_tail':[],'arrow_head':[],'uncertainties':[]} for i in (1,2)],
        'targets':[{'id':'t'+str(i),'bbox':[110+i*50,120,130+i*50,150],
                    'printed_text':word,'source_anchor_ids':[],'uncertainties':[]} for i,word in [(1,'합집합'),(2,'교집합')]],
        'relations':[{'id':'r'+str(i),'mark_ids':['m'+str(i)],'from_target_ids':[],
            'to_target_ids':['t'+str(i)],'kind':'emphasis','direction':'not_applicable','visual_evidence':'separate visible oval'} for i in (1,2)],
        'full_region_scanned':True,'truncated':False,'notes':[]}


def context():
    return {'relations':[{'relation_id':'r'+str(i),'speech_relevance':'aligned','speech_quote':word,
        'start_seconds':10+i,'end_seconds':11+i,'importance':'medium','reason':'matching explanation','conflicts':[]}
        for i,word in [(1,'합집합'),(2,'교집합')]],'word_candidates':[],'notes':[]}


def audit():
    return {'checks':[{'unit':unit,'id':x['id'],'decision':'supported','reason':'seen in source'}
        for unit,key in [('mark','marks'),('target','targets'),('relation','relations')] for x in inventory()[key]],
        'missing_marks':[],'missing_targets':[],'unassigned_ink_boxes':[],'scan_complete':True,'notes':[]}


class FakeClient:
    def __init__(self,stop=None):self.calls=[];self.stop=stop
    def call(self,stage,images,prompt,schema):
        self.calls.append((stage,images,prompt))
        if self.stop and self.stop in stage:raise Blocked('request_budget_exhausted')
        if '_inventory_' in stage:return inventory()
        if '_context_' in stage:return context()
        return audit()


class InkMarksTests(unittest.TestCase):
    def test_multiple_marks_targets_and_relations_are_preserved(self):
        inv=inventory();validate_inventory(inv,task());validate_context(context(),inv,task());validate_audit(audit(),inv,task())
        self.assertEqual(coverage_findings(inv,audit()),[])
        with tempfile.TemporaryDirectory() as p:
            result=execute(task(),Path(p),{},FakeClient())
        self.assertEqual(len(result['inventory']['marks']),2)
        self.assertEqual(len(result['audio_context']['relations']),2)
        self.assertFalse(result['approved']);self.assertFalse(result['applied']);self.assertFalse(result['ground_truth'])

    def test_missing_secondary_mark_in_audit_forces_hold(self):
        inv=inventory();a=audit()
        a['missing_marks']=[{'kind':'circle','bbox':[310,110,350,170],'description':'secondary oval'}]
        validate_audit(a,inv,task());self.assertIn('missing_marks',coverage_findings(inv,a))
        a['checks'][0]['decision']='partial'
        self.assertIn('source_check_unresolved',coverage_findings(inv,a))

    def test_audit_must_check_every_item_once(self):
        a=audit();a['checks'].pop()
        with self.assertRaisesRegex(ValueError,'audit_coverage'):validate_audit(a,inventory(),task())
        a=audit();a['checks'].append(copy.deepcopy(a['checks'][0]))
        with self.assertRaisesRegex(ValueError,'audit_coverage'):validate_audit(a,inventory(),task())

    def test_no_speech_leak_to_visual_inventory_or_source_audit(self):
        with tempfile.TemporaryDirectory() as p:
            c=FakeClient();execute(task(),Path(p),{},c)
            for index in (0,2):
                self.assertNotIn('SECRET_SPEECH',c.calls[index][2])
                self.assertTrue(all(x.suffix!='.wav' for x in c.calls[index][1]))
            self.assertIn('SECRET_SPEECH',c.calls[1][2]);self.assertEqual(c.calls[1][1][-1].suffix,'.wav')

    def test_cancelled_marks_cannot_become_emphasis(self):
        inv=inventory();inv['marks'][0]['lifecycle']='cancelled'
        with self.assertRaisesRegex(ValueError,'cancelled_mark'):validate_inventory(inv,task())
        inv['relations'][0]['kind']='cancellation';validate_inventory(inv,task())

    def test_sequence_needs_arrow_head_tail_and_targets(self):
        inv=inventory();r=inv['relations'][0];r.update(kind='sequence',direction='observed',from_target_ids=['t1'],to_target_ids=['t2'])
        with self.assertRaisesRegex(ValueError,'visible_endpoints'):validate_inventory(inv,task())
        inv['marks'][0].update(kind='arrow',arrow_tail=[155,120],arrow_head=[185,150])
        validate_inventory(inv,task())
        r['direction']='unknown'
        with self.assertRaisesRegex(ValueError,'sequence_without_direction'):validate_inventory(inv,task())

    def test_bad_references_and_off_region_targets_rejected(self):
        inv=inventory();inv['relations'][0]['to_target_ids']=['absent']
        with self.assertRaisesRegex(ValueError,'invalid_target_reference'):validate_inventory(inv,task())
        inv=inventory();inv['targets'][0]['source_anchor_ids']=['invented']
        with self.assertRaisesRegex(ValueError,'invented_source_anchor'):validate_inventory(inv,task())
        inv=inventory();inv['targets'][0]['bbox']=[800,800,900,900]
        with self.assertRaisesRegex(ValueError,'outside_scope'):validate_inventory(inv,task())

    def test_underlined_target_can_be_nearby_without_touching_mark(self):
        inv=inventory();t=task();t['bbox']=[100,150,600,180]
        inv['targets'][0]['bbox']=[155,126,185,146]
        validate_inventory(inv,t)

    def test_audio_cannot_add_relations_or_interpret_circle_as_word(self):
        c=context();c['relations'][0]['relation_id']='invented'
        with self.assertRaisesRegex(ValueError,'context_relation_coverage'):validate_context(c,inventory(),task())
        c=context();c['word_candidates']=[{'mark_id':'m1','value':'추측','basis':'sound'}]
        with self.assertRaisesRegex(ValueError,'nontext_symbol'):validate_context(c,inventory(),task())
        c=context();c['relations'][0]['end_seconds']=99
        with self.assertRaisesRegex(ValueError,'invalid_speech_interval'):validate_context(c,inventory(),task())

    def test_interrupted_run_reuses_completed_stage_receipts(self):
        with tempfile.TemporaryDirectory() as p:
            root=Path(p)
            with self.assertRaises(Blocked):execute(task(),root,{},FakeClient(stop='_context_'))
            self.assertTrue((root/'stages/sample.inventory.json').exists())
            c=FakeClient();execute(task(),root,{},c)
            self.assertEqual(len(c.calls),2)
            self.assertIn('_context_',c.calls[0][0])
            receipt=root/'stages/sample.audit.json';d=read(receipt);d['signature']='bad';save(receipt,d)
            with self.assertRaisesRegex(ValueError,'stale_stage'):execute(task(),root,{},FakeClient())

    def test_completed_run_does_not_construct_api_client(self):
        with tempfile.TemporaryDirectory() as p:
            root=Path(p);plan={'tasks':[task()],'model':'fake'}
            save(root/'results/sample.json',{'plan_signature':signature(plan)})
            with patch('video_extraction.ink.recognition.ink_marks.freeze_check',return_value=plan), \
                 patch('video_extraction.ink.recognition.ink_marks.report',return_value={}), \
                 patch('video_extraction.ink.recognition.ink_marks.Gemini',side_effect=AssertionError('API forbidden')):
                run(root,root/'unused.env')
            self.assertEqual(read(root/'run-state.json')['api_stats']['requests'],0)


if __name__=='__main__':unittest.main()
