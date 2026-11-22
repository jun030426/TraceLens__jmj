"""Multimodal Data Integration and Bundling (Step 5).

Integrates verified usable records across heterogeneous modalities (PPT OOXML, PDF,
Video frames, Audio ASR, Ink handwriting/marks, Code AST) into cohesive slide- and
segment-level multimodal bundles. These unified bundles serve as inputs for Step 6
(Chunking & Automatic Concept Mapping) and Step 7 (RAG Indexing).

Policy: slide_anchored_multimodal_bundler_v1
"""
import copy
import hashlib
import json
import math
import re
from pathlib import Path
from video_extraction.shared.common import read, save, jsonl, signature, digest_file
from video_extraction.pipeline.multimodal_preprocessor import (
    detect_columns_and_sort_blocks,
    parse_exam_question_sets,
    build_whisper_initial_prompt,
    deduplicate_consecutive_frames,
    verify_code_snippet_integrity
)

INTEGRATION_VERSION = "multimodal_bundle_v1"
BUNDLE_POLICY = "slide_anchored_multimodal_bundler_v1"


def _clean_text(s):
    return (s or "").strip()


def _compact_text(s):
    return re.sub(r'\s+', '', s or '')


def _parse_page_number(val):
    if val is None:
        return None
    if isinstance(val, int):
        return val
    if isinstance(val, float) and math.isfinite(val):
        return int(val)
    if isinstance(val, str):
        val = val.strip()
        if val.isdigit():
            return int(val)
        m = re.search(r'(\d+)', val)
        if m:
            return int(m.group(1))
    return None


def extract_slide_key(record):
    """Determine (source_id, page_number) for a document, visual, or handwriting record."""
    source_id = record.get('source_id') or record.get('source_sha256') or 'unknown_source'
    loc = record.get('location') or {}
    page = _parse_page_number(loc.get('page'))
    if page is None:
        page = _parse_page_number(loc.get('slide_number'))
    if page is None:
        page = _parse_page_number(record.get('slide_number'))
    if page is None and isinstance(record.get('unit_id'), str):
        # e.g. 'source_id:visual:3' -> slide 4
        parts = record['unit_id'].split(':')
        if len(parts) >= 3 and parts[-2] == 'visual' and parts[-1].isdigit():
            page = int(parts[-1]) + 1
    return source_id, page


def detect_emphasis_type(description):
    """Classify the emphasis style from Korean handwriting/marker descriptions."""
    d = (description or "").lower()
    if any(k in d for k in ('타원', '동그라미', '원형', '원 ')):
        return 'circle'
    if any(k in d for k in ('밑줄', '언더라인', '줄 ')):
        return 'underline'
    if any(k in d for k in ('형광펜', '하이라이트', '음영')):
        return 'highlight'
    if any(k in d for k in ('박스', '사각', '네모', '테두리', '사각형')):
        return 'box'
    if any(k in d for k in ('화살표', '포인터', '지시')):
        return 'arrow'
    if any(k in d for k in ('체크', 'v표시', '별표')):
        return 'check'
    return 'annotation'


def sort_text_blocks(blocks):
    """Sort text blocks in true human visual reading order (supporting 2-column gutters and line grouping)."""
    return detect_columns_and_sort_blocks(blocks)


def build_slide_intervals_from_units(units):
    """Extract display time intervals for each slide from video/visual unit timeline."""
    intervals = {}  # (source_id, page): [start_seconds, end_seconds]
    if not units:
        return intervals

    # Group visual units by (source_id, page)
    by_slide = {}
    for u in units:
        if u.get('modality') != 'visual':
            continue
        sid = u.get('source_id') or u.get('source_sha256')
        loc = u.get('location') or {}
        page = _parse_page_number(loc.get('page')) or _parse_page_number(loc.get('slide_number'))
        t = u.get('time_seconds')
        if t is None:
            t = loc.get('frame_time_seconds')
        if sid and page is not None and t is not None:
            try:
                t = float(t)
                by_slide.setdefault((sid, page), []).append(t)
            except (ValueError, TypeError):
                pass

    for key, times in by_slide.items():
        if times:
            intervals[key] = [min(times), max(times)]

    # If each slide only has a single sample timestamp, expand interval to next slide
    sorted_keys = sorted(intervals.keys(), key=lambda k: (k[0], intervals[k][0]))
    for i, key in enumerate(sorted_keys):
        cur_start, cur_end = intervals[key]
        if cur_start == cur_end:
            if i + 1 < len(sorted_keys) and sorted_keys[i + 1][0] == key[0]:
                next_start = intervals[sorted_keys[i + 1]][0]
                intervals[key] = [cur_start, max(cur_start + 1.0, next_start)]
            else:
                intervals[key] = [cur_start, cur_start + 30.0]  # default slide window
    return intervals


