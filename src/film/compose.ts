import type { Shot, StagePlan } from './types'
import type { StageLayout } from './layout'

/* 구성(composition) — 애니메이션 무대의 심장.
   샷마다 "누가 무대에, 어디에, 얼마나 크게"를 결정적으로 계산한다:
   이번 샷에 모션이 닿은 배우 = 포커스(중앙, 크게) / 최근 LINGER샷 안 배우 = 대기열(옆, 작게) /
   그 밖은 무대 밖. 무대 밖 상태는 인스펙터가 항상 들고 있으므로 사실은 사라지지 않는다 —
   화면에서 물러날 뿐이다. */

export type Placement = { x: number; y: number; s: number; focus: boolean }
export type Composition = Map<string, Placement> // 'o<objectId>' | 'v<varKey>'

export const LINGER = 6 // 마지막으로 닿은 뒤 무대에 머무는 샷 수

const TOP = 90
const FOCUS_CX = 760 // 포커스 열의 중심축
const SIDE_X = 1010 // 대기 열
const VAR_X = 330 // 변수 스트립
const VAR_PITCH = 52
const SIDE_S = 0.55
const VAR_IDLE_S = 0.8
const MAX_VARS = 8

export function compose(shots: Shot[], plan: StagePlan, layout: StageLayout): Composition[] {
  const objSize = new Map(
    plan.objects.map(o => {
      const r = layout.objPos.get(o.objectId)
      return [o.objectId, { w: r?.w ?? 120, h: r?.h ?? 64 }]
    }),
  )
  const objKeys = new Set(plan.objects.map(o => `o${o.objectId}`))
  const varKeys = new Set(plan.variables.map(v => `v${v.varKey}`))

  const lastTouch = new Map<string, number>()
  const firstTouch = new Map<string, number>()
  const comps: Composition[] = []
  let prevOrder: string[] = [] // 직전 구성의 객체 세로 순서 (sticky)

  shots.forEach((sh, i) => {
    const touched = new Set<string>()
    for (const m of sh.motions) {
      if ('objectId' in m && typeof m.objectId === 'number') touched.add(`o${m.objectId}`)
      if ('varKey' in m && typeof m.varKey === 'string') touched.add(`v${m.varKey}`)
      if (m.v === 'spotlight') for (const k of m.varKeys) touched.add(`v${k}`)
      if (m.v === 'compare')
        for (const t of m.targets) touched.add(t.kind === 'cell' ? `o${t.objectId}` : `v${t.varKey}`)
    }
    for (const k of touched) {
      lastTouch.set(k, i)
      if (!firstTouch.has(k)) firstTouch.set(k, i)
    }

    const staged = [...lastTouch.entries()].filter(([, at]) => i - at <= LINGER)
    const comp: Composition = new Map()

    // ── 객체: 포커스는 중앙 열, 대기는 우측 열 — 이전 세로 순서를 유지해 출렁임을 막는다
    const objs = staged
      .filter(([k]) => objKeys.has(k))
      .map(([k, at]) => ({ k, id: Number(k.slice(1)), focus: at === i }))
    objs.sort((a, b) => {
      const pa = prevOrder.indexOf(a.k)
      const pb = prevOrder.indexOf(b.k)
      const ka = pa >= 0 ? pa : 1000 + (firstTouch.get(a.k) ?? 0)
      const kb = pb >= 0 ? pb : 1000 + (firstTouch.get(b.k) ?? 0)
      return ka - kb
    })
    let yFocus = TOP
    let ySide = TOP
    for (const o of objs) {
      const size = objSize.get(o.id) ?? { w: 120, h: 64 }
      if (o.focus) {
        const x = Math.max(555, Math.min(FOCUS_CX - size.w / 2, 1200 - size.w - 16))
        comp.set(o.k, { x, y: yFocus, s: 1, focus: true })
        yFocus += size.h + 64
      } else {
        const x = Math.min(SIDE_X, 1200 - size.w * SIDE_S - 12)
        comp.set(o.k, { x, y: ySide, s: SIDE_S, focus: false })
        ySide += size.h * SIDE_S + 34
      }
    }
    prevOrder = objs.map(o => o.k)

    // ── 변수: 좌측 스트립, 최근에 닿은 순 — 손대는 것들만 무대에
    const vars = staged
      .filter(([k]) => varKeys.has(k))
      .sort((a, b) => b[1] - a[1])
      .slice(0, MAX_VARS)
    let yVar = TOP
    for (const [k, at] of vars) {
      comp.set(k, { x: VAR_X, y: yVar, s: at === i ? 1 : VAR_IDLE_S, focus: at === i })
      yVar += VAR_PITCH
    }

    comps.push(comp)
  })

  return comps
}

/** 구성 전체가 요구하는 무대 높이 (하단 HUD가 이 아래로 붙는다) */
export function stageHeightOf(comps: Composition[], plan: StagePlan, layout: StageLayout): number {
  const objH = new Map(plan.objects.map(o => [`o${o.objectId}`, layout.objPos.get(o.objectId)?.h ?? 64]))
  let need = 640
  for (const comp of comps) {
    for (const [k, p] of comp) {
      const h = (objH.get(k) ?? 36) * p.s
      need = Math.max(need, p.y + h + 150) // 하단 HUD(프레임·출력) 몫
    }
  }
  return need
}
