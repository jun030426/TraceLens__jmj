// 오류 장면 설명 — 예외 문구와 그 순간 장면만으로 "어디서·왜"를 만든다
import test from "node:test";
import assert from "node:assert/strict";
import { explainError } from "../src/visualization/screen/errorModel.ts";
import { EMPTY_SCENE, type Scene } from "../src/visualization/screen/sceneModel.ts";

const scene = (rows: { id: string; names: string[]; len: number }[]): Scene => ({
  ...EMPTY_SCENE,
  rows: rows.map(r => ({ objectId: r.id, names: r.names, cells: Array.from({ length: r.len }, (_, i) => ({ text: String(i), num: i })), hidden: 0, type: "list" })),
});

test("Java 범위 밖: 번호와 길이로 그 배열의 없는 칸을 짚는다", () => {
  const e = explainError("ArrayIndexOutOfBoundsException: Index 5 out of bounds for length 4", scene([{ id: "1", names: ["arr"], len: 4 }, { id: "2", names: ["b"], len: 6 }]));
  assert.equal(e.kind, "index");
  assert.equal(e.title, "5번 칸은 없어요");
  assert.deepEqual(e.target, { objectId: "1", index: 5, length: 4 });
  assert.match(e.why, /arr에는 칸이 0번부터 3번까지/);
});

test("Python 범위 밖: 번호가 없으면 배열이 하나일 때만 짚고, 여럿이면 짚지 않는다", () => {
  const one = explainError("IndexError: list index out of range", scene([{ id: "1", names: ["nums"], len: 3 }]));
  assert.equal(one.target?.objectId, "1");
  assert.equal(one.target?.index, undefined);
  const two = explainError("IndexError: list index out of range", scene([{ id: "1", names: ["a"], len: 3 }, { id: "2", names: ["b"], len: 3 }]));
  assert.equal(two.target, undefined);
});

test("없는 이름·0 나누기·null·그 밖의 오류", () => {
  const n = explainError("NameError: name 'total' is not defined", EMPTY_SCENE);
  assert.equal(n.kind, "name");
  assert.equal(n.target?.varName, "total");
  assert.equal(explainError("ZeroDivisionError: division by zero", EMPTY_SCENE).kind, "zero");
  assert.equal(explainError("ArithmeticException: / by zero", EMPTY_SCENE).kind, "zero");
  assert.equal(explainError("SIGSEGV: Segmentation fault", EMPTY_SCENE).kind, "null");
  const o = explainError("OSError: disk", EMPTY_SCENE);
  assert.equal(o.kind, "other");
  assert.equal(o.raw, "OSError: disk");
});