def integrate_records(records, units=None, code_corpus=None, metadata=None):
    """Core function to integrate heterogeneous usable records into multimodal bundles.

    Parameters:
      records: list of dictionaries from usable-records.jsonl
      units: list of unit dictionaries from source_plan (optional)
      code_corpus: code-rag corpus dictionary with chunks (optional)
      metadata: optional extra metadata dictionary

    Returns:
      list of multimodal bundle dictionaries
    """
    units = units or []
    slide_intervals = build_slide_intervals_from_units(units)

    # Buckets
    slide_records = {}       # (source_id, page) -> list of records
    speech_records = []      # list of audio/speech records
    code_records = []        # list of code records
    orphan_records = []      # records that don't belong to a slide or known modality

    for r in records:
        if not r.get('eligible_for_chunking', True):
            continue
        modality = r.get('modality')
        kind = r.get('kind')

        if modality == 'audio' or kind == 'speech':
            speech_records.append(r)
        elif modality == 'code' or kind == 'code':
            code_records.append(r)
        elif modality in ('document', 'visual', 'handwriting', 'image', 'text') or kind in ('text', 'table', 'diagram', 'annotation', 'handwriting'):
            sid, page = extract_slide_key(r)
            if page is not None:
                slide_records.setdefault((sid, page), []).append(r)
            else:
                orphan_records.append(r)
        else:
            orphan_records.append(r)

    # Also incorporate code_corpus chunks if provided and not already in records
    existing_code_ids = {r['id'] for r in code_records}
    if code_corpus and 'chunks' in code_corpus:
        for chunk in code_corpus['chunks']:
            if chunk.get('id') not in existing_code_ids:
                code_records.append({
                    'id': chunk['id'],
                    'modality': 'code',
                    'kind': 'code',
                    'source_id': chunk.get('source_sha256', 'code_source'),
                    'source_file': chunk.get('source_file', ''),
                    'source_sha256': chunk.get('source_sha256', ''),
                    'observed_text': chunk.get('code_text', chunk.get('text', '')),
                    'language': chunk.get('language', ''),
                    'symbol_name': chunk.get('symbol_name') or chunk.get('title', '').split(' · ')[-1],
                    'location': chunk.get('location', {}),
                    'slide_number': chunk.get('slide_number'),
                    'concept_candidates': chunk.get('concept_candidates', []),
                    'eligible_for_chunking': True,
                    'reasons': [],
                    'judgment': 'verified'
                })

    bundles = []
    attached_speech_ids = set()
    attached_code_ids = set()

    # 1. Build Slide Bundles
    sorted_slide_keys = sorted(slide_records.keys(), key=lambda k: (k[0], k[1]))

    for (sid, page) in sorted_slide_keys:
        items = slide_records[(sid, page)]
        source_file = next((x.get('source_file') for x in items if x.get('source_file')), "")
        source_sha256 = next((x.get('source_sha256') for x in items if x.get('source_sha256')), sid)

        # Separate items by kind
        text_items = []
        table_items = []
        diagram_items = []
        ink_items = []

        for item in items:
            m = item.get('modality')
            k = item.get('kind')
            if m == 'handwriting' or k in ('annotation', 'handwriting'):
                ink_items.append(item)
            elif k == 'table':
                table_items.append(item)
            elif k == 'diagram' or m == 'image':
                diagram_items.append(item)
            else:
                text_items.append(item)

        # Organize text blocks and prepare emphasis slots
        text_blocks = []
        block_by_id = {}
        for r in text_items:
            txt = _clean_text(r.get('observed_text') or r.get('normalized_text') or r.get('original_text'))
            if not txt:
                continue
            block = {
                'id': r['id'],
                'text': txt,
                'bbox': r.get('bbox'),
                'is_title': False,
                'emphasis': [],
                'record_id': r['id']
            }
            text_blocks.append(block)
            block_by_id[r['id']] = block

        text_blocks = sort_text_blocks(text_blocks)
        exam_questions = parse_exam_question_sets(text_blocks)
        has_exam_questions = any(q.get('is_exam_question') for q in exam_questions)

        # Mark first block as potential title if not too long
        if text_blocks and len(text_blocks[0]['text']) <= 80:
            text_blocks[0]['is_title'] = True
            title = text_blocks[0]['text']
        else:
            title = f"Slide {page}"

        # Correlate Handwriting / Annotations
        emphasized_keywords = []
        handwritten_notes = []
        handwritten_text_additions = []

        for ink in ink_items:
            desc = ink.get('description', '')
            emp_type = detect_emphasis_type(desc)
            related_ids = ink.get('related_record_ids') or []
            ink_text = _clean_text(ink.get('observed_text') or ink.get('normalized_text'))

            matched = False
            for target_id in related_ids:
                if target_id in block_by_id:
                    matched = True
                    target_block = block_by_id[target_id]
                    target_block['emphasis'].append({
                        'annotation_id': ink['id'],
                        'type': emp_type,
                        'description': desc,
                        'bbox': ink.get('bbox')
                    })
                    if target_block['text'] and target_block['text'] not in emphasized_keywords:
                        emphasized_keywords.append(target_block['text'])

            if not matched:
                # Standalone handwriting or margin note
                if ink_text:
                    handwritten_text_additions.append({
                        'id': ink['id'],
                        'text': ink_text,
                        'description': desc,
                        'bbox': ink.get('bbox')
                    })
                    if ink_text not in emphasized_keywords:
                        emphasized_keywords.append(ink_text)
                elif desc:
                    handwritten_notes.append({
                        'id': ink['id'],
                        'description': desc,
                        'type': emp_type,
                        'bbox': ink.get('bbox')
                    })

        # Process Tables
        tables = []
        for t in table_items:
            tbl_text = _clean_text(t.get('observed_text') or t.get('normalized_text'))
            tables.append({
                'id': t['id'],
                'markdown': tbl_text,
                'rows': t.get('table_rows'),
                'bbox': t.get('bbox')
            })

        # Process Diagrams
        diagrams = []
        for d in diagram_items:
            diagrams.append({
                'id': d['id'],
                'description': d.get('description', ''),
                'bbox': d.get('bbox')
            })

        # Slide time interval
        t_interval = slide_intervals.get((sid, page))
        slide_start = t_interval[0] if t_interval else None
        slide_end = t_interval[1] if t_interval else None

        # Correlate Speech Records
        slide_speech = []
        for sp in speech_records:
            sp_loc = sp.get('location') or {}
            sp_page = _parse_page_number(sp_loc.get('page')) or _parse_page_number(sp_loc.get('slide_number'))
            st = sp.get('start_seconds')
            et = sp.get('end_seconds')

            # Direct page match
            if sp_page is not None and sp_page == page:
                slide_speech.append(sp)
                attached_speech_ids.add(sp['id'])
                continue

            # Temporal overlap match
            if slide_start is not None and slide_end is not None and st is not None and et is not None:
                overlap = min(et, slide_end) - max(st, slide_start)
                duration = et - st
                if overlap > 0 and (overlap >= 1.0 or (duration > 0 and overlap / duration >= 0.3)):
                    slide_speech.append(sp)
                    attached_speech_ids.add(sp['id'])

        slide_speech.sort(key=lambda s: (s.get('start_seconds', 0), s.get('id', '')))
        speech_transcript = " ".join(_clean_text(s.get('observed_text') or s.get('normalized_text')) for s in slide_speech).strip()
        speech_segments = [{
            'record_id': s['id'],
            'start_seconds': s.get('start_seconds'),
            'end_seconds': s.get('end_seconds'),
            'text': _clean_text(s.get('observed_text') or s.get('normalized_text')),
            'words': s.get('original_words') or []
        } for s in slide_speech]

        # Correlate Code Snippets
        slide_code = []
        slide_full_text = " ".join([b['text'] for b in text_blocks] + [speech_transcript])

        for c in code_records:
            code_source, c_page = extract_slide_key(c)
            sym = c.get('symbol_name', '')
            c_file = Path(c.get('source_file', '')).name

            if c_page is not None:
                if code_source == sid and c_page == page:
                    slide_code.append(c)
                    attached_code_ids.add(c['id'])
            elif sym and len(sym) >= 3 and sym in slide_full_text:
                slide_code.append(c)
                attached_code_ids.add(c['id'])
            elif c_file and len(c_file) >= 4 and c_file in slide_full_text:
                slide_code.append(c)
                attached_code_ids.add(c['id'])

        code_snippets = []
        for c in slide_code:
            c_text = _clean_text(c.get('observed_text') or c.get('code_text'))
            c_lang = c.get('language') or 'java'
            syntax_check = verify_code_snippet_integrity(c_text, language=c_lang)
            code_snippets.append({
                'record_id': c['id'],
                'language': c_lang,
                'symbol_name': c.get('symbol_name', ''),
                'code': c_text,
                'location': c.get('location', {}),
                'source_locator': c.get('source_locator', ''),
                'syntax_integrity': syntax_check
            })

        # Aggregate warnings and check low impact warning status
        all_constituents = items + slide_speech + slide_code
        all_warnings = sorted({w for r in all_constituents for w in r.get('warnings', [])})
        has_low_impact = any(r.get('judgment') == 'accepted_with_low_impact_warning' or
                             'low_impact_warning_accepted' in r.get('warnings', [])
                             for r in all_constituents)
        if has_low_impact and 'low_impact_warning_accepted' not in all_warnings:
            all_warnings.append('low_impact_warning_accepted')

        modalities = sorted({r.get('modality') for r in all_constituents if r.get('modality')})

        # Concept candidates gathered from code candidates, emphasized keywords
        concept_candidates = []
        for kw in emphasized_keywords:
            concept_candidates.append({'concept': kw, 'source': 'handwriting_emphasis', 'confidence': 'high'})
        for c in slide_code:
            for cand in c.get('concept_candidates', []):
                concept_candidates.append(cand)

        # Base text composition
        base_text_parts = [b['text'] for b in text_blocks]
        if handwritten_text_additions:
            base_text_parts.append("\n[추가 필기 내용]\n" + "\n".join(h['text'] for h in handwritten_text_additions))
        base_text = "\n\n".join(base_text_parts)

        bundle_id = f"{sid}:slide:{page:03d}"
        content_dict = {
            'title': title,
            'base_text': base_text,
            'text_blocks': text_blocks,
            'tables': tables,
            'diagrams': diagrams,
            'emphasized_keywords': emphasized_keywords,
            'handwritten_notes': handwritten_notes,
            'handwritten_text_additions': handwritten_text_additions,
            'speech': {
                'transcript': speech_transcript,
                'segments': speech_segments
            },
            'code_snippets': code_snippets,
            'exam_questions': exam_questions if has_exam_questions else [],
            'is_exam_page': has_exam_questions
        }

        content_digest = signature(content_dict)

        bundle = {
            'bundle_id': bundle_id,
            'bundle_type': 'slide_bundle',
            'version': INTEGRATION_VERSION,
            'policy': BUNDLE_POLICY,
            'source_id': sid,
            'source_sha256': source_sha256,
            'source_file': source_file,
            'slide_number': page,
            'page': page,
            'time_interval': {
                'start_seconds': slide_start,
                'end_seconds': slide_end
            } if (slide_start is not None or slide_end is not None) else None,
            'content': content_dict,
            'provenance': {
                'record_ids': sorted({r['id'] for r in all_constituents}),
                'modalities': modalities,
                'warnings': all_warnings,
                'has_low_impact_warnings': has_low_impact,
                'content_digest': content_digest
            },
            'concept_metadata': {
                'concept_ids': [],
                'concept_candidates': concept_candidates,
                'status': 'ready_for_step6'
            }
        }
        bundles.append(bundle)

    # 2. Build Orphan Speech Bundles (e.g. spoken segments outside slides or standalone audio)
    orphan_speeches = [sp for sp in speech_records if sp['id'] not in attached_speech_ids]
    if orphan_speeches:
        orphan_speeches.sort(key=lambda s: (s.get('start_seconds', 0), s.get('id', '')))
        # Group contiguous speech intervals (gap <= 5.0 seconds) into audio segments
        cur_group = []
        for sp in orphan_speeches:
            if not cur_group:
                cur_group.append(sp)
            else:
                last_end = cur_group[-1].get('end_seconds', 0)
                this_start = sp.get('start_seconds', 0)
                if this_start - last_end <= 5.0:
                    cur_group.append(sp)
                else:
                    bundles.append(_build_audio_segment_bundle(cur_group))
                    cur_group = [sp]
        if cur_group:
            bundles.append(_build_audio_segment_bundle(cur_group))

    # A page with only accepted code has no slide bundle to attach it to.
    orphan_codes = [c for c in code_records if c['id'] not in attached_code_ids]
    by_file = {}
    for c in orphan_codes:
        f = c.get('source_file') or c.get('source_id') or 'code_file'
        source, page = extract_slide_key(c)
        by_file.setdefault((f, source, page), []).append(c)

    for (fpath, _, page), citems in by_file.items():
        bundles.append(_build_code_module_bundle(fpath, citems, page))

    return bundles


