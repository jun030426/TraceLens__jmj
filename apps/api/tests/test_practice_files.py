"""Synthetic files, fake model proposals and sandbox receipts; never run the submitted source."""

import hashlib
import json
from contextlib import nullcontext
from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from lerny import practice, practice_files, worker
from lerny.models import (
    Chunk,
    ContentGeneration,
    Course,
    Job,
    Material,
    MaterialVersion,
    PracticeExercise,
)
from lerny.practice_inputs import literal_inputs
import test_weekly_publication as publication
from test_weekly_publication import login, start

# Reuse the local DB, authenticated test client and fake provider fixtures.
api = publication.api
configured = publication.configured
integration = publication.integration
weekly = publication.weekly


def setup_file(weekly, tmp_path, monkeypatch, parts, response):
    client, db, _ = weekly
    code = "\r\n\r\n".join(parts) + "\r\n"
    path = tmp_path / "synthetic.py"
    path.write_bytes(code.encode())
    version = db.get(MaterialVersion, "version")
    version.filename, version.sha256 = path.name, hashlib.sha256(path.read_bytes()).hexdigest()
    db.execute(delete(Chunk).where(Chunk.version_id == version.id))
    citations = []
    for i, part in enumerate(parts):
        start_at = code.index(part)
        chunk_id = f"piece-{len(parts) - i}"
        citations.append({"chunk_id": chunk_id, "quote": part})
        db.add(
            Chunk(
                id=chunk_id,
                version_id=version.id,
                content=f"```python\n{part}\n```",
                locator={
                    "engine": {
                        "source_sha256": version.sha256,
                        "language": "python",
                        "eligible_for_chunking": True,
                        "location": {"char_start": start_at, "char_end": start_at + len(part)},
                        "code_text": part,
                    }
                },
            )
        )
    db.commit()
    gid = start(client)
    job = Job(
        owner_id="teacher",
        course_id="course",
        kind="practice_prepare",
        payload={"generation_id": gid, "source_version_id": version.id},
    )
    db.add(job)
    db.commit()
    monkeypatch.setattr(practice_files, "source_file", lambda v: nullcontext(path))

    def model(prompt, schema):
        entry = json.loads(prompt.rsplit("\n", 1)[1])
        assert entry["text"] == code and entry["source_id"] == "file:version"
        return {"title": "출력 계산", "prompt": "주어진 프로그램을 완성하고 출력값을 확인하세요.",
                "variants": [], "blank_lines": [2], **response}

    monkeypatch.setattr(worker, "model_json", model)
    runs = []

    def sandbox(language, src, **kw):
        runs.append(src)
        return str(len(runs))

    monkeypatch.setattr(practice, "output_of", sandbox)
    return job, code, citations, runs


def test_file_only_blank_submission_grade_snapshot_and_revocation(weekly, tmp_path, monkeypatch):
    client, db, tokens = weekly
    job, code, evidence, runs = setup_file(
        weekly,
        tmp_path,
        monkeypatch,
        ["def twice(value):\r\n    return value * 2", "print(twice(4))"],
        {},
    )
    result = practice.prepare(db, job)
    exercise = db.get(PracticeExercise, result["exercise_ids"][0])
    assert len(result["exercise_ids"]) == 1 and runs == [code]
    assert exercise.kind == "blank" and exercise.reference == code and exercise.sources == evidence
    assert exercise.tests == [{"expected": "1"}]
    assert not practice.prepare(db, job)["exercise_ids"] and len(runs) == 1
    g = db.get(ContentGeneration, job.payload["generation_id"])
    g.status = "published"
    db.commit()
    login(client, tokens, "student")
    base = "/api/v1/sections/section/practice"
    (problem,) = client.post(base + "/daily").json()["items"]
    assert set(problem["variants"]) == {"blank"} and problem["example_input"] == ""
    template = problem["template"]
    fill = "return value * 2"
    body = {
        "exercise_id": exercise.id,
        "source": template.replace("[[빈칸]]", fill),
        "editor": {"template": template, "fills": [fill]},
    }
    submitted = client.post(base + "/submit", json=body, headers={"Idempotency-Key": str(uuid4())})
    assert submitted.status_code == 202, submitted.text
    assert submitted.json()["submission_snapshot"]["kind"] == "blank"
    monkeypatch.setattr(practice, "output_of", lambda *args, **kwargs: "1")
    assert practice.grade(db, db.get(Job, submitted.json()["job_id"]))["correct"] is True
    assert (
        client.post(
            base + "/submit", json=body, headers={"Idempotency-Key": str(uuid4())}
        ).status_code
        == 409
    )
    assert practice.current_source(db, exercise)
    material = db.get(Material, "material")
    material.deleted = True
    db.commit()
    assert practice.current_source(db, exercise) is None
    material.deleted = False
    material.active_version_id = None
    db.commit()
    assert practice.current_source(db, exercise) is None


