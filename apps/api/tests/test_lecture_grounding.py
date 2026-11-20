import json

import pytest
import test_lecture_specs as intake_tests
from lerny import worker
from lerny.inference import ModelPending
from lerny.lecture_contract import LectureSpec
from lerny.lecture_grounding import INSTRUCTIONS, assess, review_units
from lerny.models import Chunk, Job, Material
from lerny.security import COOKIE

api = intake_tests.api
spec = intake_tests.spec
prepare = intake_tests.prepare

SOURCES = [
    {
        "source_id": "src_stack_01",
        "text": "스택은 후입선출 자료구조다. 마지막에 삽입한 원소를 먼저 제거한다.",
    },
    {
        "source_id": "src_stack_02",
        "text": "push는 스택에 원소를 추가하고, pop은 맨 위의 원소를 제거한다.",
    },
]


def simulated_reviewer(prompt, schema):
    """Contract double, NOT a test of any real model's semantic accuracy."""
    payload = json.loads(prompt[len(INSTRUCTIONS) :])
    evidence = {s["source_id"]: s["text"] for s in payload["evidence"]}
    items = []
    for unit in payload["units"]:
        key = unit["source_refs"][0] if unit["source_refs"] else next(iter(evidence))
        items.append(
            {
                "unit_id": unit["unit_id"],
                "verdict": "supported",
                "all_claims_checked": True,
                "explanation": "모의 검증 결과",
                "evidence": [{"source_id": key, "quote": evidence[key]}],
            }
        )
    return {"items": items}


def test_all_texts_and_numeric_states_are_reviewed(spec):
    parsed = LectureSpec.model_validate(spec)
    sent = []

    def reviewer(prompt, schema):
        sent.extend(json.loads(prompt[len(INSTRUCTIONS) :])["units"])
        return simulated_reviewer(prompt, schema)

    result = assess(parsed, SOURCES, reviewer)
    assert len(result["items"]) == len(review_units(parsed)) == 13
    assert any(u["kind"] == "connective" for u in sent)
    assert any(u["unit_id"].endswith("key_points.0") for u in sent)
    assert result["semantic_grounding"] == "model_supported"
    assert result["human_review_required"] and not result["render_allowed"]
    states = result["computed_stack_states"]["scene_02"]
    assert states[-2]["during"] == [10, 20, 30]
    assert states[-1]["during"] == [10, 20]


@pytest.mark.parametrize(
    "verdict", ["contradicted", "insufficient_evidence", "uncertain", "conflicting_evidence"]
)
def test_negative_or_mixed_claim_holds_whole_lecture(spec, verdict):
    spec["scenes"][2]["utterances"][0]["text"] = (
        "스택은 후입선출이다. 하지만 처음 넣은 값을 먼저 꺼낸다."
    )

    def reviewer(prompt, schema):
        output = simulated_reviewer(prompt, schema)
        for item in output["items"]:
            if item["unit_id"] == "scenes.2.utterances.0":
                item["verdict"] = verdict
                if verdict == "conflicting_evidence":
                    item["evidence"] = [
                        {"source_id": s["source_id"], "quote": s["text"]} for s in SOURCES
                    ]
        return output

    result = assess(LectureSpec.model_validate(spec), SOURCES, reviewer)
    assert result["semantic_grounding"] == verdict
    assert result["status"] == "held" and not result["publication_allowed"]


@pytest.mark.parametrize(
    "mutation,code",
    [
        (lambda o: o["items"].pop(), "INCOMPLETE_GROUNDING_OUTPUT"),
        (
            lambda o: o["items"][1].update(unit_id=o["items"][0]["unit_id"]),
            "INCOMPLETE_GROUNDING_OUTPUT",
        ),
        (
            lambda o: o["items"][0]["evidence"][0].update(quote="원문에 존재하지 않는 가짜 인용"),
            "INVALID_GROUNDING_CITATION",
        ),
        (
            lambda o: o["items"][0]["evidence"][0].update(source_id="private"),
            "INVALID_GROUNDING_CITATION",
        ),
        (lambda o: o["items"][0].update(evidence=[]), "MISSING_GROUNDING_CITATION"),
        (
            lambda o: o["items"][0].update(verdict="conflicting_evidence"),
            "MISSING_CONFLICT_EVIDENCE",
        ),
        (lambda o: o["items"][0].update(verdict="approved"), "INVALID_GROUNDING_OUTPUT"),
    ],
)
def test_invalid_reviewer_output_fails_closed(spec, mutation, code):
    def reviewer(prompt, schema):
        result = simulated_reviewer(prompt, schema)
        mutation(result)
        return result

    with pytest.raises(ValueError, match=code):
        assess(LectureSpec.model_validate(spec), SOURCES, reviewer)


