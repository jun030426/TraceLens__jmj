"""Synthetic shared-dispatcher regressions; source accuracy is not measured here."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw
from pptx import Presentation
from pptx.util import Inches

from video_extraction.pipeline import connected, ppt_reuse, visual_gate
from video_extraction.shared.common import digest_file, read, save, signature


class PptReuseTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.ppt = self.root/'lecture.pptx'
        deck = Presentation()
        deck.slide_width, deck.slide_height = Inches(10), Inches(5.625)
        slide = deck.slides.add_slide(deck.slide_layouts[6])
        for i,text in enumerate(['1+1=2', 'Original explanation', 'Do not remove negation']):
            shape = slide.shapes.add_textbox(Inches(1), Inches(1+i), Inches(7), Inches(.7))
            shape.text = text
        deck.save(self.ppt)
        self.image = self.root/'frame.png'
        image = Image.new('RGB', (640,360), 'white')
        ImageDraw.Draw(image).text((64,64),'1+1=2', fill='black')
        image.save(self.image)
        native = ppt_reuse.candidates(self.ppt)[1]
        self.reference = {'pages': [{'source': {'path': str(self.ppt), 'sha256': digest_file(self.ppt)},
            'page': 1, 'image': str(self.image), 'image_sha256': digest_file(self.image), 'candidate': native}]}
        save(self.root/'references.json', self.reference)
        save(self.root/'native-inventory.json', {'records': [], 'pending': []})
        self.unit = {'id': 'video:visual:1', 'unit_key': 'frame', 'source_id': 'video',
            'source_file': 'source.mp4', 'source_kind': 'video', 'modality': 'visual',
            'image': str(self.image), 'dimensions': [640,360], 'time_seconds': 0, 'location': {}}
        self.plan = {'source_plan': {'config': {'region_budget': 20}, 'gemini_model': 'synthetic',
                    'units': [self.unit]}, 'seeds': {}, '_output': str(self.root),
                    'ppt_reference': str(self.root/'references.json'), 'ocr_models': None, 'ocr_python': None}

    def client(self, unclear=False):
        class Client:
            model = 'synthetic'
            def __init__(self): self.calls = []
            def call(self, name, media, prompt, schema):
                self.calls.append(name)
                if name == 'layers_extract': raise AssertionError('Native proposal should be reused')
                if name == 'layers_audit':
                    return {'text_regions': [], 'visual_regions': [], 'complete_scan': True, 'notes': []}
                data = json.loads(prompt.split('DATA:\n',1)[1])
                items = []
                for row in data['regions']:
                    if name.endswith('read'):
                        value = {'text': row['before']['text'], 'kind': 'text', 'readable': not unclear,
                                 'uncertainties': ['synthetic uncertain'] if unclear else [], 'source_conflicts': []}
                        key = 'reading'
                    elif name.endswith('verify'):
                        value = {'decision': 'unchanged', 'source_clear': True, 'all_changes_visible': True,
                                 'same_region': True, 'source_conflict': False, 'reason': 'synthetic fixture'}
                        key = 'verification'
                    else: raise AssertionError(name)
                    items.append({'region_id': row['region_id'], key: value})
                return {'items': items}
        return Client()

    def test_common_dispatch_reuses_proposal_but_rechecks_even_noncritical_text(self):
        client = self.client()
        folder = self.root/'work'/signature(self.unit['id'])[:24]
        result = connected.visual(self.unit, self.plan, folder, client, [])
        self.assertTrue(all(r['eligible_for_chunking'] for r in result['records']))
        self.assertEqual(client.calls, ['layers_audit', 'layers_text_read', 'layers_text_verify'])
        self.assertIn(ppt_reuse.POLICY, result['executed'])
        base = read(folder/'visual-base.json')
        candidate = read(base['evidence']['visual_result'])
        self.assertEqual(len(candidate['ppt_rechecks']), 3)
        connected.revalidate_result(self.root, self.plan, {'id': self.unit['id'], 'kind': 'visual', 'unit': self.unit}, result)

    def test_reused_text_without_fresh_source_evidence_stays_held(self):
        folder = self.root/'unclear'
        result = connected.visual(self.unit, self.plan, folder, self.client(unclear=True), [])
        self.assertFalse(any(r['eligible_for_chunking'] for r in result['records']))

    def test_removed_recheck_cannot_be_rehashed_into_a_passing_candidate(self):
        folder = self.root/'work'
        connected.visual(self.unit, self.plan, folder, self.client(), [])
        candidate = read(read(folder/'visual-base.json')['evidence']['visual_result'])
        candidate['ppt_rechecks'] = []
        # Replaying the common gate must hold the content, even if external
        # evidence hashes were recomputed after tampering.
        guarded = visual_gate.enforce(candidate, self.image)
        self.assertTrue(guarded['common_gate']['blocked'])
        # A stale positive receipt is rejected on saved-selection replay too,
        # even if its outer payload hash was recomputed.
        candidate['common_gate']['payload_sha256'] = signature({k:v for k,v in candidate.items() if k!='common_gate'})
        with self.assertRaises(ValueError):
            visual_gate.require(candidate,self.image)

    def test_changed_reference_and_native_text_are_rejected(self):
        proposal = ppt_reuse.choose(self.unit, self.reference)
        changed = copy.deepcopy(proposal)
        changed['candidate']['blocks'][0]['text'] = '1+1=3'
        with self.assertRaisesRegex(ValueError, 'candidate_changed'):
            ppt_reuse.validate_proposal(changed, self.image)
        self.ppt.write_bytes(b'changed source')
        with self.assertRaisesRegex(ValueError, 'source_changed'):
            ppt_reuse.validate_proposal(proposal, self.image)

    def test_different_scene_is_not_a_ppt_candidate(self):
        target = self.root/'different.png'
        Image.new('RGB', (640,360), 'black').save(target)
        self.assertIsNone(ppt_reuse.choose({**self.unit,'image':str(target)}, self.reference))

    def test_picture_slide_uses_normal_visual_pipeline(self):
        deck = Presentation(self.ppt)
        deck.slides[0].shapes.add_picture(str(self.image), Inches(1), Inches(1), width=Inches(2))
        deck.save(self.ppt)
        self.assertEqual(ppt_reuse.candidates(self.ppt), {})
