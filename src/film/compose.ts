import type { CompareTarget, Motion, Shot, StagePlan } from './types'
import { STACK_SLOTS, type StageLayout } from './layout'

/* 구성(composition) — 애니메이션 무대의 심장.
   샷마다 "누가 무대에, 어디에, 얼마나 크게"를 결정적으로 계산한다:
   이번 샷에 모션이 닿은 배우 = 포커스(중앙, 크게) / 최근 LINGER샷 안 배우 = 대기열(옆, 작게) /
   그 밖은 무대 밖. 무대 밖 상태는 인스펙터가 항상 들고 있으므로 사실은 사라지지 않는다 —
   화면에서 물러날 뿐이다. */

export type Placement = { x: number; y: number; s: number; focus: boolean }
export type Composition = Map<string, Placement> // 'o<objectId>' | 'v<varKey>'
/** 오토 프레이밍 — 무대 위 배우들의 경계 상자를 프레임(1200×640)에 맞추는 카메라 */
export type Camera = { k: number; x: number; y: number }
/** 저울 자리 — 샷마다 저울 허브가 설 화면 좌표. null = 그 샷에는 저울이 없다 */
export type ScalePlace = { x: number; y: number }
/** 호출 스택 창 — 프레임이 앉을 슬롯(0=맨 아래)과, 창 밖으로 생략된 얕은 호출 수 */
export type FrameStack = { slots: Map<number, number>; hidden: number }

