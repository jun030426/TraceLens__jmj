"""Reuse native slide candidates, never slide verdicts, on matching video frames.

Pixel similarity only chooses a proposal. Every proposed text block must still
receive the original source-pixel reread AND independent verification, followed
by all common gates. New diagrams/ink remain the ordinary specialist's job.
"""
import copy
import math
from pathlib import Path

import numpy as np
from PIL import Image

from video_extraction.pipeline import adapters
from video_extraction.shared.common import digest_file, read, save, signature
from video_extraction.video import vision_layers as layers
from video_extraction.video.vision import critical

POLICY = 'native_ppt_candidate_all_regions_rechecked_v1'


def candidates(path):
    from pptx import Presentation
    from pptx.enum.shapes import MSO_SHAPE_TYPE
    deck = Presentation(str(path))
    output = {}
    for number, slide in enumerate(deck.slides, 1):
        if slide._element.get('show') == '0':
            continue
        blocks = []
        supported = True
        for shape in slide.shapes:
            # Pictures, tables, groups, equations and drawings need normal full
            # visual extraction. Do not reconstruct them from native text alone.
            if shape.shape_type not in (MSO_SHAPE_TYPE.TEXT_BOX, MSO_SHAPE_TYPE.PLACEHOLDER) or not shape.has_text_frame:
                supported = False
                break
            if not shape.text.strip():
                continue
            box = [round(shape.left/deck.slide_width*1000), round(shape.top/deck.slide_height*1000),
                   round((shape.left+shape.width)/deck.slide_width*1000),
                   round((shape.top+shape.height)/deck.slide_height*1000)]
            if not (0 <= box[0] < box[2] <= 1000 and 0 <= box[1] < box[3] <= 1000):
                supported = False
                break
            blocks.append({'id': 'ppt-'+str(shape.shape_id), 'kind': 'text', 'bbox': box,
                           'text': shape.text, 'uncertainties': []})
        if not supported or not blocks or len(blocks) > 20:
            continue
        # Never add more verification batches just to save one extraction call.
        # All reused blocks are checked even if the ordinary route only checks
        # its critical subset. Complex/non-beneficial slides use the normal path.
        if math.ceil(len(blocks)/3) != math.ceil(sum(critical(b) for b in blocks)/3):
            continue
        output[number] = {'blocks': blocks, 'visuals': [], 'readable': True,
                          'notes': ['Native PPT proposal; all blocks require fresh frame-pixel reread and verification.']}
    return output


def prepare(references, folder):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    manifest_path = folder/'references.json'
    request = [{'path': str(Path(p).resolve()), 'sha256': digest_file(p)} for p in references]
    if manifest_path.exists():
        saved = read(manifest_path)
        if saved['request'] != request or saved['policy'] != POLICY:
            raise ValueError('ppt_reference_changed_prepare_new_version')
        for path, digest in saved['inputs'].items():
            if digest_file(path) != digest:
                raise ValueError('ppt_reference_asset_changed')
        return saved
    result = {'policy': POLICY, 'request': request, 'pages': [], 'inputs': {}, 'unavailable': []}
    for source in request:
        result['inputs'][source['path']] = source['sha256']
        try:
            native = candidates(source['path'])
            if not native:
                continue
            target = folder/source['sha256']
            _, units = adapters.prepare_source(source['path'], target, {'pdf_dpi': 96}, 'ppt')
            for unit in units:
                number = unit['location']['page']
                if number not in native or unit.get('preparation_holds'):
                    continue
                image = unit['image']
                result['inputs'][image] = digest_file(image)
                result['pages'].append({'source': source, 'page': number, 'image': image,
                    'image_sha256': digest_file(image), 'candidate': native[number]})
        except (ValueError, OSError):
            # Reference optimization cannot make an otherwise valid video fail.
            result['unavailable'].append(source['sha256'])
    save(manifest_path, result)
    return result


def choose(unit, reference):
    if unit.get('source_kind') != 'video' or unit.get('preparation_holds'):
        return None
    with Image.open(unit['image']) as image:
        target_size = image.size
        frame = np.asarray(image.convert('RGB').resize((640, 360)), dtype=np.int16)
    matches = []
    for page in reference.get('pages', []):
        with Image.open(page['image']) as image:
            if abs(image.width/image.height - target_size[0]/target_size[1]) > .01:
                continue
            slide = np.asarray(image.convert('RGB').resize((640, 360)), dtype=np.int16)
        difference = np.abs(frame-slide).max(axis=2)
        mean = float(difference.mean())
        changed = float((difference > 24).mean())
        if mean <= 6 and changed <= .015:
            matches.append((mean, changed, page))
    if not matches:
        return None
    matches.sort(key=lambda value: value[:2])
    # Near ties with different native text are ambiguous. No text-similarity
    # acceptance, crop substitution, or source decision is made here.
    if len(matches)>1 and matches[1][0]-matches[0][0]<1 and matches[1][2]['candidate'] != matches[0][2]['candidate']:
        return None
    mean, changed, page = matches[0]
    return {'policy': POLICY, 'reference': copy.deepcopy(page), 'frame_sha256': digest_file(unit['image']),
            'match': {'mean_pixel_difference': mean, 'changed_pixel_fraction': changed, 'proposal_only': True},
            'candidate': copy.deepcopy(page['candidate'])}


def validate_proposal(proposal, image):
    reference = proposal['reference']
    if (proposal['policy'] != POLICY or proposal['frame_sha256'] != digest_file(image) or
        digest_file(reference['source']['path']) != reference['source']['sha256'] or
        digest_file(reference['image']) != reference['image_sha256']):
        raise ValueError('ppt_reuse_source_changed')
    native = candidates(reference['source']['path']).get(reference['page'])
    if native != proposal['candidate'] or native != reference['candidate']:
        raise ValueError('ppt_reuse_candidate_changed')
    with Image.open(image) as opened:
        layers.validate_extraction(proposal['candidate'], opened.size)
    return copy.deepcopy(proposal['candidate'])


def unresolved(candidate, image):
    """Mandatory new-source evidence for every reused block, on save and replay."""
    initial = validate_proposal(candidate['ppt_proposal'], image)
    if initial != candidate['original']:
        raise ValueError('ppt_reuse_original_changed')
    checks = candidate.get('ppt_rechecks', [])
    from video_extraction.shared.common import validate
    unresolved_ids = []
    final = {b['id']: b for b in candidate['final_blocks']}
    for block in initial['blocks']:
        matches = [c for c in checks if c['target_id'] == block['id']]
        good = len(matches) == 1
        if good:
            check = matches[0]
            reading, verifier = check['reading'], check['verification']
            validate(reading, layers.TEXT_READ)
            validate(verifier, layers.VERIFY)
            current = final.get(block['id'], {})
            good = (reading['readable'] and not reading['uncertainties'] and not reading['source_conflicts'] and
                    verifier['decision'] in ('unchanged','accept') and not verifier['source_conflict'] and
                    all(verifier[k] is True for k in ('source_clear','all_changes_visible','same_region')) and
                    reading['text'] == current.get('text') and reading['kind'] == current.get('kind') and
                    check['bbox'] == block['bbox'])
        if not good:
            unresolved_ids.append(block['id'])
    return unresolved_ids
