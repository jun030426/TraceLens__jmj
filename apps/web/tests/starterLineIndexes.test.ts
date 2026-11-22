import assert from "node:assert/strict";
import test from "node:test";
import { starterLineIndexes } from "../src/starterLineIndexes.ts";

test("matches repeated starter lines once each and in order", () => {
  const lines = ["init", "second", "first", "first", "added"];
  const matched = starterLineIndexes(lines, "init\nfirst\nsecond\nfirst");
  assert.equal(matched.size, 3);
  assert.ok(matched.has(0) && !matched.has(4));
  assert.ok(!(matched.has(1) && matched.has(2) && matched.has(3)));
});

test("preserves indentation and ignores line endings, trailing space and blank lines", () => {
  assert.deepEqual([...starterLineIndexes(["", "  emit()", "emit() ", "end"], "emit()\r\nend")], [2, 3]);
  assert.deepEqual([...starterLineIndexes(["a", "a", "b"], "a\nb")], [0, 2]);
});