@pytest.mark.parametrize(
    "first,variants",
    [
        ('word = input("단어")', ["word = 'one'", "word = 'two'", "word = 'three'"]),
        ('items = ["a", "b"]', ["items = ['c']", "items = ['d','e']"]),
    ],
)
def test_changed_literals_use_sandbox_and_keep_original_reference(
    weekly, tmp_path, monkeypatch, first, variants
):
    _, db, _ = weekly
    name = first.split()[0]
    job, code, evidence, runs = setup_file(
        weekly,
        tmp_path,
        monkeypatch,
        [first + "\nresult = len(" + name + ")\nprint(result)"],
        {"variants": variants},
    )
    result = practice.prepare(db, job)
    rows = list(
        db.scalars(select(PracticeExercise).where(PracticeExercise.id.in_(result["exercise_ids"])))
    )
    assert {r.kind for r in rows} == {"blank", "full"} and len(runs) == 3
    assert all(r.sources == evidence and r.reference == code for r in rows)
    assert all("input(" not in r for r in runs)


@pytest.mark.parametrize("prefix", [
    "def scale(x):\n    return x * 2",
    "class Solution:\n    factor = 2",
    "offset = sum([1, 2])",
])
@pytest.mark.parametrize("declaration,variants", [
    ("items = [1, 2]", ["items = [3]", "items = [4, 5]"]),
    ("items = input()", ["items = 'a'", "items = 'bb'", "items = 'ccc'"]),
])
def test_solution_before_declaration_only_creates_blank(weekly, tmp_path, monkeypatch, prefix, declaration, variants):
    job, code, _, runs = setup_file(
        weekly, tmp_path, monkeypatch,
        [prefix, declaration + "\nsize = len(items)\nprint(size)"],
        {"variants": variants},
    )
    result = practice.prepare(weekly[1], job)
    (exercise_id,) = result["exercise_ids"]
    exercise = weekly[1].get(PracticeExercise, exercise_id)
    assert exercise.kind == "blank" and exercise.reference == code
    assert len(runs) == len(exercise.tests) == 3


@pytest.mark.parametrize("extension,kinds", [("py", {"blank"}), ("pptx", {"blank", "full"})])
@pytest.mark.parametrize("decl", ["amount = 3", "amount = int(input())"])
def test_same_program_uses_the_starter_from_its_source(weekly, tmp_path, monkeypatch, extension, kinds, decl):
    _, db, _ = weekly
    code = f"def scale(value):\n    return value * 2\n{decl}\nprint(scale(amount))"
    starter = decl + "\n# Write the calculation"
    variants = ["amount=4", "amount=5"] if decl == "amount = 3" else ["amount=3", "amount=4", "amount=5"]
    proposal = {"variants": variants, "full_template": starter}
    job, _, _, runs = setup_file(weekly, tmp_path, monkeypatch, [code], {"variants": variants})
    if extension == "pptx":
        db.get(MaterialVersion, "version").filename = "synthetic.pptx"
        monkeypatch.setattr(worker, "model_json", lambda *args: {"programs": [{
            "source_id": "piece-1", "code": code, "title": "출력 연습", "prompt": "예제의 결과를 계산하고 출력하세요.",
            "input_statement": decl, "blank_lines": [2], **proposal,
        }]})
    result = practice.prepare(db, job)
    rows = [db.get(PracticeExercise, eid) for eid in result["exercise_ids"]]
    assert len(runs) == 3 and {row.kind for row in rows} == kinds
    assert all(row.template == starter.replace(decl, row.tests[0]["statement"]) for row in rows if row.kind == "full")


@pytest.mark.parametrize("invalid", ["missing", "repeated", "entire_program"])
def test_ppt_starter_is_checked_before_substituting_stdin(weekly, tmp_path, monkeypatch, invalid):
    _, db, _ = weekly
    decl = "amount = int(input())"
    code = f"def scale(value):\n    return value * 2\n{decl}\nprint(scale(amount))"
    job, _, _, runs = setup_file(weekly, tmp_path, monkeypatch, [code], {})
    db.get(MaterialVersion, "version").filename = "synthetic.pptx"
    starter = {"missing": "# implement", "repeated": decl + "\n" + decl, "entire_program": code}[invalid]
    monkeypatch.setattr(worker, "model_json", lambda *args: {"programs": [{
        "source_id": "piece-1", "code": code, "title": "출력 연습", "prompt": "예제의 결과를 계산하고 출력하세요.",
        "input_statement": decl, "variants": ["amount=3", "amount=4", "amount=5"],
        "blank_lines": [2], "full_template": starter,
    }]})
    result = practice.prepare(db, job)
    assert not runs and result["held"] == [{"source_id": "piece-1", "reason": "INVALID_PRACTICE_TEMPLATE"}]


