import type { Digest, DigestSpan } from '../digest/buildDigest'
import type { Screenplay, Chapter, Scene, PrimitiveKind, Pacing, DirectingVerb, Staging } from '../screenplay/types'

// LLM 출력(spanRef 기반) → 검증 → 기존 Screenplay 타입으로 결정적 치환.
// 핵심 계약: LLM은 seq 숫자를 쓸 수 없다 — seq는 여기서 DigestSpan으로부터만 부여된다.

export class ValidationError extends Error {}

const PRIMITIVES: PrimitiveKind[] = ['variables', 'callStack', 'sequence', 'objectGraph', 'generic']
const PACINGS: Pacing[] = ['slow', 'normal', 'fast']
const VERBS: DirectingVerb[] = ['zoom', 'hold', 'skip']

type RawBinding = { name?: unknown }
type RawScene = {
  spanRef?: unknown
  primitive?: unknown
  focus?: unknown
  pacing?: unknown
  direction?: unknown
  narration?: { template?: unknown; bindings?: Record<string, RawBinding> }
}
type RawScreenplay = {
  chapters?: { title?: unknown; scenes?: RawScene[] }[]
  staging?: { grid?: unknown; noGrid?: unknown }
}

// staging — 변수명 선택만 받는다. digest에 등장한 이름만 통과 (지어낸 이름 차단).
function resolveStaging(raw: RawScreenplay, digest: Digest): Staging | undefined {
  const known = new Set(digest.spans.flatMap(s => s.changedVars))
  const names = (v: unknown): string[] =>
    Array.isArray(v) ? [...new Set(v.filter((n): n is string => typeof n === 'string' && known.has(n)))] : []
  const grid = names(raw.staging?.grid)
  const noGrid = names(raw.staging?.noGrid)
  return grid.length || noGrid.length ? { grid, noGrid } : undefined
}

// 장면 하나의 검증·치환 — 엄격 경로와 salvage 경로가 같은 잣대를 쓴다
function resolveScene(
  sc: RawScene,
  byId: Map<string, DigestSpan>,
  lastEnd: number,
  where: string,
): { scene: Scene; end: number } {
  if (typeof sc.spanRef !== 'string' || !byId.has(sc.spanRef))
    throw new ValidationError(`${where}: 존재하지 않는 spanRef (${String(sc.spanRef)})`)
  const span = byId.get(sc.spanRef)!
  if (span.sourceSeqRange[0] <= lastEnd)
    throw new ValidationError(`${where}: 실행 순서를 어기는 배열 (spanRef ${sc.spanRef})`)

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
  for (const t of template.matchAll(/\{(\w+)\}/g)) {
    if (!bindings[t[1]]) throw new ValidationError(`${where}: {${t[1]}}에 대한 바인딩이 없습니다`)
  }

  const focus = Array.isArray(sc.focus) ? sc.focus.filter((f): f is string => typeof f === 'string') : []
  // 연출 동사는 장식이다 — 모르는 동사는 그 동사만 버리고 장면은 살린다
  const direction = Array.isArray(sc.direction)
    ? [...new Set(sc.direction.filter((v): v is DirectingVerb => VERBS.includes(v as DirectingVerb)))]
    : []
  return {
    scene: {
      seqStart: span.sourceSeqRange[0],
      seqEnd: span.sourceSeqRange[1],
      primitive: sc.primitive as PrimitiveKind,
      focus,
      pacing,
      direction,
      ...(span.iterations && span.iterations > 1 ? { repeat: span.iterations } : {}),
      narration: { template, bindings },
    },
    end: span.sourceSeqRange[1],
  }
}

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
      const r = resolveScene(sc, byId, lastEnd, `챕터 ${ci} 장면 ${si}`)
      lastEnd = r.end
      return r.scene
    })
    return { title: ch.title as string, scenes }
  })

  const staging = resolveStaging(doc, digest)
  return { chapters, ...(staging ? { staging } : {}) }
}

// AI가 실수해도 유효한 장면은 살린다 — 무효 장면은 개별 폐기하고,
// 빠진 구간은 규칙 장면으로 메꿔 완주를 보장한다. 채택 0이면 null(전체 규칙 폴백).
export function salvageScreenplay(raw: unknown, digest: Digest, rule: Screenplay): Screenplay | null {
  const doc = raw as RawScreenplay
  if (!doc || !Array.isArray(doc.chapters)) return null
  const byId = new Map<string, DigestSpan>(digest.spans.map(s => [s.spanId, s]))

  let lastEnd = -1
  const kept: { scene: Scene; ch: number }[] = []
  const titles: string[] = []
  doc.chapters.forEach((ch, ci) => {
    titles.push(typeof ch.title === 'string' && ch.title ? ch.title : `구간 ${ci + 1}`)
    for (const sc of Array.isArray(ch.scenes) ? ch.scenes : []) {
      try {
        const r = resolveScene(sc, byId, lastEnd, `챕터 ${ci}`)
        kept.push({ scene: r.scene, ch: ci })
        lastEnd = r.end
      } catch {
        /* 이 장면만 버린다 */
      }
    }
  })
  if (kept.length === 0) return null

  const covered = (seq: number) => kept.some(k => seq >= k.scene.seqStart && seq <= k.scene.seqEnd)
  const fillers = rule.chapters.flatMap(c => c.scenes).filter(s => !covered(s.seqStart))
  const merged = [...kept, ...fillers.map(scene => ({ scene, ch: -1 }))].sort(
    (a, b) => a.scene.seqStart - b.scene.seqStart,
  )

  // 충전 장면은 직전 AI 장면의 챕터에 얹는다 — 순서는 이미 seq로 보장된다
  const chapters: Chapter[] = titles.map(title => ({ title, scenes: [] as Scene[] }))
  let cur = 0
  for (const m of merged) {
    if (m.ch >= 0) cur = m.ch
    chapters[cur].scenes.push(m.scene)
  }
  const staging = resolveStaging(doc, digest)
  return { chapters: chapters.filter(c => c.scenes.length > 0), ...(staging ? { staging } : {}) }
}
