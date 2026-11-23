"""Synthetic conversations through the real retrieval and answer pipeline."""

import json
from datetime import timedelta
from types import SimpleNamespace

import pytest
from lerny import rag_answers, retrieval, worker
from lerny.auth import COOKIE
from lerny.chat_topics import mentions_topic, previous_topic, topic_terms
from lerny.models import ChatMessage, Chunk, Enrollment, Job, Material, Section, now
from publication_fixtures import published
from test_gemini_integration import VECTOR, configured, index_all, integration  # noqa: F401
from test_lecture_specs import api  # noqa: F401


@pytest.fixture
def chat(integration, monkeypatch):
    client, db, tokens = integration
    db.get(Material, "material").kind = "lecture"
    first = db.get(Chunk, "src_stack_01")
    first.content = "upper()는 문자를 바꿉니다. 예시: 'mint'.upper() → 'MINT'."
    second = db.get(Chunk, "src_stack_02")
    second.content = "출력 예시: print('lantern')"
    published(db, "course")
    db.add(Section(id="section", course_id="course", title="synthetic"))
    db.flush()
    db.add(Enrollment(student_id="student", section_id="section", course_id="course", status="active"))
    db.commit()
    index_all(db)
    queries, prompts = [], []

    def embed(operation, payload):
        assert operation == "embed" and payload["task"] == "query"
        queries.extend(payload["input"])
        return {"embeddings": [VECTOR]}

    def model(prompt, schema):
        prompts.append(prompt)
        evidence = json.loads(prompt.rsplit("\n", 1)[1])["sources"][0]
        return {"answerable": True, "reason": "", "claims": [
            {"source_id": evidence["source_id"], "quote": evidence["text"], "text": evidence["text"]}]}

    monkeypatch.setattr(retrieval, "perform", embed)
    monkeypatch.setattr(worker, "model_json", model)

    def ask(question, context=None):
        message = ChatMessage(student_id="student", section_id="section", thread_id="sample",
                              question=question, access_epoch=1, learning_context=context or {})
        db.add(message)
        db.flush()
        job = Job(owner_id="student", course_id="course", kind="chat", payload={"message_id": message.id})
        db.add(job)
        db.flush()
        answer = rag_answers.answer_job(db, job)
        db.commit()
        return answer

    return SimpleNamespace(ask=ask, db=db, client=client, tokens=tokens, first=first, second=second,
                           queries=queries, prompts=prompts)


@pytest.mark.parametrize("question", ["다시 설명해 주세요", "왜 그런가요?", "더 쉽게", "예시로 설명해줘"])
def test_context_only_requests(question):
    assert not topic_terms(question)


def test_concept_terms_and_identifiers_are_new_topics():
    assert topic_terms("len은 뭐야?") == ["len"]
    assert topic_terms("연결 리스트를 설명해줘") == ["연결", "리스트"]
    assert mentions_topic("A queue stores pending items.", topic_terms("큐는 뭐야?"))
    assert mentions_topic("Call upper() on the word.", topic_terms("대문자 변환"))
    assert not mentions_topic("The supper menu", ["upper"])


def test_legacy_generic_answer_cannot_introduce_an_unrelated_source():
    def turn(question, chunk):
        return SimpleNamespace(question=question, learning_context={}, answer={"answer_kind":"grounded",
            "validation":"citation_and_model_review", "citations":[{"chunk_id":chunk}]})
    terms, ids = previous_topic([turn("더 쉽게", "unrelated"), turn("len은 뭐야?", "length")], {})
    assert terms == ["len"] and ids == ["length"]


def test_single_search_per_turn_and_new_topic(chat):
    assert chat.ask("upper()의 뜻은?")["citations"][0]["chunk_id"] == chat.first.id
    result = chat.ask("예시를 보여주세요")
    assert result["validation"] == "citation_checked"
    assert {c["chunk_id"] for c in result["citations"]} == {chat.first.id}
    assert chat.queries == ["upper()의 뜻은?", "upper 예시를 보여주세요"]
    assert chat.second.id not in {s["source_id"] for s in json.loads(chat.prompts[-1].rsplit("\n", 1)[1])["sources"]}
    assert chat.ask("print()의 뜻은?")["citations"][0]["chunk_id"] == chat.second.id
    assert chat.queries[-1] == "print()의 뜻은?"
    assert len(chat.prompts) == len(chat.queries) == 3