@pytest.mark.parametrize("language,decl,variants", [
    ("python", "amount = 3", ["amount = 3 + 8", "amount=4", "amount=5", "amount=1001"]),
    ("java", "int amount = 3;", ["int amount = 3 + 8;", "int amount=4;", "int amount=5;", "int amount=1001;"]),
    ("c", "int amount = 3;", ["int amount = 3 + 8;", "int amount=4;", "int amount=5;", "int amount=1001;"]),
])
def test_only_valid_values_reach_sandbox_and_discard_is_diagnostic(weekly, tmp_path, monkeypatch, language, decl, variants):
    _, db, _ = weekly
    code = {
        "python": f"{decl}\nvalue = amount * 2\nprint(value)",
        "java": f"class Main {{\npublic static void main(String[] args) {{\n{decl}\nSystem.out.println(amount * 2);\n}}\n}}",
        "c": f'#include <stdio.h>\nint main(void) {{\n{decl}\nprintf("%d", amount * 2);\n}}',
    }[language]
    job, _, _, runs = setup_file(weekly, tmp_path, monkeypatch, [code], {})
    db.get(MaterialVersion, "version").filename = "synthetic.pptx"
    db.get(Course, "course").teaching_language = language
    db.flush()
    monkeypatch.setattr(worker, "model_json", lambda *args: {"programs": [{
        "source_id": "piece-1", "code": code, "title": "출력 연습", "prompt": "예제의 결과를 계산하고 출력하세요.",
        "input_statement": decl, "variants": variants, "blank_lines": [2 if language == "python" else 4],
        "full_template": decl + "\n",
    }]})
    result = practice.prepare(db, job)
    assert len(result["exercise_ids"]) == 2 and not result["held"] and not result["skipped"]
    assert [entry["index"] for entry in result["discarded_probes"]["piece-1"]] == [1, 4]
    assert runs == [code, code.replace(decl, variants[1]), code.replace(decl, variants[2])]
    from lerny.weekly_content import job_view
    job.result = result
    view = job_view(job)
    assert not view["held"] and not view["skipped"] and "discarded_probes" not in view


def test_fixed_file_ignores_unsolicited_variants(weekly, tmp_path, monkeypatch):
    job, code, _, runs = setup_file(weekly, tmp_path, monkeypatch,
        ["def square(value):\n    return value * value\nprint(square(3))"],
        {"variants": ["other = 1", "other = 2", "other = 3", "other = 4", "other = 5"]})
    result = practice.prepare(weekly[1], job)
    assert not result["held"] and runs == [code]
    (exercise_id,) = result["exercise_ids"]
    exercise = weekly[1].get(PracticeExercise, exercise_id)
    assert exercise.kind == "blank" and exercise.tests == [{"expected": "1"}]


@pytest.mark.parametrize("selected", ["middle", "missing"])
def test_literal_file_binds_only_a_verified_candidate(weekly, tmp_path, monkeypatch, selected):
    declarations = ["first = [1]", "middle = [2]", "last = [3]"]
    job, code, evidence, runs = setup_file(weekly, tmp_path, monkeypatch,
        ["\n".join([*declarations, "print(sum(middle))"])], {})
    variants = [f"{selected} = [4]", f"{selected} = [5]"]
    calls = []
    def propose(prompt, schema):
        data = json.loads(prompt.rsplit("\n", 1)[1])
        assert data["candidate_statements"] == declarations and data["statement"] == declarations[0]
        calls.append(data["retry_reason"])
        return file_metadata(variants, line=4)
    monkeypatch.setattr(worker, "model_json", propose)
    result = practice.prepare(weekly[1], job)
    if selected == "missing":
        assert calls == [None, "INVALID_PRACTICE_PROBES"] and not runs and not result["exercise_ids"]
        assert result["held"] == [{"source_id": "file:version", "reason": "INVALID_PRACTICE_PROBES"}]
        assert [p["reason"] for p in result["discarded_probes"]["file:version"]] == ["PRACTICE_PROBE_NAMES_MISMATCH"] * 4
    else:
        assert calls == [None] and not result["held"]
        original = code.replace("\r\n", "\n")
        assert runs == [original, *(original.replace(declarations[1], v) for v in variants)]
        rows = [weekly[1].get(PracticeExercise, eid) for eid in result["exercise_ids"]]
        assert {r.kind for r in rows} == {"blank", "full"}
        assert all(r.sources == evidence and r.reference == code for r in rows)
        for row in rows:
            assert [c["input"] for c in row.tests] == [declarations[1], *variants]
            assert all(c["statement"] == declarations[1] for c in row.tests)


