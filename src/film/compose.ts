import type { Shot, StagePlan } from './types'
import type { StageLayout } from './layout'

/* 구성(composition) — 애니메이션 무대의 심장.
   샷마다 "누가 무대에, 어디에, 얼마나 크게"를 결정적으로 계산한다:
   이번 샷에 모션이 닿은 배우 = 포커스(중앙, 크게) / 최근 LINGER샷 안 배우 = 대기열(옆, 작게) /
   그 밖은 무대 밖. 무대 밖 상태는 인스펙터가 항상 들고 있으므로 사실은 사라지지 않는다 —
   화면에서 물러날 뿐이다. */

export type Placement = { x: number; y: number; s: number; focus: boolean }
export type Composition = Map<string, Placement> // 'o<objectId>' | 'v<varKey>'
/** 오토 프레이밍 — 무대 위 배우들의 경계 상자를 프레임(1200×640)에 맞추는 카메라 */
export type Camera = { k: number; x: number; y: number }

export const LINGER = 6 // 마지막으로 닿은 뒤 무대에 머무는 샷 수

const TOP = 90
const FOCUS_CX = 760 // 포커스 열의 중심축
const SIDE_X = 1010 // 대기 열
const VAR_X = 330 // 변수 스트립
const VAR_PITCH = 52
const SIDE_S = 0.55
const VAR_IDLE_S = 0.8
const MAX_VARS = 8

