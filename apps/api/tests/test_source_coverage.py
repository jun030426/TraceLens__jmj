"""Content coverage through real ingestion; all sources and providers are synthetic."""
import hashlib
from pathlib import Path
from types import SimpleNamespace
import pytest
from pptx import Presentation
from pptx.util import Inches
from sqlalchemy import select
from lerny import local_media_checks as checks, worker
from lerny.config import settings
from lerny.models import Chunk, Job, MaterialVersion
from lerny.team_engine import native_document
from test_gemini_integration import configured, integration
from test_lecture_specs import api
from test_document_materials import site, synthetic_engine


def transcript(words):
    return {'segments': [{'text': ' '.join(t for t, _ in words), 'start': 0, 'end': len(words),
        'words': [{'word': ' ' + t, 'start': i, 'end': i+1, 'probability': p} for i, (t, p) in enumerate(words)]}]}


def audio(words):
    n = len(words)
    return checks.audio_records(transcript(words), n, 0,
        [{'start': 0, 'end': n, 'rms_dbfs': -20, 'clipped_fraction': 0}], [[0, n]])[0]


def selected(rows):
    return [c['text'] for c in checks.build_chunks(rows, 'source')]


def test_uncertain_filler_does_not_remove_database_relation():
    words = [('자', .1), ('데이터베이스는', .95), ('B-트리와', .95), ('해시', .95), ('테이블을', .95), ('사용합니다.', .95)]
    rows = audio(words)
    assert selected(rows) == ['데이터베이스는 B-트리와 해시 테이블을 사용합니다.']
    held = [r for r in rows if not r['eligible_for_chunking']]
    assert len(held) == 1 and held[0]['text'].strip() == '자'
    assert held[0]['source_context'] == transcript(words)['segments'][0]['text']
    assert ''.join(r['text'] for r in rows) == transcript(words)['segments'][0]['text']


@pytest.mark.parametrize('uncertain', ['아니다.', '10', '미만이면', 'B-트리', '아마', '아닌', '라고'])
def test_critical_or_unknown_word_is_never_deleted_to_assert_the_rest(uncertain):
    rows = audio([('스택은', .95), ('FIFO가', .95), (uncertain, .1)])
    assert selected(rows) == []
    assert ''.join(r['text'] for r in rows) == f'스택은 FIFO가 {uncertain}'


def test_only_independent_sentence_survives_uncertain_content():
    rows = audio([('스택은', .95), ('LIFO다.', .95), ('큐는', .95), ('이상한용어다.', .1), ('배열은', .95), ('연속적이다.', .95)])
    chunks = selected(rows)
    assert [x.strip() for x in chunks] == ['스택은 LIFO다.', '배열은 연속적이다.']
    assert all('이상한용어' not in x for x in chunks)
    assert any('큐는' in r['text'] and not r['eligible_for_chunking'] for r in rows)


def test_unaligned_words_fail_closed_and_zero_duration_is_not_relaxed():
    value = transcript([('자', .1), ('데이터를', .95), ('저장한다.', .95)])
    value['segments'][0]['words'][1]['word'] = ' 다른내용'
    rows, _ = checks.audio_records(value, 3, 0, [], [])
    assert not selected(rows) and 'asr_word_alignment_unverified' in rows[0]['reasons']
    value = transcript([('자', .1), ('데이터를', .95), ('저장한다.', .95)])
    value['segments'][0]['words'][1]['end'] = 1
    rows, _ = checks.audio_records(value, 3, 0, [], [])
    assert not selected(rows) and 'word_timestamp_outside_segment' in rows[0]['reasons']


def test_existing_good_chunks_do_not_merge_across_recovered_spans():
    rows = audio([('자', .1), ('정상', .95), ('본문이다.', .95)])
    before = {'id': 'before', 'modality': 'audio', 'text': '기존 앞 문장', 'start_seconds': 0, 'end_seconds': 1, 'eligible_for_chunking': True}
    after = {**before, 'id': 'after', 'text': '기존 뒤 문장', 'start_seconds': 3, 'end_seconds': 4}
    assert [x.strip() for x in selected([before, *rows, after])] == ['기존 앞 문장', '정상 본문이다.', '기존 뒤 문장']


