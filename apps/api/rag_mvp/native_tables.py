"""OOXML table rows with explicit column relationships; no OCR or guessed cells."""
import hashlib
import re
import xml.etree.ElementTree as ET

from .code_regions import regions, fenced, MONO
from .markdown_tools import code_blocks

A = 'http://schemas.openxmlformats.org/drawingml/2006/main'
NS = {'a': A}
POLICY = 'native-table-rows-v1'


def table_units(table, locator, part, page):
    from .document_ingest import text_of
    grid = table.findall('a:tblGrid/a:gridCol', NS)
    rows = table.findall('a:tr', NS)
    ncols = len(grid)
    xml_hash = hashlib.sha256(ET.tostring(table)).hexdigest()
    if not ncols or not rows or any(not re.fullmatch(r'[1-9][0-9]*', col.get('w', '')) for col in grid):
        return [], [{'locator': locator, 'reason': 'native_table_grid_invalid', 'source_part': part,
                     'text': '\n'.join(text_of(p, A) for p in table.findall('.//a:p', NS))}]
    prepared = []; damaged = set()
    for r, tr in enumerate(rows):
        cells = tr.findall('a:tc', NS); reason = ''
        if len(cells) != ncols: reason = 'native_table_row_width_mismatch'
        values = []
        for c, cell in enumerate(cells):
            body = cell.find('a:txBody', NS)
            raw = '\n'.join(text_of(p, A) for p in body.findall('a:p', NS)) if body is not None else ''
            cell_reason = ''
            if any(cell.get(key) is not None and not re.fullmatch(r'[1-9][0-9]*', cell.get(key)) for key in ('gridSpan', 'rowSpan')):
                cell_reason = 'native_table_span_invalid'
            # Merged rows require a separate span proof. Keep unrelated intact rows.
            merged = any(cell.get(key) not in (None, '0', 'false', '1') for key in ('gridSpan', 'rowSpan')) or any(
                cell.get(key) not in (None, '0', 'false') for key in ('hMerge', 'vMerge'))
            if merged:
                cell_reason = cell_reason or 'native_table_merged_region_requires_review'
                span = cell.get('rowSpan', '1')
                stop = min(len(rows), r + int(span)) if span.isdigit() and 0 < int(span) <= len(rows) else len(rows)
                damaged.update(range(r, stop))
            if body is None or '\ufffd' in raw or any(ord(x) < 32 and x not in '\t\n\r' for x in raw):
                cell_reason = cell_reason or 'native_table_cell_text_invalid'
            if body is not None and any(node.tag.rsplit('}', 1)[-1] in {'fld', 'oMath', 'oMathPara', 'sym', 'blip'} for node in body.iter()):
                cell_reason = cell_reason or 'native_table_cell_structure_requires_review'
            fonts = [f.get('typeface', '') for f in body.findall('.//a:latin', NS)] if body is not None else []
            spans = regions(raw, bool(fonts) and all(MONO.search(f) for f in fonts))
            rendered = []
            for span in spans:
                value = raw[span['start']:span['end']]
                cell_reason = cell_reason or span.get('reason', '')
                if span['kind'] == 'code':
                    code = span.get('code_text', value)
                    value = value if span.get('already_fenced') else fenced(code, span.get('language', ''))
                    expected = code.replace('\r\n', '\n').replace('\r', '\n')
                    if not expected.endswith('\n'): expected += '\n'
                    if not cell_reason and code_blocks(value) != [expected]: cell_reason = 'code_fence_roundtrip_failed'
                rendered.append(value)
            reason = reason or cell_reason
            values.append({'row': r+1, 'column': c+1, 'text': raw, 'rendered': ''.join(rendered),
                           'source_locator': f'{locator}/cell:{r+1},{c+1}'})
        prepared.append({'cells': values, 'reason': reason})
    props = table.find('a:tblPr', NS)
    has_header = props is not None and props.get('firstRow') in ('1', 'true')
    headers = prepared[0]['cells'] if has_header else []
    header_invalid = has_header and (prepared[0]['reason'] or 0 in damaged)
    units = []
    for r, row in enumerate(prepared):
        reason = row['reason'] or ('native_table_merged_region_requires_review' if r in damaged else '')
        if header_invalid and r > 0: reason = reason or 'native_table_header_requires_review'
        # Repeat the source header with each complete data row, never flatten columns.
        parts = [f'표 {locator} · 행 {r+1}']
        for c, cell in enumerate(row['cells']):
            heading = headers[c]['text'] if has_header and c < len(headers) and not header_invalid else ''
            parts.append(f'열 {c+1}' + (f' [{heading}]' if heading else '') + ':\n' + cell['rendered'])
        value = '\n'.join(parts)
        if len(value) > 1800: reason = reason or 'native_table_row_too_large'
        units.append({'locator': f'{locator}/row:{r+1}', 'source_part': part, 'page': page,
            'text': value, 'held_reason': reason, 'native_table': {
                'policy': POLICY, 'table_locator': locator, 'row': r+1, 'column_count': ncols,
                'first_row_header': has_header, 'cells': [{k:v for k,v in cell.items() if k!='rendered'} for cell in row['cells']],
                'headers': [{k:v for k,v in cell.items() if k!='rendered'} for cell in headers] if not header_invalid else [],
                'source_xml_sha256': xml_hash, 'validation': 'row_grid_and_literal_text' if not reason else 'held'}})
    return units, []


def table_chunk(unit, base):
    value = unit['text']; reason = unit.get('held_reason', '')
    chunk = {**base, 'id': base['parent_unit_id'] + ':table-row', 'kind': 'text',
             'text': value, 'source_text': value, 'source_char_start': 0, 'source_char_end': len(value),
             'table': unit['native_table'], 'quality': POLICY, 'eligible_for_chunking': not reason}
    if reason: chunk.update(status='held', reasons=[reason])
    evidence = {'locator': unit['locator'], 'original_text': value, 'table': unit['native_table'],
                'scope': 'native_grid_relationships_and_literal_text_not_visual_or_factual_accuracy'}
    return chunk, evidence
