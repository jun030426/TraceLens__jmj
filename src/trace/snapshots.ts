import type { TraceEvent, Value, ObjectSnap } from './types'

export type FrameState = {
  frameId: number
  func: string
  parentFrameId: number | null
  locals: Map<string, Value>
}

export type Snapshot = {
  seq: number
  line: number
  stack: FrameState[]
  objects: Map<number, ObjectSnap>
  stdout: string
}

export function buildSnapshots(events: TraceEvent[]): Snapshot[] {
  const snaps: Snapshot[] = []
  let stack: FrameState[] = []
  let objects = new Map<number, ObjectSnap>()
  let stdout = ''

  const cloneStack = () => stack.map(f => ({ ...f, locals: new Map(f.locals) }))

  for (const e of events) {
    if (e.kind === 'call') {
      stack.push({ frameId: e.frameId, func: e.func, parentFrameId: e.parentFrameId, locals: new Map() })
    }
    let frame = stack.find(f => f.frameId === e.frameId)
    if (!frame) {
      frame = { frameId: e.frameId, func: e.func, parentFrameId: e.parentFrameId, locals: new Map() }
      stack.push(frame)
    }
    for (const d of e.localsDelta) {
      if (d.op === 'set' && d.value) frame.locals.set(d.name, d.value)
      else frame.locals.delete(d.name)
    }
    if (e.objectsDelta.length) {
      objects = new Map(objects)
      for (const d of e.objectsDelta) {
        if (d.op === 'set' && d.obj) objects.set(d.obj.id, d.obj)
        else if (d.id !== undefined) objects.delete(d.id)
      }
    }
    stdout += e.stdout
    if (e.kind === 'return') stack = stack.filter(f => f.frameId !== e.frameId)
    snaps.push({
      seq: e.seq,
      line: e.causedByLine ?? e.observedAtLine,
      stack: cloneStack(),
      objects,
      stdout,
    })
  }
  return snaps
}

export function aliasGroups(s: Snapshot): { id: number; names: string[] }[] {
  const byId = new Map<number, string[]>()
  for (const f of s.stack) {
    for (const [name, v] of f.locals) {
      if (v.k === 'ref') byId.set(v.id, [...(byId.get(v.id) ?? []), name])
    }
  }
  return [...byId.entries()]
    .filter(([, names]) => names.length > 1)
    .map(([id, names]) => ({ id, names }))
}
