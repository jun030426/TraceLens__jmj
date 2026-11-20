"""Whole-unit boundary review and conservative difference policy, offline only."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from video_extraction.audio import audio_finalize as mod
from video_extraction.shared.common import save, read
from video_extraction.tests.test_audio_finalize import fixture, response, outcome
from video_extraction.tests.test_audio_target_window import raw_file


def row(key,a,b,text):
    return {'id':key,'start_seconds':a,'end_seconds':b,'text':text}


def control(text):
    return {'id':'control','role':'control','target_id':'b','interval':[5,5.36],
            'before':text,'after':text,'review_protocol':3,'review_after':text}


def judged(task, blind_text, review_text=None):
    return mod.decision(task, {'text':blind_text,'uncertain':False,'boundary_clear':True,'reason':'mock'},
                        response(review_text or blind_text,task['role']=='repair'))


class BoundaryReviewTests(unittest.TestCase):
    def test_short_target_expands_to_whole_neighbours_and_keeps_ids(self):
        t=control('되겠죠');before=copy.deepcopy(t)
        rows=[row('a',3,5,'그러면'),row('b',5,5.36,'되겠죠'),row('c',5.36,7,'다음입니다')]
        unit=mod.review_unit(t,rows)
        self.assertEqual(t,before)
        self.assertEqual(unit['review_interval'],[3,7])
        self.assertEqual(unit['review_before'],'그러면 되겠죠 다음입니다')
        self.assertEqual(unit['review_before'],unit['review_after'])
        self.assertEqual(unit['review_row_ids'],['a','b','c'])

    def test_neighbours_never_rewritten_and_imported_word_is_visible_twice(self):
        t=control('가격을 계산하기');t.update(role='repair',after='가격을 계산하기 위한')
        rows=[row('a',3,5,'전체적으로'),row('b',5,5.36,t['before']),row('c',5.36,7,'위한 코드입니다')]
        unit=mod.review_unit(t,rows)
        self.assertEqual(unit['review_after'],'전체적으로 가격을 계산하기 위한 위한 코드입니다')
        self.assertNotEqual(mod.canonical(unit['review_before']),mod.canonical(unit['review_after']))

    def test_insertion_missing_utterance_preserves_both_neighbours(self):
        t=control('');t.update(target_id='',after='새 발화',role='repair')
        unit=mod.review_unit(t,[row('a',3,5,'앞'),row('c',5.36,7,'뒤')])
        self.assertEqual(unit['review_before'],'앞 뒤')
        self.assertEqual(unit['review_after'],'앞 새 발화 뒤')

    def test_recording_edges_and_far_neighbours(self):
        t=control('시작');t.update(interval=[0,.36])
        unit=mod.review_unit(t,[row('b',0,.36,'시작'),row('c',10,12,'먼 말')])
        self.assertEqual(unit['review_interval'],[0,.36])
        self.assertFalse(unit['boundary_expanded'])

    def test_changed_target_mapping_fails_closed(self):
        with self.assertRaisesRegex(ValueError,'frozen_row'):
            mod.review_unit(control('되겠죠'),[row('b',5,5.36,'다른 말')])

    def test_overlapping_context_closes_without_editing_primary_or_rows(self):
        t=control('되겠죠');before=copy.deepcopy(t)
        rows=[row('a',3,5,'앞'),row('b',5,5.36,'되겠죠'),row('c',5.36,7,'다음'),
              row('d',6.98,8,'경계'),row('e',7.98,9,'끝')]
        frozen=copy.deepcopy(rows)
        unit=mod.review_unit(t,rows)
        self.assertEqual(unit['review_interval'],[3,9])
        self.assertEqual(unit['review_row_ids'],['a','b','c','d','e'])
        self.assertEqual(unit['review_before'],'앞 되겠죠 다음 경계 끝')
        self.assertEqual(rows,frozen);self.assertEqual(t,before)

    def test_overlap_chain_cannot_create_unbounded_context(self):
        rows=[row('a',3,5,'앞'),row('b',5,5.36,'되겠죠'),row('c',5.36,7,'다음'),
              row('d',6.98,60,'긴 겹침')]
        with self.assertRaisesRegex(ValueError,'overlapping_segment'):
            mod.review_unit(control('되겠죠'),rows)

    def test_surface_warning_retains_content_and_needs_all_safety_checks(self):
        t=control('이 구조를 뭐라 부르느냐')
        gate=judged(t,'이 구조를 뭐라고 부르느냐',t['after'])
        self.assertTrue(gate['passed']);self.assertEqual(gate['classification'],'surface_warning')
        self.assertTrue(gate['warnings'])
        b={'text':'이 구조를 뭐라고 부르느냐','uncertain':False,'boundary_clear':True,'reason':'mock'}
        for key in ['repetitions_preserved','no_neighbor_double_capture','boundaries_supported','no_new_error']:
            r=response(t['after'],False);r[key]=False
            self.assertFalse(mod.decision(t,b,r)['passed'])
        b['boundary_clear']=False
        self.assertEqual(mod.decision(t,b,response(t['after'],False))['classification'],'boundary_or_audio_uncertain')

    def test_numbers_negation_repeats_and_endings_are_not_surface(self):
        for a,b in [('1.5','15'),('-3','3'),('3','4'),('a+b','a-b'),('가능하다','불가능하다'),
                    ('상품 상품','상품'),('거죠','거잖아요'),('객체','개체'),('과','가')]:
            with self.subTest(a=a,b=b):
                self.assertEqual(mod.text_difference(a,b),'content_or_reading_difference')
                self.assertFalse(judged(control(a),b,a)['passed'])

    def test_spelling_only_warning_does_not_apply_a_repair(self):
        _,tasks=fixture();t=tasks[0]
        t.update(review_protocol=3,review_after='메소드 이름과 점수')
        self.assertFalse(judged(t,'메서드 이름과 점수',t['review_after'])['passed'])
        self.assertTrue(judged(control('메소드'),'메서드')['passed'])

    def test_warning_control_original_preserved_in_selection(self):
        snap,tasks=fixture();t=tasks[1]
        snap['rows'][1]['text']=snap['rows'][1]['baseline_text']='뭐라 부르느냐'
        t.update(before='뭐라 부르느냐',after='뭐라 부르느냐',review_protocol=3,review_after='뭐라 부르느냐')
        outcomes={tasks[0]['id']:outcome(tasks[0]),t['id']:{'gate':judged(t,'뭐라고 부르느냐')}}
        bundle=mod.selection(snap,tasks,outcomes)
        selected=next(r for r in bundle['selected'] if r['id']=='b')
        self.assertEqual(selected['observed_text'],'뭐라 부르느냐')
        self.assertTrue(selected['audio_recheck_warnings'])
        self.assertFalse(selected['audio_coverage_repair_applied'])

    def test_whole_unit_pcm_and_both_requests_and_publish(self):
        snap,tasks=fixture()
        # Dense rows ensure review units include neighbours, not just the target.
        snap['rows'][1].update(start_seconds=3,end_seconds=5)
        tasks[1]['interval']=[3,5]
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);source=raw_file(root);save(root/'snapshot.json',snap)
            calls=[]
            for t in tasks:
                t.update(mod.review_unit(t,snap['rows']))
                t.update(target_clip=t['id']+'.wav')
                t['target_clip_meta']=mod.clip(source,root/t['target_clip'],*t['review_interval'])
                mod.verify_slice(source,root/t['target_clip'],t['target_clip_meta'],t['review_interval'])
            p={'version':3,'tasks':tasks,'model':'fake'}
            class Fake:
                def __init__(self,*a,**kw):pass
                def call(self,stage,media,prompt,schema):
                    t=next(t for t in tasks if media[0].name==t['target_clip'])
                    data=json.loads(prompt.split('DATA:\n',1)[1])
                    assert len(media)==1 and data['scope']=='entire_attached_file'
                    calls.append((t['id'],str(media[0]),data['target_seconds']))
                    if stage.endswith('blind-v3'):
                        assert 'current_text' not in data
                        return {'text':t['review_after'],'uncertain':False,'boundary_clear':True,'reason':'mock'}
                    assert data['current_text']==t['review_before']
                    assert data['proposed_text']==t['review_after']
                    return response(t['review_after'],t['role']=='repair')
            with patch.object(mod,'verify',return_value=p),patch.object(mod,'api_key',return_value='mock'),patch.object(mod,'Gemini',Fake):
                mod.run(root,root/'.env',delay=0)
                count=len(calls);mod.run(root,root/'.env',delay=0)
                self.assertEqual(len(calls),count)
            for t in tasks:
                pair=[c for c in calls if c[0]==t['id']]
                self.assertEqual(pair[0],pair[1])
            manifest=read(read(root/'latest.json')['manifest'])
            self.assertEqual(manifest['applied_repairs'],1)
            self.assertFalse(manifest['old_files_overwritten'])


if __name__=='__main__':
    unittest.main()
