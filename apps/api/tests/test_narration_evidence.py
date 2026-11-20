import copy,json
import pytest
from lerny.narration_evidence import review_narration


SOURCES=[{'source_id':'intro','text':'스택은 후입선출 구조입니다. 맨 위에서 넣고 꺼냅니다.'},
         {'source_id':'example','text':'2, 5, 8을 순서대로 넣습니다. 두 번 pop하면 8과 5가 반환되고 2가 남습니다.'}]
UNITS=[{'target':'/lesson/narration/0','text':'스택은 마지막에 넣은 값부터 꺼냅니다.','source_ids':['intro']},
       {'target':'/lesson/narration/1','text':'2, 5, 8을 넣고 두 번 꺼내면 2가 남습니다.','source_ids':['intro']}]


def output():
    return {'units':[{'target':UNITS[0]['target'],'verdict':'supported','evidence_ids':['E0']},
                     {'target':UNITS[1]['target'],'verdict':'supported','evidence_ids':['E2','E3']}]}


def test_review_selects_exact_evidence_from_full_authorized_scope():
    def generate(prompt,schema):
        data=json.loads(prompt.rsplit('\n',1)[1])
        assert data['sources']==SOURCES
        assert all(item['quote'] in next(s['text'] for s in SOURCES if s['source_id']==item['source_id'])
                   for item in data['source_fragments'])
        return output()
    citations=review_narration(UNITS,SOURCES,generate)
    assert citations==[
        {'target':UNITS[0]['target'],'source_id':'intro','quote':'스택은 후입선출 구조입니다.'},
        {'target':UNITS[1]['target'],'source_id':'example','quote':'2, 5, 8을 순서대로 넣습니다.'},
        {'target':UNITS[1]['target'],'source_id':'example','quote':'두 번 pop하면 8과 5가 반환되고 2가 남습니다.'}]


@pytest.mark.parametrize('mutation',[
    lambda r:r['units'][1].update(verdict='unsupported'),
    lambda r:r['units'][1].update(verdict='contradicted'),
    lambda r:r['units'][1].update(evidence_ids=['PRIVATE_KEY']),
    lambda r:r['units'][1].update(evidence_ids=['두 번 pop하면 8과 5가 반환되고 2가 남습니다.']),
    lambda r:r['units'][1].update(evidence_ids=[]),
    lambda r:r['units'][1].update(evidence_ids=['E2','E2']),
    lambda r:r['units'][1].update(target=UNITS[0]['target']),
    lambda r:r['units'].pop(),
])
def test_unsupported_forged_or_incomplete_review_stays_held(mutation):
    result=copy.deepcopy(output());mutation(result)
    assert review_narration(UNITS,SOURCES,lambda *_:result) is None


def test_missing_evidence_never_calls_model():
    def fail(*_):raise AssertionError('No model calls without usable evidence')
    assert review_narration(UNITS,[{'source_id':'tiny','text':'abc'}],fail) is None