def test_unchecked_claims_cannot_pass(spec):
    def reviewer(prompt, schema):
        result = simulated_reviewer(prompt, schema)
        result["items"][0]["all_claims_checked"] = False
        return result

    assert (
        assess(LectureSpec.model_validate(spec), SOURCES, reviewer)["semantic_grounding"]
        == "uncertain"
    )


def test_source_based_cannot_be_dismissed_as_nonfactual(spec):
    def reviewer(prompt, schema):
        result = simulated_reviewer(prompt, schema)
        for item in result["items"]:
            if item["unit_id"] == "scenes.2.utterances.0":
                item["verdict"] = "non_factual"
        return result

    with pytest.raises(ValueError, match="INVALID_NONFACTUAL_VERDICT"):
        assess(LectureSpec.model_validate(spec), SOURCES, reviewer)


def test_supported_claim_cannot_switch_to_an_undeclared_source(spec):
    def reviewer(prompt, schema):
        result = simulated_reviewer(prompt, schema)
        for item in result["items"]:
            if item["unit_id"] == "scenes.1.utterances.0":
                item["evidence"] = [
                    {"source_id": SOURCES[0]["source_id"], "quote": SOURCES[0]["text"]}
                ]
        return result

    with pytest.raises(ValueError, match="UNDECLARED_GROUNDING_CITATION"):
        assess(LectureSpec.model_validate(spec), SOURCES, reviewer)


def test_context_limit_never_silently_truncates_evidence(spec):
    with pytest.raises(ValueError, match="GROUNDING_CONTEXT_TOO_LARGE"):
        assess(
            LectureSpec.model_validate(spec),
            [{"source_id": "x", "text": "a" * 8001}],
            lambda *args: pytest.fail("must not call model"),
        )


def seed_request(api, spec):
    client, session, _ = api
    for source in SOURCES:
        session.get(Chunk, source["source_id"]).content = source["text"]
    session.commit()
    base = prepare(api, spec)
    assert client.post(base + "/validate", json=spec).status_code == 200
    response = client.post(base + "/grounding")
    assert response.status_code == 202, response.text
    return base, response.json()


def test_queue_worker_poll_and_duplicate_request(api, spec, monkeypatch):
    client, session, _ = api
    base, queued = seed_request(api, spec)
    assert client.post(base + "/grounding").json()["job_id"] == queued["job_id"]
    monkeypatch.setattr(worker, "engine", lambda: session.get_bind())
    monkeypatch.setattr(worker, "model_json", simulated_reviewer)
    assert worker.run_once(queued["job_id"])
    response = client.get(queued["poll_url"])
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "succeeded"
    assert response.json()["result"]["semantic_grounding"] == "model_supported"
    assert not response.json()["result"]["render_allowed"]
    assert client.post(base + "/grounding").json()["job_id"] == queued["job_id"]
    assert client.get("/api/v1/jobs/" + queued["job_id"]).status_code == 404
    assert client.post("/api/v1/jobs/" + queued["job_id"] + "/retry").status_code == 409


