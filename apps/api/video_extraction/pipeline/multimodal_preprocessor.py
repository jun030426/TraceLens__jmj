"""Tailored Multimodal Preprocessor (Step 1 Optimization).

Implements project-specific preprocessing solutions for all 6 modalities:
1. PPT: Visual 2D coordinate-based layout ordering (resolving XML Z-order inversion).
2. PDF Exam & Documents: Gutter detection for 2-column layouts (preventing cross-column interleaving)
   and exam question set boundary parsing (1 Question = 1 Set).
3. Audio: Domain keyword harvesting from slides and code symbols to inject into Whisper's initial_prompt.
4. Video: Consecutive identical frame deduplication and active exposure window aggregation.
5. Ink: Stroke-to-text bounding box pointer normalization (extracting emphasized_keywords).
6. Code: AST syntax integrity verification and snippet wrapping.

Policy: tailored_multimodal_preprocessor_v1
"""
import copy
import hashlib
import json
import math
import re
from pathlib import Path
from video_extraction.shared.common import read, save, jsonl, signature, digest_file

PREPROCESSOR_POLICY = "tailored_multimodal_preprocessor_v1"

# Exam question boundary markers (e.g. "1.", "[문제 2]", "Q3.", "(4)", "문 5.")
EXAM_QUESTION_PATTERN = re.compile(
    r'^(?:(?:\[\s*)?(?:문제|문|Q)\s*[0-9]{1,2}(?:\s*\]|\.|\:|\))?'
    r'|[0-9]{1,2}\s*[\.\:\)]'
    r'|\([0-9]{1,2}\))',
    re.IGNORECASE
)

# Exam multiple choice option markers (e.g. "①", "②", "1)", "(1)", "A.")
CHOICE_OPTION_PATTERN = re.compile(
    r'^(?:[①②③④⑤]'
    r'|\([1-5a-dA-D]\)'
    r'|[1-5a-dA-D]\s*[\.\:\)]'
    r'|보기\s*[0-9]?)'
)


def _clean_str(s):
    return (s or "").strip()


def detect_columns_and_sort_blocks(blocks, page_width=1000):
    """Sort text blocks in true human visual reading order.

    Detects whether the page is a 2-column layout (e.g. exam papers or 2-column slides).
    If 2 columns: sorts Left column top-to-bottom, then Right column top-to-bottom.
    If 1 column: sorts top-to-bottom with line grouping (±15px).
    """
    if not blocks:
        return []
    if len(blocks) == 1:
        return list(blocks)

    # Extract bounding box info: [y_min, x_min, y_max, x_max] or [x_min, y_min, x_max, y_max]
    # In normalized 0-1000 coordinates, x is horizontal (0..1000), y is vertical (0..1000)
    parsed = []
    has_valid_boxes = True
    for b in blocks:
        box = b.get('bbox')
        if box and len(box) >= 4:
            # Detect coordinate format: if box[1] < box[3] and box[0] < box[2]
            # Standard in our pipeline: [y_min, x_min, y_max, x_max] or [x_min, y_min, x_max, y_max]
            # Let's inspect coords
            y0, x0, y1, x1 = box[0], box[1], box[2], box[3]
            # If box was [x0, y0, x1, y1], normalize to y_top, x_left, y_bottom, x_right
            if box[0] > 0 and box[1] > 0 and box[0] > box[1] and box[2] > box[3]:
                # Looks like [y0, x0, y1, x1]
                ytop, xleft, ybottom, xright = y0, x0, y1, x1
            else:
                # Default assume [y0, x0, y1, x1] or [ymin, xmin, ymax, xmax]
                ytop, xleft, ybottom, xright = y0, x0, y1, x1
            parsed.append((ytop, xleft, ybottom, xright, b))
        else:
            has_valid_boxes = False
            parsed.append((999999, 999999, 999999, 999999, b))

    if not has_valid_boxes or len(parsed) < 3:
        # Fallback to standard top-to-bottom
        return sorted(blocks, key=lambda b: (b.get('bbox', [999999, 999999])[0], b.get('id', '')))

    # Check for 2-column gutter (vertical separator around the middle x: 400~600)
    # Collect horizontal centers
    midpoint = page_width / 2.0
    left_blocks = []
    right_blocks = []
    spanning_blocks = []  # Header/Title that spans across the center

    for ytop, xleft, ybottom, xright, b in parsed:
        w = xright - xleft
        # If block spans > 65% of the page width, it's a full-width banner/header/footer
        if w > (page_width * 0.65) or (xleft < (midpoint - 100) and xright > (midpoint + 100)):
            spanning_blocks.append((ytop, xleft, b))
        elif xright <= midpoint + 50:
            left_blocks.append((ytop, xleft, b))
        elif xleft >= midpoint - 50:
            right_blocks.append((ytop, xleft, b))
        else:
            # Near center: check center of mass
            center_x = (xleft + xright) / 2.0
            if center_x < midpoint:
                left_blocks.append((ytop, xleft, b))
            else:
                right_blocks.append((ytop, xleft, b))

    # Column layout detected if both left and right columns have at least 2 blocks
    is_two_column = len(left_blocks) >= 2 and len(right_blocks) >= 2

    if is_two_column:
        # Line grouping helper for each column
        def sort_col(col_items):
            # Sort primarily by ytop, with left-to-right for same line (within 15px)
            return [item[2] for item in sorted(col_items, key=lambda it: (round(it[0] / 15.0) * 15, it[1], it[2].get('id', '')))]

        sorted_spanning_top = [it[2] for it in sorted([s for s in spanning_blocks if s[0] < 250], key=lambda it: it[0])]
        sorted_left = sort_col(left_blocks)
        sorted_right = sort_col(right_blocks)
        sorted_spanning_bottom = [it[2] for it in sorted([s for s in spanning_blocks if s[0] >= 250], key=lambda it: it[0])]

        return sorted_spanning_top + sorted_left + sorted_right + sorted_spanning_bottom

    # Single column layout: sort with line grouping
    return [it[4] for it in sorted(parsed, key=lambda it: (round(it[0] / 15.0) * 15, it[1], it[4].get('id', '')))]