export const LINGER = 6 // 마지막으로 닿은 뒤 무대에 머무는 샷 수
/** 영화 프레임 높이 — WorldStage의 viewBox와 같은 값 (배우가 화면에 담기는지 판정한다) */
const FRAME_H = 640

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
): {
  comps: Composition[]
  cams: Camera[]
  scales: (ScalePlace | null)[]
  autos: { k: number; x: number; y: number }[]
  stacks: FrameStack[]
} {
  const objSize = new Map(
    plan.objects.map(o => {
      const r = layout.objPos.get(o.objectId)
      return [o.objectId, { w: r?.w ?? 120, h: r?.h ?? 64 }]
    }),
  )
  const objKeys = new Set(plan.objects.map(o => `o${o.objectId}`))
  // 주인공은 무대를 지킨다 — LINGER는 "이야기를 가져가지 않는 조연은 물러난다"는 규칙이지
  // 주인공을 내리라는 규칙이 아니었다 (실측 BFS: 격자가 19샷 무대 밖, 15샷은 상자가 0개라
  // 화면에 알약만 남았다). 리드는 buildStage가 변화 횟수·수명으로 이미 고르고 있다.
  // 격자도 함께 상주한다: leadObjectId는 변화 횟수로 고르는데 미로의 벽은 한 번 만들어지고
  // 안 바뀌므로 격자는 영영 리드가 될 수 없다. 그러나 공간 탐색에서 무대는 격자 그 자체다 —
  // 변하는 값이 아니라 탐색이 일어나는 공간이고, 방문 칠·커서·경로가 전부 그것을 좌표계로 쓴다.
  const leadKey = plan.leadObjectId === null ? null : `o${plan.leadObjectId}`
  const lifeOf = new Map(plan.objects.map(o => [`o${o.objectId}`, o.life]))
  const residentKeys = [
    ...new Set([
      ...(leadKey ? [leadKey] : []),
      ...plan.objects.filter(o => o.grid).map(o => `o${o.objectId}`),
    ]),
  ]

  const lastTouch = new Map<string, number>()
  const firstTouch = new Map<string, number>()
  const deadVars = new Set<string>() // exitVar로 내려간 변수 — 다시 닿기 전까지 무대 금지
  const deadObjs = new Set<string>() // exitObj로 퇴장한 상자 — 커튼콜에도 돌아오지 않는다

  // 인덱스 포인터 변수는 알약 스트립에 서지 않는다 — 그 배열 아래 화살표로 산다 (WorldStage)
  const pointerVars = new Set<string>()
  for (const sh of shots)
    for (const m of sh.motions) if (m.v === 'pointer') pointerVars.add(`v${m.varKey}`)

  // 상자를 쥔 변수도 알약을 접는다 — 상자가 이미 그 이름표를 달고 있어 알약은 중복 소음이다.
  // ("numbers → 상자" 알약이 그 예.) 프림을 다시 쥐면(재대입) 알약으로 복귀한다.
  // 이름이 겹쳐 카드가 든 변수도 알약을 접는다 — 판정은 의미층(foldVars)이 했다.
  // 여기서 같은 판정을 다시 하지 않는다: 두 층이 각자 판정하면 조용히 어긋난다.
  const foldedVars = new Set<string>()
  const boundVars = new Set<string>()
  const comps: Composition[] = []
  let prevOrder: string[] = [] // 직전 구성의 객체 세로 순서 (sticky)
  let prevFocus: string[] = [] // 직전 샷의 포커스 객체 (sticky focus — 주인공은 중앙을 지킨다)

  shots.forEach((sh, i) => {
    const touched = new Set<string>()
    for (const m of sh.motions) {
      if (m.v === 'foldVars') {
        // 물러나는 것은 "닿음"이 아니다. 이 프레임이 든 목록을 통째로 갈아끼운다
        for (const k of [...foldedVars]) if (k.startsWith(`v${m.frameId}:`)) foldedVars.delete(k)
        for (const k of m.varKeys) foldedVars.add(`v${k}`)
        continue
      }
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
      if (m.v === 'bind') boundVars.add(`v${m.varKey}`)
      if (m.v === 'setVar') boundVars.delete(`v${m.varKey}`)
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
    // 살아있는 주인공은 포커스를 빼앗겨 대기 열로 물러날지언정 화면에서 사라지지 않는다.
    // 명시적 퇴장(exitObj)은 존중한다 — 죽은 상자를 붙잡지는 않는다
    for (const k of residentKeys) {
      const life = lifeOf.get(k)
      if (life && born(life) && !deadObjs.has(k) && !stagedObjKeys.includes(k)) stagedObjKeys.push(k)
    }
    const touchedObjs = [...touched].filter(k => objKeys.has(k))
    const focusSet = new Set(
      curtainCall ? stagedObjKeys
      : touchedObjs.length ? touchedObjs
      : prevFocus.filter(k => stagedObjKeys.includes(k)),
    )
    // 무대에 배우가 있는데 포커스가 비면 리드가 중앙을 맡는다 — 안 그러면 "무대를 지킨다"가
    // "구석에서 0.55배로 쪼그라든다"가 되고, 오토 프레이밍이 그 구석을 확대해 더 이상해진다
    if (focusSet.size === 0 && stagedObjKeys.length)
      focusSet.add(leadKey && stagedObjKeys.includes(leadKey) ? leadKey : stagedObjKeys[0])
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
    // 자리는 등장순으로 고정한다 (재배열은 알약 교차의 어지러움을 만든다).
    // 단, 모션으로 소개된 적 없는 변수는 후보가 아니다 — 사슬 빨리감기 태생 변수가
    // 값 한 번 못 받은 빈 알약으로 서는 경로를 막는다 (부록 A 08-22 (마)①)
    const vars = plan.variables
      .filter(
        v =>
          born(v.life) &&
          firstTouch.has(`v${v.varKey}`) &&
          !deadVars.has(`v${v.varKey}`) &&
          !pointerVars.has(`v${v.varKey}`) &&
          !boundVars.has(`v${v.varKey}`) &&
          !foldedVars.has(`v${v.varKey}`),
      )
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
  // 상단 여백은 저울 홈 띠까지 계산에 넣는다 — 접시가 기울면 y≈79까지 내려오므로
  // 콘텐츠는 84부터. 저울은 비교 칸 위로 내려갈 수 있지만(아래 scales 패스), 내려갈
  // 자리는 배우 사각형과의 비교차가 증명될 때만이다 — 못 내려가면 이 홈 띠로 돌아온다.
  // 겹침은 위치 조정이 아니라 이 경계 계약 + 기하 판정으로 막는다.
  // y0는 저울 홈 바닥(HOME_Y 36 + S_DOWN 48 = 84)보다 실제로 더 내려가 있어야 한다 —
  // 딱 맞물리면 여유가 0이라 판정 여유(CLEAR_Y)를 줄 수 없고, 글리프 잉크가 모델을 몇 px
  // 넘는 순간 그대로 스침이 된다. 16을 띄워 경계에 진짜 여백을 만든다.
  const AREA = { x0: 60, y0: 100, x1: 1140, y1: 470 } // 상단 배지·저울 홈·하단 HUD를 뺀 프레임
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

  // ── 저울 자리 — 판단(저울)과 대상(칸)이 한 시야에 있도록, cell 타깃 비교면 저울이
  // 비교 칸들의 화면 x 중점 위·대상 이름표 띠 바로 위로 내려간다. 겹침 0 계약:
  // 후보 자리의 저울 사각형이 다른 배우 사각형(이름표·칸번호·포인터 띠 포함)과
  // 교차하면 내려가지 않고 상단 홈 띠로 폴백한다 — 다른 배우 위를 떠도는 저울은 오독이다.
  // var 전용 비교는 홈 고정(알약 스트립 위는 늘 붐빈다), 비교 연속 구간의 사이 샷에도
  // 마지막 타깃 기준으로 자리를 갱신한다 (카메라가 움직여도 저울이 내용을 따라간다).
  // 좌표는 오토 프레이밍(cams)에 AI 연출의 줌(camera 모션, film-cam-auto)까지 겹친
  // 최종 화면 기준이다 — 줌을 빼먹으면 저울만 낡은 자리에 남는다 (실측으로 잡은 함정).
  // 치수는 WorldStage 저울 부품에서 온다: 위 34(부등호 배지) / 아래 48(±10° 기운
  // 접시의 바깥 모서리 — 수평 접시 32에 기울기 몫 16) / 왼쪽 94(접시 끝) / 오른쪽 162(판정 도장).
  const S_UP = 34
  const S_DOWN = 48
  const S_LEFT = 94
  const S_RIGHT = 162
  const S_GAP = 8
  const HOME_Y = 36
  const BADGE_RIGHT = 264 // 반복 배지(x 24..264, y 14..44) — 홈 띠에서는 그 오른쪽에 선다
  const HOME: ScalePlace = { x: layout.width / 2, y: HOME_Y }
  const homeXOf = (mx: number) =>
    Math.min(Math.max(mx, BADGE_RIGHT + S_LEFT + S_GAP), layout.width - S_RIGHT - 8)

  // 인덱스 포인터가 상자 아래로 늘어뜨리는 화살표 줄 수 — 상자의 점유 사각형에 넣는다
  const pointerRowCount = new Map<number, number>()
  {
    const seen = new Set<string>()
    for (const sh of shots)
      for (const m of sh.motions)
        if (m.v === 'pointer' && !seen.has(m.varKey)) {
          seen.add(m.varKey)
          pointerRowCount.set(m.objectId, (pointerRowCount.get(m.objectId) ?? 0) + 1)
        }
  }

  // 강조 카메라 — decorate는 "이 샷이 그 비트다"라는 표시(emphasis)만 남기고, 좌표는
  // 배치를 아는 이 층이 만든다. 대상의 실제 화면 중심을 AREA 중앙에 놓되, 확대 후
  // AREA에 담기지 않으면 배율을 낮추고 그래도 안 되면 강조를 포기한다 —
  // 잘린 강조는 강조가 아니다 (프레임 중앙 기준 확대가 대상을 화면 밖으로 밀어냈던 결함).
  type Auto = { k: number; x: number; y: number }
  const IDENTITY: Auto = { k: 1, x: 0, y: 0 }
  let auto: Auto = IDENTITY

  type Rect4 = { x0: number; x1: number; y0: number; y1: number }

  const actorRect = (key: string, p: Placement, cam: Camera, a0: Auto): Rect4 => {
    const fx = (v: number) => a0.x + a0.k * (cam.x + cam.k * v)
    const fy = (v: number) => a0.y + a0.k * (cam.y + cam.k * v)
    if (objKeys.has(key)) {
      const id = Number(key.slice(1))
      const size = objSize.get(id) ?? { w: 120, h: 64 }
      const rows = pointerRowCount.get(id) ?? 0
      return {
        x0: fx(p.x),
        x1: fx(p.x + size.w * p.s),
        y0: fy(p.y - 26 * p.s), // 이름표 띠 — 글리프 상단 실측 -23.5에 여유 (카메라 bbox의 22와 다르다)
        y1: fy(p.y + (size.h + (rows ? 26 + rows * 26 : 16)) * p.s), // 번호·포인터 띠
      }
    }
    return { x0: fx(p.x), x1: fx(p.x + 190 * p.s), y0: fy(p.y), y1: fy(p.y + 36 * p.s) }
  }

  type CellTarget = Extract<CompareTarget, { kind: 'cell' }>
  // 배우의 실제 페인트 범위는 모델 사각형보다 넓다 — 이름표·번호 글리프의 잉크 상자, 획(stroke),
  // 폰트 여백이 컨테이너 밖으로 번진다 (실측: 좌 6 / 상 9.6 / 하 7.6 화면px ≈ 뷰박스 11~18).
  // 모델을 글리프 단위까지 맞추는 대신 판정에 여유를 준다 — 스치느니 홈에 서는 편이 정직하다.
  // 배우의 실제 페인트 범위는 모델 사각형보다 넓다 (글리프 잉크·획·폰트 여백).
  // 세로 여유는 AREA.y0가 저울 바닥(84)보다 아래(100)일 때만 성립한다 — 딱 맞물린 상태에서
  // 세로 여유를 주면 저울이 스스로 계약선을 넘어 "가짜 겹침"을 만들고 홈 띠 전체가
  // 사용 불가가 되어, 오히려 크게 겹치는 자리로 물러나게 된다 (실측으로 잡은 자충수).
  const CLEAR_X = 10
  const CLEAR_Y = 10
  const rectsOf = (comp: Composition, cam: Camera, a0: Auto) => {
    const m = new Map<string, Rect4>()
    for (const [key, p] of comp) m.set(key, actorRect(key, p, cam, a0))
    return m
  }
  // 구성 전환은 애니메이션이다 — 배우는 직전 사각형에서 현재 사각형으로 이동하므로,
  // 그 사이 어느 프레임에서도 두 사각형의 볼록 껍질 밖으로 나가지 않는다. 껍질을 피하면
  // 전환 도중에도 스치지 않고, 퇴장하며 사라지는 중인 배우까지 함께 피해진다.
  const hull = (a: Map<string, Rect4>, b: Map<string, Rect4>) => {
    const out = new Map(b)
    for (const [k, r] of a) {
      const c = out.get(k)
      out.set(
        k,
        c
          ? { x0: Math.min(c.x0, r.x0), x1: Math.max(c.x1, r.x1), y0: Math.min(c.y0, r.y0), y1: Math.max(c.y1, r.y1) }
          : r,
      )
    }
    return out
  }
  /** 저울이 그 자리에 섰을 때 배우와 겹치는 총 면적 (0이면 빈 자리) */
  const overlapAt = (x: number, y: number, rects: Map<string, Rect4>, skip: Set<string>) => {
    const r = { x0: x - S_LEFT - CLEAR_X, x1: x + S_RIGHT + CLEAR_X, y0: y - S_UP - CLEAR_Y, y1: y + S_DOWN + CLEAR_Y }
    let sum = 0
    for (const [key, a] of rects) {
      if (skip.has(key)) continue
      const w = Math.min(r.x1, a.x1) - Math.max(r.x0, a.x0)
      const h = Math.min(r.y1, a.y1) - Math.max(r.y0, a.y0)
      if (w > 0 && h > 0) sum += w * h
    }
    return sum
  }
  // 홈 띠도 안전지대가 아니다 — AI 연출의 카메라 팬(camera 모션)이 콘텐츠를 위로 올리면
  // AREA.y0=84가 보장하던 여백이 줄어 배우가 홈 띠로 올라온다 (실측으로 잡은 케이스).
  // 홈에서 겹치면 저울을 좌우로 밀어 빈 자리를 찾는다 — 위로는 갈 곳이 없다.
  const homeAt = (mx: number, rects: Map<string, Rect4>, skip: Set<string>): ScalePlace => {
    const x0 = homeXOf(mx)
    let best = { x: x0, area: overlapAt(x0, HOME_Y, rects, skip) }
    if (best.area === 0) return { x: x0, y: HOME_Y }
    const lo = BADGE_RIGHT + S_LEFT + S_GAP
    const hi = layout.width - S_RIGHT - 8
    for (let d = 40; d <= 720; d += 40) {
      for (const cand of [x0 - d, x0 + d]) {
        if (cand < lo || cand > hi) continue
        const area = overlapAt(cand, HOME_Y, rects, skip)
        if (area === 0) return { x: cand, y: HOME_Y }
        if (area < best.area) best = { x: cand, area }
      }
    }
    // 무대가 꽉 찼다 — 자리를 지어내지 않고, 가장 덜 가리는 자리로 물러난다
    return { x: best.x, y: HOME_Y }
  }
  const scaleSpot = (
    cells: CellTarget[],
    comp: Composition,
    cam: Camera,
    rects: Map<string, Rect4>,
  ): ScalePlace | null => {
    if (cells.length === 0) return null
    let sx = 0
    let labelTop = Infinity
    const involved = new Set<string>()
    for (const t of cells) {
      const p = comp.get(`o${t.objectId}`)
      if (!p) return null
      sx += auto.x + auto.k * (cam.x + cam.k * (p.x + (8 + t.index * layout.cellW + (layout.cellW - 6) / 2) * p.s))
      labelTop = Math.min(labelTop, auto.y + auto.k * (cam.y + cam.k * (p.y - 26 * p.s)))
      involved.add(`o${t.objectId}`)
    }
    const mx = Math.min(Math.max(sx / cells.length, S_LEFT + 8), layout.width - S_RIGHT - 8)
    const hy = labelTop - S_GAP - S_DOWN
    // 내려갈 거리가 없으면 홈 띠가 곧 그 자리다. 홈에서는 비교 대상도 피할 배우로 센다 —
    // 대상 위가 아니라 빈 곳에 서는 것이 홈의 계약이다
    if (hy <= HOME_Y) return homeAt(mx, rects, new Set())
    if (overlapAt(mx, hy, rects, involved) > 0) return homeAt(mx, rects, new Set())
    return { x: mx, y: hy }
  }

  const isCmp = (sh: Shot) => sh.motions.some(m => m.v === 'compare' && m.a !== undefined && m.b !== undefined)
  const scales: (ScalePlace | null)[] = []
  let visible = false
  let lastCells: CellTarget[] | null = null
  let prevSpot: ScalePlace | null = null
  // 강조 대상 — 그 샷의 사실 중 가장 구체적인 것 (비교가 짚은 칸 → 스왑 칸 → 포커스 객체)
  const emphasisTarget = (sh: Shot): number | null => {
    const cmp = sh.motions.find(m => m.v === 'compare') as Extract<Motion, { v: 'compare' }> | undefined
    const cell = cmp?.targets.find(t => t.kind === 'cell') as { objectId: number } | undefined
    if (cell) return cell.objectId
    const sw = sh.motions.find(m => m.v === 'swap') as Extract<Motion, { v: 'swap' }> | undefined
    if (sw) return sw.objectId
    return sh.focus?.kind === 'object' ? sh.focus.objectId : null
  }
  const AC = { x: (AREA.x0 + AREA.x1) / 2, y: (AREA.y0 + AREA.y1) / 2 }
  const autoFor = (si: number, kWanted: number): Auto => {
    const id = emphasisTarget(shots[si])
    if (id === null) return IDENTITY
    const p = comps[si].get(`o${id}`)
    if (!p) return IDENTITY
    // 배우가 실제로 점유하는 범위는 actorRect가 이미 안다 — 이름표 띠와 칸 번호는 물론
    // 인덱스 포인터가 상자 아래로 늘어뜨리는 화살표 줄까지. 여기서 따로 계산하면
    // 그만큼 대상이 중앙에서 아래로 밀린다 (실측 44px)
    const r = actorRect(`o${id}`, p, cams[si], IDENTITY)
    const bx0 = r.x0
    const bx1 = r.x1
    const by0 = r.y0
    const by1 = r.y1
    const fits = (k: number) => (bx1 - bx0) * k <= AREA.x1 - AREA.x0 && (by1 - by0) * k <= AREA.y1 - AREA.y0
    let k = kWanted
    while (k > 1.15 && !fits(k)) k -= 0.05
    if (!fits(k)) return IDENTITY // 담기지 않는다 — 강조를 포기한다
    return { k, x: AC.x - k * ((bx0 + bx1) / 2), y: AC.y - k * ((by0 + by1) / 2) }
  }

  const autos: Auto[] = []
  let prevRects = new Map<string, Rect4>()
  shots.forEach((sh, si) => {
    const prevAuto = auto
    const emph = sh.motions.find(m => m.v === 'emphasis') as Extract<Motion, { v: 'emphasis' }> | undefined
    auto = emph ? autoFor(si, emph.k) : IDENTITY
    autos.push(auto)
    // 강조는 "이것만 본다"는 선언이다 — 그 배율에 밀려 프레임에 온전히 담기지 않는 배우는
    // 가장자리에 반쯤 걸치는 대신 물러난다. 사라짐이 카메라의 부작용이 아니라 구성의 결정이
    // 되어야 "구성이 가시성의 단일 소유자"가 지켜진다 (무대 밖 상태는 인스펙터가 들고 있다).
    // cams·autos는 다시 계산하지 않는다 — 그러면 강조 좌표가 무효가 되어 진짜 순환이 된다.
    // 대상은 autoFor가 AREA(프레임보다 좁다) 안에 넣으므로 절대 접히지 않는다.
    if (auto.k !== 1) {
      for (const [key, p] of [...comps[si]]) {
        const r = actorRect(key, p, cams[si], auto)
        if (r.x0 < 0 || r.x1 > layout.width || r.y0 < 0 || r.y1 > FRAME_H) comps[si].delete(key)
      }
    }
    const cur = rectsOf(comps[si], cams[si], auto)
    // 이 샷 동안 배우가 실제로 점유하는 범위 = 세 사각형의 껍질:
    // ① 직전 배치(구성 전환 트윈의 출발) ② 현재 배치를 직전 카메라로 본 것(카메라 트윈의
    // 출발 — 이 샷에 새로 등장한 배우는 ①이 없어 이것이 없으면 카메라 이동 경로가 빠진다)
    // ③ 현재 배치·현재 카메라(정착). 트윈은 두 끝 사이를 지나므로 껍질을 피하면 전 구간이 안전하다
    const rects = hull(hull(prevRects, rectsOf(comps[si], cams[si - 1] ?? cams[si], prevAuto)), cur)
    prevRects = cur
    const cmp = sh.motions.find(m => m.v === 'compare' && m.a !== undefined && m.b !== undefined) as
      | Extract<Motion, { v: 'compare' }>
      | undefined
    if (cmp) {
      const cells = cmp.targets.filter((t): t is CellTarget => t.kind === 'cell')
      lastCells = cells
      const spot = cells.length
        ? (scaleSpot(cells, comps[si], cams[si], rects) ?? homeAt(HOME.x, rects, new Set()))
        : homeAt(HOME.x, rects, new Set())
      scales.push(spot)
      prevSpot = spot
      // WorldStage의 체류 판정과 같은 규칙 — 두 샷 안에 다음 비교가 오면 저울이 떠 있다
      visible = shots.slice(si + 1, si + 3).some(isCmp)
    } else if (visible) {
      // 사이 샷 — 배우가 움직였으면 저울도 따라 자리를 갱신한다. 대상이 무대에서 내려가
      // 해석이 안 되면 직전 자리를 그대로 쓰지 않고 홈에서 다시 빈 자리를 찾는다 —
      // 가만히 선 저울 밑으로 다른 배우가 미끄러져 들어오는 경로가 여기였다 (실측)
      const spot =
        (lastCells?.length ? scaleSpot(lastCells, comps[si], cams[si], rects) : null) ??
        homeAt(prevSpot?.x ?? HOME.x, rects, new Set())
      scales.push(spot)
      prevSpot = spot
    } else {
      scales.push(null)
    }
  })

  // ── 호출 스택 창 — 깊이는 무한할 수 있지만 화면은 유한하다.
  // 창은 늘 "가장 깊은 쪽"을 잡는다: 현재 실행 중인 프레임이 곧 가장 깊은 프레임이므로
  // 조명이 화면 밖으로 나가는 일이 구조적으로 없다. 생략되는 것은 얕은 쪽(아래)이고,
  // 그 자리에 "앞선 호출 k개"를 적어 화면이 무엇을 안 보여주는지 스스로 밝힌다.
  const stacks: FrameStack[] = shots.map(sh => {
    const alive = plan.frames
      .filter(f => f.life.from <= sh.seq && sh.seq <= f.life.to)
      .sort((a, b) => a.depth - b.depth)
    const slots = new Map<number, number>()
    if (alive.length <= STACK_SLOTS) {
      alive.forEach((f, i) => slots.set(f.frameId, i))
      return { slots, hidden: 0 }
    }
    const shown = alive.slice(-(STACK_SLOTS - 1)) // 가장 깊은 것들 — 맨 아래 슬롯은 요약 띠 몫
    shown.forEach((f, i) => slots.set(f.frameId, i + 1))
    return { slots, hidden: alive.length - shown.length }
  })

  return { comps, cams, scales, autos, stacks }
}