def test_first_stdin_fixture_can_be_discarded(weekly, tmp_path, monkeypatch):
    job, _, _, runs = setup_file(weekly, tmp_path, monkeypatch, ["n = int(input())\nvalue = n * 2\nprint(value)"],
                                {"variants": ["n = wrong", "n = 2", "n = 3", "n = 4"]})
    result = practice.prepare(weekly[1], job)
    assert len(result["exercise_ids"]) == 2 and not result["held"]
    assert len(runs) == 3 and all("wrong" not in src and "input(" not in src for src in runs)
    assert result["discarded_probes"]["file:version"][0]["index"] == 1


@pytest.mark.parametrize("language,decl,variants", [
    ("python", "n=1", ["n=+1", "other=2", "n=3.0", "n=2"]),
    ("c", "int n=1;", ["int n=+1;", "int other=2;", "int n=3.0;", "int n=2;"]),
    ("java", "int n=1;", ["int n=+1;", "int other=2;", "int n=3.0;", "int n=2;"]),
])
def test_semantic_duplicates_wrong_names_and_types_do_not_count(language, decl, variants):
    rejected = []
    with pytest.raises(ValueError, match="INVALID_PRACTICE_PROBES"):
        practice.input_variants(decl, variants, language, rejected=rejected)
    assert [r["index"] for r in rejected] == [1, 2, 3]
    assert [r["reason"] for r in rejected] == [
        "DUPLICATE_PRACTICE_INPUT", "PRACTICE_PROBE_NAMES_MISMATCH", "PRACTICE_PROBE_TYPE_MISMATCH"]


@pytest.mark.parametrize("decl,expected", [
    ("PI = 3.14\nMAX_SIZE = [1,2]", "fixed"),
    ("MAX_SIZE = [1,2]\ncount = 4", "count = 4"),
    ("PI = 3.14\ncount = 4\nitems = [1,2]", "items = [1,2]"),
    ("items = [1,2]\nname = input()", "name = input()"),
])
def test_file_input_priority(decl, expected):
    mode, statement, _ = practice_files.python_shape(decl + "\nprint(1)")
    assert (statement or mode) == expected


def test_uppercase_only_literal_file_uses_a_single_fixed_blank(weekly, tmp_path, monkeypatch):
    job, original, _, runs = setup_file(weekly, tmp_path, monkeypatch,
        ["MAX_SIZE = 7\nvalue = MAX_SIZE * 2\nprint(value)"], {})
    result = practice.prepare(weekly[1], job)
    (exercise,) = [weekly[1].get(PracticeExercise, eid) for eid in result["exercise_ids"]]
    assert exercise.reference == original and exercise.kind == "blank"
    assert len(runs) == len(exercise.tests) == 1 and "input(" not in runs[0]
    assert "input" not in exercise.tests[0] and "statement" not in exercise.tests[0]


@pytest.mark.parametrize("language,keyword", [("java", "final"), ("c", "const")])
def test_native_constants_cannot_be_proposed_by_quoting_only_the_assignment(language, keyword):
    code = f"{keyword} int limit = 2;\nint SIZE = 5;\nint count = 3;"
    for stmt in (f"{keyword} int limit = 2;", "int limit = 2;", "limit = 2;", "int SIZE = 5;"):
        with pytest.raises(ValueError, match="UNSUPPORTED_PRACTICE_INPUT"):
            practice.input_variants(stmt, [stmt.replace("2", "6"), stmt.replace("2", "8")], language, source=code)
    assert len(practice.input_variants("int count = 3;", ["int count=4;", "int count=5;"], language, source=code)) == 3
    rejected = []
    accepted = practice.input_variants("int count = 3;", ["intcount=8;", "int count=4;", "int count=5;"],
                                      language, rejected=rejected, source=code)
    assert len(accepted) == 3 and rejected == [{"index": 1, "reason": "PRACTICE_PROBE_NAMES_MISMATCH"}]


@pytest.mark.parametrize("language", ["java", "c"])
def test_native_float_rounding_does_not_create_a_distinct_probe(language):
    rejected = []
    result = practice.input_variants("float n=1.0f;", [
        "float n=1.00000001f;", "float n=2.0f;", "float n=3.0f;"], language, rejected=rejected)
    assert len(result) == 3 and rejected == [{"index": 1, "reason": "DUPLICATE_PRACTICE_INPUT"}]


@pytest.mark.parametrize("declaration,variants", [
    ("items = [1, 2]", ["items = [3]", "items = [4, 5]"]),
    ("items = input()", ["items = 'a'", "items = 'bb'", "items = 'ccc'"]),
])
def test_safe_preamble_is_preserved_in_full_starter(weekly, tmp_path, monkeypatch, declaration, variants):
    prefix = "# fixture\nimport math\nfrom math import floor\nunit = -2"
    job, _, _, _ = setup_file(
        weekly, tmp_path, monkeypatch,
        [prefix + "\n" + declaration + "\nsize = len(items)\nprint(size)"],
        {"variants": variants, "blank_lines": [6]},
    )
    rows = [weekly[1].get(PracticeExercise, eid) for eid in practice.prepare(weekly[1], job)["exercise_ids"]]
    assert {row.kind for row in rows} == {"full", "blank"}
    full = next(row for row in rows if row.kind == "full")
    assert full.template == prefix + "\n" + full.tests[0]["statement"] + "\n# 구현하세요."


