"""Provider-independent lecture contract. Validation never calls a model or renderer."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

Identifier = Annotated[str, Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")]
Text = Annotated[str, Field(min_length=1, max_length=1000, pattern=r"\S")]
Refs = Annotated[list[Identifier], Field(max_length=30)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)


class Utterance(StrictModel):
    utterance_id: Identifier
    text: Text
    content_origin: Literal["source_based", "generated_example", "connective"]
    source_refs: Refs


class Card(StrictModel):
    type: Literal["title_card", "key_points"]
    heading: Text
    key_points: Annotated[list[Text], Field(max_length=8)]


class Element(StrictModel):
    element_id: Identifier
    type: Literal["number_block"]
    value: Annotated[int, Field(ge=-1000000, le=1000000)]


class StackState(StrictModel):
    items_bottom_to_top: Annotated[list[Identifier], Field(max_length=20)]


class Stack(StrictModel):
    type: Literal["stack_diagram"]
    heading: Text
    element_id: Identifier
    initial_state: StackState
    elements: Annotated[list[Element], Field(min_length=1, max_length=20)]


class Trigger(StrictModel):
    utterance_id: Identifier
    boundary: Literal["start", "end"]


class Event(StrictModel):
    event_id: Identifier
    trigger: Trigger
    action: Literal["push", "pop"]
    container_id: Identifier
    element_id: Identifier
    expected_value: int | None = None


class Gesture(StrictModel):
    cue_id: Identifier
    utterance_id: Identifier
    action: Literal["point_toward"]
    target_element_id: Identifier
    intent: Text
    intensity: Literal["subtle"]


class Provenance(StrictModel):
    type: Literal["source_example", "generated_example"]
    description: Text
    source_refs: Annotated[list[Identifier], Field(min_length=1, max_length=30)]


class Scene(StrictModel):
    scene_id: Identifier
    role: Literal["introduction", "explanation", "worked_example", "summary"]
    utterances: Annotated[list[Utterance], Field(min_length=1, max_length=30)]
    visual: Annotated[Card | Stack, Field(discriminator="type")]
    visual_events: Annotated[list[Event], Field(max_length=50)]
    gesture_cues: Annotated[list[Gesture], Field(max_length=20)]
    example_provenance: Provenance | None = None


class LearningLinks(StrictModel):
    related_concept_ids: Annotated[list[Identifier], Field(min_length=1, max_length=20)]
    practice_objective: Text


class Issue(StrictModel):
    code: Identifier
    message: Text
    source_refs: Refs
    affected_utterance_ids: Refs


class LectureSpec(StrictModel):
    schema_version: Literal["1.0"]
    request_id: Identifier
    concept_id: Identifier
    concept_revision: Annotated[int, Field(ge=1)]
    source_snapshot_id: Identifier
    generation_status: Literal["draft", "insufficient_evidence", "conflicting_evidence"]
    title: Text
    language: Literal["ko-KR"]
    learning_objective: Text
    target_duration_seconds: Annotated[int, Field(ge=15, le=90)]
    scenes: Annotated[list[Scene], Field(max_length=8)]
    learning_links: LearningLinks
    issues: Annotated[list[Issue], Field(max_length=30)]


def report(errors, status="needs_content_review"):
    return {
        "status": "rejected" if errors else status,
        "structure_valid": not errors,
        "errors": errors,
        "semantic_grounding": "not_checked",
        "render_allowed": False,
        "publication_allowed": False,
        "question_response_mode": "text_only",
    }


def validate_spec(data, context):
    """Check an untrusted spec against a server-owned immutable request snapshot."""
    try:
        spec = LectureSpec.model_validate(data)
    except ValidationError as exc:
        # Do not return input values, custom validator context, or unknown field names.
        errors = [
            {
                "code": "SCHEMA_INVALID",
                "path": ".".join(
                    str(part)
                    for part in (
                        error["loc"][:-1] if error["type"] == "extra_forbidden" else error["loc"]
                    )
                ),
                "reason": error["type"],
            }
            for error in exc.errors(include_input=False)[:50]
        ]
        return None, report(errors)
    errors = []

    def check(condition, code, path):
        if not condition:
            errors.append({"code": code, "path": path})

    def unique(values, path):
        check(len(values) == len(set(values)), "DUPLICATE_ID", path)

    def refs(values, path):
        unique(values, path)
        check(set(values) <= set(context["allowed_source_ids"]), "UNKNOWN_SOURCE", path)

    for field in (
        "request_id",
        "concept_id",
        "concept_revision",
        "source_snapshot_id",
        "language",
        "target_duration_seconds",
        "learning_objective",
    ):
        check(getattr(spec, field) == context[field], "REQUEST_MISMATCH", field)
    links = spec.learning_links.related_concept_ids
    unique(links, "learning_links.related_concept_ids")
    check(set(links) <= set(context["allowed_concept_ids"]), "UNKNOWN_CONCEPT", "learning_links")
    if spec.generation_status != "draft":
        check(not spec.scenes and bool(spec.issues), "INVALID_FAILURE_STATE", "generation_status")
    else:
        check(bool(spec.scenes), "EMPTY_DRAFT", "scenes")
    unique([s.scene_id for s in spec.scenes], "scenes")
    all_utterances = [u.utterance_id for s in spec.scenes for u in s.utterances]
    unique(all_utterances, "utterances")
    check(
        sum(len(u.text) for s in spec.scenes for u in s.utterances) <= 2000,
        "SCRIPT_TOO_LONG",
        "utterances",
    )
    for index, scene in enumerate(spec.scenes):
        path = f"scenes.{index}"
        utterances = {u.utterance_id for u in scene.utterances}
        for ui, utterance in enumerate(scene.utterances):
            upath = f"{path}.utterances.{ui}"
            refs(utterance.source_refs, upath + ".source_refs")
            check(
                utterance.content_origin == "connective" or bool(utterance.source_refs),
                "MISSING_EVIDENCE",
                upath,
            )
            if utterance.content_origin == "generated_example":
                check(context["allow_generated_examples"], "EXAMPLE_NOT_ALLOWED", upath)
                check(
                    scene.example_provenance is not None
                    and scene.example_provenance.type == "generated_example",
                    "MISSING_EXAMPLE_PROVENANCE",
                    path,
                )
        if scene.example_provenance:
            refs(scene.example_provenance.source_refs, path + ".example_provenance")
            if scene.example_provenance.type == "generated_example":
                check(context["allow_generated_examples"], "EXAMPLE_NOT_ALLOWED", path)
        unique([e.event_id for e in scene.visual_events], path + ".visual_events")
        unique([g.cue_id for g in scene.gesture_cues], path + ".gesture_cues")
        for event in scene.visual_events:
            check(event.trigger.utterance_id in utterances, "UNKNOWN_UTTERANCE", path)
        for gesture in scene.gesture_cues:
            check(gesture.utterance_id in utterances, "UNKNOWN_UTTERANCE", path)
        if not isinstance(scene.visual, Stack):
            check(not scene.visual_events and not scene.gesture_cues, "VISUAL_HAS_NO_TARGETS", path)
            continue
        visual = scene.visual
        elements = {e.element_id: e.value for e in visual.elements}
        unique([visual.element_id] + [e.element_id for e in visual.elements], path + ".visual")
        stack = list(visual.initial_state.items_bottom_to_top)
        unique(stack, path + ".visual.initial_state")
        check(set(stack) <= elements.keys(), "UNKNOWN_ELEMENT", path + ".visual.initial_state")
        # Execute in utterance order, then start/end boundary; array order breaks ties.
        # A pointing cue is active throughout its utterance, between these boundaries.
        for utterance in scene.utterances:
            for boundary in ("start", "end"):
                for event in scene.visual_events:
                    if (event.trigger.utterance_id, event.trigger.boundary) != (
                        utterance.utterance_id,
                        boundary,
                    ):
                        continue
                    valid_target = (
                        event.container_id == visual.element_id and event.element_id in elements
                    )
                    check(valid_target, "UNKNOWN_EVENT_TARGET", path)
                    if not valid_target:
                        continue
                    if event.action == "push":
                        check(event.expected_value is None, "UNEXPECTED_PUSH_VALUE", path)
                        check(event.element_id not in stack, "DUPLICATE_PUSH", path)
                        if event.element_id not in stack:
                            stack.append(event.element_id)
                    else:
                        valid_pop = bool(stack) and stack[-1] == event.element_id
                        check(valid_pop, "INVALID_POP", path)
                        check(
                            event.expected_value == elements[event.element_id],
                            "POP_VALUE_MISMATCH",
                            path,
                        )
                        if valid_pop:
                            stack.pop()
                if boundary == "start":
                    for gesture in scene.gesture_cues:
                        if gesture.utterance_id == utterance.utterance_id:
                            check(
                                gesture.target_element_id in stack
                                or gesture.target_element_id == visual.element_id,
                                "GESTURE_TARGET_NOT_VISIBLE",
                                path,
                            )
    for issue in spec.issues:
        refs(issue.source_refs, "issues.source_refs")
        check(
            set(issue.affected_utterance_ids) <= set(all_utterances),
            "UNKNOWN_UTTERANCE",
            "issues.affected_utterance_ids",
        )
    status = "held" if spec.generation_status != "draft" or spec.issues else "needs_content_review"
    return spec, report(errors[:50], status)
