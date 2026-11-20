"""PCM/time-base and request-binding regressions; no API or speech model used."""
import copy
import json
import struct
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from video_extraction.audio import audio_finalize as mod
from video_extraction.shared.common import save, digest_file, signature
from video_extraction.tests.test_audio_finalize import fixture, outcome


def raw_file(root):
    path = root/'source.wav'
    with wave.open(str(path), 'wb') as w:
        w.setparams((1,2,1000,0,'NONE','not compressed'))
        w.writeframes(b''.join(struct.pack('<h', (i*31)%30000) for i in range(30000)))
    return path


def task_file(root, interval=(12.345, 12.705)):
    source = raw_file(root)
    t = {'id':'short', 'interval':list(interval), 'target_clip':'target.wav', 'neighbors':[
        {'start_seconds':11,'end_seconds':12,'text':'앞 문장'},
        {'start_seconds':13,'end_seconds':14,'text':'뒤 문장'}]}
    t['target_clip_meta'] = mod.clip(source,root/t['target_clip'],*interval)
    t['target_sample_check'] = mod.verify_slice(source,root/t['target_clip'],t['target_clip_meta'],interval)
    return source,t


class TargetWindowTests(unittest.TestCase):
    def test_exact_short_target_no_surrounding_five_seconds(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);source,t=task_file(root)
            path,binding,data,neighbors=mod.request_bundle(root,t)
            self.assertEqual(data['target_seconds'],[0.0,.36])
            self.assertEqual(data['time_basis'],'attached_file_relative_seconds')
            self.assertEqual(t['target_sample_check']['sample_count'],360)
            self.assertEqual(binding['target_sha256'],digest_file(path))
            self.assertEqual([n['position'] for n in neighbors],['before','after'])
            self.assertNotIn('12.345',json.dumps(data))
            self.assertNotIn('start_seconds',json.dumps(neighbors))

    def test_start_of_recording_uses_zero_not_fixed_five_second_offset(self):
        with tempfile.TemporaryDirectory() as d:
            _,t=task_file(Path(d),(0,.6))
            self.assertEqual(t['target_sample_check']['source_start_sample'],0)
            self.assertEqual(mod.request_bundle(Path(d),t)[2]['target_seconds'],[0.0,.6])

    def test_shifted_audio_rejected_even_if_hash_is_updated(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);source,t=task_file(root)
            meta=mod.clip(source,root/t['target_clip'],13.345,13.705)
            # Pretend the shifted audio has the right timestamps: PCM comparison catches it.
            meta.update({k:t['target_clip_meta'][k] for k in ['start_seconds','end_seconds','duration_seconds']})
            with self.assertRaisesRegex(ValueError,'original_samples'):
                mod.verify_slice(source,root/t['target_clip'],meta,t['interval'])

    def test_wrong_timestamp_and_wrong_duration_are_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);source,t=task_file(root)
            meta=copy.deepcopy(t['target_clip_meta']);meta['start_seconds']+=1
            with self.assertRaisesRegex(ValueError,'timestamp'):
                mod.verify_slice(source,root/t['target_clip'],meta,t['interval'])
            t['target_clip_meta']['duration_seconds']+=1
            with self.assertRaisesRegex(ValueError,'duration'):
                mod.request_bundle(root,t)

    def test_context_file_cannot_be_substituted_for_target(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);source,t=task_file(root)
            mod.clip(source,root/t['target_clip'],7.345,17.705)
            with self.assertRaisesRegex(ValueError,'target_clip_changed'):
                mod.request_bundle(root,t)

    def test_cached_result_bound_to_same_target_in_both_calls(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);_,t=task_file(root)
            _,tasks=fixture();test_task=tasks[0]
            test_task.update({k:t[k] for k in ['target_clip','target_clip_meta']})
            p={'version':2,'tasks':[test_task]}
            r=outcome(test_task);r['plan_signature']=signature(p)
            binding=mod.request_bundle(root,test_task)[1]
            r['input_bindings']={'blind':binding,'review':binding}
            dest=root/'results'/(test_task['id']+'.json');save(dest,r)
            self.assertEqual(len(mod.results(root,p)),1)
            r['input_bindings']['review']={**binding,'target_sha256':'different-file'};save(dest,r)
            with self.assertRaisesRegex(ValueError,'binding_mismatch'):
                mod.results(root,p)

    def test_file_mutation_between_calls_never_requests_review_or_publishes(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);_,t=task_file(root);_,tasks=fixture();test_task=tasks[0]
            test_task.update({k:t[k] for k in ['target_clip','target_clip_meta']})
            p={'version':2,'tasks':[test_task],'model':'fake'}
            class Fake:
                def __init__(self,*a,**kw):pass
                def call(self,stage,paths,prompt,schema):
                    if not stage.endswith('blind-v2'):
                        raise AssertionError('review must not run after file mutation')
                    paths[0].write_bytes(b'changed')
                    return outcome(test_task)['blind']
            with patch.object(mod,'verify',return_value=p),patch.object(mod,'api_key',return_value='mock'),patch.object(mod,'Gemini',Fake):
                with self.assertRaisesRegex(ValueError,'target_clip_changed'):
                    mod.run(root,root/'.env',delay=0)
            self.assertFalse((root/'latest.json').exists())
            self.assertFalse((root/'results'/(test_task['id']+'.json')).exists())


if __name__ == '__main__':
    unittest.main()
