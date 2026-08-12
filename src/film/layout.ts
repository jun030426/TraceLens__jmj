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
const ROW_H = 64

// 폭을 "최대 크기" 기준으로 미리 예약한다 — 그래야 리스트가 자랄 때 이웃이 밀려나지 않는다.
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
    varPos.set(v.varKey, { x: VAR_X, y: 70 + i * 46, w: 168, h: 36 })
  })

  const framePos = new Map<number, Rect>()
  for (const f of plan.frames) {
    framePos.set(f.frameId, {
      x: 24 + f.depth * 18,
      y: H - 96 - f.depth * 68,
      w: 260 - f.depth * 18,
      h: 58,
    })
  }

  const maxObjBottom = Math.max(...[...objPos.values()].map(r => r.y + r.h), 0)
  const maxVarBottom = Math.max(...[...varPos.values()].map(r => r.y + r.h), 0)
  const height = Math.max(H, maxObjBottom + 40, maxVarBottom + 40)

  return { width: W, height, varPos, objPos, framePos, cellW }
}