@pytest.mark.parametrize("code", [
    'print("a single line longer than twenty characters")',
    'label = "long enough"\n  \n\nprint(label)',
    "v=1\nw=v+1\nprint(w)#",  # 19 characters after newline normalization
])
def test_short_verified_file_has_a_reason_without_model_or_sandbox(weekly, tmp_path, monkeypatch, code):
    job, _, _, runs = setup_file(weekly, tmp_path, monkeypatch, [code], {})
    monkeypatch.setattr(worker, "model_json", lambda *a: pytest.fail("short file sent to model"))
    result = practice.prepare(weekly[1], job)
    assert not result["exercise_ids"] and not runs
    assert result["skipped"] == [{"source_id": "file:version", "reason": "PRACTICE_PROGRAM_TOO_SHORT"}]


def test_twenty_characters_and_three_nonempty_lines_are_enough():
    practice_files.check_program_size("v=1\nw=v+1\nprint(w)#x")


def test_document_checks_the_proposed_program_size_not_the_chunk(weekly, tmp_path, monkeypatch):
    _, db, _ = weekly
    code = 'label = "a long literal"\nprint(label)'
    job, _, _, runs = setup_file(weekly, tmp_path, monkeypatch, [code], {})
    db.get(MaterialVersion, "version").filename = "synthetic.pdf"
    chunk = db.get(Chunk, "piece-1")
    chunk.content = "Example program\n" + code + "\nSample output"
    db.flush()
    monkeypatch.setattr(worker, "model_json", lambda *args: {"programs": [{
        "source_id": chunk.id, "code": code, "title": "출력 연습", "prompt": "주어진 코드의 결과를 출력하세요.",
        "input_statement": "", "variants": [], "blank_lines": [2], "full_template": "",
    }]})
    result = practice.prepare(db, job)
    assert not result["exercise_ids"] and not runs
    assert result["held"] == [{"source_id": chunk.id, "reason": "PRACTICE_PROGRAM_TOO_SHORT"}]


def test_invented_code_rejected_before_sandbox(weekly, tmp_path, monkeypatch):
    job, _, _, runs = setup_file(
        weekly,
        tmp_path,
        monkeypatch,
        ["def run():\n    return 8", "print(run())"],
        {"code": "def run():\n    return 9\nprint(run())"},
    )
    result = practice.prepare(weekly[1], job)
    assert (
        not result["exercise_ids"]
        and result["held"][0]["reason"] == "INVALID_PRACTICE_SOURCE"
        and not runs
    )


@pytest.mark.parametrize("output", [None, "", "x" * 4001], ids=["failed", "empty", "too_long"])
def test_fixed_program_requires_one_bounded_output(weekly, tmp_path, monkeypatch, output):
    job, _, _, _ = setup_file(
        weekly, tmp_path, monkeypatch, ["def fixed():\n    return 7", "print(fixed())"], {}
    )
    runs = []
    monkeypatch.setattr(practice, "output_of", lambda *a, **kw: runs.append(1) or output)
    result = practice.prepare(weekly[1], job)
    assert runs == [1] and not result["exercise_ids"]
    assert result["held"][0]["reason"] == "PRACTICE_REFERENCE_UNVERIFIED"


def test_variable_program_requires_distinct_outputs(weekly, tmp_path, monkeypatch):
    job, _, _, _ = setup_file(
        weekly, tmp_path, monkeypatch, ["word = input()\nsize = len(word)\nprint(size)"],
        {"variants": ["word = 'a'", "word = 'b'", "word = 'c'"]},
    )
    monkeypatch.setattr(practice, "output_of", lambda *a, **kw: "1")
    result = practice.prepare(weekly[1], job)
    assert not result["exercise_ids"] and result["held"][0]["reason"] == "PRACTICE_PROBES_INEFFECTIVE"


def test_repeated_input_skipped_without_model_or_execution(weekly, tmp_path, monkeypatch):
    job, _, _, runs = setup_file(
        weekly, tmp_path, monkeypatch, ["while True:\n    item = input()\n    print(item)"], {}
    )
    monkeypatch.setattr(
        worker, "model_json", lambda *a: pytest.fail("unsupported file sent to model")
    )
    result = practice.prepare(weekly[1], job)
    assert not runs and result["status"] == "no_verified_source_code"
    assert [item["reason"] for item in result["skipped"]] == ["PRACTICE_LOOP_INPUT"] and not result[
        "held"
    ]


