import assert from "node:assert/strict";
import test from "node:test";
import type { Classroom } from "../src/api.ts";
import {
  isSubmitted,
  materialWeeks,
  nextClassroom,
  weekLabel,
} from "../src/studentOverview.ts";

const rooms = ["a", "b"].map((id) => ({ section: { id } }) as Classroom);
const entry = (
  section_id: string,
  submitted: number,
  total = 3,
  day = "2026-10-12",
) => ({ id: section_id, section_id, submitted, total, day, pending: 0 });

test("an unfinished bundle takes priority over the first classroom", () => {
  assert.equal(
    nextClassroom(rooms, [entry("b", 0)], "2026-10-12", false)?.section.id,
    "b",
  );
  assert.equal(
    nextClassroom(rooms, [entry("b", 1)], "2026-10-12", false)?.section.id,
    "b",
  );
});
test("global completion leads to the completed classroom even if another is unfinished", () => {
  assert.equal(
    nextClassroom(rooms, [entry("a", 1), entry("b", 3)], "2026-10-12", true)
      ?.section.id,
    "b",
  );
});
test("old records and empty bundles do not imply today's completion", () => {
  assert.equal(
    nextClassroom(rooms, [entry("b", 1, 3, "2026-10-11")], "2026-10-12", false)
      ?.section.id,
    "a",
  );
  assert.equal(isSubmitted(entry("a", 0, 0)), false);
  assert.equal(isSubmitted(entry("a", 2, 2)), true);
  assert.equal(nextClassroom([], [], "2026-10-12", false), undefined);
});
test("week groups preserve published future files and include an empty current week", () => {
  assert.deepEqual(materialWeeks([16, 1, 4, 1], 6), [1, 4, 6, 16]);
  assert.deepEqual(materialWeeks([4, 1], null), [1, 4]);
  assert.deepEqual(materialWeeks([4, 1], 0), [1, 4]);
  assert.equal(weekLabel(null), "교수 지정 진도");
  assert.equal(weekLabel(0), "학기 시작 전");
});
