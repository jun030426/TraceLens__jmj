import hashlib
import json
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from lerny import practice, worker
from lerny.models import Chunk, Job, Material, PracticeExercise
from lerny.practice_inputs import adapted_programs, blank_template, condition_spans, literal_inputs, numeric_source
from test_weekly_publication import api, configured, integration, weekly, start  # noqa: F401

CODE = 'a = int(input("첫 수: "))\nb = float(input("다음 수: "))\n\ntotal = a + b\nprint("두 수의 합은", total)\nprint("평균은", total / 2)'


def proposal(**changes):
    return {'source_id':'numeric', 'title':'합과 평균', 'prompt':'두 수의 합과 평균을 계산하여 출력하세요.',
            'cases':[[2,4],[0,2],[-2,8]], 'blank_lines':[4], **changes}


def adapt(code=CODE, **changes):
    return adapted_programs([SimpleNamespace(id='numeric',content='```python\n'+code+'\n```')],
                            lambda *args: {'programs':[proposal(**changes)]})


def test_adaptation_preserves_source_and_calculation_suffix():
    item, quote = adapt()[0]
    assert quote == CODE
    assert item.code == 'a = 2\nb = 4.0' + CODE[CODE.index('\n\n'):]
    assert practice.input_variants(item.input_statement,item.variants) == ['a = 2\nb = 4.0','a = 0\nb = 2.0','a = -2\nb = 8.0']
    crlf = CODE.replace('\n','\r\n')
    item, quote = adapt(crlf)[0]
    assert quote == crlf and item.code.endswith(crlf[crlf.index('\r\n\r\n'):])
    assert item.input_statement == 'a = 2\nb = 4.0'
    assert '\n'.join(item.code.splitlines()).count(item.input_statement) == 1


@pytest.mark.parametrize('combined', [True, False])
def test_verified_ppt_shape_preserves_numeric_example(combined):
    digest = hashlib.sha256(CODE.encode()).hexdigest()
    engine = {'document_type':'pptx','source_sha256':'deck','slide_number':3}
    page = {'page':3,'shapes':[{'shape_id':7,'text_sha256':digest}]}
    version = SimpleNamespace(id='v',sha256='deck',extraction_report={'source_reviews':[
        {'review':{'source_sha256':'deck','pages':[page]}}]})
    if combined:
        engine.update(quality='visually_reviewed_native_text_v1', reviewed_shape_ids=[7])
        content = '실습 예제\n\n'+CODE+'\n\n[출력 결과]\n두 수의 합은 6'
    else:
        engine['source_region'] = {'kind':'text','text_sha256':digest,'source_sha256':'deck'}
        content = CODE
    chunk = SimpleNamespace(id='c',version_id='v',content=content,locator={'engine':engine})
    def generate(prompt, _schema):
        item = json.loads(prompt.split('\n',1)[1])['sources'][0]
        assert item['code'] == CODE
        return {'programs':[proposal(source_id=item['source_id'])]}
    (item, quote), = adapted_programs([chunk],generate,[version])
    assert quote == CODE and item.source_id == 'c' and quote in chunk.content
    chunk.content = content.replace('total / 2','total * 2')
    assert adapted_programs([chunk],generate,[version]) == []


@pytest.mark.parametrize('code',[
    'a = int(input()); print(a)',
    'name = input("이름:")\nprint(name)',
    'a = int(input())\nb = input()\nprint(a,b)',
    'a = int(input(fetch()))\nprint(a)',
    'a = int(input())\na = int(input())\nprint(a)',
])
def test_unsupported_inputs_are_not_adapted(code):
    assert numeric_source('```python\n'+code+'\n```') is None


@pytest.mark.parametrize('cases',[
    [[2,4],[0,2],[2,4]], [[2,4],[0,2],['__import__("os")',8]],
    [[2,4],[0,2],[1.5,8]], [[2,4],[0,2],[2,float('inf')]],
])
def test_only_distinct_finite_numeric_fixtures(cases):
    with pytest.raises(ValueError): adapt(cases=cases)


