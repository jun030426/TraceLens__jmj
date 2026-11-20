// 팀원 B 명세 — 3-스트라이크(문법 오류는 세지 않음) · 회색 따라쓰기(친 만큼 지워짐) 규칙
import { test } from "node:test";
import assert from "node:assert/strict";
import { fillTemplate, ghostLines, ghostRest } from "../src/practiceRules.ts";
import { BLANK_QUIZZES } from "../src/blankQuizzes.ts";

test("회색 글씨는 학생이 친 만큼 앞에서부터 지워져요", () => {
  assert.deepEqual(ghostRest("n - 1 - i", ""), { typed: "", rest: "n - 1 - i", matched: true });
  assert.deepEqual(ghostRest("n - 1 - i", "n - 1"), { typed: "n - 1", rest: " - i", matched: true });
  assert.equal(ghostRest("n - 1 - i", "n - 1 - i").rest, "");
  assert.equal(ghostRest("n - 1 - i", "x").matched, false);
  const lines = ghostLines("a = 1\nprint(a)", "a = 1\npri");
  assert.deepEqual(lines.map(l => l.rest), ["", "nt(a)"]);
});

test("빈칸 틀을 답지로 채운 target_code는 서버와 같은 모양이에요", () => {
  const bubble = BLANK_QUIZZES.Python.find(q => q.id === "py-bubble")!;
  const code = fillTemplate(bubble.template, bubble.answers!);
  assert.ok(!code.includes("[[빈칸]]"));
  assert.ok(code.includes("for j in range(n - 1 - i):"));
});