export function compose(
  shots: Shot[],
  plan: StagePlan,
  layout: StageLayout,
): { comps: Composition[]; cams: Camera[] } {
  const objSize = new Map(
    plan.objects.map(o => {
      const r = layout.objPos.get(o.objectId)
      return [o.objectId, { w: r?.w ?? 120, h: r?.h ?? 64 }]
    }),
  )
  const objKeys = new Set(plan.objects.map(o => `o${o.objectId}`))

  const lastTouch = new Map<string, number>()
  const firstTouch = new Map<string, number>()
  const deadVars = new Set<string>() // exitVar로 내려간 변수 — 다시 닿기 전까지 무대 금지
  const deadObjs = new Set<string>() // exitObj로 퇴장한 상자 — 커튼콜에도 돌아오지 않는다
  const comps: Composition[] = []
  let prevOrder: string[] = [] // 직전 구성의 객체 세로 순서 (sticky)
  let prevFocus: string[] = [] // 직전 샷의 포커스 객체 (sticky focus — 주인공은 중앙을 지킨다)

  shots.forEach((sh, i) => {
    const touched = new Set<string>()
    for (const m of sh.motions) {
      // 퇴장·이름표 정리는 "닿음"이 아니다 — 떠나는 배우를 무대에 붙잡으면 모순이 된다
      if (m.v === 'exitObj' || m.v === 'exitVar' || m.v === 'label') {
        if (m.v === 'exitObj') {
          lastTouch.delete(`o${m.objectId}`)
          deadObjs.add(`o${m.objectId}`)
        }
        if (m.v === 'exitVar') {
          lastTouch.delete(`v${m.varKey}`)
          deadVars.add(`v${m.varKey}`)
        }
        continue
      }
      if ('objectId' in m && typeof m.objectId === 'number') touched.add(`o${m.objectId}`)
      if ('varKey' in m && typeof m.varKey === 'string') touched.add(`v${m.varKey}`)
      if (m.v === 'spotlight') for (const k of m.varKeys) touched.add(`v${k}`)
      if (m.v === 'compare')
        for (const t of m.targets) touched.add(t.kind === 'cell' ? `o${t.objectId}` : `v${t.varKey}`)
    }
    for (const k of touched) {
      lastTouch.set(k, i)
      if (!firstTouch.has(k)) firstTouch.set(k, i)
      deadVars.delete(k) // 재등장 (del 후 재대입 등) — 무대 복귀
      deadObjs.delete(k)
    }
    const curtainCall = i === shots.length - 1 // 마지막 장면 — 살아있는 전원이 중앙에 (최종 상태의 완성)
    // 생존 판정 — plan의 life.to는 "마지막 수정"이지 스코프 종료가 아니다 (한 번만 대입된
    // 변수가 곧바로 죽는 오판의 근원). 탄생(from) 이후 + 명시적 퇴장(exit) 전이면 살아있다.
    const born = (life: { from: number; to: number }) => life.from <= sh.seq

    const comp: Composition = new Map()

    // ── 객체: 체류는 LINGER, 포커스는 sticky — 이번 샷에 닿은 객체가 없으면 직전 주인공이
    // 중앙을 지킨다 (변수만 바뀌는 샷마다 주인공이 대기열로 밀려나는 출렁임 방지).
    // 커튼콜은 lastTouch가 아니라 생존 전원 — 최종 상태의 완성이 마지막 그림이다.
    const stagedObjKeys = curtainCall
      ? plan.objects.filter(o => born(o.life) && !deadObjs.has(`o${o.objectId}`)).map(o => `o${o.objectId}`)
      : [...lastTouch.entries()]
          .filter(([k, at]) => objKeys.has(k) && i - at <= LINGER)
          .map(([k]) => k)
    const touchedObjs = [...touched].filter(k => objKeys.has(k))
    const focusSet = new Set(
      curtainCall ? stagedObjKeys
      : touchedObjs.length ? touchedObjs
      : prevFocus.filter(k => stagedObjKeys.includes(k)),
    )
    const objs = stagedObjKeys.map(k => ({ k, id: Number(k.slice(1)), focus: focusSet.has(k) }))
    objs.sort((a, b) => {
      const pa = prevOrder.indexOf(a.k)
      const pb = prevOrder.indexOf(b.k)
      const ka = pa >= 0 ? pa : 1000 + (firstTouch.get(a.k) ?? 0)
      const kb = pb >= 0 ? pb : 1000 + (firstTouch.get(b.k) ?? 0)
      return ka - kb
    })
    let yFocus = TOP
    let ySide = TOP
    // 포커스 배우들을 먼저 앉히고 최우단을 잰다 — 대기 열은 그 오른쪽부터 (침범 금지).
    // 화면을 넘치면 카메라가 줌아웃으로 담는다.
    let focusRight = FOCUS_CX
    for (const o of objs) {
      if (!o.focus) continue
      const size = objSize.get(o.id) ?? { w: 120, h: 64 }
      const x = Math.max(555, FOCUS_CX - size.w / 2)
      comp.set(o.k, { x, y: yFocus, s: 1, focus: true })
      focusRight = Math.max(focusRight, x + size.w)
      yFocus += size.h + 96 // 이름표(위)와 칸 번호(아래) 몫까지 — 덩어리짐 방지
    }
    const sideX = Math.max(SIDE_X, focusRight + 40)
    for (const o of objs) {
      if (o.focus) continue
      const size = objSize.get(o.id) ?? { w: 120, h: 64 }
      comp.set(o.k, { x: sideX, y: ySide, s: SIDE_S, focus: false })
      ySide += size.h * SIDE_S + 46
    }
    prevOrder = objs.map(o => o.k)
    prevFocus = objs.filter(o => o.focus).map(o => o.k)

    // ── 변수: 좌측 스트립 — 기준은 최근성이 아니라 생존이다. 살아있는 변수가 말없이
    // 사라지면 학습자는 "i 어디 갔지?"가 된다. 상한 초과분만 최근성으로 강등하고,
    // 자리는 등장순으로 고정한다 (재배열은 알약 교차의 어지러움을 만든다)
    const vars = plan.variables
      .filter(v => born(v.life) && !deadVars.has(`v${v.varKey}`))
      .map(v => `v${v.varKey}`)
      .sort((a, b) => (lastTouch.get(b) ?? 0) - (lastTouch.get(a) ?? 0))
      .slice(0, MAX_VARS)
      .sort((a, b) => (firstTouch.get(a) ?? 0) - (firstTouch.get(b) ?? 0))
    let yVar = TOP
    for (const k of vars) {
      const hot = curtainCall || lastTouch.get(k) === i
      comp.set(k, { x: VAR_X, y: yVar, s: hot ? 1 : VAR_IDLE_S, focus: hot })
      yVar += VAR_PITCH
    }

    comps.push(comp)
  })

  // ── 오토 프레이밍 — 매 샷, 배우 경계 상자를 콘텐츠 영역에 맞춘다.
  // 이것이 "꽉 찬 프레임"이다: 빈 벽을 보여주지 않고 카메라가 이야기를 따라간다.
  // 상단 여백은 저울 띠까지 계산에 넣는다 — 접시가 기울면 y≈75까지 내려오므로
  // 콘텐츠는 84부터. 겹침은 위치 조정이 아니라 이 경계 계약으로 막는다.
  const AREA = { x0: 60, y0: 84, x1: 1140, y1: 470 } // 상단 배지·저울·하단 HUD를 뺀 프레임
  const sizeOf = (key: string): { w: number; h: number } =>
    objKeys.has(key) ? (objSize.get(Number(key.slice(1))) ?? { w: 120, h: 64 }) : { w: 190, h: 36 }
  const cams: Camera[] = []
  let prevCam: Camera | null = null
  for (const comp of comps) {
    if (comp.size === 0) {
      cams.push(prevCam ?? { k: 1, x: 0, y: 0 })
      continue
    }
    let bx0 = Infinity
    let by0 = Infinity
    let bx1 = -Infinity
    let by1 = -Infinity
    for (const [key, p] of comp) {
      const s = sizeOf(key)
      bx0 = Math.min(bx0, p.x)
      by0 = Math.min(by0, p.y - 22 * p.s) // 이름표 띠
      bx1 = Math.max(bx1, p.x + s.w * p.s)
      by1 = Math.max(by1, p.y + (s.h + 16) * p.s) // 번호 띠
    }
    const bw = Math.max(bx1 - bx0, 120)
    const bh = Math.max(by1 - by0, 120)
    const k = Math.min(1.6, Math.max(0.45, Math.min((AREA.x1 - AREA.x0) / bw, (AREA.y1 - AREA.y0) / bh)))
    const cam: Camera = {
      k,
      x: (AREA.x0 + AREA.x1) / 2 - k * (bx0 + bw / 2),
      y: (AREA.y0 + AREA.y1) / 2 - k * (by0 + bh / 2),
    }
    // 감쇠 — 조금 변한 프레임은 유지한다 (카메라 덜덜림 방지). 같은 참조를 다시 넣어
    // 렌더 층이 "안 바뀌었음"을 참조 비교로 알 수 있게 한다.
    if (
      prevCam &&
      Math.abs(cam.k - prevCam.k) / prevCam.k < 0.08 &&
      Math.abs(cam.x - prevCam.x) < 60 &&
      Math.abs(cam.y - prevCam.y) < 60
    ) {
      cams.push(prevCam)
    } else {
      cams.push(cam)
      prevCam = cam
    }
  }

  return { comps, cams }
}
