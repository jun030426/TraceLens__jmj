import type { StagePlan } from './types'

export type Rect = { x: number; y: number; w: number; h: number }
export type StageLayout = {
  width: number
  height: number
  varPos: Map<string, Rect>
  objPos: Map<number, Rect>
  framePos: Map<number, Rect>
  cellW: number
}

const W = 1200
const H = 640
const OBJ_X = 560
const VAR_X = 340
const VAR_W = 190 // 이름 + 값이 한 알약 안에서 부딪히지 않을 폭 (오른쪽 끝 530 < 객체 열 560)
const ROW_H = 64
const NUMERAL_H = 14 // 칸 번호가 상자 아래로 내려오는 높이
const STDOUT_BAND = 52 // 출력 바 띠 (height-52부터) — 아무도 침범하지 않는다

// 폭을 "최대 크기" 기준으로 미리 예약한다 — 그래야 리스트가 자랄 때 이웃이 밀려나지 않는다.
// 세로는 콘텐츠(객체·변수·프레임)를 먼저 재고, 출력 바 띠를 그 아래 확보한다 — 겹침은 좌표에서 죽인다.
export function layoutStage(plan: StagePlan): StageLayout {
  const cellW = Math.max(26, Math.min(56, Math.floor((W - OBJ_X - 60) / Math.max(plan.maxListLength, 1))))

  const objPos = new Map<number, Rect>()
  for (const o of plan.objects) {
    const w = Math.max(120, o.maxItems * cellW + 16)
    objPos.set(o.objectId, {
      x: OBJ_X,
      y: 70 + o.slot * (ROW_H + 24),
      w: Math.min(w, W - OBJ_X - 24),
      h: ROW_H,
    })
  }

  const varPos = new Map<string, Rect>()
  const varOrder = [...plan.variables].sort((a, b) => a.life.from - b.life.from)
  varOrder.forEach((v, i) => {
    varPos.set(v.varKey, { x: VAR_X, y: 70 + i * 46, w: VAR_W, h: 36 })
  })

  // 프레임 무리의 키(깊이 계단)까지 콘텐츠로 세고 나서 최종 높이를 정한다
  const maxDepth = Math.max(...plan.frames.map(f => f.depth), 0)
  const frameStackH = 58 + maxDepth * 68

  const maxObjBottom = Math.max(...[...objPos.values()].map(r => r.y + r.h + NUMERAL_H), 0)
  const maxVarBottom = Math.max(...[...varPos.values()].map(r => r.y + r.h), 0)
  const height = Math.max(
    H,
    maxObjBottom + STDOUT_BAND + 8,
    maxVarBottom + STDOUT_BAND + 8,
    70 + frameStackH + STDOUT_BAND + 8,
  )

  // 프레임 카드는 출력 바 8px 위에서 끝나도록 아래에서 위로 쌓는다
  const framePos = new Map<number, Rect>()
  for (const f of plan.frames) {
    framePos.set(f.frameId, {
      x: 24 + f.depth * 18,
      y: height - STDOUT_BAND - 8 - 58 - f.depth * 68,
      w: 260 - f.depth * 18,
      h: 58,
    })
  }

  return { width: W, height, varPos, objPos, framePos, cellW }
}