def test_instructor_can_retry_legacy_empty_draft_once(weekly):
    client, db, _ = weekly
    generation_id = start(client)
    job = Job(owner_id="teacher", course_id="course", kind="practice_prepare", status="succeeded",
              payload={"generation_id": generation_id, "source_version_id": "version"},
              result={"status": "no_verified_source_code", "exercise_ids": [], "held": []})
    db.add(job)
    db.commit()
    url = f"/api/v1/courses/course/content-generations/{generation_id}/retry"
    assert client.post(url).json() == {"retried": 1}
    db.refresh(job)
    assert job.status == "queued" and job.result is None
    job.status = "succeeded"
    job.result = {"status": "no_verified_source_code", "exercise_ids": [], "held": [],
                  "skipped": [{"reason": "PRACTICE_LOOP_INPUT"}]}
    db.commit()
    assert client.post(url).status_code == 409


@pytest.mark.parametrize(
    "bad",
    [
        "v = get()",
        "v = other",
        "v = [1+2]",
        "v = [x]",
        "v = ['" + "x" * 121 + "']",
        "v = " + str([1] * 65),
    ],
)
def test_probe_cannot_introduce_expressions_or_oversized_literals(bad):
    with pytest.raises(ValueError):
        literal_inputs("v = ['a']", ["v = ['b']", bad])


def test_multiline_literal_setup_can_precede_stdin_and_inputs_must_be_grouped():
    code = 'records = [\n    ["blue", 2]\n]\nlabel = input()\nprint(label in records[0])'
    assert practice_files.python_shape(code) == ("stdin", "label = input()", [("label", "str")])
    with pytest.raises(ValueError, match="PRACTICE_INPUT_POSITION"):
        practice_files.python_shape(code + "\nother = input()")
    with pytest.raises(ValueError, match="PRACTICE_INPUT_POSITION"):
        practice_files.python_shape("\n".join(f"x{i} = input()" for i in range(7)))


def test_missing_executable_span_and_changed_chunk_are_rejected(weekly, tmp_path, monkeypatch):
    job, _, _, runs = setup_file(
        weekly, tmp_path, monkeypatch, ["def scale(x):\n    return x * 2", "print(scale(4))"], {}
    )
    _, db, _ = weekly
    first = db.get(Chunk, "piece-2")
    first.content = "unrelated"
    db.flush()
    assert practice.prepare(db, job)["skipped"][0]["reason"] == "PRACTICE_FILE_EVIDENCE"
    db.delete(first)
    db.flush()
    assert practice.prepare(db, job)["skipped"][0]["reason"] == "PRACTICE_FILE_GAP"
    assert not runs


@pytest.mark.parametrize(
    "language,code",
    [
        (
            "java",
            "class Main {\n public static void main(String[] args) {\n  System.out.println(7);\n }\n}",
        ),
        ("c", '#include <stdio.h>\nint main(void) {\n puts("seven");\n}'),
    ],
)
def test_attested_native_file_uses_fixed_output_gate(weekly, monkeypatch, language, code):
    client, db, _ = weekly
    v = db.get(MaterialVersion, "version")
    v.filename = "synthetic." + language
    v.sha256 = hashlib.sha256(code.encode()).hexdigest()
    db.get(Course, "course").teaching_language = language
    db.execute(delete(Chunk).where(Chunk.version_id == v.id))
    db.add(Chunk(version_id=v.id, content=code, locator={}))
    db.commit()
    job = Job(
        owner_id="teacher",
        course_id="course",
        kind="practice_prepare",
        payload={"generation_id": start(client), "source_version_id": v.id},
    )
    monkeypatch.setattr(
        worker,
        "model_json",
        lambda *a: {"title": "출력 연습", "prompt": "빈칸을 완성하고 결과를 출력하세요.",
                    "variants": [], "blank_lines": [3]},
    )
    runs = []
    monkeypatch.setattr(
        practice, "output_of", lambda lang, src, **kw: runs.append((lang, src)) or "seven"
    )
    result = practice.prepare(db, job)
    (ex,) = [db.get(PracticeExercise, e) for e in result["exercise_ids"]]
    assert ex.kind == "blank" and ex.reference == code and runs == [(language, code)]


def file_metadata(variants=(), line=2):
    return {"title": "출력 계산", "prompt": "주어진 프로그램을 완성하고 출력값을 확인하세요.",
            "blank_lines": [line], "variants": list(variants)}