def test_no_example_in_topic_sources(chat):
    chat.first.content = "upper()는 문자를 바꾸는 메서드입니다. 이 자료에는 예시가 없습니다."
    index_all(chat.db)
    chat.ask("upper()의 뜻은?")
    answer = chat.ask("예시를 보여주세요")
    assert answer["answer_kind"] == "insufficient" and not answer["citations"]
    assert len(chat.queries) == 2 and len(chat.prompts) == 1


def test_alias_and_final_citation_check(chat, monkeypatch):
    chat.ask("upper()의 뜻은?")
    chat.second.content = "대문자 변환 예시: mug → MUG. 별도의 예시: 종을 친다."
    index_all(chat.db)

    def cite(quote):
        return lambda *_: {"answerable": True, "reason": "", "claims": [
            {"source_id": chat.second.id, "quote": quote, "text": quote}]}

    monkeypatch.setattr(worker, "model_json", cite("대문자 변환 예시: mug → MUG."))
    assert chat.ask("예시를 보여주세요")["answer_kind"] == "grounded"
    # Start a new named turn: only the first chunk is now the inherited citation.
    monkeypatch.setattr(worker, "model_json", lambda *_: {"answerable": True, "reason": "", "claims": [
        {"source_id": chat.first.id, "quote": chat.first.content, "text": chat.first.content}]})
    chat.ask("upper()의 뜻은?")
    monkeypatch.setattr(worker, "model_json", cite("별도의 예시: 종을 친다."))
    assert chat.ask("예시를 보여주세요")["answer_kind"] == "insufficient"


def test_prior_citation_outside_top_results_is_reauthorized(chat, monkeypatch):
    chat.first.content = "예시: 'mug' → 'MUG'."
    index_all(chat.db)
    # The previous turn used this source without spelling out the identifier.
    prior = ChatMessage(student_id="student", section_id="section", thread_id="sample",
        question="upper()의 뜻은?", access_epoch=1, created_at=now() - timedelta(minutes=1),
        answer={"answer_kind":"grounded", "answer":"합성 답변", "validation":"citation_and_model_review",
                "citations":[{"chunk_id":chat.first.id}]})
    chat.db.add(prior)
    chat.db.commit()
    original = rag_answers.search_public
    monkeypatch.setattr(rag_answers, "search_public", lambda *a, **kw: [
        row for row in original(*a, **kw) if row[0].id == chat.second.id])
    answer = chat.ask("다시 설명해 주세요")
    assert [c["chunk_id"] for c in answer["citations"]] == [chat.first.id], (answer, chat.queries)
    chat.client.cookies.set(COOKIE, chat.tokens["student"][0])
    response = chat.client.get("/api/v1/sections/section/chat/history", params={"thread_id":"sample"})
    assert response.status_code == 200
    assert next(m for m in response.json()["items"] if m["id"] == prior.id)["answer"]["validation"] == "citation_and_model_review"
    chat.db.get(Material, "material").visibility = "private"
    assert chat.ask("다시 설명해 주세요")["answer_kind"] == "insufficient"


def test_first_ambiguous_turn_and_practice_context(chat):
    assert chat.ask("더 쉽게")["answer_kind"] == "insufficient"
    assert not chat.queries and not chat.prompts
    context = {"mode":"practice", "practice_title":"출력", "exercise_id":"synthetic-exercise",
               "student_context":"합성 풀이 상태"}
    assert chat.ask("다시 설명해 주세요", context)["answer_kind"] == "grounded"
    assert chat.queries == ["출력 다시 설명해 주세요"]
    assert context["student_context"] in chat.prompts[-1]