def test_multiline_variants_cannot_change_logic_or_variable_order():
    for changed in ['a = 3\nb = 4\nprint(a)', 'b = 3\na = 4', 'a = 3\nb = 2+4']:
        with pytest.raises(ValueError): literal_inputs('a = 1\nb = 2',['a = 2\nb = 3',changed])


def test_preparation_uses_isolated_runner_preserves_evidence_and_draft(weekly,monkeypatch):
    client,session,_ = weekly
    session.add(Chunk(id='numeric',version_id='version',content='```python\n'+CODE+'\n```',locator={}))
    session.commit()
    gid = start(client)
    job = Job(owner_id='teacher',course_id='course',kind='practice_prepare',
              payload={'source_version_id':'version','source_version_ids':['version'],'generation_id':gid})
    session.add(job);session.commit()
    monkeypatch.setattr(worker,'model_json',lambda prompt,schema: {'programs':[proposal()]} if '"cases"' in str(schema).replace("'",'"') else {'programs':[]})
    runs=[]
    def sandbox(language,source,**kwargs):
        assert language == 'python' and kwargs == {'owner_id':'teacher','section_id':'section'}
        assert 'input(' not in source and source.endswith(CODE[CODE.index('\n\n'):])
        runs.append(source)
        return str(len(runs))  # Synthetic sandbox receipt; never execute source on the test host.
    monkeypatch.setattr(practice,'output_of',sandbox)
    result = practice.prepare(session,job)
    session.commit()
    assert len(result['exercise_ids']) == 2 and len(runs) == 3 and result['held'] == []
    rows = list(session.scalars(select(PracticeExercise).where(PracticeExercise.generation_id==gid)))
    assert {row.kind for row in rows} == {'blank','full'}
    assert all(row.sources == [{'chunk_id':'numeric','quote':CODE}] for row in rows)
    assert all(practice.current_source(session,row) is None for row in rows)
    assert practice.prepare(session,job)['exercise_ids'] == [] and len(runs) == 3


def test_input_and_empty_lines_are_replaced_with_verified_calculation_lines():
    for selected in [[1],[2],[3],[999]]:
        item, _ = adapt(blank_lines=selected)[0]
        assert item.blank_lines == [4,5,6]
        assert item.input_statement in '\n'.join(item.code.splitlines())


@pytest.mark.parametrize("original", [CODE, "# numeric inputs\r\n\r\n" + CODE.replace("\n", "\r\n")])
def test_adapted_source_prevents_duplicate_stdin_hold(weekly,monkeypatch,original):
    client,session,_ = weekly
    session.add(Chunk(id='numeric',version_id='version',content='```python\n'+original+'\n```',locator={}))
    session.commit();gid=start(client)
    job=Job(owner_id='teacher',course_id='course',kind='practice_prepare',payload={'source_version_id':'version','generation_id':gid})
    old={'source_id':'numeric','concept_id':None,'code':CODE,'title':'합과 평균',
        'prompt':'두 수의 합과 평균을 계산하여 출력하세요.','input_statement':CODE.splitlines()[0],
        'variants':['a = 1','a = 2'],'blank_lines':[4],'full_template':'# 구현하세요.'}
    monkeypatch.setattr(worker,'model_json',lambda prompt,schema: {'programs':[proposal(blank_lines=[2])]} if 'cases' in str(schema) else {'programs':[old]})
    outputs=iter(['first','second','third'])
    monkeypatch.setattr(practice,'output_of',lambda *a,**k: next(outputs))
    result=practice.prepare(session,job)
    assert len(result['exercise_ids'])==2 and result['held']==[]
    rows = list(session.scalars(select(PracticeExercise).where(PracticeExercise.generation_id == gid)))
    assert all(row.sources == [{'chunk_id':'numeric','quote':original}] for row in rows)


