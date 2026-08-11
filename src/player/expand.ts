import type { Screenplay, PrimitiveKind } from '../screenplay/types'
import type { Snapshot } from '../trace/snapshots'
import type { Value, ObjectSnap } from '../trace/types'

export type PlaybackStep = {
  seq: number
  chapterIndex: number
  primitive: PrimitiveKind
  focus: string[]
  narration: string
  durationMs: number
}

export const PACING_MS = { slow: 1800, normal: 1000, fast: 180 } as const

export function valueLabel(v: Value | undefined, objects: Map<number, ObjectSnap>): string {
  if (!v) return '?'
  if (v.k === 'prim') return v.v
  const o = objects.get(v.id)
  if (!o) return '객체'
  if (o.items) return `[${o.items.map(x => valueLabel(x, objects)).join(', ')}${o.truncated ? ', …' : ''}]`
  if (o.entries) return `{${o.entries.map(([k, x]) => `${k}: ${valueLabel(x, objects)}`).join(', ')}}`
  return o.type
}

export function lookup(snap: Snapshot, name: string): Value | undefined {
  for (let i = snap.stack.length - 1; i >= 0; i--) {
    const v = snap.stack[i].locals.get(name)
    if (v) return v
  }
  return undefined
}

export function expandScreenplay(sp: Screenplay, snaps: Snapshot[]): PlaybackStep[] {
  const bySeq = new Map(snaps.map(s => [s.seq, s]))
  const steps: PlaybackStep[] = []
  sp.chapters.forEach((ch, chapterIndex) => {
    for (const sc of ch.scenes) {
      let narration = sc.narration.template
      for (const [key, b] of Object.entries(sc.narration.bindings)) {
        const snap = bySeq.get(b.seq)
        narration = narration.replaceAll(`{${key}}`, snap ? valueLabel(lookup(snap, b.name), snap.objects) : '?')
      }
      const durationMs = PACING_MS[sc.pacing]
      if (sc.pacing === 'fast' && sc.seqEnd > sc.seqStart) {
        const label = `${narration} (×${sc.repeat ?? sc.seqEnd - sc.seqStart + 1}회)`
        steps.push({ seq: sc.seqStart, chapterIndex, primitive: sc.primitive, focus: sc.focus, narration: label, durationMs })
        steps.push({ seq: sc.seqEnd, chapterIndex, primitive: sc.primitive, focus: sc.focus, narration: label, durationMs })
      } else {
        steps.push({ seq: sc.seqStart, chapterIndex, primitive: sc.primitive, focus: sc.focus, narration, durationMs })
      }
    }
  })
  return steps
}
