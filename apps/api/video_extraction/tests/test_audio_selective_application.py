"""Local control failures cannot block unrelated, source-bound repairs."""
import copy
import unittest
from video_extraction.audio import audio_finalize as mod
from video_extraction.tests.test_audio_finalize import fixture
from video_extraction.tests.test_audio_primary_scope import v4task,scoped


def setup():
    snap,tasks=fixture();tasks=[v4task(t) for t in tasks]
    good=copy.deepcopy(tasks[1]);good.update(id='control-good',target_id='d',interval=[15,16],before='정상',after='정상')
    tasks.append(good)
    outcomes={}
    for t in tasks:
        b,r=scoped(t)
        if t['id']=='control-b':b['uncertain']=True
        outcomes[t['id']]={'blind':b,'review':r,'gate':mod.decision(t,b,r)}
    return snap,tasks,outcomes


class SelectiveApplicationTests(unittest.TestCase):
    def test_unrelated_failed_control_kept_held_but_seven_style_repair_applies(self):
        snap,tasks,outcomes=setup();baseline=copy.deepcopy(snap)
        result=mod.selection(snap,tasks,outcomes,mod.LOCAL_POLICY)
        self.assertFalse(result['controls_passed'])
        self.assertEqual(len(result['receipts']),1)
        self.assertEqual(result['rows'][0]['text'],'이름과 점수')
        self.assertEqual(result['rows'][1]['text'],'반복 반복')
        self.assertIn('b',[r['id'] for r in result['excluded']])
        self.assertEqual(snap,baseline)

    def test_no_successful_controls_stops_all_application(self):
        snap,tasks,outcomes=setup();tasks=tasks[:2];outcomes={t['id']:outcomes[t['id']] for t in tasks}
        result=mod.selection(snap,tasks,outcomes,mod.LOCAL_POLICY)
        self.assertFalse(result['receipts'])
        self.assertIn('no_supported_control',result['application_decisions'][tasks[0]['id']]['reasons'])

    def test_overlapping_failed_control_blocks_only_related_repair(self):
        snap,tasks,outcomes=setup();tasks[1]['interval']=[2,4]
        app=mod.application_decisions(snap,tasks,outcomes,mod.LOCAL_POLICY)
        self.assertFalse(app[tasks[0]['id']]['apply'])
        self.assertTrue(any(x.startswith('dependent_or_overlapping_task') for x in app[tasks[0]['id']]['reasons']))

    def test_conflicting_repair_target_cannot_double_apply(self):
        snap,tasks,outcomes=setup();extra=copy.deepcopy(tasks[0]);extra['id']='repair-duplicate'
        tasks.append(extra);outcomes[extra['id']]=copy.deepcopy(outcomes[tasks[0]['id']])
        result=mod.selection(snap,tasks,outcomes,mod.LOCAL_POLICY)
        self.assertFalse(result['receipts'])

    def test_unresolved_finding_on_target_blocks_but_same_repair_is_superseded(self):
        snap,tasks,outcomes=setup();f=copy.deepcopy(tasks[0]['candidate']['finding'])
        snap['held']=[{'finding':f}]
        self.assertTrue(mod.application_decisions(snap,tasks,outcomes,mod.LOCAL_POLICY)[tasks[0]['id']]['apply'])
        f['after']='다른 보류 내용'
        self.assertFalse(mod.application_decisions(snap,tasks,outcomes,mod.LOCAL_POLICY)[tasks[0]['id']]['apply'])

    def test_forged_gate_or_missing_result_rejected(self):
        snap,tasks,outcomes=setup();outcomes[tasks[1]['id']]['gate']['passed']=True
        with self.assertRaisesRegex(ValueError,'gate_mismatch'):
            mod.application_decisions(snap,tasks,outcomes,mod.LOCAL_POLICY)
        del outcomes[tasks[1]['id']]
        with self.assertRaisesRegex(ValueError,'complete_outcomes'):
            mod.application_decisions(snap,tasks,outcomes,mod.LOCAL_POLICY)

    def test_invalid_evidence_blocks_individual_repair(self):
        snap,tasks,outcomes=setup();t=tasks[0];r=outcomes[t['id']]
        r['review']['addition_spans'][0]['end_seconds']=99
        r['gate']=mod.decision(t,r['blind'],r['review'])
        result=mod.selection(snap,tasks,outcomes,mod.LOCAL_POLICY)
        self.assertFalse(result['receipts'])


if __name__=='__main__':unittest.main()
