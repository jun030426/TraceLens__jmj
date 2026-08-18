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
  /** 접힌 반복 구간에서 나온 스텝 — 필름은 전체를 재생하므로 자막은 필름 것이 정확하다 */
  folded?: boolean
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
  const indexOf = new Map(snaps.map((s, i) => [s.seq, i]))
  const steps: PlaybackStep[] = []

  // "X가 {v}로 초기화됩니다"를 대입 관측 직전 스팬에 붙이는 대본이 흔하다 —
  // 그 시점 스냅샷엔 값이 아직 없으므로, 몇 스냅 앞에서 처음 등장하는 값으로 치환한다.
  // 값은 여전히 실제 트레이스에서만 온다. 끝까지 없으면 그때가 '?'다.
  const resolveBinding = (seq: number, name: string): string => {
    const start = indexOf.get(seq)
    if (start === undefined) return '?'
    for (let i = start; i < Math.min(start + 6, snaps.length); i++) {
      const v = lookup(snaps[i], name)
      if (v) return valueLabel(v, snaps[i].objects)
    }
    return '?'
  }

  sp.chapters.forEach((ch, chapterIndex) => {
    for (const sc of ch.scenes) {
      let narration = sc.narration.template
      for (const [key, b] of Object.entries(sc.narration.bindings)) {
        narration = narration.replaceAll(`{${key}}`, resolveBinding(b.seq, b.name))
      }
      const durationMs = PACING_MS[sc.pacing]
      if (sc.pacing === 'fast' && sc.seqEnd > sc.seqStart) {
        const label = sc.repeat && sc.repeat > 1 ? `${narration} (총 ${sc.repeat}회 반복)` : narration
        steps.push({ seq: sc.seqStart, chapterIndex, primitive: sc.primitive, focus: sc.focus, narration: label, durationMs, folded: true })
        steps.push({ seq: sc.seqEnd, chapterIndex, primitive: sc.primitive, focus: sc.focus, narration: label, durationMs, folded: true })
      } else {
        steps.push({ seq: sc.seqStart, chapterIndex, primitive: sc.primitive, focus: sc.focus, narration, durationMs })
      }
    }
  })
  return steps
}
