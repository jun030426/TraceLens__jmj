import json
from types import SimpleNamespace

import pytest

from lerny import team_engine
from lerny.team_engine import complete_short_narration,validate_short_narration


def test_one_complete_continuation_preserves_original_script_and_original_sources():
    narration=['도입입니다.','설명.'*98,'마무리입니다.']
    source='기존 원문에 있는 구체적인 예제 설명입니다.'
    calls=[]
    def generate(prompt,schema):
        data=json.loads(prompt.rsplit('\n',1)[1]);calls.append(data)
        assert data['previous']==narration and data['sources']==[{'source_id':'source','text':source}]
        length=data['minimum_additional_characters']
        return {'continuations':['너무 짧아요.','새로운 설명'+('가'*(length-7))+'.','길어요.'*100]}
    result=complete_short_narration(narration,[(SimpleNamespace(id='source',content=source),None,None)],'개념',generate)
    validate_short_narration(result,50)
    assert result[0]==narration[0] and result[2]==narration[2]
    assert result[1].startswith(narration[1]+' ') and result[1].endswith('.')
    assert len(calls)==1


@pytest.mark.parametrize('candidate',['짧아요.','긴 설명.'*200,'완결되지 않은 설명','가'*64,'.'*60])
def test_invalid_continuation_never_pads_or_truncates(candidate):
    narration=['도입입니다.','설명.'*98,'마무리입니다.']
    result=complete_short_narration(narration,[],'개념',lambda *args:{'continuations':[candidate]*3})
    assert result==narration
    with pytest.raises(ValueError,match='SHORTS_NARRATION_LENGTH'):validate_short_narration(result,50)


@pytest.mark.parametrize('body',['설명.'*123,'너무 짧아요.','너무 깁니다.'*100])
def test_valid_or_unusable_draft_makes_no_continuation_call(body):
    narration=['도입입니다.',body,'마무리입니다.']
    def fail(*args):raise AssertionError('No model call expected')
    assert complete_short_narration(narration,[],'개념',fail)==narration


def test_later_shorter_repair_never_discards_the_better_complete_draft(monkeypatch):
    source='원문에서 제공한 설명입니다.'
    script={'target_seconds':50,'source_id':'source','quote':source,
        'hook':{'narration':'가'*30},'body':{'narration':'나'*230,'key_takeaways':[source]},'outro':{'narration':'다'*30}}
    monkeypatch.setattr(team_engine,'make_engine',lambda *a,**k:SimpleNamespace(generate_shorts_script=lambda *a,**k:script))
    calls=[]
    def generate(prompt,schema):
        data=json.loads(prompt.rsplit('\n',1)[1]);calls.append(data)
        if 'continuations' in schema['properties']:
            assert data['actual_characters']==334
            assert data['minimum_additional_characters']==25
            return {'continuations':['보충 설명.'+'가'*40+'.','너무 짧아요.','과도한 설명.'*100]}
        target=334 if len(calls)==1 else 294
        candidate={'hook':'가'*30,'body':'나'*(target-62),'outro':'다'*30}
        return {'candidates':[candidate]*3}
    job=SimpleNamespace(id='job',course_id='course',payload={'learning_objective':'학습','target_duration_seconds':50,'source_snapshot_id':'snapshot'})
    result=team_engine.narration_draft([(SimpleNamespace(id='source',content=source),None,None)],job,SimpleNamespace(name='개념'),generate)
    assert len(' '.join(result.lesson.narration))==382 and len(calls)==3


def test_almost_ready_draft_still_requires_a_meaningful_complete_continuation():
    narration=['도입입니다.','가'*344,'마무리입니다.']
    assert len(' '.join(narration))==359
    def generate(prompt,schema):
        assert schema['properties']['continuations']['items']['minLength']==12
        return {'continuations':['.','.'*12,' ']*1}
    assert complete_short_narration(narration,[],'개념',generate)==narration
