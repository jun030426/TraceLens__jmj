import test from "node:test";
import assert from "node:assert/strict";
import {
  prioritySignals,
  reviewCounts,
  reviewState,
  reviewStudents,
  signalNote,
  type Signal,
} from "../src/professorWeakness.ts";
const signal = (
  id: string,
  state: string,
  weakness: number | null,
  sample = 5,
): Signal => ({
  id,
  name: id,
  state,
  weakness,
  sample,
  correct: weakness == null ? 0 : 5 - weakness / 20,
  success_days: 2,
  trend_points: null,
});
const student = (id: string, signals: Signal[], active = true) => ({
  id,
  name: id,
  active,
  concept_signals: signals,
  theory: { accuracy: 80 },
  last_activity_at: null,
});
const options = { search: "", concept: "", scope: "all", sort: "review" };
test("recent-five weakness, insufficient samples and no data remain distinct", () => {
  assert.equal(
    reviewState([signal("스택", "insufficient", null, 2)]),
    "insufficient",
  );
  assert.equal(reviewState([]), "no_data");
  assert.equal(reviewState([signal("스택", "no_data", null, 0)]), "no_data");
  assert.equal(
    reviewState([signal("큐", "mastered", 0), signal("스택", "review", 40)]),
    "review",
  );
  assert.match(
    signalNote(signal("스택", "insufficient", null, 2)),
    /아직 취약도를 판단하지 않아요/,
  );
});
test("priority sorts the worst reviewed concept first without mutating input", () => {
  const input = [
    signal("스택", "review", 40),
    signal("큐", "review", 80),
    signal("트리", "insufficient", null, 2),
  ];
  assert.deepEqual(
    prioritySignals(input).map((s) => s.id),
    ["큐", "스택", "트리"],
  );
  assert.equal(input[0].id, "스택");
  const people = [
    student("A", [input[0]]),
    student("B", [input[1]]),
    student("C", [input[2]]),
  ];
  assert.deepEqual(
    reviewStudents(people, options).map((s) => s.id),
    ["B", "A", "C"],
  );
  assert.equal(people[0].id, "A");
});
test("status counts partition students instead of double counting mixed concepts", () => {
  const rows = [
    student("A", [
      signal("스택", "review", 80),
      signal("큐", "insufficient", null, 1),
    ]),
    student("B", []),
    student("C", [signal("스택", "mastered", 0)]),
  ];
  assert.deepEqual(reviewCounts(rows), {
    all: 3,
    review: 1,
    insufficient: 0,
    learning: 0,
    mastered: 1,
    no_data: 1,
  });
  assert.deepEqual(reviewCounts(rows, "큐"), {
    all: 3,
    review: 0,
    insufficient: 1,
    learning: 0,
    mastered: 0,
    no_data: 2,
  });
});
test("concept filtering cannot borrow a student's weakness in a different concept", () => {
  const rows = [
    student("A", [signal("스택", "review", 80), signal("큐", "mastered", 0)]),
    student("B", [signal("큐", "review", 60)]),
  ];
  assert.deepEqual(
    reviewStudents(rows, { ...options, concept: "큐", scope: "review" }).map(
      (s) => s.id,
    ),
    ["B"],
  );
  assert.deepEqual(
    reviewStudents(rows, { ...options, search: "스택" }).map((s) => s.id),
    ["A"],
  );
  assert.deepEqual(
    reviewStudents(rows, { ...options, search: "스택", concept: "큐" }),
    [],
  );
});
test("same-day correct answers do not become multi-day mastery", () => {
  const item = { ...signal("스택", "learning", 0), success_days: 1 };
  assert.equal(reviewState([item]), "learning");
  assert.match(signalNote(item), /다른 날짜의 풀이/);
});
test("missing scores are not interpreted as zero weakness or low accuracy", () => {
  const rows = [
    student("기록 없음", []),
    {
      ...student("기록 있음", [signal("스택", "mastered", 20)]),
      theory: { accuracy: 100 },
    },
  ];
  rows[0].theory.accuracy = null as unknown as number;
  assert.deepEqual(
    reviewStudents(rows, { ...options, sort: "accuracy" }).map((s) => s.id),
    ["기록 있음", "기록 없음"],
  );
  assert.equal(
    reviewStudents(rows, { ...options, scope: "mastered" }).length,
    1,
  );
});