@pytest.mark.parametrize("change", ["private_source", "edited_spec"])
def test_change_during_inference_discards_result(api, spec, monkeypatch, change):
    client, session, _ = api
    base, queued = seed_request(api, spec)
    changed = False

    def reviewer(prompt, schema):
        nonlocal changed
        if not changed:
            if change == "private_source":
                session.get(Material, "material").visibility = "private"
                session.commit()
            else:
                spec["title"] = "수정한 제목"
                assert client.post(base + "/validate", json=spec).status_code == 200
            changed = True
        return simulated_reviewer(prompt, schema)

    monkeypatch.setattr(worker, "engine", lambda: session.get_bind())
    monkeypatch.setattr(worker, "model_json", reviewer)
    worker.run_once(queued["job_id"])
    job = session.get(Job, queued["job_id"], populate_existing=True)
    assert job.status == "failed" and job.result is None
    response = client.get(queued["poll_url"])
    assert response.status_code == 409 and response.json()["result"] is None


@pytest.mark.parametrize("failure", [TimeoutError, ValueError, ModelPending])
def test_model_failure_or_pending_never_passes(api, spec, monkeypatch, failure):
    client, session, _ = api
    _, queued = seed_request(api, spec)

    def reviewer(*args):
        raise failure()

    monkeypatch.setattr(worker, "engine", lambda: session.get_bind())
    monkeypatch.setattr(worker, "model_json", reviewer)
    worker.run_once(queued["job_id"])
    response = client.get(queued["poll_url"])
    assert response.status_code == 200
    assert response.json()["result"] is None
    assert response.json()["status"] in {"failed", "queued", "waiting_ai"}


def test_structural_failure_never_queues_grounding(api, spec):
    client, _, _ = api
    base = prepare(api, spec)
    assert client.post(base + "/grounding").status_code == 409
    spec["scenes"][1]["visual_events"][3]["expected_value"] = 99
    assert client.post(base + "/validate", json=spec).status_code == 422
    assert client.post(base + "/grounding").status_code == 409


@pytest.mark.parametrize("actor", ["student", "outsider", "anonymous", "bad_csrf"])
def test_grounding_permission_boundaries(api, spec, actor):
    client, _, tokens = api
    base, queued = seed_request(api, spec)
    if actor == "anonymous":
        client.cookies.clear()
    elif actor == "bad_csrf":
        client.headers["X-CSRF-Token"] = "bad"
    else:
        client.cookies.set(COOKIE, tokens[actor][0])
        client.headers["X-CSRF-Token"] = tokens[actor][1]
    assert client.post(base + "/grounding").status_code in {401, 403, 404}
    if actor != "bad_csrf":
        assert client.get(queued["poll_url"]).status_code in {401, 403, 404}


def test_private_source_before_execution_never_reaches_model(api, spec, monkeypatch):
    client, session, _ = api
    _, queued = seed_request(api, spec)
    session.get(Material, "material").visibility = "private"
    session.commit()
    monkeypatch.setattr(worker, "engine", lambda: session.get_bind())
    monkeypatch.setattr(worker, "model_json", lambda *args: pytest.fail("must not send source"))
    worker.run_once(queued["job_id"])
    assert client.get(queued["poll_url"]).status_code == 409
    assert session.get(Job, queued["job_id"], populate_existing=True).status == "failed"


def test_completed_review_disappears_after_edit_and_new_request_has_new_job(api, spec, monkeypatch):
    client, session, _ = api
    base, queued = seed_request(api, spec)
    monkeypatch.setattr(worker, "engine", lambda: session.get_bind())
    monkeypatch.setattr(worker, "model_json", simulated_reviewer)
    worker.run_once(queued["job_id"])
    assert client.get(queued["poll_url"]).json()["result"] is not None
    spec["title"] = "새 제목"
    assert client.post(base + "/validate", json=spec).status_code == 200
    response = client.get(queued["poll_url"])
    assert response.status_code == 409 and response.json()["result"] is None
    assert client.post(base + "/grounding").json()["job_id"] != queued["job_id"]


def test_failed_review_can_be_explicitly_retried(api, spec, monkeypatch):
    client, session, _ = api
    base, queued = seed_request(api, spec)
    monkeypatch.setattr(worker, "engine", lambda: session.get_bind())
    monkeypatch.setattr(worker, "model_json", lambda *args: {})
    worker.run_once(queued["job_id"])
    assert client.get(queued["poll_url"]).json()["status"] == "failed"
    retried = client.post(base + "/grounding").json()
    assert retried["job_id"] != queued["job_id"] and retried["status"] == "queued"
