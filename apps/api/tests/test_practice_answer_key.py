"""The answer shown after submission must line up with the template the student sees."""
from types import SimpleNamespace

from lerny.practice import student_exercise_template
from lerny.practice_support import answer_key, full_answer_on_template, normalize_blanks_and_template

REFERENCE = ('score = 85\nattendance = 90\n\nif score >= 60 and attendance >= 80:\n'
             '    result = "합격"\nelse:\n    result = "불합격"\nprint(result)')


def exercise(**changes):
    values = {"kind": "blank", "language": "python", "title": "합격 판정", "prompt": "", "reference": REFERENCE,
              "template": "", "blanks": {}, "tests": []}
    return SimpleNamespace(**{**values, **changes})


def test_blank_answers_match_the_normalized_blanks_on_screen():
    # A stored print(...) blank is replaced on screen. The answers must follow the replacement.
    stored = exercise(template=REFERENCE.replace("print(result)", "[[빈칸]]"), blanks={"1": "print(result)"})
    template, blanks = normalize_blanks_and_template(stored)
    answers = answer_key(stored)
    assert blanks != stored.blanks and answers == list(blanks.values())
    assert not any(answer.startswith("print(") for answer in answers)
    assert student_exercise_template(stored).count("[[빈칸]]") == template.count("[[빈칸]]") == len(answers)
    # Each answer restores its own line of the reference, in blank order.
    lines = iter(answers)
    restored = "\n".join(line.replace("[[빈칸]]", next(lines)) if "[[빈칸]]" in line else line
                         for line in template.splitlines())
    assert restored == REFERENCE


def test_blank_answers_follow_blank_numbers_whatever_the_stored_key_order():
    stored = exercise(template="score = 85\nattendance = 90\n\n[[빈칸]]\n    [[빈칸]]\nelse:\n"
                               '    result = "불합격"\nprint(result)',
                      blanks={"2": 'result = "합격"', "1": "if score >= 60 and attendance >= 80:  # 조건"})
    assert answer_key(stored) == ["if score >= 60 and attendance >= 80:", 'result = "합격"']


def test_full_answer_starts_below_the_starter_comment():
    starter = "score = 85\nattendance = 90\n\n# 계산과 출력을 구현하세요.\n"
    full = exercise(kind="full", template=starter)
    answer, = answer_key(full)
    editor, copy = starter.split("\n"), answer.split("\n")
    # Every starter line is already typed, so the grey text begins on the empty line under the comment.
    assert copy[:4] == editor[:4] and editor[4] == ""
    assert copy[4:] == REFERENCE.split("\n")[3:]
    assert copy[3] == "# 계산과 출력을 구현하세요." and copy[4].startswith("if score")


def test_full_answer_keeps_the_reference_when_the_starter_is_not_its_prefix():
    assert full_answer_on_template(exercise(kind="full", template="total = 0\n# 구현하세요.")) == REFERENCE
    assert full_answer_on_template(exercise(kind="full", template="")) == REFERENCE
    java = exercise(kind="full", language="java", reference="int n = 3;\nSystem.out.println(n + 1);",
                    template="int n = 3;\n// 구현하세요.")
    assert full_answer_on_template(java) == "int n = 3;\n// 구현하세요.\nSystem.out.println(n + 1);"
