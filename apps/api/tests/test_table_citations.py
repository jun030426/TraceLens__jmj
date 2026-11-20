import pytest
from lerny.team_engine import verbatim_source_quote

ROW='표 slide:14/shape:5 · 행 8\n열 1:\n해시 테이블(Hash Table)\n열 2:\n빠른 검색\n열 3:\n로그인, 회원 정보 조회, 캐시'
QUOTE='해시 테이블(Hash Table) 빠른 검색 로그인, 회원 정보 조회, 캐시'


def test_ordered_complete_cells_restore_exact_contiguous_source():
    restored=verbatim_source_quote(QUOTE,ROW)
    assert restored==ROW[ROW.index('해시'):]
    assert restored in ROW and '열 2:' in restored and '열 3:' in restored
    assert verbatim_source_quote('해시 테이블(Hash Table) | 빠른 검색 | 로그인, 회원 정보 조회, 캐시',ROW)==restored
    partial=verbatim_source_quote('빠른 검색 로그인, 회원 정보 조회, 캐시',ROW)
    assert partial==ROW[ROW.index('빠른'):]
    assert verbatim_source_quote(QUOTE,ROW.replace('\n','\r\n'))==restored.replace('\n','\r\n')


@pytest.mark.parametrize('quote',[
    '해시 테이블(Hash Table) 아주 빠른 검색 로그인, 회원 정보 조회, 캐시',
    '빠른 검색 해시 테이블(Hash Table) 로그인, 회원 정보 조회, 캐시',
    '해시 테이블(Hash Table) 로그인, 회원 정보 조회, 캐시',
    '빠른 검색 로그인, 회원 정보',
    '해시 테이블(Hash | Table) 빠른 검색 로그인, 회원 정보 조회, 캐시',
])
def test_cell_content_changes_reordering_gaps_and_fragments_stay_rejected(quote):
    assert verbatim_source_quote(quote,ROW) is None


def test_only_extractor_table_rows_and_unambiguous_spans_are_restored():
    assert verbatim_source_quote(QUOTE,ROW.replace('표 slide:14/shape:5 · 행 8','일반 문단')) is None
    ambiguous='표 slide:1/shape:1 · 행 1\n열 1:\n첫째\n열 2:\n둘째\n열 3:\n첫째\n열 4:\n둘째'
    assert verbatim_source_quote('첫째 둘째',ambiguous) is None