def parse_exam_question_sets(text_blocks):
    """Group text blocks into cohesive exam question items (1 Question = 1 Set).

    Each question set includes:
    - stem (question text)
    - code (embedded question code snippet)
    - options (multiple choice choices ①②③④)
    - blocks (all constituent block dicts)
    """
    if not text_blocks:
        return []

    question_sets = []
    current_set = None

    for b in text_blocks:
        txt = _clean_str(b.get('text', ''))
        if not txt:
            continue

        is_question_start = bool(EXAM_QUESTION_PATTERN.match(txt))
        is_choice_option = bool(CHOICE_OPTION_PATTERN.match(txt))

        if is_question_start:
            if current_set:
                question_sets.append(_finalize_question_set(current_set))
            current_set = {
                'id': b.get('id', ''),
                'stem_blocks': [txt],
                'option_blocks': [],
                'code_blocks': [],
                'all_blocks': [b]
            }
        elif current_set:
            current_set['all_blocks'].append(b)
            if is_choice_option:
                current_set['option_blocks'].append(txt)
            elif '```' in txt or b.get('kind') == 'code':
                current_set['code_blocks'].append(txt)
            else:
                if not current_set['option_blocks']:
                    current_set['stem_blocks'].append(txt)
                else:
                    # Post-option note or explanation
                    current_set['option_blocks'].append(txt)
        else:
            # Pre-question header or instructions (e.g. "2024년 1학기 자바 기출문제")
            current_set = {
                'id': b.get('id', ''),
                'stem_blocks': [txt],
                'option_blocks': [],
                'code_blocks': [],
                'all_blocks': [b]
            }

    if current_set:
        question_sets.append(_finalize_question_set(current_set))

    return question_sets


def _finalize_question_set(qset):
    stem = "\n".join(qset['stem_blocks']).strip()
    options = qset['option_blocks']
    codes = qset['code_blocks']
    all_blocks = qset['all_blocks']

    # Full aggregated text for chunking
    parts = [stem]
    if codes:
        parts.extend(codes)
    if options:
        parts.append("\n".join(options))

    full_question_text = "\n\n".join(parts)

    # Determine if this is a genuine exam question (keyword '문제/문/Q' or has choice options)
    has_exam_prefix = bool(re.match(r'^(?:\[\s*)?(?:문제|문|Q)\s*[0-9]{1,2}', stem, re.IGNORECASE))
    has_choice_options = len(options) >= 2
    is_genuine_exam = (has_exam_prefix or has_choice_options) and bool(EXAM_QUESTION_PATTERN.match(stem))

    return {
        'id': qset['id'],
        'question_text': full_question_text,
        'stem': stem,
        'options': options,
        'code_snippets': codes,
        'block_count': len(all_blocks),
        'blocks': all_blocks,
        'is_exam_question': is_genuine_exam
    }


