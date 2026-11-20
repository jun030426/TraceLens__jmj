// 실행 기록(ExecutionTrace)을 화면용 공통 데이터(Recording)로 바꾸는 어댑터.
// 각 단계는 그 순간의 전체 상태(current)를 그대로 가지고, 직전 단계와의 차이(events·changes)를 덧붙인다.
// 모든 결과는 읽기 전용으로 얼린다 — 화면용 상태는 화면이 따로 관리한다.
import type { ExecutionTrace, TraceStep } from "../pythonTrace.ts";
import type { Observation, ObservationChanges, Recording } from "./contracts.ts";
import { buildEvents, variableChanges } from "./executionEvents.ts";

function deepFreeze<T>(value: T): T {
  if (value && typeof value === "object" && !Object.isFrozen(value)) {
    Object.freeze(value);
    for (const v of Object.values(value as Record<string, unknown>)) deepFreeze(v);
  }
  return value;
}

/** 소스가 같은지 빠르게 비교하는 해시 (보안용 아님) */
export function hashSource(source: string): string {
  let h = 2166136261;
  for (let i = 0; i < source.length; i++) {
    h ^= source.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return (h >>> 0).toString(16).padStart(8, "0");
}

function changesOf(prev: TraceStep | null, step: TraceStep): ObservationChanges {
  const vars = variableChanges(prev, step);
  const before = prev?.objects ?? {};
  const added: string[] = [];
  const changed: string[] = [];
  const removed: string[] = [];
  for (const [id, o] of Object.entries(step.objects)) {
    if (!(id in before)) added.push(id);
    else if (JSON.stringify(before[id]) !== JSON.stringify(o)) changed.push(id);
  }
  for (const id of Object.keys(before)) if (!(id in step.objects)) removed.push(id);
  const was = new Set((prev?.frames ?? []).map(f => f.id));
  const now = new Set(step.frames.map(f => f.id));
  return {
    variables: {
      added: vars.filter(v => v.kind === "added"),
      changed: vars.filter(v => v.kind === "changed"),
      removed: vars.filter(v => v.kind === "removed"),
    },
    objects: { added, changed, removed },
    enteredFrames: [...now].filter(id => !was.has(id)),
    exitedFrames: [...was].filter(id => !now.has(id)),
  };
}

export function adaptExecutionTrace(trace: ExecutionTrace, source: string): Recording {
  const steps: Observation[] = trace.steps.map((step, index) => {
    const prev = index > 0 ? trace.steps[index - 1] : null;
    const id = `step-${index}`;
    return {
      id,
      index,
      event: step.event,
      nextLine: step.nextLine,
      causedByLine: step.causedByLine,
      frames: step.frames,
      objects: step.objects,
      events: buildEvents(prev, prev ? `step-${index - 1}` : null, step, id),
      changes: changesOf(prev, step),
      stdout: step.stdout,
      ...(step.error ? { error: step.error } : {}),
      ...(step.returned ? { returned: step.returned } : {}),
    };
  });
  return deepFreeze({
    language: trace.language,
    source,
    sourceHash: hashSource(source),
    steps,
    status: trace.status,
    message: trace.message ?? null,
    error: trace.error ?? null,
    stdout: trace.stdout,
    blankStop: trace.blankStop ?? null,
  });
}
