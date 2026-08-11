import type { TraceEvent } from '../trace/types'
import { buildSnapshots, aliasGroups } from '../trace/snapshots'

// Digest — LLM Director의 입력. 원본 트레이스의 안정 참조(DigestSpan)를 유지한 압축 요약.
export type DigestSpan = {
  spanId: string
  sourceSeqRange: [number, number]
  lines: [number, number]
  eventKinds: string[]
  funcs: string[]
  changedVars: string[]
  iterations?: number
  stdoutDelta?: string
  exception?: string
}

export type Digest = {
  spans: DigestSpan[]
  aliasNote?: string
}

export function buildDigest(events: TraceEvent[]): Digest {
  const spans: DigestSpan[] = []
  const lineCount = new Map<string, number>()
  let idCounter = 0
  let loopCounter = 0

  const singleSpan = (e: TraceEvent): DigestSpan => ({
    spanId: `s${idCounter++}`,
    sourceSeqRange: [e.seq, e.seq],
    lines: [e.causedByLine ?? e.observedAtLine, e.observedAtLine],
    eventKinds: [e.kind],
    funcs: [e.func],
    changedVars: e.localsDelta.map(d => d.name),
    ...(e.stdout ? { stdoutDelta: e.stdout } : {}),
    ...(e.error ? { exception: e.error } : {}),
  })

  let folding: DigestSpan | null = null
  for (const e of events) {
    const key = `${e.frameId}:${e.observedAtLine}`
    const n = (lineCount.get(key) ?? 0) + 1
    lineCount.set(key, n)
    if (n >= 3 && e.kind === 'line') {
      if (folding) {
        folding.sourceSeqRange[1] = e.seq
        folding.iterations = (folding.iterations ?? 1) + 1
        for (const d of e.localsDelta) {
          if (!folding.changedVars.includes(d.name)) folding.changedVars.push(d.name)
        }
        if (e.stdout) folding.stdoutDelta = (folding.stdoutDelta ?? '') + e.stdout
      } else {
        folding = { ...singleSpan(e), spanId: `loop_${loopCounter++}`, iterations: 1 }
      }
      continue
    }
    if (folding) { spans.push(folding); folding = null }
    spans.push(singleSpan(e))
  }
  if (folding) spans.push(folding)

  // aliasing 요약 — Director가 objectGraph를 고르도록 힌트
  const snaps = buildSnapshots(events)
  const seen = new Map<string, true>()
  const notes: string[] = []
  for (const s of snaps) {
    for (const g of aliasGroups(s)) {
      const label = g.names.slice().sort().join('/')
      if (!seen.has(label)) {
        seen.set(label, true)
        notes.push(`${label}는 같은 객체를 참조 (seq ${s.seq}부터)`)
      }
    }
  }

  return { spans, ...(notes.length ? { aliasNote: notes.join('; ') } : {}) }
}
