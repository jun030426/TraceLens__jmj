import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import type { ExecutionTrace, TraceObject, TraceStep, TraceValue } from "../src/pythonTrace.ts";
import { buildEvents, diffArray } from "../src/visualization/executionEvents.ts";
import { initialPlayback, playbackReducer } from "../src/visualization/playback.ts";
import { adaptExecutionTrace } from "../src/visualization/traceAdapter.ts";
import { toExecutionTrace } from "../src/visualizer/toExecutionTrace.ts";

const p = (text: string): TraceValue => ({ kind: "primitive", text });
const list = (...xs: (string | number)[]) => ({ id: "o1", type: "list", items: xs.map(x => p(String(x))) });
const step = (items: TraceObject, extra: Record<string, TraceValue> = {}): TraceStep => ({
  event: "line",
  causedByLine: 4,
  nextLine: 5,
  frames: [{ id: "f1", name: "<module>", line: 4, variables: [{ name: "numbers", value: { kind: "reference", object_id: "o1" } }, ...Object.entries(extra).map(([name, value]) => ({ name, value }))] }],
  objects: { o1: items },
  stdout: "",
});
const fixture = (name: string) => JSON.parse(readFileSync(new URL(`./fixtures/${name}.trace.json`, import.meta.url), "utf8"));

test("두 원소가 맞바뀌면 array.swap 하나 (문서 예시)", () => {
  const events = buildEvents(step(list(3, 410, 1, 5)), "step-7", step(list(3, 1, 410, 5)), "step-8");
  const swap = events.filter(e => e.type === "array.swap");
  assert.equal(swap.length, 1);
  const e = swap[0];
  assert.ok(e.type === "array.swap");
  assert.deepEqual(e.indices, [1, 2]);
  assert.deepEqual(e.before.map(v => v.text), ["410", "1"]);
  assert.deepEqual(e.after.map(v => v.text), ["1", "410"]);
  assert.deepEqual(e.target.bindings, [{ frameId: "f1", name: "numbers" }]);
  assert.equal(e.fromStepId, "step-7");
  assert.equal(e.sourceLine, 4);
});

test("한 칸 변경·삽입·제거·모호·복합 변경을 구분한다", () => {
  const d = (a: (string | number)[], b: (string | number)[]) => diffArray(list(...a), list(...b));
  assert.deepEqual(d([1, 2, 3], [1, 9, 3]), { kind: "set", index: 1 });
  assert.deepEqual(d([1, 2, 3], [1, 2, 3]), { kind: "none" });
  assert.deepEqual(d([1, 3], [1, 2, 3]), { kind: "insert", index: 1, count: 1 });
  assert.deepEqual(d([1, 2, 3], [1, 3]), { kind: "remove", index: 1, count: 1 });
  // 같은 값이 이웃에 있으면 어느 자리에 들어갔는지 알 수 없다
  assert.deepEqual(d([5, 5], [5, 5, 5]), { kind: "snapshot", reason: "ambiguous-edit" });
  assert.deepEqual(d([1, 2, 3], [3, 1, 2]), { kind: "snapshot", reason: "compound-edit" });
  // 같은 값끼리 바뀌면 상태가 같으므로 swap이 없다
  assert.deepEqual(d([7, 7], [7, 7]), { kind: "none" });
});

test("빈 배열·첫 관측·변수 변화", () => {
  const first = buildEvents(null, null, step(list(), { n: p("0") }), "step-0");
  assert.ok(first.some(e => e.type === "array.snapshot" && e.reason === "first-observation"));
  assert.ok(first.some(e => e.type === "variable.change" && e.change.kind === "added" && e.change.name === "n"));
  const next = buildEvents(step(list(), { n: p("0") }), "step-0", step(list(), { n: p("1") }), "step-1");
  const change = next.find(e => e.type === "variable.change");
  assert.ok(change && change.type === "variable.change" && change.change.kind === "changed" && change.change.before?.text === "0");
});

test("Java·C fixture가 같은 계약으로 바뀐다", () => {
  for (const [name, lang] of [["java-bubble", "java"], ["c-list", "c"]] as const) {
    const { code, events, error } = fixture(name);
    const trace: ExecutionTrace = toExecutionTrace(lang, events, { clipped: false, error });
    const rec = adaptExecutionTrace(trace, code);
    assert.equal(rec.steps.length, events.length);
    assert.equal(rec.status, "error");
    assert.ok(Object.isFrozen(rec.steps[0]));
    assert.equal(rec.steps[0].id, "step-0");
    for (const s of rec.steps) for (const e of s.events) assert.equal(e.toStepId, s.id);
  }
  const { code, events } = fixture("java-bubble");
  const rec = adaptExecutionTrace(toExecutionTrace("java", events, { clipped: false }), code);
  assert.ok(rec.steps.some(s => s.events.some(e => e.type === "array.swap" || e.type === "array.set")), "버블 정렬에서 배열 변화가 보인다");
});

test("재생 엔진: 마지막에서 재생하면 처음부터, 이동하면 재생이 멈춘다", () => {
  const r = playbackReducer(3);
  let s = initialPlayback();
  s = r(s, { type: "play" });
  assert.equal(s.playing, true);
  s = r(s, { type: "tick" });
  s = r(s, { type: "tick" });
  assert.equal(s.index, 2);
  assert.equal(s.playing, false);
  s = r(s, { type: "play" });
  assert.equal(s.index, 0);
  assert.equal(s.transition.kind, "restart");
  s = r(s, { type: "next" });
  assert.equal(s.playing, false);
  assert.equal(s.transition.kind, "next");
  const rev = s.transition.revision;
  s = r(s, { type: "seek", index: 99 });
  assert.equal(s.index, 2);
  assert.equal(s.transition.revision, rev + 1);
  s = r(s, { type: "interval", ms: 5 });
  assert.equal(s.intervalMs, 100);
  assert.equal(r(initialPlayback(), { type: "play" }).playing, true);
  assert.equal(playbackReducer(0)(initialPlayback(), { type: "play" }).playing, false);
});
