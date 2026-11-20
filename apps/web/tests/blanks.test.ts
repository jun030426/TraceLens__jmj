// 빈칸 채우기 — 틀 읽기와 "안 채운 빈칸 줄에서 멈추기" 코드 만들기
import test from "node:test";
import assert from "node:assert/strict";
import { buildRunnable, parseTemplate, showBlanks } from "../src/visualizer/blanks.ts";
import { BLANK_QUIZZES, DAILY_PRACTICE_COUNT, todaysQuizzes } from "../src/blankQuizzes.ts";

const T = "nums = [5, 2]\nfor j in range([[빈칸]]):\n    if nums[j] > [[빈칸]]:\n        [[빈칸]]\nprint(nums)";

test("빈칸에 위→아래 순서로 번호를 붙이고 줄 번호를 기억한다", () => {
  const t = parseTemplate(T);
  assert.deepEqual(t.blanks, [{ n: 1, line: 2 }, { n: 2, line: 3 }, { n: 3, line: 4 }]);
  assert.equal(t.lines.length, 5);
});

test("하나도 안 채우면 첫 빈칸 줄부터 멈춤 줄이 되고, 줄 수는 그대로다", () => {
  const r = buildRunnable(parseTemplate(T), {});
  assert.deepEqual(r.stopLines, { 2: 1, 3: 2, 4: 3 });
  assert.deepEqual(r.unfilled, [1, 2, 3]);
  assert.equal(r.code.split("\n").length, 5);
  assert.match(r.code, /range\(__blank1__\)/);
});

test("빈칸 ①만 채우면 ② 줄에서 멈추고, 모두 채우면 멈춤 줄이 없다", () => {
  const t = parseTemplate(T);
  const one = buildRunnable(t, { 1: "len(nums) - 1" });
  assert.deepEqual(one.stopLines, { 3: 2, 4: 3 });
  assert.match(one.code, /range\(len\(nums\) - 1\)/);
  const all = buildRunnable(t, { 1: "1", 2: "nums[j + 1]", 3: "nums[j], nums[j + 1] = nums[j + 1], nums[j]\n" });
  assert.deepEqual(all.stopLines, {});
  assert.equal(all.code.split("\n").length, 5, "줄바꿈을 넣어도 줄 번호가 밀리지 않는다");
});

test("자리표시 이름은 화면에서 빈칸 번호로 보인다", () => {
  assert.equal(showBlanks("for j in range(__blank1__):"), "for j in range(［빈칸 ①］):");
});

test("기본 문제는 언어마다 있고, 빈칸 문제는 빈칸을, 풀코딩 문제는 정답 코드와 기대 출력을 가진다", () => {
  for (const list of Object.values(BLANK_QUIZZES)) {
    assert.ok(list.length >= 1);
    for (const q of list) {
      if (q.kind === "full") {
        assert.ok(q.expected, `${q.id}: 기대 출력이 있어야 해요`);
        assert.ok(q.answers && q.answers.length >= 1, `${q.id}: 정답 코드가 있어야 해요`);
      } else {
        assert.ok(parseTemplate(q.template).blanks.length >= 1, q.id);
      }
    }
  }
});


test("하루 실습은 2문제이고, 같은 날엔 같은 문제, 다음 날엔 다른 묶음이다", () => {
  assert.equal(DAILY_PRACTICE_COUNT, 2);
  for (const lang of ["Python", "Java", "C"] as const) {
    const a = todaysQuizzes(lang, 100);
    assert.equal(a.length, 2);
    assert.notEqual(a[0].id, a[1].id);
    assert.deepEqual(todaysQuizzes(lang, 100).map(q => q.id), a.map(q => q.id));
    assert.notDeepEqual(todaysQuizzes(lang, 101).map(q => q.id), a.map(q => q.id));
    assert.ok(a.every(q => BLANK_QUIZZES[lang].includes(q)));
  }
});