@pytest.mark.parametrize("missing_first", [False, True])
def test_each_file_gets_a_proposal_and_retry_adds_only_missing(weekly, monkeypatch, missing_first):
    client, db, _ = weekly
    db.get(MaterialVersion, "version").filename = "synthetic.pptx"
    for n in range(3):
        vid = f"example-{n}"
        source = f"def scale(value):\n    return value * {n+2}\nprint(scale(3))"
        db.add(Material(id=vid, course_id="course", title=vid, kind="example", week=1,
                        visibility="public", active_version_id=vid))
        db.add(MaterialVersion(id=vid, material_id=vid, version_no=1, filename=vid+".py", object_key="unused",
                               sha256=hashlib.sha256(source.encode()).hexdigest(), status="ready"))
        db.add(Chunk(version_id=vid, content=source, locator={}))
        if n == 0:
            db.add(Chunk(id="slide-example", version_id="version", content=source, locator={}))
    db.commit()
    generation = start(client)
    job = Job(owner_id="teacher", course_id="course", kind="practice_prepare", payload={"generation_id": generation,
              "source_version_id": "version", "source_version_ids": ["version", "example-0", "example-1", "example-2"]})
    db.add(job)
    db.commit()
    file_calls, document_batches, executions = [], [], []
    def propose(prompt, schema):
        data = json.loads(prompt.rsplit("\n", 1)[1])
        if "sources" in data:
            document_batches.append([s["source_id"] for s in data["sources"]])
            assert all(not s.startswith("file:") for s in document_batches[-1])
            slide = next(s for s in data["sources"] if s["source_id"] == "slide-example")
            return {"programs": [{**file_metadata(), "source_id": slide["source_id"], "code": slide["text"],
                                  "input_statement": "", "full_template": ""}]}
        assert set(schema["properties"]) == {"title", "prompt", "variants", "blank_lines"}
        file_calls.append(data["source_id"])
        if missing_first and data["source_id"] == "file:example-2":
            return {}
        return file_metadata()
    monkeypatch.setattr(worker, "model_json", propose)
    monkeypatch.setattr(practice, "output_of", lambda lang, src, **kw: executions.append(src) or "6")
    result = practice.prepare(db, job)
    assert len(document_batches) == 1
    assert set(file_calls) == {f"file:example-{n}" for n in range(3)}
    assert all(db.get(PracticeExercise, eid).version_id != "version" for eid in result["exercise_ids"])
    if not missing_first:
        assert len(file_calls) == len(result["exercise_ids"]) == len(executions) == 3 and not result["held"]
        return
    assert file_calls.count("file:example-2") == 2 and len(executions) == 2
    assert result["held"] == [{"source_id": "file:example-2", "reason": "PRACTICE_NO_PROPOSAL"}]
    job.status, job.result = "succeeded", result
    db.commit()
    assert client.post(f"/api/v1/courses/course/content-generations/{generation}/retry").json() == {"retried": 1}
    file_calls.clear()
    missing_first = False
    recovered = practice.prepare(db, job)
    assert file_calls == ["file:example-2"] and len(executions) == 3 and len(recovered["exercise_ids"]) == 1
    rows = list(db.scalars(select(PracticeExercise).where(PracticeExercise.generation_id == generation)))
    assert {r.id for r in rows} == set(result["exercise_ids"] + recovered["exercise_ids"])
    assert sorted(r.position for r in rows) == [1, 2, 3]


@pytest.mark.parametrize("alternate", ["effective", "unchanged", "invalid_output"])
def test_ineffective_list_tries_next_declaration_then_fixed(weekly, tmp_path, monkeypatch, alternate):
    job, code, _, _ = setup_file(weekly, tmp_path, monkeypatch, [
        "buffer = [1]\ncount = 2\nvalue = count * 3\nprint(value)"
    ], {})
    calls, executions = [], []
    def propose(prompt, schema):
        data = json.loads(prompt.rsplit("\n", 1)[1])
        calls.append(data["statement"])
        if len(calls) == 1:
            return file_metadata(["buffer = [3]", "buffer = [4]"], line=3)
        assert data["retry_reason"] == "PRACTICE_PROBES_INEFFECTIVE"
        return file_metadata(["count = 3", "count = 4"], line=3)
    def sandbox(language, src, **kw):
        executions.append(src)
        if "count = 3" in src and alternate == "invalid_output":
            return None
        return "9" if alternate == "effective" and "count = 3" in src else "6"
    monkeypatch.setattr(worker, "model_json", propose)
    monkeypatch.setattr(practice, "output_of", sandbox)
    result = practice.prepare(weekly[1], job)
    rows = [weekly[1].get(PracticeExercise, eid) for eid in result["exercise_ids"]]
    assert not result["held"] and calls == ["buffer = [1]", "count = 2"]
    assert all(row.reference == code for row in rows)
    assert len(set(executions)) == len(executions) <= practice_files.FileProbeBudget.limit
    if alternate == "effective":
        assert {r.kind for r in rows} == {"blank", "full"}
        assert all(r.tests[0]["statement"] == "count = 2" for r in rows)
    else:
        assert [r.kind for r in rows] == ["blank"] and rows[0].tests == [{"expected": "6"}]


