"""Pure offline Video Agent compilation. No credentials, HTTP client or submission code."""

from typing import Annotated

from pydantic import Field

from lerny.heygen_lecture_profile import (
    LERNY_LOOK_ID,
    LERNY_VOICE_ID,
    MAX_PROMPT_CHARACTERS,
    PromptTooLong,
    production_instructions,
)
from lerny.lecture_contract import StrictModel, validate_spec
from lerny.lecture_presentation import presentation_profile
from lerny.security import digest

DOC_URL = "https://developers.heygen.com/reference/create-video-agent-session"
ENDPOINT = "https://api.heygen.com/v3/video-agents"
ProviderId = Annotated[
    str, Field(min_length=1, max_length=255, pattern=r"^[A-Za-z0-9_.:-]+$")
]


class PreviewOptions(StrictModel):
    # Staff choices, never model-generated IDs or credentials.
    avatar_id: ProviderId | None = LERNY_LOOK_ID
    voice_id: ProviderId | None = LERNY_VOICE_ID
    style_id: ProviderId | None = None


def build_prompt(spec):
    lines = production_instructions(spec.target_duration_seconds) + [
        f"강의 제목: {spec.title}",
        "[대본과 기존 명세의 의미 정보]",
        "장면 번호는 설명 순서이며 카메라 전환 지시가 아니다. 화면 지시를 낭독하지 않는다.",
        "아래 보드는 오른쪽 자료 영역을 뜻한다. 자료의 디자인과 전환은 HeyGen AI가 결정한다.",
        "start/end는 해당 발화 시작/종료의 의미 기준이다. 절대 초 단위 시간표가 아니다.",
    ]
    previous_state = None
    for scene in spec.scenes:
        visual = scene.visual
        lines += [
            f"\n장면 {scene.scene_id} ({scene.role})",
            f"보드 제목: {visual.heading}",
        ]
        is_stack = visual.type == "stack_diagram"
        values, stack = {}, []
        if is_stack:
            values = {e.element_id: e.value for e in visual.elements}
            stack = list(visual.initial_state.items_bottom_to_top)

        def state_text(values=values, stack=stack):
            items = [values[key] for key in stack]
            return f"아래→위 {items}, TOP={items[-1] if items else '없음'}"

        if is_stack:
            lines.append(f"보드 스택 {visual.element_id} 초기 상태: {state_text()}")
        else:
            lines += [f"보드 핵심 문구: {point}" for point in visual.key_points]
            if previous_state is not None:
                lines.append(
                    f"직전 스택을 지우지 않고 핵심 문구 옆에 유지: {previous_state}"
                )
            elif scene.role == "introduction":
                upcoming = next(
                    (s.visual for s in spec.scenes if s.visual.type == "stack_diagram"),
                    None,
                )
                if upcoming is not None:
                    lookup = {e.element_id: e.value for e in upcoming.elements}
                    initial = [
                        lookup[key]
                        for key in upcoming.initial_state.items_bottom_to_top
                    ]
                    lines.append(
                        f"도입 보드에 이후 예시의 스택 초기 상태를 표시: 아래→위 {initial}"
                    )
        for utterance in scene.utterances:
            lines += [
                f"발화 {utterance.utterance_id} 원문 시작",
                utterance.text,
                "발화 원문 끝",
            ]
            for boundary in ("start", "end"):
                for event in scene.visual_events:
                    if (event.trigger.utterance_id, event.trigger.boundary) != (
                        utterance.utterance_id,
                        boundary,
                    ):
                        continue
                    if event.action == "push":
                        stack.append(event.element_id)
                    else:
                        stack.pop()  # validate_spec checked the LIFO transition.
                    lines.append(
                        f"화면 {boundary}: {event.container_id}에 {event.action} "
                        f"{event.element_id}(값 {values[event.element_id]}). 결과: {state_text()}"
                    )
                if boundary == "start":
                    for gesture in scene.gesture_cues:
                        if gesture.utterance_id == utterance.utterance_id:
                            target = gesture.target_element_id
                            label = (
                                f"블록 {values[target]} ({target})"
                                if target in values
                                else target
                            )
                            lines.append(
                                f"이 발화의 자료 강조 대상: {label} 방향. 직접 가리키는 동작은 강제하지 않는다."
                            )
            if is_stack:
                lines.append(f"발화 종료 상태 검증: {state_text()}")
        if is_stack:
            previous_state = state_text()
    lines += [
        "[마무리]",
        "강사는 왼쪽에 앉은 채 마무리하고 오른쪽 자료에 핵심 내용을 정리한다.",
    ]
    prompt = "\n".join(lines)
    if len(prompt) > MAX_PROMPT_CHARACTERS:
        # Never truncate or split, which could lose narration or state dependencies.
        raise PromptTooLong("VIDEO_AGENT_PROMPT_TOO_LONG")
    return prompt


