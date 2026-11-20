import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from video_extraction.shared.common import read, digest_file
from video_extraction.ink.selection.usable_selection import select_result, build, SOURCE, REVIEW_OUTPUT, result_paths


def case(tid='frame-00058-ink-001'):
    snapshot=Path(read(REVIEW_OUTPUT/'latest.json')['snapshot'])
    path=snapshot/'results'/(tid+'.json')
    return path,read(path)


class UsableSelectionTests(unittest.TestCase):
    def test_confirmed_ocr_false_positive_selected_without_rewriting(self):
        path,r=case();before=copy.deepcopy(r);good,bad=select_result(r,path)
        item=next(x for x in good if x['local_id']=='c-1')
        self.assertEqual(item['text_for_chunking'],'for product in products:')
        self.assertEqual(r,before);self.assertFalse(item['embedding_created'])
        self.assertFalse(item['gold_approved']);self.assertFalse(item['record']['approved_for_rag'])

    def test_held_targets_cannot_reenter_via_relation(self):
        path,r=case();next(d for d in r['decisions'] if d['id']=='c-1')['status']='held'
        good,bad=select_result(r,path);ids={x['local_id'] for x in good}
        self.assertFalse(ids & {'c-1','l-1','l-13'})
        self.assertTrue(any('unselected_relation_target' in x['reasons'] for x in bad))

    def test_unverified_and_unsupported_source_not_selected(self):
        path,r=case()
        for mutation in ['status','audit','duplicate_check','method','blocking','source']:
            z=copy.deepcopy(r);row=next(x for x in z['records'] if x['local_id']=='c-1')
            if mutation=='status':row['judgment']='unassessed'
            elif mutation=='audit':next(c for c in z['final_audit']['checks'] if c['id']=='c-1')['content']='unsupported'
            elif mutation=='duplicate_check':z['final_audit']['checks'].append(next(c for c in z['final_audit']['checks'] if c['id']=='c-1'))
            elif mutation=='method':row['verification']['method']='local_geometry_only'
            elif mutation=='blocking':row['policy_findings']['blocking']=['invalid_box']
            else:row['selected_frame']='/does/not/exist.png'
            good,_=select_result(z,path);self.assertNotIn('c-1',{x['local_id'] for x in good},mutation)

    def test_cancel_uncertainty_and_invalid_box_excluded(self):
        path,r=case()
        for mutation in ['cancelled','uncertainties','geometry']:
            z=copy.deepcopy(r);row=next(x for x in z['records'] if x['local_id']=='c-1')
            if mutation=='geometry':row['normalized']['box_source_fraction']=[0,0,2,1]
            else:row['raw_payload']['raw'][mutation]=True if mutation=='cancelled' else ['0/o']
            good,_=select_result(z,path);self.assertNotIn('c-1',{x['local_id'] for x in good})

    def test_numeric_context_candidate_never_substitutes_literal(self):
        path,r=case('frame-00059-ink-001');good,bad=select_result(r,path)
        self.assertNotIn('it-8',{x['local_id'] for x in good})
        held=next(x for x in bad if x['local_id']=='it-8')
        self.assertEqual(held['observation']['text'],'max_product = products[0]')
        self.assertEqual(held['decision']['status'],'held')

    def test_approximate_emphasis_is_metadata_not_invented_text(self):
        path,r=case('frame-00005-ink-000');good,_=select_result(r,path)
        row=next(x for x in good if x['local_id']=='m3')
        self.assertEqual(row['route'],'linked_metadata');self.assertEqual(row['text_for_chunking'],'')
        self.assertFalse(row['selection']['exact_geometry_verified'])
        self.assertEqual(row['selection']['interpretation_scope'],'coarse_emphasis_target_only')

    def test_unknown_warning_is_not_silently_allowed(self):
        path,r=case();next(x for x in r['records'] if x['local_id']=='c-1')['policy_findings']['warnings'].append('unknown_warning')
        good,bad=select_result(r,path)
        self.assertNotIn('c-1',{x['local_id'] for x in good})

    def test_latest_task_versions_no_concatenation_and_stale_result_rejected(self):
        snapshot=Path(read(REVIEW_OUTPUT/'latest.json')['snapshot']);plan=read(SOURCE/'plan.json')
        paths=result_paths(SOURCE,plan,snapshot)
        self.assertEqual(len(paths),len(list((SOURCE/'results').glob('*.json')))+24)
        self.assertIn('ink-source-review-v1',str(paths['frame-00007-ink-001']))
        with patch('video_extraction.ink.selection.usable_selection.read',wraps=read) as reader:
            original=read
            def changed(path):
                value=original(path)
                if str(path).startswith(str(snapshot)) and '/results/' in str(path):value['overlay_source_signature']='bad'
                return value
            reader.side_effect=changed
            with self.assertRaisesRegex(ValueError,'review_stale'):result_paths(SOURCE,plan,snapshot)

    def test_end_to_end_no_api_no_embedding_partial_and_input_preserved(self):
        path,r=case();before=digest_file(path)
        # This is a frozen historical fixture, not permission to republish a stale
        # production run. Keep the version guard tested; replay selection alone
        # with its archived plan and still verify every bound input.
        from video_extraction.ink.runner.ink_continue_v2 import check_plan, hashes
        from video_extraction._layout import code_hashes_match
        archived=read(SOURCE/'plan.json')
        if not code_hashes_match(archived['code_hashes'],hashes()):
            with self.assertRaisesRegex(ValueError,'code_changed_prepare_new_output'):check_plan(SOURCE)
        def frozen_plan(source):
            self.assertIn(source,(SOURCE,Path(archived['source'])))
            fixture=read(source/'plan.json')
            for filename,expected in fixture['input_hashes'].items():
                self.assertEqual(digest_file(filename),expected)
            return copy.deepcopy(fixture)
        with tempfile.TemporaryDirectory() as tmp,patch('video_extraction.shared.gemini.Gemini',side_effect=AssertionError('API forbidden')),patch('video_extraction.ink.selection.usable_selection.check_plan',side_effect=frozen_plan),patch('video_extraction.ink.runner.ink_continue.check_plan',side_effect=frozen_plan):
            out=Path(tmp)/'select';s=build(output=out)
            self.assertGreater(s['selected_records'],0);self.assertGreater(s['remaining_regions'],0)
            self.assertEqual(s['stage'],'partial_selection');self.assertFalse(s['all_modalities_complete'])
            self.assertFalse(s['embedding_created']);self.assertEqual(s['api_requests'],0)
            snapshot=Path(read(out/'latest.json')['snapshot'])
            rows=[json.loads(l) for l in (snapshot/'usable-records.jsonl').read_text().splitlines()]
            self.assertEqual(len(rows),len({r['id'] for r in rows}))
            self.assertTrue(all(r['record']['judgment']!='held' for r in rows))
            self.assertEqual(read(snapshot/'other-modality-status.json')['records'],2124)
            first=str(snapshot);build(output=out);self.assertEqual(read(out/'latest.json')['snapshot'],first)
        self.assertEqual(before,digest_file(path))


if __name__=='__main__':unittest.main()