def test_uppercase_stdin_has_variable_fixtures_and_legacy_fixed_fixture_still_reads(weekly, tmp_path, monkeypatch):
    from lerny.practice_support import editor_reference
    job, code, _, runs = setup_file(weekly, tmp_path, monkeypatch,
        ["N = int(input())\nvalue = N * 2\nprint(value)"], {"variants": ["N = 2", "N = 3", "N = 4"]})
    result = practice.prepare(weekly[1], job)
    rows = [weekly[1].get(PracticeExercise, eid) for eid in result["exercise_ids"]]
    assert {row.kind for row in rows} == {"blank", "full"} and len(runs) == 3
    assert all([case["input"] for case in row.tests] == ["N = 2", "N = 3", "N = 4"] for row in rows)
    blank = next(row for row in rows if row.kind == "blank")
    blank.tests = [{"source_statement": "N = int(input())", "fixture_statement": "N = 2", "expected": "4"}]
    weekly[1].commit()
    weekly[1].refresh(blank)
    assert editor_reference(blank) == code.replace("N = int(input())", "N = 2")
    assert practice.exercise_view(weekly[1], blank, weekly[1].get(Material, "material"))["example_input"] == ""


@pytest.mark.parametrize("language", ["java", "c"])
def test_native_file_with_array_allows_selected_scalar(weekly, monkeypatch, language):
    client, db, _ = weekly
    prefix, suffix = (("class Main {\npublic static void main(String[] args) {", "System.out.println(count);\n}\n}")
                      if language == "java" else ("#include <stdio.h>\nint main(void) {", 'printf("%d", count);\n}'))
    array = "int[] items = {1, 2};" if language == "java" else "int items[] = {1, 2};"
    code = "\n".join([prefix, array, "int count = 3;", suffix])
    v = db.get(MaterialVersion, "version")
    v.filename, v.sha256 = "example."+language, hashlib.sha256(code.encode()).hexdigest()
    db.get(Course, "course").teaching_language = language
    db.execute(delete(Chunk).where(Chunk.version_id == v.id))
    db.add(Chunk(version_id=v.id, content=code, locator={}))
    db.commit()
    job = Job(owner_id="teacher", course_id="course", kind="practice_prepare",
              payload={"generation_id": start(client), "source_version_id": v.id})
    monkeypatch.setattr(worker, "model_json", lambda *_: file_metadata(
        ["int count = 3;", "int count = 4;", "int count = 5;"], line=5))
    runs = []
    monkeypatch.setattr(practice, "output_of", lambda lang, src, **kw: runs.append(src) or str(len(runs)))
    result = practice.prepare(db, job)
    assert not result["held"] and len(runs) == 3
    assert {db.get(PracticeExercise, eid).kind for eid in result["exercise_ids"]} == {"blank", "full"}


def test_legacy_skipped_file_proposal_can_retry_but_permanent_skips_cannot(weekly):
    client, db, _ = weekly
    gid = start(client)
    job = Job(owner_id="teacher", course_id="course", kind="practice_prepare", status="succeeded",
              payload={"generation_id": gid, "source_version_id": "version"},
              result={"status":"no_verified_source_code", "exercise_ids":[], "held":[],
                      "skipped":[{"source_id":"file:synthetic", "reason":"PRACTICE_NO_PROPOSAL"}]})
    db.add(job)
    db.commit()
    url = f"/api/v1/courses/course/content-generations/{gid}/retry"
    assert client.post(url).json() == {"retried": 1}
    job.status, job.result = "succeeded", {"skipped":[{"source_id":"file:synthetic", "reason":"PRACTICE_LOOP_INPUT"}]}
    db.commit()
    assert client.post(url).status_code == 409


def test_file_sandbox_limit_and_cached_outputs_survive_worker_replay(tmp_path):
    receipt = tmp_path / "probes.json"
    calls = []
    def evaluate(source):
        calls.append(source)
        return "12"
    for n in range(practice_files.FileProbeBudget.limit):
        assert practice_files.FileProbeBudget(receipt).run(f"synthetic-{n}", evaluate) == "12"
    resumed = practice_files.FileProbeBudget(receipt)
    assert resumed.run("synthetic-0", evaluate) == "12"
    with pytest.raises(ValueError, match="PRACTICE_PROBES_INEFFECTIVE"):
        resumed.run("one more", evaluate)
    assert len(calls) == 11


def test_python_alternate_order_leaves_uppercase_literals_last():
    source = "factor=2\nCAP=[3]\nvalues=[1]\nprint(factor)"
    assert [s[1] for s in practice_files.python_shapes(source)] == ["values=[1]", "factor=2", "CAP=[3]"]
