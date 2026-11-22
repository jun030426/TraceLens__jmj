import hashlib
import json
import math
import os
import threading
from pathlib import Path
from datetime import datetime, timezone


def now():
    return datetime.now(timezone.utc).isoformat()


def digest_file(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def signature(data):
    return hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def save(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f'.{os.getpid()}.{threading.get_ident()}.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    tmp.replace(path)


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def jsonl(path, rows):
    path = Path(path)
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(''.join(json.dumps(r, ensure_ascii=False, allow_nan=False) + '\n' for r in rows), encoding='utf-8')
    tmp.replace(path)


def validate(value, schema, at='$'):
    """Strict validator for the fixed JSON Schema subset used by this package.

    Not a general JSON Schema engine. Schemas are code-owned, never user-supplied.
    Supports types, required, additionalProperties, enum, items and size/range bounds.
    """
    kinds = {'object': dict, 'array': list, 'string': str, 'boolean': bool,
             'integer': int, 'number': (int, float)}
    typ = schema['type']
    if type(value) not in (kinds[typ] if isinstance(kinds[typ], tuple) else (kinds[typ],)):
        raise ValueError(f'{at}: invalid {typ}')
    if typ == 'number' and not math.isfinite(value):
        raise ValueError(f'{at}: non-finite number')
    if 'enum' in schema and value not in schema['enum']:
        raise ValueError(f'{at}: invalid enum')
    if typ == 'object':
        for key in schema.get('required', []):
            if key not in value:
                raise ValueError(f'{at}: missing {key}')
        props = schema['properties']
        if schema.get('additionalProperties') is False and set(value) - set(props):
            raise ValueError(f'{at}: unexpected properties')
        for key, item in value.items():
            if key in props:
                validate(item, props[key], f'{at}.{key}')
    elif typ == 'array':
        if len(value) < schema.get('minItems', 0) or len(value) > schema.get('maxItems', 100000):
            raise ValueError(f'{at}: invalid array size')
        for i, item in enumerate(value):
            validate(item, schema['items'], f'{at}[{i}]')
    elif typ == 'string':
        if len(value) < schema.get('minLength', 0) or len(value) > schema.get('maxLength', 100000):
            raise ValueError(f'{at}: invalid string size')
    elif typ in ('number', 'integer'):
        if value < schema.get('minimum', -math.inf) or value > schema.get('maximum', math.inf):
            raise ValueError(f'{at}: number outside bounds')
    return value


def overlap(a, b, c, d):
    return max(0.0, min(b, d) - max(a, c))


def bbox_pixels(box, size, pad=8):
    if len(box) != 4 or not all(type(n) is int for n in box):
        raise ValueError('bbox must contain four integers')
    x1, y1, x2, y2 = box
    if not (0 <= x1 < x2 <= 1000 and 0 <= y1 < y2 <= 1000):
        raise ValueError('invalid bbox ordering')
    w, h = size
    return (max(0, math.floor(x1*w/1000)-pad), max(0, math.floor(y1*h/1000)-pad),
            min(w, math.ceil(x2*w/1000)+pad), min(h, math.ceil(y2*h/1000)+pad))


def atomic_patches(original, proposals):
    """All offsets refer to immutable original. Reject ALL conflicting edits."""
    valid, held = [], []
    for p in proposals:
        before = p['before']
        if not before or original.count(before) != 1:
            held.append({**p, 'hold_reason': 'ambiguous_anchor'})
            continue
        start = original.index(before)
        valid.append({**p, 'start': start, 'end': start + len(before)})
    rejected = set()
    for i, p in enumerate(valid):
        for j in range(i):
            q = valid[j]
            if p['start'] < q['end'] and q['start'] < p['end']:
                rejected.update((i, j))
    accepted = []
    for i, p in enumerate(valid):
        if i in rejected:
            held.append({**p, 'hold_reason': 'overlapping_edits'})
        else:
            accepted.append(p)
    result = original
    for p in sorted(accepted, key=lambda x: x['start'], reverse=True):
        result = result[:p['start']] + p['after'] + result[p['end']:]
    return result, accepted, held