def compile_preview(data, context, options: PreviewOptions):
    spec, validation = validate_spec(data, context)
    if (
        not validation["structure_valid"]
        or validation["status"] != "needs_content_review"
    ):
        raise ValueError("LECTURE_NOT_PREVIEWABLE")
    prompt = build_prompt(spec)
    scenes = []
    for scene in spec.scenes:
        script = "\n".join(u.text for u in scene.utterances)
        segments, offset = [], 0
        for utterance in scene.utterances:
            segments.append(
                {
                    "utterance_id": utterance.utterance_id,
                    "character_start": offset,
                    "character_end": offset + len(utterance.text),
                    "text": utterance.text,
                }
            )
            offset += len(utterance.text) + 1
        scenes.append(
            {
                "scene_id": scene.scene_id,
                "request_index": 0,
                "script": script,
                "script_sha256": digest(script),
                "utterances": segments,
                "visual": scene.visual.model_dump(),
                "visual_events": [
                    e.model_dump(exclude_none=True) for e in scene.visual_events
                ],
                "gesture_cues": [g.model_dump() for g in scene.gesture_cues],
            }
        )
    body = {
        "mode": "generate",
        "orientation": "landscape",
        "visibility": "private",
        "avatar_id": options.avatar_id or "<SELECTED_AVATAR_LOOK_ID>",
        "voice_id": options.voice_id or "<SELECTED_KOREAN_VOICE_ID>",
        "prompt": prompt,
    }
    if options.style_id is not None:
        body["style_id"] = options.style_id
    unresolved = [
        name for name in ("avatar_id", "voice_id") if not getattr(options, name)
    ]
    profile = presentation_profile()
    return {
        "dry_run": True,
        "submitted": False,
        "submission_allowed": False,
        "render_allowed": False,
        "publication_allowed": False,
        "preview_kind": "request_template"
        if unresolved
        else "unverified_request_preview",
        "request_count": 1,
        "requests": [
            {
                "method": "POST",
                "url": ENDPOINT,
                "headers": {"Content-Type": "application/json"},
                "body": body,
            }
        ],
        "unresolved_fields": unresolved,
        "asset_verification": "not_checked",
        "authentication": "not_loaded_or_included",
        "api_reference": {"url": DOC_URL, "checked_on": "2026-10-29"},
        "prompt_characters": len(prompt),
        "composition_plan": {
            "status": "not_rendered",
            "aspect_ratio": profile["aspect_ratio"],
            "presentation_profile_id": profile["profile_id"],
            "layout": profile["layout"],
            "target_duration_seconds": spec.target_duration_seconds,
            "actual_duration_seconds": None,
            "timing_status": "agent_alignment_requested_not_verified",
            "character_offsets": "Unicode code points in each scene.script, zero-based [start, end); not timestamps or prompt offsets",
            "scene_order": [s.scene_id for s in spec.scenes],
            "scenes": scenes,
            "gesture_status": "natural_motion_requested_not_verified",
            "question_response_mode": "text_only",
        },
        "blockers": [
            "DRY_RUN_ONLY",
            "ASSETS_NOT_VERIFIED",
            "HUMAN_REVIEW_REQUIRED",
            "GENERATED_CONTENT_NOT_VERIFIED",
        ]
        + [f"MISSING_{field.upper()}" for field in unresolved],
    }