def _build_audio_segment_bundle(speech_group):
    first = speech_group[0]
    sid = first.get('source_id') or first.get('source_sha256') or 'audio_source'
    start_sec = first.get('start_seconds', 0.0)
    end_sec = speech_group[-1].get('end_seconds', start_sec)
    transcript = " ".join(_clean_text(s.get('observed_text') or s.get('normalized_text')) for s in speech_group).strip()
    all_warnings = sorted({w for r in speech_group for w in r.get('warnings', [])})
    has_low_impact = any(r.get('judgment') == 'accepted_with_low_impact_warning' or
                         'low_impact_warning_accepted' in r.get('warnings', []) for r in speech_group)

    bundle_id = f"{sid}:audio:{start_sec:.1f}-{end_sec:.1f}"
    content_dict = {
        'title': f"Audio Segment ({start_sec:.1f}s - {end_sec:.1f}s)",
        'base_text': transcript,
        'speech': {
            'transcript': transcript,
            'segments': [{
                'record_id': s['id'],
                'start_seconds': s.get('start_seconds'),
                'end_seconds': s.get('end_seconds'),
                'text': _clean_text(s.get('observed_text') or s.get('normalized_text')),
                'words': s.get('original_words') or []
            } for s in speech_group]
        }
    }
    return {
        'bundle_id': bundle_id,
        'bundle_type': 'audio_segment',
        'version': INTEGRATION_VERSION,
        'policy': BUNDLE_POLICY,
        'source_id': sid,
        'source_sha256': first.get('source_sha256', sid),
        'source_file': first.get('source_file', ''),
        'slide_number': None,
        'page': None,
        'time_interval': {'start_seconds': start_sec, 'end_seconds': end_sec},
        'content': content_dict,
        'provenance': {
            'record_ids': sorted({s['id'] for s in speech_group}),
            'modalities': ['audio'],
            'warnings': all_warnings,
            'has_low_impact_warnings': has_low_impact,
            'content_digest': signature(content_dict)
        },
        'concept_metadata': {
            'concept_ids': [],
            'concept_candidates': [],
            'status': 'ready_for_step6'
        }
    }


