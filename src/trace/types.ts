export type Value =
  | { k: 'prim'; v: string; t: string }
  | { k: 'ref'; id: number }

export type ObjectSnap = {
  id: number
  type: string
  items?: Value[]
  entries?: [string, Value][]
  truncated?: boolean
  unsupported?: boolean
}

export type LocalsDelta = { name: string; op: 'set' | 'delete'; value?: Value }
export type ObjectsDelta = { op: 'set' | 'delete'; obj?: ObjectSnap; id?: number }

export type TraceEvent = {
  seq: number
  kind: 'line' | 'call' | 'return' | 'exception'
  frameId: number
  parentFrameId: number | null
  func: string
  causedByLine: number | null
  observedAtLine: number
  localsDelta: LocalsDelta[]
  objectsDelta: ObjectsDelta[]
  stdout: string
  error?: string
}

export type TraceResult = {
  events: TraceEvent[]
  clipped: boolean
  error?: string
}

export const MAX_EVENTS = 5000
export const EXEC_TIMEOUT_MS = 10000
