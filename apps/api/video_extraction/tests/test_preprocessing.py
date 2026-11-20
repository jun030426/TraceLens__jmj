import copy
import json
import tempfile
import unittest
import wave
from pathlib import Path

from video_extraction.shared.common import digest_file, save, jsonl
from video_extraction.shared.preprocessing import normalize_text, normalize_table, resolve_sources, adapt_frame, adapt_slide, build_queue, plan_batch, validate_records
from video_extraction.review.evaluation_prepare import select_frames, prepare

AT = '2026-10-26T00:00:00+00:00'


class PreprocessingTests(unittest.TestCase):
    def test_code_digits_and_whitespace_are_preserved(self):
        code = '  name = student[o]\r\n\tprint("가", 0, "001")  '
        self.assertEqual(normalize_text(code, 'code'), (code, []))
        self.assertEqual(normalize_text(code, 'unclassified'), (code, []))
        self.assertEqual(normalize_text('가\r\n0 o', 'speech')[0], '가\n0 o')

    def test_tables_preserve_null_empty_leading_zeros_and_types(self):
        original = [['001', 0, None, '', False, 1.25]]
        result = normalize_table(original)
        self.assertEqual(result, original)
        result[0][0] = 'changed'
        self.assertEqual(original[0][0], '001')
        with self.assertRaises(ValueError):
            normalize_table([[float('nan')]])

    def test_source_relocation_uses_hash_not_similar_filename(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            wrong = root/'가.txt'
            wrong.write_text('wrong')
            right = root/'renamed.txt'
            right.write_text('original')
            entry = {'original_path': '/missing/가.txt', 'sha256': digest_file(right), 'bytes': right.stat().st_size}
            got = resolve_sources([entry], root)[0]
            self.assertEqual(got['resolved_path'], str(right.resolve()))
            self.assertEqual(resolve_sources([{**entry, 'sha256': 'wronghash'}], root)[0]['availability'], 'missing_original')

    def test_frame_preserves_payload_candidate_and_scoped_review(self):
        frame = {'id': 'f1', 'time_seconds': 1, 'path': 'relative.png'}
        extraction = {'final_blocks': [{'id': 'b', 'kind': 'code', 'text': 'student[o]', 'bbox': [1, 2, 10, 20]}],
                      'holds': [{'target_id': 'b', 'context_candidate': {'value': '0', 'applied': False}}],
                      'source_coordinate_review': {'decisions': [{'target_id': 'b', 'decision': 'corrected'}]}}
        original = copy.deepcopy(extraction)
        rows = adapt_frame('sha', frame, extraction, [], '/absolute.png')
        self.assertEqual(rows[0]['raw_payload']['frame'], frame)
        self.assertEqual(rows[0]['location']['image_path'], '/absolute.png')
        child = rows[1]
        self.assertEqual(child['normalized_text'], 'student[o]')
        self.assertFalse(child['correction_candidates'][0]['applied'])
        self.assertEqual(child['judgment'], 'held')
        self.assertFalse(child['approved_for_rag'])
        child['raw_payload']['text'] = 'changed'
        self.assertEqual(extraction, original)
        validate_records(rows)
        missing = adapt_frame('sha', frame, None, [ {'reason': 'no_baseline_extraction'} ])[0]
        self.assertEqual(missing['stage'], 'not_extracted')

    def test_slide_keeps_raw_asset_path_and_answer_role_on_children(self):
        slide = {'id': 's1', 'slide_number': 1, 'source_file': 'a.pptx', 'role': 'evaluation_reference',
                 'blocks': [], 'assets': [{'shape_id': 2, 'path': 'assets/a.png',
                                          'bbox_emu': {'left': 0, 'top': 0, 'width': 10, 'height': 10}}]}
        before = copy.deepcopy(slide)
        rows = adapt_slide('sha', slide, '/data')
        self.assertEqual(slide, before)
        self.assertEqual(rows[1]['raw_payload']['path'], 'assets/a.png')
        self.assertEqual(rows[1]['location']['image_path'], '/data/assets/a.png')
        self.assertTrue(all(r['educational_role']=='evaluation_reference' for r in rows))
        validate_records(rows)

    def test_queue_expands_budget_merges_audio_and_distinguishes_new_regions(self):
        def group(box):
            return {'category': 'other_verification_hold', 'frame_id': 'f', 'target_id': 'NEW',
                    'source_record_indices': [1], 'records': [{'original_hold': {'region': {'bbox': box}}}]}
        grouped = [group([0, 0, 10, 10]), group([20, 20, 30, 30]),
                   {'category': 'budget_summary', 'frame_id': 'f', 'remaining_regions':
                    [{'region': {'target_id': 'b1'}}, {'region': {'target_id': 'b2'}}]}]
        warnings = [{'reason': 'spoken_number_requires_listening', 'segment_id': 's1'},
                    {'reason': 'overlapping_transcript_intervals', 'segment_ids': ['s1', 's2']}]
        tasks = build_queue('sha', grouped, warnings, AT)
        self.assertEqual(len(tasks), 6)
        self.assertEqual(len(next(t for t in tasks if t['target']=={'segment_id':'s1'})['evidence_records']), 2)
        grouped[0]['source_record_indices'] = [99]
        again = build_queue('sha', grouped, warnings, '2026-10-27T00:00:00+00:00', tasks)
        self.assertEqual(tasks[0]['id'], again[0]['id'])
        self.assertEqual(again[0]['first_seen_at'], AT)

    def test_batch_preserves_all_work_and_never_executes(self):
        tasks = [{'id': str(i), 'estimated_effort_units': 2 if i else 100,
                  'first_seen_at': AT, 'importance_score': None, 'risk_score': 1} for i in range(8)]
        before = copy.deepcopy(tasks)
        batch = plan_batch(tasks, 6, 8, AT)
        self.assertEqual(batch['planned_effort_units'], 6)
        self.assertEqual(len(batch['selected'])+len(batch['deferred']), 8)
        self.assertTrue(all(t['execution_status']=='not_started' for t in batch['selected']))
        self.assertEqual(tasks, before)
        self.assertEqual(len(plan_batch(tasks, 0, 8, AT)['selected']), 0)
        tasks[1]['estimated_effort_units'] = 0
        with self.assertRaises(ValueError):
            plan_batch(tasks, 6, 8, AT)

    def test_invalid_coordinates_and_orphan_are_rejected(self):
        rows = adapt_frame('sha', {'id': 'f', 'path': 'x', 'time_seconds': 0},
                           {'final_blocks': [{'id':'b', 'kind':'text', 'text':'x', 'bbox':[5, 2, 1, 3]}]}, [])
        with self.assertRaisesRegex(ValueError, 'bbox'):
            validate_records(rows)
        rows[1]['location']['bbox'] = [1, 2, 5, 6]
        with self.assertRaisesRegex(ValueError, 'parent'):
            validate_records(rows[1:])

    def test_frame_sampling_does_not_depend_on_findings(self):
        frames = [{'id': str(i), 'time_seconds': i} for i in range(100)]
        sampled = select_frames(frames, 24, 7)
        self.assertEqual(len({f['id'] for f in sampled}), 24)
        for f in frames:
            f['error'] = True
        self.assertEqual([f['id'] for f in sampled], [f['id'] for f in select_frames(frames, 24, 7)])

    def test_blind_bundle_separates_predictions_and_freezes_inputs(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)/'inputs'
            base.mkdir()
            image = base/'frame.png'
            image.write_bytes(b'placeholder pixels')
            audio = base/'source.wav'
            with wave.open(str(audio), 'wb') as f:
                f.setnchannels(1); f.setsampwidth(2); f.setframerate(8000)
                f.writeframes(b'\0\0'*16000)
            save(base/'evaluation-inputs.json', {'source_sha256': 'sha', 'audio_path': str(audio),
                 'audio_offset_seconds': 10, 'frames': [{'id':'f1','time_seconds':10,'path':str(image)}],
                 'speech': [{'id':'s1','text':'SECRET PREDICTION','start_seconds':10,'end_seconds':12}]})
            jsonl(base/'records.jsonl', [{'location': {'frame_id':'f1'}, 'observed_text':'SECRET PREDICTION'}])
            save(base/'manifest.json', {'input_sha256': {str(p):digest_file(p) for p in [image,audio]},
                 'output_sha256': {n:digest_file(base/n) for n in ['evaluation-inputs.json','records.jsonl']}})
            out = Path(temp)/'output'
            summary = prepare(base, out, frame_count=1, audio_count=1, clip_seconds=1)
            self.assertIsNone(summary['accuracy'])
            self.assertEqual(summary['reference_labels_completed'], 0)
            self.assertNotIn('SECRET', (out/'references.blank.json').read_text())
            self.assertNotIn('SECRET', (out/'원본표본.html').read_text())
            self.assertIn('SECRET', (out/'predictions.json').read_text())
            with wave.open(str(out/'audio/audio-sample-01.wav'), 'rb') as f:
                self.assertEqual(f.getnframes(), 8000)
            with self.assertRaisesRegex(ValueError, 'output_exists'):
                prepare(base, out, frame_count=1, audio_count=1, clip_seconds=1)
            (base/'records.jsonl').write_text('changed')
            with self.assertRaisesRegex(ValueError, 'changed'):
                prepare(base, Path(temp)/'other', frame_count=1, audio_count=1, clip_seconds=1)


if __name__ == '__main__':
    unittest.main()
