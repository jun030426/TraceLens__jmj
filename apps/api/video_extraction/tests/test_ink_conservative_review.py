import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from video_extraction.shared.common import read, digest_file
from video_extraction.ink.policy.ink_conservative_review import SOURCE, RECEIPTS, reconcile, protect_original, simple_emphasis_eligible, cause_groups, administrator_groups, build


def case(tid):
    return read(SOURCE/'prepared'/(tid+'.json')), read(SOURCE/'results'/(tid+'.json'))


class ConservativeReviewTests(unittest.TestCase):
    def test_real_ocr_conflict_releases_only_verified_three_without_rewriting(self):
        tid='frame-00058-ink-001';p,r=case(tid)
        updated=reconcile(p,r,read(RECEIPTS)[tid]);protect_original(r,updated)
        self.assertEqual(updated['candidate'],r['candidate'])
        self.assertFalse(any(d['status']=='held' for d in updated['decisions']))
        self.assertEqual(len(updated['records'])-len(r['records']),3)

    def test_ambiguous_zero_and_structure_and_real_geometry_remain_held(self):
        for tid in ['frame-00059-ink-001','frame-00079-ink-000','frame-00028-ink-002']:
            p,r=case(tid);u=reconcile(p,r,read(RECEIPTS)[tid]);protect_original(r,u)
            self.assertEqual([d['id'] for d in r['decisions'] if d['status']=='held'],
                             [d['id'] for d in u['decisions'] if d['status']=='held'])
            self.assertEqual(u['missing_core'],r['missing_core'])
        p,r=case('frame-00059-ink-001');u=reconcile(p,r,read(RECEIPTS)['frame-00059-ink-001'])
        span=u['direct_observation']['unresolved_spans'][0]
        self.assertEqual(span['status'],'unconfirmed');self.assertEqual(span['contextual_candidate'],'0')

    def test_simple_emphasis_extent_warns_without_geometry_repair(self):
        p,r=case('frame-00005-ink-000');self.assertTrue(simple_emphasis_eligible(r,'m3'))
        u=reconcile(p,r);protect_original(r,u)
        for iid in ['m3','l3']:
            d=next(d for d in u['decisions'] if d['id']==iid)
            self.assertEqual(d['status'],'usable_with_warning')
            self.assertIn('imprecise_simple_emphasis_extent',d['warnings'])
        self.assertEqual(u['candidate'],r['candidate'])

    def test_direction_cancel_partial_content_critical_and_split_cannot_be_waived(self):
        _,r=case('frame-00005-ink-000')
        for field,value in [('kind','arrow'),('cancelled',True),('text','3'),('uncertainties',['unclear'])]:
            z=copy.deepcopy(r);next(i for i in z['candidate']['items'] if i['id']=='m3')[field]=value
            self.assertFalse(simple_emphasis_eligible(z,'m3'),field)
        for field,value in [('critical',True),('split_required',True),('role_risk',True),('content','partial'),('meaning','uncertain')]:
            z=copy.deepcopy(r);next(c for c in z['final_audit']['checks'] if c['id']=='m3')[field]=value
            self.assertFalse(simple_emphasis_eligible(z,'m3'),field)

    def test_invalid_box_no_pixels_or_held_target_cannot_be_waived(self):
        _,r=case('frame-00005-ink-000')
        z=copy.deepcopy(r);next(i for i in z['candidate']['items'] if i['id']=='m3')['box']['right']=1100
        self.assertFalse(simple_emphasis_eligible(z,'m3'))
        z=copy.deepcopy(r);next(d for d in z['decisions'] if d['id']=='t2')['status']='held'
        self.assertFalse(simple_emphasis_eligible(z,'m3'))
        with patch('video_extraction.ink.policy.ink_conservative_review.pixel_evidence',return_value={'foreground_pixels':0}):
            self.assertFalse(simple_emphasis_eligible(r,'m3'))

    def test_own_relation_error_is_not_hidden_by_grouping_or_release(self):
        p,r=case('frame-00058-ink-001')
        next(d for d in r['decisions'] if d['id']=='l-1')['reasons'].append('direction_without_endpoints')
        groups=cause_groups(r)
        self.assertEqual(len(groups),2)
        self.assertTrue(any(g['root_ids']==['l-1'] for g in groups))

    def test_unrelated_same_frame_holds_not_merged(self):
        _,r=case('frame-00028-ink-002')
        self.assertEqual(len(cause_groups(r)),1)
        d=next(d for d in r['decisions'] if d['id']=='t4')
        d.update(status='held',reasons=['ocr_text_conflict'])
        self.assertEqual(len(cause_groups(r)),2)

    def test_stale_review_does_not_release_a_new_sample(self):
        tid='frame-00058-ink-001';p,r=case(tid);receipt=read(RECEIPTS)[tid]
        receipt['source_sha256']='different'
        u=reconcile(p,r,receipt)
        self.assertEqual(sum(d['status']=='held' for d in u['decisions']),3)
        self.assertEqual(u['overlay_notices'],['source_review_receipt_stale_not_applied'])

    def test_guard_rejects_text_geometry_and_healthy_status_regressions(self):
        _,r=case('frame-00005-ink-000')
        for change in ['text','box','status','record']:
            u=copy.deepcopy(r)
            if change=='text':u['candidate']['items'][0]['text']='wrong'
            elif change=='box':u['candidate']['items'][0]['box']['left']=0
            elif change=='status':next(d for d in u['decisions'] if d['status']!='held')['status']='held'
            else:u['records'][0]['judgment']='held'
            with self.assertRaises(ValueError):protect_original(r,u)

    def test_all_existing_normal_regions_preserved(self):
        checked=0
        for f in (SOURCE/'results').glob('*.json'):
            r=read(f)
            if any(d['status']=='held' for d in r['decisions']):continue
            p=read(SOURCE/'prepared'/f.name);u=reconcile(p,r);protect_original(r,u)
            self.assertEqual(u['records'],r['records']);self.assertEqual(u['decisions'],r['decisions'])
            checked+=1
        self.assertGreaterEqual(checked,25)

    def test_end_to_end_no_api_preserves_inputs_and_groups_nine_admin_entries(self):
        paths=list((SOURCE/'results').glob('*.json'))+[SOURCE/'records.jsonl',SOURCE/'pending.jsonl']
        before={str(p):digest_file(p) for p in paths}
        source_results=[read(p) for p in (SOURCE/'results').glob('*.json')]
        held_before=sum(d['status']=='held' for r in source_results for d in r.get('decisions',[]))
        group_before=sum(len([g for g in cause_groups(r) if g['status']=='held']) for r in source_results)
        missing_before=sum(len(r.get('missing_core',[])) for r in source_results)
        with tempfile.TemporaryDirectory() as tmp, patch('video_extraction.shared.gemini.Gemini',side_effect=AssertionError('API forbidden')):
            out=Path(tmp)/'review';s=build(SOURCE,out)
            self.assertEqual((s['held_items_before'],s['held_items_after']),(held_before,held_before-5))
            self.assertEqual(s['held_cause_groups'],group_before-2);self.assertEqual(s['missing_mark_groups'],missing_before)
            self.assertEqual((s['administrator_entries'],s['administrator_groups']),(9,3))
            self.assertEqual(s['literal_or_geometry_edits'],0);self.assertEqual(s['api_requests'],0)
            first=read(out/'latest.json')['snapshot'];build(SOURCE,out)
            self.assertEqual(read(out/'latest.json')['snapshot'],first)
            report=(out/'보류원인_검토.html').read_text()
            self.assertIn('기존 의미 미확정',report);self.assertIn('상태 변경 내역',report)
        self.assertEqual(before,{str(p):digest_file(p) for p in paths})


if __name__=='__main__':unittest.main()
