import copy
import unittest

from video_extraction.shared.recovery import normalize_box, normalize_time, inspect_batch, plan_recovery
from video_extraction.review.recovery_replay import adapt_inventory


def box(coords, **kwargs):
    return {'shape': 'box', 'coordinates': coords, 'order': 'xyxy',
            'unit': 'fraction', 'reference': 'source', **kwargs}


def item(name, geometry=None, **kwargs):
    return {'id': name, 'modality': 'image',
            'location': {'geometry': geometry or box([.1, .2, .3, .4])}, **kwargs}


class RecoveryTests(unittest.TestCase):
    def test_explicit_orders_and_named_coordinates(self):
        expected = [.1, .2, .3, .4]
        self.assertEqual(normalize_box(box([100, 200, 300, 400], unit='normalized_1000')), expected)
        self.assertEqual(normalize_box(box([200, 100, 400, 300], order='yxyx', unit='normalized_1000')), expected)
        got = normalize_box(box([10, 40, 20, 40], order='xywh', unit='pixel', reference_size=[100, 200]))
        for a, b in zip(got, expected): self.assertAlmostEqual(a, b)
        self.assertEqual(normalize_box(box(dict(left=.1, top=.2, right=.3, bottom=.4), order='named')), expected)

    def test_crop_transform_and_native_emu(self):
        got = normalize_box(box([0, 0, 100, 50], unit='pixel', reference_size=[100, 50],
                                reference='crop', crop_in_source=[.2, .3, .6, .8]))
        self.assertEqual(got, [.2, .3, .6, .8])
        self.assertEqual(normalize_box(box([0, 0, 50, 100], unit='emu', reference_size=[100, 100])), [0, 0, .5, 1])

    def test_unknown_contract_never_guessed(self):
        for change in ({'order': None}, {'reference': None}, {'unit': 'unknown'},
                       {'shape': 'polygon'}, {'rotation_degrees': 90}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                normalize_box(box([.1, .2, .3, .4], **change))

    def test_nonfinite_inverted_and_boolean_coordinates_rejected(self):
        for coords in ([0, 0, float('inf'), 1], [True, 0, 1, 1], [0, 0, 0, 1], [.4, 0, .2, 1]):
            with self.subTest(coords=coords), self.assertRaises(ValueError): normalize_box(box(coords))

    def test_outside_coordinates_preserved_without_clamping(self):
        raw = item('outside', box([-.1, .2, 1.2, .4]))
        before = copy.deepcopy(raw)
        row = inspect_batch([raw], 'sha', 'tool')[0]
        self.assertEqual(row['normalized']['box_source_fraction'], [-.1, .2, 1.2, .4])
        self.assertIn('outside_source', [i['code'] for i in row['issues']])
        self.assertEqual(raw, before)

    def test_proposal_boundary_is_warning_and_swap_only_hypothesis(self):
        row = inspect_batch([item('swap', box([.2, .7, .3, .8]))], 'sha', 'tool', [.65, .15, .85, .35])[0]
        self.assertEqual(row['normalized']['box_source_fraction'], [.2, .7, .3, .8])
        self.assertEqual(row['correction_candidates'][0]['box_source_fraction'], [.7, .2, .8, .3])
        self.assertFalse(row['correction_candidates'][0]['applied'])
        self.assertEqual(next(i['category'] for i in row['issues'] if i['code']=='outside_proposal'), 'warning')

    def test_inside_roi_is_not_verified_geometry(self):
        row = inspect_batch([item('ok')], 'sha', 'tool', [0, 0, 1, 1])[0]
        self.assertIn('geometry_evidence_pending', [i['code'] for i in row['issues']])
        self.assertFalse(row['content_verified'])
        self.assertFalse(row['approved_for_rag'])

    def test_time_units_offsets_and_durations(self):
        self.assertEqual(normalize_time({'interval': [1000, 3000], 'unit': 'milliseconds',
            'reference': 'clip', 'clip_start_seconds': 10}), [11, 13])
        self.assertEqual(normalize_time({'interval': [16000, 32000], 'unit': 'samples',
            'sample_rate': 16000, 'reference': 'source'}), [1, 2])
        u = {'id': 'speech', 'modality': 'audio', 'location': {'time': {'interval': [9, 11],
            'unit': 'seconds', 'reference': 'source', 'source_duration_seconds': 10}}}
        self.assertIn('outside_source_time', [i['code'] for i in inspect_batch([u], 'sha', 'asr')[0]['issues']])

    def test_bad_member_does_not_discard_siblings_or_extensions(self):
        units = [item('good', custom_payload={'tool_field': [0, None, '001']}), None,
                 item('bad', box([.8, .1, .2, .3]))]
        rows = inspect_batch(units, 'sha', 'tool')
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]['raw_payload'], units[0])
        self.assertFalse(any(i['category']=='error' for i in rows[0]['issues']))
        self.assertEqual(rows[1]['stage'], 'unprocessed')
        self.assertTrue(any(i['category']=='error' for i in rows[2]['issues']))

    def test_duplicate_ids_preserved_and_dependents_blocked(self):
        rows = inspect_batch([item('x'), item('x'), {'id':'rel', 'modality':'relation',
            'location':{}, 'references':['x']}, item('occurrence:0')], 'sha', 'tool')
        self.assertEqual(len({r['id'] for r in rows}), 4)
        self.assertIn('missing_or_ambiguous_reference', [i['code'] for i in rows[2]['issues']])

    def test_dependency_failure_is_local_and_transitive(self):
        units = [item('bad', box([1, 0, 0, 1])), item('fine'),
                 {'id':'a', 'modality':'relation', 'location':{}, 'references':['bad']},
                 {'id':'b', 'modality':'relation', 'location':{}, 'references':['a']}]
        rows = inspect_batch(units, 'sha', 'tool')
        self.assertNotIn('dependency_unresolved', [i['code'] for i in rows[1]['issues']])
        for r in rows[2:]: self.assertIn('dependency_unresolved', [i['code'] for i in r['issues']])

    def test_unknown_modality_and_mixed_structured_data_remain_raw(self):
        table = {'id':'table','modality':'table','location':{},'rows':[['001',0,None,'',False]]}
        unknown = {'id':'3d','modality':'point_cloud','location':{},'points':[[1,2,3]]}
        rows = inspect_batch([table,unknown], 'sha', 'native')
        self.assertEqual(rows[0]['raw_payload'], table)
        self.assertEqual(rows[1]['raw_payload'], unknown)
        self.assertEqual(rows[1]['stage'], 'unprocessed')

    def test_queue_is_idempotent_budgeted_and_has_attempt_cap(self):
        rows = inspect_batch([item('one'),item('two')], 'sha', 'tool')
        jobs = plan_recovery(rows+rows, max_items=1)
        self.assertEqual(len(jobs), 2)
        self.assertEqual([j['state'] for j in jobs], ['planned','deferred_budget'])
        capped = plan_recovery(rows, {jobs[0]['id']:2}, max_attempts=2)
        self.assertEqual(capped[0]['state'], 'review_required')
        self.assertTrue(all(not j['executed'] for j in capped))
        blocked = plan_recovery(rows, api_actions=['source_geometry_review'], api_budget=0)
        self.assertTrue(all(j['state']=='deferred_budget' for j in blocked))

    def test_changed_input_new_queue_identity(self):
        old = plan_recovery(inspect_batch([item('x')], 'sha', 'tool'))[0]['id']
        new = plan_recovery(inspect_batch([item('x', box([.1,.2,.4,.5]))], 'sha', 'tool'))[0]['id']
        self.assertNotEqual(old,new)

    def test_inventory_adapter_retains_partial_results_and_typed_references(self):
        raw = {'marks':[{'id':'x','bbox':[0,0,50,50]}, {'id':'bad','bbox':None}],
               'targets':[{'id':'x','bbox':[0,0,30,30]}],
               'relations':[{'id':'r','mark_ids':['x'],'to_target_ids':['x'],'from_target_ids':[]}]}
        before = copy.deepcopy(raw)
        rows = inspect_batch(adapt_inventory(raw), 'sha', 'ink')
        self.assertEqual(len(rows),4)
        self.assertNotIn('missing_or_ambiguous_reference',[i['code'] for i in rows[-1]['issues']])
        self.assertEqual(raw,before)
        self.assertEqual(rows[1]['raw_payload']['raw'],raw['marks'][1])


if __name__ == '__main__': unittest.main()
