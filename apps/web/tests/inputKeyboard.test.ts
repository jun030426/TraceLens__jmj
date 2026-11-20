import assert from "node:assert/strict";
import test from "node:test";
import { isComposingInput } from "../src/inputKeyboard.ts";

test("Korean composition-confirming Enter must not submit or commit a blank", () => {
  assert.equal(isComposingInput({ isComposing: true, keyCode: 13 }), true);
});
test("Safari's late confirming Enter is guarded even after compositionend", () => {
  assert.equal(isComposingInput({ isComposing: false, keyCode: 229 }), true);
});
test("An ordinary Enter remains available for submission after composition", () => {
  assert.equal(isComposingInput({ isComposing: false, keyCode: 13 }), false);
});
test("A normal key does not enter the IME guard", () => {
  assert.equal(isComposingInput({ isComposing: false, keyCode: 65 }), false);
});