def deck(path, *, problem=None):
    p = Presentation(); slide = p.slides.add_slide(p.slide_layouts[6])
    table = slide.shapes.add_table(4, 3, Inches(1), Inches(1), Inches(8), Inches(4)).table
    values = [['활용 분야', '자료구조', '알고리즘'], ['데이터베이스', 'B-트리, 해시 테이블', '탐색, 정렬'],
              ['운영체제', '큐, 스택', 'CPU 스케줄링'], ['네트워크', '그래프', '최단 경로']]
    for r, row in enumerate(values):
        for c, text in enumerate(row): table.cell(r, c).text = text
    if problem == 'merge': table.cell(2, 0).merge(table.cell(2, 1))
    if problem == 'badspan': table.cell(2, 1)._tc.set('gridSpan', '0')
    if problem == 'badcode': table.cell(2, 1).text = 'def broken(x):\nreturn x'
    if problem == 'width': table.rows[2]._tr.remove(table.cell(2, 2)._tc)
    if problem == 'header': table.cell(0, 0).merge(table.cell(0, 1))
    p.save(path)
    return values


def test_native_table_preserves_rows_headers_cells_and_source(tmp_path):
    path = tmp_path/'lecture.pptx'; values = deck(path); before = path.read_bytes()
    document, chunks, held, evidence = native_document(path)
    assert not held and len(chunks) == 4 and path.read_bytes() == before
    assert document['source_sha256'] == hashlib.sha256(before).hexdigest()
    row = next(c for c in chunks if c['table']['row'] == 2)
    assert '열 1 [활용 분야]:\n데이터베이스' in row['text']
    assert '열 2 [자료구조]:\nB-트리, 해시 테이블' in row['text']
    assert 'CPU 스케줄링' not in row['text']
    assert [x['text'] for x in row['table']['cells']] == values[1]
    assert all(x['table']['source_xml_sha256'] for x in evidence)


@pytest.mark.parametrize('problem', ['merge', 'badspan', 'badcode', 'width'])
def test_problem_row_does_not_suppress_independent_table_rows(tmp_path, problem):
    path = tmp_path/'table.pptx'; deck(path, problem=problem)
    _, chunks, held, _ = native_document(path)
    assert {x['table']['row'] for x in chunks} == {1, 2, 4}
    assert len(held) == 1 and held[0]['table']['row'] == 3
    assert 'B-트리' in '\n'.join(c['text'] for c in chunks)


def test_uncertain_merged_header_never_labels_data_with_guessed_columns(tmp_path):
    path = tmp_path/'table.pptx'; deck(path, problem='header')
    _, chunks, held, _ = native_document(path)
    assert not chunks and len(held) == 4
    assert any('native_table_header_requires_review' in r['reasons'] for r in held)


def test_table_reaches_actual_weekly_generation_input_and_rag_chunks(site, synthetic_engine, monkeypatch):
    from lerny import weekly_content
    # The site path verifies rendered candidates against native PPT evidence.
    # Return independently readable rows; the merged row remains unresolved.
    synthetic_engine.text = ('| 활용 분야 | 자료구조 | 알고리즘 |\n'
                             '| 데이터베이스 | B-트리, 해시 테이블 | 탐색, 정렬 |\n'
                             '| 네트워크 | 그래프 | 최단 경로 |')
    _, db, _ = site
    path = settings().runtime_root/'data/files/coverage.pptx'; path.parent.mkdir(parents=True, exist_ok=True); deck(path, problem='merge')
    version = db.get(MaterialVersion, 'version')
    version.filename = version.object_key = path.name; version.sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    job = Job(owner_id='teacher', course_id='course', kind='extract', payload={'version_id': version.id})
    db.add(job); db.commit()
    assert worker.run_once(job.id)
    db.expire_all()
    assert job.status == "succeeded", job.error_code
    assert version.extraction_report["native_evidence"]["mandatory_calculation_gate"]
    chunks = list(db.scalars(select(Chunk).where(Chunk.version_id == version.id)))
    assert any('데이터베이스' in c.content and 'B-트리' in c.content and '탐색, 정렬' in c.content for c in chunks)
    assert all('CPU 스케줄링' not in c.content for c in chunks)
    source = {'version_id': version.id, 'title': '강의자료'}
    monkeypatch.setattr(weekly_content, 'generation_for_job', lambda *a: SimpleNamespace(sources=[source]))
    seen = []
    class Captured(Exception): pass
    def capture(prompt, schema): seen.append(prompt); raise Captured()
    monkeypatch.setattr(worker, 'model_json', capture)
    with pytest.raises(Captured): weekly_content.generate_job(db, job)
    assert 'B-트리, 해시 테이블' in seen[0] and '데이터베이스' in seen[0]
    assert 'CPU 스케줄링' not in seen[0]
    assert version.extraction_report['review_queue']
    assert 'CPU 스케줄링' in str(version.extraction_report['review_queue'])
