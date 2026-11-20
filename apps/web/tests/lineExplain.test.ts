// 시각화 설명 문장 — 방금 실행한 줄을 학생 말로
import test from "node:test";
import assert from "node:assert/strict";
import { blockEnd, explainLine, ieyo, substitute } from "../src/visualization/screen/lineExplain.ts";
import type { Observation } from "../src/visualization/contracts.ts";

const prim = (text: string) => ({ kind: "primitive" as const, text });
function obs(caused: number | null, next: number | null, vars: Record<string, string> = {}, stdout = "", nums?: number[]): Observation {
  const variables = Object.entries(vars).map(([name, v]) => ({ name, value: prim(v) }));
  const objects: Observation["objects"] = {};
  if (nums) { objects.o1 = { id: "o1", type: "list", items: nums.map(n => prim(String(n))) }; variables.push({ name: "nums", value: { kind: "reference", object_id: "o1" } as never }); }
  return {
    id: "s", index: 1, event: "line", nextLine: next, causedByLine: caused,
    frames: [{ id: "f", name: "<module>", line: next, variables }], objects, events: [],
    changes: { variables: { added: [], changed: [], removed: [] }, objects: { added: [], changed: [], removed: [] }, enteredFrames: [], exitedFrames: [] },
    stdout,
  };
}

const PY = ["nums = [5, 2, 4, 1]", "n = len(nums)", "for i in range(n - 1):", "    for j in range(n - 1 - i):", "        if nums[j] > nums[j + 1]:", "            nums[j], nums[j + 1] = nums[j + 1], nums[j]", "print(nums)"].join("\n");

test("블록 끝은 들여쓰기로 찾는다", () => {
  const lines = PY.split("\n");
  assert.equal(blockEnd(lines, 3), 6);
  assert.equal(blockEnd(lines, 5), 6);
});

test("조건이 참이면 안으로, 거짓이면 건너뛴다고 말하고 값으로 바꿔 보여 준다", () => {
  const t = explainLine(PY, obs(5, 6, { j: "0" }, "", [5, 2, 4, 1]), null)!;
  assert.equal(t.kind, "cond-true");
  assert.match(t.text, /참이에요/);
  assert.equal(t.detail, "5 > 2");
  const f = explainLine(PY, obs(5, 4, { j: "1" }, "", [2, 5, 4, 1]), null)!;
  assert.equal(f.kind, "cond-false");
  assert.equal(f.detail, "5 > 4");
});

test("for 반복: 들어갈 때 변수 값, 끝날 때 끝난다고 말한다", () => {
  assert.match(explainLine(PY, obs(4, 5, { j: "2" }), null)!.text, /j이\(가\) 2일 때/);
  assert.equal(explainLine(PY, obs(4, 3, { j: "2" }), null)!.kind, "loop-out");
});

test("대입·바꾸기·출력", () => {
  assert.match(explainLine(PY, obs(2, 3, { n: "4" }), null)!.text, /len\(nums\)을\(를\) 계산하면 4예요\. 그 값을 n에 저장했어요/);
  assert.match(explainLine(PY, obs(6, 4, { j: "0" }), null)!.text, /서로 바꿨어요/);
  const prev = obs(6, 7, {}, "");
  assert.match(explainLine(PY, obs(7, null, {}, "[1, 2, 4, 5]\n"), prev)!.text, /"\[1, 2, 4, 5\]"을\(를\) 출력/);
});

test("Java: for(;;) 조건, if 괄호, i++", () => {
  const J = ["int[] a = {3, 1};", "for (int i = 0; i < a.length; i++) {", "    if (a[i] > 2) {", "        a[i] = 0;", "    }", "}", "System.out.println(a[0]);"].join("\n");
  assert.equal(explainLine(J, obs(2, 3, { i: "0" }), null)!.kind, "loop-in");
  assert.equal(explainLine(J, obs(2, 7, { i: "2" }), null)!.kind, "loop-out");
  assert.equal(explainLine(J, obs(3, 5, { i: "1" }), null)!.kind, "cond-false");
});

test("괄호 짝이 안 맞으면 벗기지 않는다", () => {
  const t = explainLine("x = 1\nif (x) and (x > 0):\n    x = 2\n", obs(2, 3, { x: "1" }), null)!;
  assert.match(t.text, /\(x\) 그리고 \(x > 0\)/);
  assert.equal(substitute("x > 0", new Map([["x", prim("1")]]), obs(1, 2)), "1 > 0");
});

test("숫자 뒤 이에요/예요", () => {
  assert.equal(ieyo("4"), "4예요");
  assert.equal(ieyo("175"), "175예요");
  assert.equal(ieyo("80"), "80이에요");
  assert.equal(ieyo("83.25"), "83.25예요");
  assert.equal(ieyo("333"), "333이에요");
  assert.equal(ieyo("10"), "10이에요");
});

test("반복 줄: 위에서 처음 들어오면 '시작', 몸통에서 돌아오면 '한 번 더'", () => {
  const start = explainLine(PY, obs(4, 5, { j: "0" }), obs(3, 4))!;
  assert.match(start.text, /^반복을 시작해요\. 처음에는 j이\(가\) 0일 때/);
  const again = explainLine(PY, obs(4, 5, { j: "1" }), obs(6, 4))!;
  assert.match(again.text, /^반복을 한 번 더 해요\. 이번에는 j이\(가\) 1일 때/);
  assert.match(explainLine(PY, obs(4, 3, { j: "2" }), obs(5, 4))!.text, /j에 넣을 값을 다 썼어요/);
});
