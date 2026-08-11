import type { Digest, DigestSpan } from '../digest/buildDigest'
import type { Screenplay, Scene, PrimitiveKind, Pacing } from '../screenplay/types'

// LLM 출력(spanRef 기반) → 검증 → 기존 Screenplay 타입으로 결정적 치환.
// 핵심 계약: LLM은 seq 숫자를 쓸 수 없다 — seq는 여기서 DigestSpan으로부터만 부여된다.

export class ValidationError extends Error {}

const PRIMITIVES: PrimitiveKind[] = ['variables', 'callStack', 'sequence', 'objectGraph', 'generic']
const PACINGS: Pacing[] = ['slow', 'normal', 'fast']

type RawBinding = { name?: unknown }
type RawScene = {
  spanRef?: unknown
  primitive?: unknown
  focus?: unknown
  pacing?: unknown
  narration?: { template?: unknown; bindings?: Record<string, RawBinding> }
}
type RawScreenplay = { chapters?: { title?: unknown; scenes?: RawScene[] }[] }

export function resolveScreenplay(raw: unknown, digest: Digest): Screenplay {
  const doc = raw as RawScreenplay
  if (!doc || !Array.isArray(doc.chapters) || doc.chapters.length === 0)
    throw new ValidationError('chapters 배열이 필요합니다')

  const byId = new Map<string, DigestSpan>(digest.spans.map(s => [s.spanId, s]))
  let lastEnd = -1
  const chapters = doc.chapters.map((ch, ci) => {
    if (typeof ch.title !== 'string' || !Array.isArray(ch.scenes) || ch.scenes.length === 0)
      throw new ValidationError(`챕터 ${ci}: title과 scenes가 필요합니다`)
    const scenes: Scene[] = ch.scenes.map((sc, si) => {
      const where = `챕터 ${ci} 장면 ${si}`
      if (typeof sc.spanRef !== 'string' || !byId.has(sc.spanRef))
        throw new ValidationError(`${where}: 존재하지 않는 spanRef (${String(sc.spanRef)})`)
      const span = byId.get(sc.spanRef)!
      if (span.sourceSeqRange[0] <= lastEnd)
        throw new ValidationError(`${where}: 실행 순서를 어기는 배열 (spanRef ${sc.spanRef})`)
      lastEnd = span.sourceSeqRange[1]

      if (typeof sc.primitive !== 'string' || !PRIMITIVES.includes(sc.primitive as PrimitiveKind))
        throw new ValidationError(`${where}: 허용되지 않은 primitive (${String(sc.primitive)})`)
      const pacing: Pacing = PACINGS.includes(sc.pacing as Pacing) ? (sc.pacing as Pacing) : 'normal'

      const template = typeof sc.narration?.template === 'string' ? sc.narration.template : ''
      if (!template) throw new ValidationError(`${where}: narration.template이 필요합니다`)
      const bindings: Scene['narration']['bindings'] = {}
      for (const [key, b] of Object.entries(sc.narration?.bindings ?? {})) {
        if (typeof b?.name !== 'string') throw new ValidationError(`${where}: 바인딩 ${key}에 name이 필요합니다`)
        bindings[key] = { seq: span.sourceSeqRange[1], name: b.name }
      }
      for (const m of template.matchAll(/\{(\w+)\}/g)) {
        if (!bindings[m[1]]) throw new ValidationError(`${where}: {${m[1]}}에 대한 바인딩이 없습니다`)
      }

      const focus = Array.isArray(sc.focus) ? sc.focus.filter((f): f is string => typeof f === 'string') : []
      return {
        seqStart: span.sourceSeqRange[0],
        seqEnd: span.sourceSeqRange[1],
        primitive: sc.primitive as PrimitiveKind,
        focus,
        pacing,
        ...(span.iterations && span.iterations > 1 ? { repeat: span.iterations } : {}),
        narration: { template, bindings },
      }
    })
    return { title: ch.title as string, scenes }
  })

  return { chapters }
}
