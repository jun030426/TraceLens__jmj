import type { Shot, StagePlan } from './types'

/* 테마 감지 — 코드 유형을 모션에서 결정적으로 읽는다. 사실은 트레이스가 소유하고
   테마는 표현만 바꾸므로, 감지가 틀려도 값이 틀려지지는 않는다. 불확실하면 중립(generic).

   막대(barObjects)는 "음수 없는 전부-숫자 리스트"에만 허용한다 — 높이 인코딩은
   |v|를 그리므로 음수가 섞이면 순서를 거짓말하게 된다. 그때는 막대를 포기한다. */

export type FilmTheme = {
  kind: 'sorting' | 'spatial' | 'generic'
  /** 값 비례 막대 높이 인코딩 대상 리스트 */
  barObjects: Set<number>
  /** objectId → 막대 정규화 기준(관측된 최댓값) */
  maxAbs: Map<number, number>
}

export function detectTheme(plan: StagePlan, shots: Shot[]): FilmTheme {
  const gridIds = new Set(plan.objects.filter(o => o.grid).map(o => o.objectId))
  const seen = new Map<number, string[]>()
  const swaps = new Map<number, number>()
  const push = (id: number, ...t: string[]) => {
    if (gridIds.has(id)) return
    const a = seen.get(id) ?? []
    a.push(...t)
    seen.set(id, a)
  }
  for (const sh of shots) {
    for (const m of sh.motions) {
      if (m.v === 'grow' || m.v === 'setCell') push(m.objectId, m.text)
      else if (m.v === 'shiftLeft') push(m.objectId, ...m.texts)
      else if (m.v === 'swap') {
        swaps.set(m.objectId, (swaps.get(m.objectId) ?? 0) + 1)
        push(m.objectId, m.iText, m.kText)
      }
    }
  }

  const barObjects = new Set<number>()
  const maxAbs = new Map<number, number>()
  for (const o of plan.objects) {
    if (o.grid || o.maxItems < 2) continue
    const texts = seen.get(o.objectId) ?? []
    if (texts.length === 0) continue
    const nums = texts.map(Number)
    if (nums.some(n => !Number.isFinite(n) || n < 0)) continue
    barObjects.add(o.objectId)
    maxAbs.set(o.objectId, Math.max(...nums, 1e-9))
  }

  const sorting = [...swaps.entries()].some(([id, n]) => n >= 2 && barObjects.has(id))
  const kind = sorting ? 'sorting' : gridIds.size > 0 ? 'spatial' : 'generic'
  return { kind, barObjects, maxAbs }
}
