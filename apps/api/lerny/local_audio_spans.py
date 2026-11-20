"""Source-exact speech spans. Uncertain content never becomes an affirmative fragment."""
import re

POLICY = 'local-audio-spans-v2'
# Only standalone discourse markers at a sentence boundary. Never negation,
# conditions, amounts, concepts, or a word merely containing one of these strings.
LEADING = {'자', '음', '어', '아', '네', '안녕하세요', '안녕하십니까'}
TRAILING = {'요'}


def aligned_words(text, words):
    positions = [i for i, c in enumerate(text) if not c.isspace()]
    observed = ''.join(text[i] for i in positions)
    cursor = 0; result = []
    for word in words:
        token = ''.join(str(word.get('word', '')).split())
        if not token or observed[cursor:cursor + len(token)] != token:
            return None
        result.append({**word, 'a': positions[cursor], 'b': positions[cursor + len(token) - 1] + 1})
        cursor += len(token)
    return result if cursor == len(observed) else None


def split_uncertain(row, record):
    """Split independent sentences, then isolate uncertain boundary fillers only.

    A low-confidence content/negative/number word holds its whole sentence.
    Retained fragments cannot be joined over a missing word by build_chunks.
    """
    if set(record['reasons']) != {'low_word_probability'}:
        return [record]
    text = row['text']; words = aligned_words(text, row['words'])
    if not words:
        return [{**record, 'reasons': [*record['reasons'], 'asr_word_alignment_unverified']}]
    ends = [m.end() for m in re.finditer(r'[.!?。！？]+(?:["”’\')\]]*)(?:\s+|$)', text)]
    if not ends or ends[-1] != len(text): ends.append(len(text))
    spans = []; start = 0
    for end in ends:
        selected = [w for w in words if w['a'] < end and w['b'] > start]
        if any(w['a'] < start or w['b'] > end for w in selected): return [record]
        bad = [w for w in selected if w.get('probability', 1) < .4]
        if not bad:
            spans.append((start, end, False, selected)); start = end; continue
        left, right = 0, len(selected)
        marker = lambda w: w['word'].strip().strip('.,!?。！？:;')
        while left < right and selected[left].get('probability', 1) < .4 and marker(selected[left]) in LEADING:
            left += 1
        while right > left and selected[right-1].get('probability', 1) < .4 and marker(selected[right-1]) in TRAILING:
            right -= 1
        middle = selected[left:right]
        # Retain a meaningful body only when every remaining token is confident.
        if len(middle) >= 2 and len(text[middle[0]['a']:middle[-1]['b']].strip()) >= 5 and not any(w.get('probability', 1) < .4 for w in middle):
            a = middle[0]['a'] if left else start
            b = selected[right]['a'] if right < len(selected) else end
            if a > start: spans.append((start, a, True, selected[:left]))
            spans.append((a, b, False, middle))
            if b < end: spans.append((b, end, True, selected[right:]))
        else:
            spans.append((start, end, True, selected))
        start = end
    if not any(not held and text[a:b].strip() for a, b, held, _ in spans): return [record]
    if ''.join(text[a:b] for a, b, _, _ in spans) != text: raise ValueError('AUDIO_SOURCE_COVERAGE_CHANGED')
    result = []
    offset = record['start_seconds'] - row['start_seconds']
    for i, (a, b, held, selected) in enumerate(spans, 1):
        if not text[a:b].strip(): continue
        start_time = selected[0]['start_seconds'] + offset
        end_time = selected[-1]['end_seconds'] + offset
        result.append({**record, 'id': record['id'] + f'-span-{i}', 'parent_record_id': record['id'],
            'text': text[a:b], 'start_seconds': start_time, 'end_seconds': end_time,
            'source_locator': f'영상 {start_time:.1f}–{end_time:.1f}초 · 음성 일부',
            'source_char_start': a, 'source_char_end': b, 'source_context': text if held else '',
            'reasons': ['low_word_probability'] if held else [], 'eligible_for_chunking': not held,
            'isolated': True, 'selection_policy': POLICY})
    return result
