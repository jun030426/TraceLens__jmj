// 공통 변화 이벤트 — 두 실행 관측(스냅숏) 사이에서 "확인된" 상태 변화만 만든다.
// 알고리즘 이름이나 비교 의도처럼 기록에 없는 것은 만들지 않는다. 모호하면 array.snapshot으로 전체 상태를 넘긴다.
import type { TraceFrame, TraceObject, TraceStep, TraceValue } from "../pythonTrace.ts";

export type Binding = { frameId: string; name: string };

export type ArrayTarget = {
  objectId: string;
  /** 지금 이 배열을 직접 가리키는 변수들 (중첩 배열이면 비어 있을 수 있다) */
  bindings: Binding[];
  /** 직전 단계에서 가리키던 변수들 */
  previousBindings: Binding[];
};

type EventBase = {
  id: string;
  evidence: "snapshot-diff";
  fromStepId: string | null;
  toStepId: string;
  sourceLine: number | null;
};

export type SnapshotReason =
  | "first-observation"
  | "left-observation"
  | "partial-observation"
  | "ambiguous-edit"
  | "compound-edit"
  | "nested-change";

export type VisualizationEvent =
  | (EventBase & { type: "array.swap"; target: ArrayTarget; indices: [number, number]; before: [TraceValue, TraceValue]; after: [TraceValue, TraceValue] })
  | (EventBase & { type: "array.set"; target: ArrayTarget; index: number; before: TraceValue; after: TraceValue })
  | (EventBase & { type: "array.insert"; target: ArrayTarget; index: number; values: TraceValue[]; beforeLength: number; afterLength: number })
  | (EventBase & { type: "array.remove"; target: ArrayTarget; index: number; values: TraceValue[]; beforeLength: number; afterLength: number })
  | (EventBase & { type: "array.snapshot"; target: ArrayTarget; before: TraceObject | null; after: TraceObject | null; reason: SnapshotReason })
  | (EventBase & {
      type: "variable.change";
      change: { id: string; kind: "added" | "changed" | "removed"; frameId: string; name: string; before?: TraceValue; after?: TraceValue };
    });

/** 값 비교용 열쇠 — primitive는 표시 문자열, reference는 객체 id로 비교한다 */
export const valueKey = (v: TraceValue | undefined): string =>
  !v ? "∅" : v.kind === "reference" ? `r:${v.object_id ?? "?"}` : `${v.kind === "primitive" ? "p" : "u"}:${v.text ?? ""}`;

export const sameValue = (a: TraceValue | undefined, b: TraceValue | undefined) => valueKey(a) === valueKey(b);

export const isArrayObject = (o: TraceObject | undefined): o is TraceObject & { items: TraceValue[] } => !!o && Array.isArray(o.items);

/** 이 배열을 직접 가리키는 변수들 (모든 프레임) */
export function bindingsOf(frames: readonly TraceFrame[] | undefined, objectId: string): Binding[] {
  const out: Binding[] = [];
  for (const f of frames ?? [])
    for (const v of f.variables) if (v.value.kind === "reference" && v.value.object_id === objectId) out.push({ frameId: f.id, name: v.name });
  return out;
}

/** 어떤 변수에서든 이어져 닿는 배열인지 — 직접 변수가 없는 중첩 배열도 포함 */
function reachable(step: TraceStep): Set<string> {
  const seen = new Set<string>();
  const walk = (v: TraceValue) => {
    if (v.kind !== "reference" || !v.object_id || seen.has(v.object_id)) return;
    seen.add(v.object_id);
    const o = step.objects[v.object_id];
    o?.items?.forEach(walk);
    o?.entries?.forEach(([, x]) => walk(x));
  };
  for (const f of step.frames) for (const v of f.variables) walk(v.value);
  return seen;
}

type ArrayDiff =
  | { kind: "none" }
  | { kind: "swap"; i: number; j: number }
  | { kind: "set"; index: number }
  | { kind: "insert"; index: number; count: number }
  | { kind: "remove"; index: number; count: number }
  | { kind: "snapshot"; reason: SnapshotReason };

/** 한 배열의 두 관측 사이 변화를 하나로 확정할 수 있으면 그 변화를, 아니면 snapshot 이유를 돌려준다 */
export function diffArray(before: TraceObject & { items: TraceValue[] }, after: TraceObject & { items: TraceValue[] }): ArrayDiff {
  if (before.truncated || after.truncated) {
    const a = before.items.map(valueKey).join("|");
    const b = after.items.map(valueKey).join("|");
    return a === b && (before.length ?? before.items.length) === (after.length ?? after.items.length) ? { kind: "none" } : { kind: "snapshot", reason: "partial-observation" };
  }
  const A = before.items.map(valueKey);
  const B = after.items.map(valueKey);
  if (A.length === B.length) {
    const diffs = A.map((x, i) => (x === B[i] ? -1 : i)).filter(i => i >= 0);
    if (diffs.length === 0) return { kind: "none" };
    if (diffs.length === 1) return { kind: "set", index: diffs[0] };
    if (diffs.length === 2) {
      const [i, j] = diffs;
      if (A[i] === B[j] && A[j] === B[i]) return { kind: "swap", i, j };
    }
    return { kind: "snapshot", reason: "compound-edit" };
  }
  const grow = B.length > A.length;
  const long = grow ? B : A;
  const short = grow ? A : B;
  const k = long.length - short.length;
  // 앞부분 q개가 같고 뒷부분이 k칸 밀려 같은 자리 q를 모두 찾는다 — 정확히 하나일 때만 삽입·제거로 확정
  const spots: number[] = [];
  for (let q = 0; q <= short.length; q++) {
    let ok = true;
    for (let x = 0; x < q && ok; x++) ok = long[x] === short[x];
    for (let x = q; x < short.length && ok; x++) ok = long[x + k] === short[x];
    if (ok) spots.push(q);
  }
  if (spots.length === 1) return grow ? { kind: "insert", index: spots[0], count: k } : { kind: "remove", index: spots[0], count: k };
  return { kind: "snapshot", reason: spots.length > 1 ? "ambiguous-edit" : "compound-edit" };
}