def _build_code_module_bundle(file_path, code_items, page):
    first = code_items[0]
    sid = first.get('source_id') or first.get('source_sha256') or 'code_source'
    fname = Path(file_path).name
    all_warnings = sorted({w for r in code_items for w in r.get('warnings', [])})
    has_low_impact = any(r.get('judgment') == 'accepted_with_low_impact_warning' for r in code_items)

    snippets = []
    candidates = []
    for c in code_items:
        snippets.append({
            'record_id': c['id'],
            'language': c.get('language', ''),
            'symbol_name': c.get('symbol_name', ''),
            'code': _clean_text(c.get('observed_text') or c.get('code_text')),
            'location': c.get('location', {}),
            'source_locator': c.get('source_locator', '')
        })
        for cand in c.get('concept_candidates', []):
            candidates.append(cand)

    full_code = "\n\n".join(s['code'] for s in snippets)
    bundle_id = f"{sid}:code:{fname}"
    if page is not None:
        bundle_id += f":page:{page}"
    content_dict = {
        'title': f"Code Module · {fname}",
        'base_text': full_code,
        'code_snippets': snippets
    }
    return {
        'bundle_id': bundle_id,
        'bundle_type': 'code_module',
        'version': INTEGRATION_VERSION,
        'policy': BUNDLE_POLICY,
        'source_id': sid,
        'source_sha256': first.get('source_sha256', sid),
        'source_file': str(file_path),
        'slide_number': page,
        'page': page,
        'time_interval': None,
        'content': content_dict,
        'provenance': {
            'record_ids': sorted({c['id'] for c in code_items}),
            'modalities': ['code'],
            'warnings': all_warnings,
            'has_low_impact_warnings': has_low_impact,
            'content_digest': signature(content_dict)
        },
        'concept_metadata': {
            'concept_ids': [],
            'concept_candidates': candidates,
            'status': 'ready_for_step6'
        }
    }


