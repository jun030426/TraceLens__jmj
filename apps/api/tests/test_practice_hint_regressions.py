"""Reproductions for stored exercises and the hints students actually receive."""
from types import SimpleNamespace

import pytest

from lerny.practice_support import explanation, format_inline_comment, hints, metadata, normalize_blanks_and_template
from rag_mvp.cloze_generator import ClozeGenerator as Generator


def exercise(code, template="", blanks=None, statement="n = 3", kind="blank", title="실습"):
    return SimpleNamespace(language="python", kind=kind, title=title, prompt="주어진 입력에 맞는 결과를 출력하세요.",
        reference=code, template=template, blanks=blanks or {},
        tests=[{"statement": statement, "input": statement, "expected": "4"}])


def test_reference_preserves_single_original_comment():
    e = exercise("# 원본 설명\nn = 3\nresult = n + 1  # 더하기\nprint(result)", kind="full")
    annotated = explanation(e)["annotated_reference"]
    assert annotated.count("# 원본 설명") == 1
    assert annotated.count("# 더하기") == 1


def test_simple_arithmetic_recovers_a_stored_print_blank():
    source = "n = 3\nresult = n * 2\nprint(result)"
    e = exercise(source, source.replace("print(result)", "[[빈칸]]"), {"1": "print(result)"})
    assert [b["answer"] for b in Generator.select_blanks(source)] == ["result = n * 2"]
    assert normalize_blanks_and_template(e) == ("n = 3\n[[빈칸]]\nprint(result)", {"1": "result = n * 2"})
    assert e.blanks == {"1": "print(result)"}


def test_inputs_remain_literal_during_blank_repair():
    statement = "n = 3\nm = 4"
    source = statement + "\nresult = n * m\nprint(result)"
    e = exercise(source, "[[빈칸]]\nm = 4\nresult = n * m\nprint(result)", {"1":"n = 3"}, statement)
    template, answers = normalize_blanks_and_template(e)
    assert template.startswith(statement) and list(answers.values()) == ["result = n * m"]


def test_output_only_repair_keeps_print_visible():
    e = exercise("n = 3\nprint(n + 1)", "n = 3\n[[빈칸]]", {"1":"print(n + 1)"})
    assert normalize_blanks_and_template(e) == ("n = 3\nprint([[빈칸]])", {"1":"n + 1"})


@pytest.mark.parametrize("title,code,unexpected", [
    ("성적 판정", "score = 75\nif score >= 70:\n    grade = 'B'\nprint(grade)", "grade_average"),
    ("원소 개수", "items = [1, 2]\nprint(len(items))", "string_len"),
    ("자료형 변경", 'items = "준비"\nitems = [1, 2]\nprint(len(items))', "string_len"),
    ("기상", "humidity = 65\nprint(humidity)", "binary_search"),
    ("시험", "midterm = 80\nprint(midterm)", "binary_search"),
])
def test_mnemonics_require_evidence(title, code, unexpected):
    assert Generator.resolve_mnemonic_flow(title, code)["flow_title"] != Generator.MNEMONIC_FLOW_CATALOG[unexpected]["flow_title"]


@pytest.mark.parametrize("header,wanted", [
    ("if 45 <= value <= 65:", "if [상수값] <= [value] <= [상수값]:"),
    ("elif 45 <= value <= 65:", "elif [상수값] <= [value] <= [상수값]:"),
    ("else:", "else:"), ("if item not in items:", "if [item] not in [items]:"),
    ("if item in items:", "if [item] in [items]:"),
    ("if x is None:", "if [x] is None:"), ("if x is not None:", "if [x] is not None:"),
    ('s = "#한글"', '[s] = "[문자열]"'),
])
def test_standalone_skeleton(header, wanted):
    assert Generator.build_abstract_skeleton(header) == wanted


@pytest.mark.parametrize("line", ["elif value > 0:", "else:", 's = "#문자열"'])
def test_comments_parse_real_code(line):
    note = format_inline_comment(line)
    assert note and note != "요구조건에 맞추어 연산 수행" and "문자열\"" not in note


def test_nested_condition_is_present_in_action_flow_and_hints():
    code = "n = 3\nlimit = n + 1\nfor v in range(n):\n    if v < limit:\n        limit += v\nprint(limit)"
    flow = Generator.generate_dynamic_action_flow(code)["steps"]
    assert any("if " in step["code_mnemonic"] for step in flow)
    assert any("for " in step["code_mnemonic"] for step in flow)
    assert any("if " in s for s in hints(exercise(code, kind="full")))


def test_condition_within_loop_follows_iteration_in_the_guide():
    code = "for item in items:\n    if item < limit:\n        print(item)"
    steps = [s["code_mnemonic"] for s in Generator.generate_dynamic_action_flow(code)["steps"]]
    assert next(i for i, s in enumerate(steps) if "for " in s) < next(i for i, s in enumerate(steps) if "if " in s)


def test_queue_catalog_does_not_supply_the_pointer_formula():
    steps = Generator.resolve_mnemonic_flow("queue_enqueue", "def enqueue(self, item):\n    pass")["steps"]
    for step in steps:
        assert "(rear + 1)" not in str(step) and "(self.rear + 1)" not in str(step)


def test_requirements_only_name_declared_inputs_and_hide_solution():
    source = "price = 100\ncount = 2\ntotal = 0\ntotal = price * count * 0.9\nprint(total)"
    e = exercise(source, statement="price = 100\ncount = 2")
    requirements = metadata(e)["requirements"]
    assert "price" in requirements[0] and "count" in requirements[0] and "total" not in requirements[0]
    assert not any("0.9" in r or "total =" in r or "평균" in r for r in requirements)


def test_blank_repair_preserves_unicode_around_output_expression():
    e = exercise('n = 3\nprint("결과😀", n * 2)', 'n = 3\n[[빈칸]]', {"1": 'print("결과😀", n * 2)'})
    assert normalize_blanks_and_template(e) == ('n = 3\nprint("결과😀", [[빈칸]])', {"1":"n * 2"})


def test_valid_stored_selection_is_preserved():
    source = "n = 3\nresult = n * 2\nprint(result)"
    e = exercise(source, source.replace("n * 2", "[[빈칸]]"), {"1": "n * 2"})
    assert normalize_blanks_and_template(e) == (e.template, e.blanks)


def test_real_string_length_and_binary_search_keep_their_guides():
    for code, key in [('text = "한글"\nprint(len(text))', 'string_len'),
                      ('low = 0\nhigh = 10\nwhile low <= high:\n    mid = (low + high) // 2\n    low = mid + 1', 'binary_search')]:
        assert Generator.resolve_mnemonic_flow("", code)["flow_title"] == Generator.MNEMONIC_FLOW_CATALOG[key]["flow_title"]


def test_commented_worker_fixture_is_preserved_but_hidden_while_solving():
    from lerny.practice import exercise_view
    statement = "# 입력 안내\n\nn = 3"
    src = statement + "\nresult = n * 2  # 답지 전용\nprint(result)"
    e = exercise(src, src.replace("n * 2", "[[빈칸]]"), {"1": "n * 2"}, statement)
    e.id, e.concept_id = "exercise", None
    view = exercise_view(None, e, SimpleNamespace(week=1, title="fixture"))
    assert statement in view["template"] and "답지 전용" not in view["template"]
    assert view["display_template"].lstrip("\n") == "n = 3\nresult = [[빈칸]]\nprint(result)"
    assert view["example_input"].lstrip("\n") == "n = 3"
