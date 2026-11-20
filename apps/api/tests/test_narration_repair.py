import json
from types import SimpleNamespace

import pytest

from lerny.narration_evidence import review_narration
from lerny.narration_lessons import LessonDraft
from lerny.narration_repair import NarrationValidationError, finish_length, repair_evidence
from test_weekly_publication import weekly as fixture_weekly, start
from test_gemini_integration import api, configured, integration


def test_short_valid_continuation_is_retained_for_next_measured_step():
    original = ['도입입니다.', '기존 설명입니다. ' * 27, '마무리입니다.']
    seen = []
    def generate(prompt, schema):
        data = json.loads(prompt.rsplit('\n', 1)[1]); seen.append(data)
        if len(seen) == 1:
            value = '추가로 설명할 원문 코드의 동작입니다.'
        else:
            value = '완결된 추가 설명입니다' + '가' * (data['minimum_additional_characters'] - 13) + '.'
        return {'continuations': [value] * 3}
    result = finish_length(original, [(SimpleNamespace(id='source', content='원문 코드'), None, None)], '개념', generate)
    assert 360 <= len(' '.join(result)) <= 400
    assert len(seen) == 2 and seen[1]['actual_characters'] > seen[0]['actual_characters']
    assert result[0] == original[0] and result[2] == original[2]
    assert result[1].startswith(original[1])


def test_unusable_continuation_fails_with_actual_safe_reason():
    with pytest.raises(NarrationValidationError) as error:
        finish_length(['시작.', '설명.' * 100, '끝.'], [], '개념', lambda *_: {'continuations': ['.' * 25] * 3})
    issue = error.value.validation_error['issues'][0]
    assert issue['code'] == 'SHORTS_NARRATION_LENGTH' and issue['actual_characters'] == 307


def test_overlong_source_correction_rewrites_whole_body_without_truncation():
    original = ['도입입니다.', '설명입니다.' * 80, '마무리입니다.']
    authored = '원문에 있는 완결된 설명입니다.' + '가' * 340 + '.'
    result = finish_length(original, [], '개념', lambda *_: {'bodies': [authored] * 3})
    assert 360 <= len(' '.join(result)) <= 400
    assert result == [original[0], authored, original[2]]


def draft():
    return LessonDraft.model_validate({'schema_version':'lerny.lesson-draft.v1', 'request_id':'job',
        'source_snapshot_id':'snapshot', 'generation_status':'draft', 'reason':'',
        'lesson':{'title':'개념', 'language':'ko-KR','narration':['원래 도입입니다.', '검증된 본론입니다.', '원래 마무리입니다.'],
            'key_facts':['검증된 사실입니다.'], 'target_duration_seconds':50},
        'citations':[{'target':'/lesson/narration/0','source_id':'source','quote':'공개 원문입니다.'}]})


def test_evidence_repair_preserves_supported_units_and_input():
    original = draft()
    result = repair_evidence(original, [{'target':'/lesson/narration/0'}], [{'source_id':'source','text':'공개 원문입니다.'}],
        lambda *_: {'replacements':[{'target':'/lesson/narration/0','text':'원문의 구체적 사실입니다.'}]})
    assert result.lesson.narration[0] != original.lesson.narration[0]
    assert result.lesson.narration[1:] == original.lesson.narration[1:]
    assert result.lesson.key_facts == original.lesson.key_facts
    # A repaired paragraph does not gain a supported verdict by being rewritten.
    issues = []
    assert review_narration([{'target':'/lesson/narration/0','text':result.lesson.narration[0]}],
        [{'source_id':'source','text':'공개 원문입니다.'}],
        lambda *_:{'units':[{'target':'/lesson/narration/0','verdict':'unsupported','evidence_ids':[]}]}, issues=issues) is None
    assert issues[0]['target'] == '/lesson/narration/0'


def test_evidence_repair_cannot_change_accepted_target():
    with pytest.raises(NarrationValidationError):
        repair_evidence(draft(), [{'target':'/lesson/narration/0'}], [],
            lambda *_: {'replacements':[{'target':'/lesson/narration/1','text':'원문 밖의 변경입니다.'}]})


def test_professor_retry_retains_original_narration_cache(fixture_weekly):
    from lerny.models import Job
    client, session, _ = fixture_weekly
    generation = start(client)
    job = Job(course_id='course',owner_id='teacher',kind='narration_lesson',status='failed',
        error_code='SCRIPT_VALIDATION_FAILED',payload={'generation_id':generation,'_ai_generation':7,'video_id':'not-yet-created'})
    session.add(job);session.commit()
    response = client.post(f'/api/v1/courses/course/content-generations/{generation}/retry')
    assert response.status_code == 200
    session.refresh(job)
    assert job.status == 'queued' and job.payload['_ai_generation'] == 7
    assert job.payload['_narration_repair_round'] == 1
    assert job.payload['_gemini_retry_round'] == 1