def bundle_directory(output_dir, dest_path=None):
    """Integrate usable records in an output directory into a bundled dataset."""
    out = Path(output_dir).resolve()
    latest_path = out / 'latest.json'
    if not latest_path.exists():
        raise ValueError(f"latest.json not found in {out}. Run extraction pipeline first.")

    latest = read(latest_path)
    usable_records_path = Path(latest.get('usable_records', ''))
    if not usable_records_path.exists():
        raise ValueError(f"usable-records.jsonl not found at {usable_records_path}")

    records = [json.loads(line) for line in usable_records_path.read_text(encoding='utf-8').splitlines() if line.strip()]

    plan_path = out / 'plan.json'
    units = []
    if plan_path.exists():
        plan = read(plan_path)
        units = plan.get('source_plan', {}).get('units', []) or plan.get('units', [])

    code_corpus = None
    if 'code_corpus' in latest and Path(latest['code_corpus']).exists():
        code_corpus = read(latest['code_corpus'])

    bundles = integrate_records(records, units=units, code_corpus=code_corpus)

    rev_dir = usable_records_path.parent
    if dest_path:
        dest = Path(dest_path).resolve()
    else:
        dest = rev_dir / 'multimodal-bundles.jsonl'

    dest.parent.mkdir(parents=True, exist_ok=True)
    jsonl(dest, bundles)

    # Summary
    slide_count = sum(1 for b in bundles if b['bundle_type'] == 'slide_bundle')
    audio_count = sum(1 for b in bundles if b['bundle_type'] == 'audio_segment')
    code_count = sum(1 for b in bundles if b['bundle_type'] == 'code_module')
    warning_bundles = sum(1 for b in bundles if b['provenance']['has_low_impact_warnings'])
    total_emphasized = sum(len(b['content'].get('emphasized_keywords', [])) for b in bundles)
    total_speech_len = sum(len(b['content'].get('speech', {}).get('transcript', '')) for b in bundles)

    summary = {
        'total_bundles': len(bundles),
        'slide_bundles': slide_count,
        'audio_segment_bundles': audio_count,
        'code_module_bundles': code_count,
        'bundles_with_low_impact_warnings': warning_bundles,
        'total_emphasized_keywords': total_emphasized,
        'total_speech_characters': total_speech_len,
        'policy': BUNDLE_POLICY,
        'bundle_file': str(dest),
        'bundle_sha256': digest_file(dest)
    }

    save(rev_dir / 'bundles-summary.json', summary)
    save(out / 'bundles-summary.json', summary)

    # Update latest.json
    latest['multimodal_bundles'] = str(dest)
    latest['bundles_summary'] = str(out / 'bundles-summary.json')
    save(latest_path, latest)

    return summary, bundles


def main():
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output', type=Path, required=True, help='Output directory of extraction pipeline')
    ap.add_argument('--dest', type=Path, help='Destination path for multimodal-bundles.jsonl')
    args = ap.parse_args()
    summary, _ = bundle_directory(args.output, args.dest)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()