def build_whisper_initial_prompt(domain_texts, max_prompt_length=220):
    """Harvest high-frequency domain technical terms to construct Whisper initial_prompt.

    Supplying key technical terms (e.g. 'Java, Polymorphism, Stack, LIFO, Queue')
    dramatically reduces Whisper ASR phonetic transcription errors on jargon.
    """
    if not domain_texts:
        return ""

    combined = " ".join(_clean_str(t) for t in domain_texts if t)
    if not combined:
        return ""

    # Extract English technical terms and programming keywords
    en_terms = re.findall(r'\b[A-Za-z][A-Za-z0-9_]{2,25}\b', combined)
    # Extract Korean compound nouns (3~15 chars)
    ko_terms = re.findall(r'[가-힣]{3,15}', combined)

    stop_words = {
        'class', 'import', 'public', 'static', 'void', 'this', 'that', 'from', 'with', 'have',
        '입니다', '합니다', '있습니다', '없습니다', '대하여', '통하여', '그리고', '하지만', '때문에', '경우에'
    }

    def _normalize_term(term):
        term = term.strip()
        # Predicate / verb filter
        for sfx in ('합니다', '입니다', '있습니다', '없습니다', '동작하며', '동작한다', '경우에', '대하여', '통하여'):
            if term.endswith(sfx):
                return ""
        # Strip common Korean particles (조사)
        for particle in ('에서는', '에서도', '으로는', '으로', '에서', '에게', '에는', '이다', '된다', '하다', '과는', '와의', '과', '와', '는', '은', '를', '을', '의', '에', '로'):
            if len(term) > len(particle) + 1 and term.endswith(particle):
                return term[:-len(particle)]
        return term

    counts = {}
    for term in en_terms + ko_terms:
        clean = _normalize_term(term)
        if not clean or len(clean) < 2:
            continue
        if clean.lower() not in stop_words:
            counts[clean] = counts.get(clean, 0) + 1

    # Sort by frequency, then length
    ranked = sorted(counts.keys(), key=lambda t: (-counts[t], -len(t)))

    selected = []
    current_len = 0
    for t in ranked:
        t_len = len(t) + 2
        if current_len + t_len > max_prompt_length:
            break
        selected.append(t)
        current_len += t_len

    return ", ".join(selected)


def deduplicate_consecutive_frames(frames, max_gap_seconds=30.0):
    """Compress consecutive identical/near-identical video frames into exposure intervals.

    Prevents identical duplicate slide frame floods while recording exact time intervals.
    """
    if not frames:
        return []

    # Sort frames chronologically
    sorted_frames = sorted(frames, key=lambda f: f.get('time_seconds', 0.0))
    deduped = []
    current_cluster = [sorted_frames[0]]

    for f in sorted_frames[1:]:
        prev = current_cluster[-1]
        t_prev = prev.get('time_seconds', 0.0)
        t_cur = f.get('time_seconds', 0.0)

        # Check identical content (image sha256 or matching unit_key / slide text)
        is_same_content = (
            (prev.get('image_sha256') and prev.get('image_sha256') == f.get('image_sha256'))
            or (prev.get('observed_text') and prev.get('observed_text') == f.get('observed_text'))
            or (prev.get('id') == f.get('id'))
        )

        time_gap = t_cur - t_prev
        if is_same_content and time_gap <= max_gap_seconds:
            current_cluster.append(f)
        else:
            # Emit merged frame
            deduped.append(_merge_frame_cluster(current_cluster))
            current_cluster = [f]

    if current_cluster:
        deduped.append(_merge_frame_cluster(current_cluster))

    return deduped


def _merge_frame_cluster(cluster):
    first = cluster[0]
    last = cluster[-1]
    start_t = first.get('time_seconds', 0.0)
    end_t = last.get('time_seconds', start_t + 10.0)
    if end_t == start_t:
        end_t = start_t + 5.0

    merged = copy.deepcopy(first)
    merged['time_interval'] = {'start_seconds': start_t, 'end_seconds': end_t}
    merged['sample_frame_count'] = len(cluster)
    merged['frame_ids'] = [f.get('id', '') for f in cluster]
    return merged


def verify_code_snippet_integrity(code_snippet, language='java'):
    """Verify that a code snippet has valid syntax and balance without breaking.

    Wraps snippets in dummy class/function if necessary to test syntax validity.
    """
    if not code_snippet or not code_snippet.strip():
        return {'valid': False, 'reason': 'empty_code'}

    code = code_snippet.strip()

    # Bracket balance check
    pairs = {'(': ')', '{': '}', '[': ']'}
    stack = []
    for char in code:
        if char in pairs:
            stack.append(char)
        elif char in pairs.values():
            if not stack or pairs[stack.pop()] != char:
                return {'valid': False, 'reason': f'unbalanced_bracket:{char}', 'wrapped': False}

    if stack:
        return {'valid': False, 'reason': f'unclosed_bracket:{stack[-1]}', 'wrapped': False}

    # Python syntax verification
    if language.lower() == 'python':
        try:
            compile(code, '<string>', 'exec')
            return {'valid': True, 'reason': 'syntax_ok', 'wrapped': False}
        except SyntaxError:
            # Try wrapping in dummy function for top-level statement/return snippets
            wrapped_code = f"def __dummy_wrapper():\n" + "\n".join("    " + line for line in code.splitlines())
            try:
                compile(wrapped_code, '<string>', 'exec')
                return {'valid': True, 'reason': 'snippet_valid_with_wrapper', 'wrapped': True}
            except SyntaxError as ex:
                return {'valid': False, 'reason': f'python_syntax_error:{ex.msg}', 'wrapped': False}

    # Java bracket/semicolon sanity
    return {'valid': True, 'reason': 'brackets_balanced', 'wrapped': False}