const frameVars = (f: TraceFrame) => new Map(f.variables.map(v => [v.name, v.value]));

/** 두 관측 사이의 변수 변화 (프레임 진입·퇴장 포함) */
export function variableChanges(prev: TraceStep | null, step: TraceStep) {
  const out: { id: string; kind: "added" | "changed" | "removed"; frameId: string; name: string; before?: TraceValue; after?: TraceValue }[] = [];
  const before = new Map((prev?.frames ?? []).map(f => [f.id, f]));
  const after = new Map(step.frames.map(f => [f.id, f]));
  for (const f of step.frames) {
    const was = before.get(f.id);
    const old = was ? frameVars(was) : new Map<string, TraceValue>();
    for (const v of f.variables) {
      const id = `${f.id}:${v.name}`;
      const b = old.get(v.name);
      if (!b) out.push({ id, kind: "added", frameId: f.id, name: v.name, after: v.value });
      else if (!sameValue(b, v.value)) out.push({ id, kind: "changed", frameId: f.id, name: v.name, before: b, after: v.value });
    }
    if (was) {
      const now = frameVars(f);
      for (const v of was.variables) if (!now.has(v.name)) out.push({ id: `${f.id}:${v.name}`, kind: "removed", frameId: f.id, name: v.name, before: v.value });
    }
  }
  for (const f of prev?.frames ?? []) {
    if (after.has(f.id)) continue;
    for (const v of f.variables) out.push({ id: `${f.id}:${v.name}`, kind: "removed", frameId: f.id, name: v.name, before: v.value });
  }
  return out;
}

/**
 * 직전 관측(prev) → 이번 관측(step) 사이의 공통 이벤트.
 * 같은 배열을 가리키는 별칭이 여럿이어도 배열 이벤트는 객체마다 하나다.
 */
export function buildEvents(prev: TraceStep | null, prevId: string | null, step: TraceStep, stepId: string): VisualizationEvent[] {
  const events: VisualizationEvent[] = [];
  const base = () => ({ id: `${stepId}:event:${events.length + 1}`, evidence: "snapshot-diff" as const, fromStepId: prevId, toStepId: stepId, sourceLine: step.causedByLine });
  const target = (objectId: string): ArrayTarget => ({ objectId, bindings: bindingsOf(step.frames, objectId), previousBindings: bindingsOf(prev?.frames, objectId) });
  const nowSeen = reachable(step);
  const wasSeen = prev ? reachable(prev) : new Set<string>();

  for (const id of nowSeen) {
    const after = step.objects[id];
    if (!isArrayObject(after)) continue;
    const before = prev && wasSeen.has(id) ? prev.objects[id] : undefined;
    if (!isArrayObject(before)) {
      events.push({ ...base(), type: "array.snapshot", target: target(id), before: null, after, reason: "first-observation" });
      continue;
    }
    const d = diffArray(before, after);
    if (d.kind === "none") continue;
    if (d.kind === "swap")
      events.push({ ...base(), type: "array.swap", target: target(id), indices: [d.i, d.j], before: [before.items[d.i], before.items[d.j]], after: [after.items[d.i], after.items[d.j]] });
    else if (d.kind === "set") events.push({ ...base(), type: "array.set", target: target(id), index: d.index, before: before.items[d.index], after: after.items[d.index] });
    else if (d.kind === "insert")
      events.push({ ...base(), type: "array.insert", target: target(id), index: d.index, values: after.items.slice(d.index, d.index + d.count), beforeLength: before.items.length, afterLength: after.items.length });
    else if (d.kind === "remove")
      events.push({ ...base(), type: "array.remove", target: target(id), index: d.index, values: before.items.slice(d.index, d.index + d.count), beforeLength: before.items.length, afterLength: after.items.length });
    else events.push({ ...base(), type: "array.snapshot", target: target(id), before, after, reason: d.reason });
  }
  if (prev)
    for (const id of wasSeen) {
      if (nowSeen.has(id)) continue;
      const before = prev.objects[id];
      if (isArrayObject(before)) events.push({ ...base(), type: "array.snapshot", target: target(id), before, after: null, reason: "left-observation" });
    }
  for (const change of variableChanges(prev, step)) events.push({ ...base(), type: "variable.change", change });
  return events;
}
