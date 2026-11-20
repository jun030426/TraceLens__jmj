// 트레이서(Pyodide·JDI·gdb)가 보낸 증분 이벤트를 공통 실행 기록(ExecutionTrace)으로 바꾼다.
// 이벤트마다 그 순간의 전체 상태를 다시 쌓아 단계 하나로 만든다 — 화면은 단계의 전체 상태만 본다.
import type { ExecutionTrace, TraceLanguage, TraceObject, TraceStep, TraceValue } from '../pythonTrace.ts'
import { buildSnapshots } from './trace/snapshots.ts'
import type { ObjectSnap, TraceEvent, Value } from './trace/types.ts'

const objectId = (id: number) => `o${id}`
const frameId = (id: number) => `f${id}`

const toValue = (v: Value): TraceValue =>
  v.k === 'prim' ? { kind: 'primitive', text: v.v } : { kind: 'reference', object_id: objectId(v.id) }

function toObject(o: ObjectSnap): TraceObject {
  return {
    id: objectId(o.id),
    type: o.type,
    ...(o.items ? { items: o.items.map(toValue) } : {}),
    ...(o.entries ? { entries: o.entries.map(([k, v]) => [k, toValue(v)] as [string, TraceValue]) } : {}),
    ...(o.n !== undefined && o.items && o.n !== o.items.length ? { length: o.n } : {}),
    ...(o.truncated ? { truncated: true } : {}),
    ...(o.unsupported ? { unsupported: true } : {}),
  }
}

export function toExecutionTrace(
  language: TraceLanguage,
  events: TraceEvent[],
  opts: { clipped: boolean; error?: string; blankStop?: { blank: number; line: number } },
): ExecutionTrace {
  const snaps = buildSnapshots(events)
  const steps: TraceStep[] = snaps.map((s, i) => {
    const e = events[i]
    const objects: Record<string, TraceObject> = {}
    for (const o of s.objects.values()) objects[objectId(o.id)] = toObject(o)
    return {
      event: e.kind,
      causedByLine: e.causedByLine,
      nextLine: e.kind === 'return' || e.kind === 'exception' ? null : e.observedAtLine,
      frames: s.stack.map((f, k) => ({
        id: frameId(f.frameId),
        name: f.func,
        line: k === s.stack.length - 1 ? s.line : null,
        variables: [...f.locals].map(([name, v]) => ({ name, value: toValue(v) })),
      })),
      objects,
      stdout: s.stdout,
      ...(e.error ? { error: e.error } : {}),
      ...(e.returned ? { returned: toValue(e.returned) } : {}),
    }
  })
  return {
    language,
    status: opts.error ? 'error' : opts.clipped ? 'partial' : 'ok',
    steps,
    message: opts.clipped ? '실행이 길어 앞부분까지만 기록했어요.' : null,
    error: opts.error ?? null,
    stdout: snaps.length ? snaps[snaps.length - 1].stdout : '',
    ...(opts.blankStop ? { blankStop: opts.blankStop } : {}),
  }
}
