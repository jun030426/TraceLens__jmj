import assert from "node:assert/strict";
import test from "node:test";
import {
  reviewReason,
  suggestedConcepts,
  type LearningConcept,
} from "../src/conceptProgress.ts";

const concept = (changes: Partial<LearningConcept> = {}): LearningConcept => ({
  id: "a",
  concept: "배열",
  weeks: [1],
  in_scope: true,
  valid_recent: 0,
  correct_recent: 0,
  mastered: false,
  review_due: null,
  review_session_id: null,
  review_question_id: null,
  ...changes,
});

test("future concepts and missing independent evidence never become review recommendations", () => {
  assert.equal(
    reviewReason(
      concept({ in_scope: false, valid_recent: 3, review_due: "2026-01-01" }),
      "2026-10-12",
    ),
    "",
  );
  assert.equal(
    reviewReason(concept({ review_due: "2026-01-01" }), "2026-10-12"),
    "",
  );
});
test("recommendations explain recorded errors or an arrived review date", () => {
  assert.match(
    reviewReason(concept({ valid_recent: 3, correct_recent: 2 }), "2026-10-12"),
    /오답/,
  );
  assert.equal(
    reviewReason(
      concept({ valid_recent: 3, correct_recent: 3, review_due: "2026-10-13" }),
      "2026-10-12",
    ),
    "",
  );
  assert.match(
    reviewReason(
      concept({ valid_recent: 3, correct_recent: 3, review_due: "2026-10-12" }),
      "2026-10-12",
    ),
    /권장일/,
  );
});
test("with no review due, current-week concepts are shown without inventing a weakness", () => {
  const result = suggestedConcepts(
    [
      concept(),
      concept({ id: "b", weeks: [6] }),
      concept({ id: "c", weeks: [16], in_scope: false }),
    ],
    "2026-10-12",
    6,
  );
  assert.equal(result.review, false);
  assert.deepEqual(
    result.items.map((item) => item.id),
    ["b"],
  );
  assert.equal(
    suggestedConcepts([concept({ in_scope: false })], "2026-10-12", 6).items
      .length,
    0,
  );
});
