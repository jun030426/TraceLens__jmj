import { test } from "node:test";
import assert from "node:assert/strict";
import { weaknessSummary, weaknessHeadline } from "../src/weakness.ts";
import { conceptStatus, type LearningConcept } from "../src/conceptProgress.ts";

function concept(
  state: NonNullable<LearningConcept["learning"]>["state"],
  sample = 5,
  correct = 0,
  weakness: number | null = null,
): LearningConcept {
  return {
    id: state,
    concept: state,
    in_scope: true,
    weeks: [1],
    valid_recent: sample,
    correct_recent: correct,
    mastered: state === "mastered",
    review_due: "2020-01-01",
    review_session_id: null,
    review_question_id: null,
    learning: {
      state,
      sample,
      correct,
      weakness,
      success_days: state === "mastered" ? 2 : 1,
      trend_points: null,
    },
  };
}
test("student cards use the professor evidence, sparse samples have no score", () => {
  const s = weaknessSummary([
    concept("mastered", 5, 4, 20),
    concept("insufficient", 2, 0),
    concept("review", 5, 1, 80),
    concept("no_data", 0, 0),
    concept("learning", 5, 5, 0),
  ]);
  assert.deepEqual(
    s.rings.map((r) => r.band),
    ["weak", "insufficient", "learning", "strong", "none"],
  );
  assert.deepEqual(
    s.rings.map((r) => r.pct),
    [80, null, 0, 20, null],
  );
  assert.match(weaknessHeadline(s), /복습이 필요한 개념이 1개/);
});
test("same-day success and untouched concepts never claim all concepts mastered", () => {
  assert.match(
    weaknessHeadline(
      weaknessSummary([concept("learning", 5, 5, 0), concept("no_data", 0)]),
    ),
    /다른 날/,
  );
  assert.match(
    weaknessHeadline(
      weaknessSummary([concept("mastered", 5, 4, 20), concept("no_data", 0)]),
    ),
    /아직 확인하지/,
  );
  assert.match(
    weaknessHeadline(weaknessSummary([concept("mastered", 5, 4, 20)])),
    /기준을 충족/,
  );
});
test("review reminders do not override the shared classification", () => {
  for (const state of [
    "mastered",
    "review",
    "insufficient",
    "learning",
    "no_data",
  ] as const)
    assert.equal(conceptStatus(concept(state), "2026-11-15"), state);
});