def test_input_identity_preserves_source_and_logic():
    from lerny.practice_inputs import input_program_identity
    key = input_program_identity('source', CODE)
    assert key != input_program_identity('different-source', CODE)
    assert key != input_program_identity('source', CODE.replace('a + b', 'a - b'))
    assert key != input_program_identity('source', CODE.replace('total =', '    total ='))


def test_condition_template_round_trips_original_and_keeps_output_visible():
    code = ('점수 = 42\r\nif (점수 >= 40\r\n    and 점수 < 50):\r\n    print("통과")\r\n'
            'elif 50 <= 점수 < 60: print("재검사")\r\n'
            'if __name__ == "__main__":\r\n    main()')
    spans = condition_spans(code)
    template, answers = blank_template(code, spans, spans)
    assert list(answers.values()) == ['점수 >= 40', '점수 < 50', '50 <= 점수 < 60']
    assert 'elif [[빈칸]]: print("재검사")' in template
    assert 'if __name__ == "__main__":' in template
    for value in answers.values():
        template = template.replace('[[빈칸]]', value, 1)
    assert template == code.replace('\r\n', '\n')


def test_input_example_with_outputs_inside_branches_can_be_prepared():
    code = 'value = int(input())\nif value < 0:\n    print("음수")\nelse:\n    print("그 외")'
    chunks = [SimpleNamespace(id='numeric', content='\x60\x60\x60python\n'+code+'\n\x60\x60\x60')]
    programs = adapted_programs(chunks, lambda *_: {'programs':[proposal(cases=[[-1],[0],[1]], blank_lines=[3])]},
                                prefer_conditions=True)
    (item, quote), = programs
    assert quote == code and item.blank_lines == [2]


@pytest.mark.parametrize('week,scope,adapted,expect_branch', [
    (4,'course',True,True), (5,'course',False,True), (3,'course',True,False), (5,'other',False,False),
])
def test_branch_choice_in_weekly_practice(weekly, configured, monkeypatch, week, scope, adapted, expect_branch):
    client, session, _ = weekly
    monkeypatch.setattr(configured,'practice_condition_course_id',scope)
    rest = '\nif 0 <= value < 8:\n    result = "low"\nelif value >= 10:\n    result = "high"\nelse:\n    result = "mid"\nprint(result)'
    first = 'value = int(input())' if adapted else 'value = 1'
    source = first + rest
    session.get(Material,'material').week = week
    session.add(Chunk(id='numeric',version_id='version',content='\x60\x60\x60python\n'+source+'\n\x60\x60\x60',locator={}))
    session.commit()
    gid = start(client,week)
    job = Job(owner_id='teacher',course_id='course',kind='practice_prepare',
              payload={'source_version_id':'version','generation_id':gid})
    session.add(job); session.commit()
    def model(prompt, schema):
        assert ('경계값 포함 여부' in prompt) == expect_branch
        if 'cases' in str(schema):
            return {'programs':[proposal(cases=[[1],[9],[12]],blank_lines=[8])]}
        if adapted:
            return {'programs':[]}
        return {'programs':[dict(source_id='numeric', concept_id=None, code=source, title='범위 분기',
            prompt='주어진 값의 범위에 따라 결과를 출력하세요.', input_statement=first,
            variants=['value = 9','value = 12'], blank_lines=[8], full_template=first+'\n# 구현')]}
    monkeypatch.setattr(worker,'model_json',model)
    outputs=iter(['low','mid','high'])
    monkeypatch.setattr(practice,'output_of',lambda *a,**k: next(outputs))
    assert not practice.prepare(session,job)['held']
    exercise=session.scalar(select(PracticeExercise).where(PracticeExercise.generation_id==gid, PracticeExercise.kind=='blank'))
    assert list(exercise.blanks.values()) == (['0 <= value < 8','value >= 10'] if expect_branch else ['print(result)'])
    assert ('print(result)' in exercise.template) == expect_branch
    assert exercise.sources == [{'chunk_id':'numeric','quote':source}]
