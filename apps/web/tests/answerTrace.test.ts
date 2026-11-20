import { test } from "node:test";
import assert from "node:assert/strict";
import { blankMatches, blankTraceProgress, fullSkeleton, fullTraceProgress } from "../src/visualizer/answerTrace.ts";
import { BLANK_QUIZZES } from "../src/blankQuizzes.ts";

test("직접 작성 따라 쓰기는 함수 머리와 꼬리 줄을 놓아 주고 몸통 줄만 비운다", () => {
  const template = "def f(n):\n    # 여기에 쓰세요\n    pass\n\nprint(f(3))\n";
  const answer = "def f(n):\n    # 여기에 쓰세요\n    total = n * 2\n    return total\n\nprint(f(3))";
  const s = fullSkeleton(template, answer);
  assert.equal(s.start, "def f(n):\n    # 여기에 쓰세요\n\n\n\nprint(f(3))");
  assert.deepEqual(s.given, [true, true, false, false, true, true]);
});

test("직접 작성 따라 쓰기는 몸통 줄이 답지와 같아야 끝나고, 줄 끝 공백은 따지지 않는다", () => {
  const template = "def f(n):\n    pass\n\nprint(f(3))";
  const answer = "def f(n):\n    return n * 2\n\nprint(f(3))";
  assert.deepEqual(fullTraceProgress(template, answer, fullSkeleton(template, answer).start), { matched: 0, total: 1, done: false });
  assert.equal(fullTraceProgress(template, answer, "def f(n):\nreturn n * 2\n\nprint(f(3))").done, false, "들여쓰기는 따진다");
  assert.deepEqual(fullTraceProgress(template, answer, "def f(n):\n    return n * 2   \n\nprint(f(3))\n\n"), { matched: 1, total: 1, done: true });
});

test("빈칸 따라 쓰기는 띄어쓰기 개수와 앞뒤 공백만 봐 준다", () => {
  assert.ok(blankMatches("  n -  1 - i ", "n - 1 - i"));
  assert.ok(!blankMatches("n-1-i", "n - 1 - i"));
  assert.deepEqual(blankTraceProgress(["a", "b"], { 1: "a" }), { matched: 1, total: 2, done: false });
  assert.equal(blankTraceProgress(["a", "b"], { 1: "a", 2: " b" }).done, true);
});

test("모든 직접 작성 문제는 머리 줄을 놓아 주고, 따라 쓸 몸통 줄이 있다", () => {
  for (const list of Object.values(BLANK_QUIZZES)) for (const q of list) {
    if (q.kind !== "full") continue;
    const s = fullSkeleton(q.template, q.answers![0]);
    assert.ok(s.given[0], `${q.id}: 첫 줄(함수 머리)은 놓아 줘요`);
    assert.ok(s.given.some(g => !g), `${q.id}: 따라 쓸 줄이 있어야 해요`);
    assert.equal(fullTraceProgress(q.template, q.answers![0], q.answers![0]).done, true, q.id);
  }
});
