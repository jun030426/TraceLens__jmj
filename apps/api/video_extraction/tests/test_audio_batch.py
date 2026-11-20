"""Synthetic contract checks; no model calls or claims of measured accuracy."""
import copy
import json
import tempfile
import unittest
from functools import wraps
from pathlib import Path

from video_extraction.pipeline import audio_batch as batch, audio_workflow as workflow
from video_extraction.shared.common import read, save
from video_extraction.tests.test_audio_primary_scope import scoped
from video_extraction.tests.test_audio_target_window import raw_file


def batch_fixture(method):
    """Adapt existing single-pair source fixtures to the new transport envelope."""
    @wraps(method)
    def call(self, name, media, prompt, schema):
        if '-batch-' not in name:
            return method(self, name, media, prompt, schema)
        data = json.loads(prompt.split('DATA:\n', 1)[1])
        items = []
        for entry in data['tasks']:
            i = entry['primary_audio_index']
            value = method(self, name.replace('-batch-', '-'), media[i:i+2],
                           'DATA:\n'+json.dumps(entry), schema)
            value['target_scope']['audio_index'] = i
            items.append({'task_id': entry['task_id'], 'reading': value})
        return {'items': items}
    return call


class AudioBatchTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        source = raw_file(self.root)
        self.rows = [{'id': 'row-'+str(i), 'text': '숫자 10 반복 반복 안 한다 '+str(i),
                      'start_seconds': float(i+1), 'end_seconds': float(i+1.8)} for i in range(10)]
        self.tasks = [workflow.bound_task({'id': 'control-'+str(i), 'role': 'control',
                     'target_id': row['id'], 'before': row['text'], 'after': row['text'],
                     'interval': [row['start_seconds'], row['end_seconds']]},
                     self.rows, source, self.root/'clips', 30) for i,row in enumerate(self.rows)]
        owner = self
        self.calls = []
        class Client:
            def call(self, name, media, prompt, schema):
                data = json.loads(prompt.split('DATA:\n', 1)[1])
                owner.calls.append((name, list(media), data))
                result = []
                for entry in data['tasks']:
                    task = next(t for t in owner.tasks if t['id'] == entry['task_id'])
                    blind, review = scoped(task)
                    value = blind if 'blind' in name else review
                    value['target_scope']['audio_index'] = entry['primary_audio_index']
                    result.append({'task_id': task['id'], 'reading': value})
                return {'items': result}
        self.client = Client()

    def test_grouping_reduces_requests_preserves_all_scopes_and_blind_isolation(self):
        outcomes = {}
        for group in batch.groups(self.tasks):
            outcomes.update(batch.run(group, self.root, self.client))
        self.assertEqual(len(self.calls), 4)  # 10 utterances formerly needed 20 calls
        self.assertEqual(len(outcomes), 10)
        self.assertTrue(all(r['gate']['passed'] for r in outcomes.values()))
        for task in self.tasks:
            batch.validate_outcome(task, outcomes[task['id']], self.root)
        for name, media, data in self.calls:
            self.assertEqual(len(media), 2*len(data['tasks']))
            if 'blind' in name:
                serialized = json.dumps(data, ensure_ascii=False)
                self.assertNotIn('current_text', serialized)
                self.assertNotIn('neighboring_transcripts', serialized)
                for row in self.rows:
                    self.assertNotIn(row['text'], serialized)
        self.assertEqual(self.calls[0][1], self.calls[1][1])
        for group in batch.groups(self.tasks):
            batch.run(group, self.root, self.client)
        self.assertEqual(len(self.calls), 4)

    def test_wrong_or_duplicate_owner_never_becomes_a_verdict(self):
        group = self.tasks[:2]
        raw = self.client.call('blind', [], batch.prompt('blind', batch.bundle(group, self.root)[2]), {})
        raw['items'][1]['reading']['target_scope']['audio_index'] = 0
        with self.assertRaisesRegex(ValueError, 'wrong_primary_attachment'):
            batch.normalize(raw, group, 'blind')
        raw['items'][1]['task_id'] = raw['items'][0]['task_id']
        with self.assertRaisesRegex(ValueError, 'duplicate_or_missing'):
            batch.normalize(raw, group, 'blind')
        self.assertNotIn('audio_index=0',batch.prompt('blind',[]))
        self.assertNotIn('audio_index=0',batch.prompt('review',[]))

    def test_modified_batch_reading_cannot_reuse_a_passing_result(self):
        result = batch.run(self.tasks[:2], self.root, self.client)
        task = self.tasks[0]
        outcome = result[task['id']]
        path = self.root/'review-batches'/(outcome['batch_id']+'.json')
        receipt = read(path)
        receipt['blind']['items'][0]['reading']['text'] = '숫자 100'
        save(path, receipt)
        with self.assertRaisesRegex(ValueError, 'reading_changed'):
            batch.validate_outcome(task, outcome, self.root)

    def test_wrong_batch_mapping_splits_without_relabeling_or_reusing_verdicts(self):
        original=self.client.call
        def confused(name,media,prompt,schema):
            value=original(name,media,prompt,schema)
            if len(value['items'])>1 and 'review' in name:
                value['items'][1]['reading']['target_scope']['audio_index']=0
            return value
        self.client.call=confused
        outcomes=batch.run(self.tasks[:4],self.root,self.client)
        self.assertEqual(len(outcomes),4)
        self.assertEqual(len(list((self.root/'review-batch-splits').glob('*.json'))),3)
        for task in self.tasks[:4]:
            batch.validate_outcome(task,outcomes[task['id']],self.root)
            receipt=read(self.root/'review-batches'/(outcomes[task['id']]['batch_id']+'.json'))
            self.assertEqual(receipt['tasks'],[task])
        count=len(self.calls)
        self.assertEqual(batch.run(self.tasks[:4],self.root,self.client),outcomes)
        self.assertEqual(len(self.calls),count)

    def test_source_change_blocks_resume(self):
        batch.run(self.tasks[:2], self.root, self.client)
        Path(self.tasks[0]['target_clip']).write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'target_clip_changed'):
            batch.run(self.tasks[:2], self.root, self.client)

    def test_normalized_batch_uses_original_strict_gate(self):
        result = batch.run(self.tasks[:2], self.root, self.client)
        task = self.tasks[0]
        good = result[task['id']]
        for mutation in ('boundary', 'number', 'repetition', 'negation'):
            with self.subTest(mutation=mutation):
                blind, review = copy.deepcopy(good['blind']), copy.deepcopy(good['review'])
                if mutation == 'boundary':
                    review['target_scope']['boundary_crossing'] = True
                else:
                    before, after = {'number': ('10','100'), 'repetition': ('반복 반복','반복'),
                                     'negation': ('안 한다','한다')}[mutation]
                    blind['text'] = blind['text'].replace(before, after)
                    blind['target_spans'][0]['text'] = blind['text']
                self.assertFalse(workflow.final.decision(task, blind, review)['passed'])
