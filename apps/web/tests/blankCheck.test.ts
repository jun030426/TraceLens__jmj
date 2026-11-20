// 빈칸 실습 채점 — 출력 비교로 맞음/틀림, 문법 오류는 빈칸을 짚는다
import test from "node:test";
import assert from "node:assert/strict";
import { checkBlanks, normalizeOutput } from "../src/visualizer/blankCheck.ts";
import type { PracticeRun } from "../src/visualizer/practiceRun.ts";

const blanks = [{ n: 1, line: 4 }, { n: 2, line: 6 }];
const ran = (stdout: string, extra: Partial<Extract<PracticeRun, { kind: "ran" }>> = {}): PracticeRun => ({ kind: "ran", code: "c", stdout, clipped: false, trace: null, ...extra });

test("출력이 같으면 정답 (줄 끝 공백·마지막 줄바꿈은 무시)", () => {
  assert.equal(checkBlanks(ran("[1, 2, 4, 5]\n"), [], blanks, "[1, 2, 4, 5]")?.kind, "correct");
  assert.equal(normalizeOutput("a  \nb\n\n"), "a\nb");
});

test("실행은 됐지만 출력이 다르면 틀림 — 기대 출력과 내 출력을 함께 준다", () => {
  const v = checkBlanks(ran("[2, 4, 1, 5]\n"), [], blanks, "[1, 2, 4, 5]");
  assert.equal(v?.kind, "wrong");
  assert.ok(v && v.kind === "wrong" && v.expected === "[1, 2, 4, 5]" && v.actual === "[2, 4, 1, 5]");
});

test("문법 오류는 그 줄의 빈칸을 짚는다", () => {
  const v = checkBlanks({ kind: "syntax", code: "c", info: { name: "SyntaxError", line: 6, offset: 1, text: "x =", msg: "invalid syntax" } }, [], blanks, "x");
  assert.equal(v?.kind, "syntax");
  assert.ok(v && v.kind !== "correct" && v.badBlanks.join() === "2" && v.title.includes("②"));
});

test("반복문 빈칸 때문에 생긴 들여쓰기 오류는 미완성 상태로 두고, 완성 후 실제 오류는 표시한다", () => {
  const run: PracticeRun = { kind: "syntax", code: "values = [2, 5, 8]\nNone\n    None", info: {
    name: "IndentationError", line: 3, offset: 4, text: "    None", msg: "unexpected indent",
  } };
  assert.equal(checkBlanks(run, [1, 2], [{ n: 1, line: 2 }, { n: 2, line: 3 }], "8\n5\n2"), null);
  assert.equal(checkBlanks(run, [], [{ n: 1, line: 2 }, { n: 2, line: 3 }], "8\n5\n2")?.kind, "syntax");
});

test("빈칸이 남았으면 아직 채점하지 않는다 · 끝나지 않으면 틀림 · 실행 오류는 틀림", () => {
  assert.equal(checkBlanks(ran("", { blankStop: { blank: 2, line: 6 } }), [2], blanks, "x"), null);
  assert.equal(checkBlanks(ran("", { clipped: true }), [], blanks, "x")?.kind, "endless");
  assert.equal(checkBlanks(ran("", { error: "ZeroDivisionError" }), [], blanks, "x")?.kind, "runtime");
});
