import { describe, it, expect } from 'vitest'
import demo from '../fixtures/film-demo.trace.json'
import type { TraceEvent } from '../trace/types'
import { buildStage } from './buildStage'
import { layoutStage } from './layout'

const events = (demo as { events: TraceEvent[] }).events
const plan = buildStage(events)
const L = layoutStage(plan)

describe('layoutStage', () => {
  it('모든 등장인물에 자리가 있다', () => {
    for (const o of plan.objects) expect(L.objPos.has(o.objectId)).toBe(true)
    for (const v of plan.variables) expect(L.varPos.has(v.varKey)).toBe(true)
    for (const f of plan.frames) expect(L.framePos.has(f.frameId)).toBe(true)
  })
  it('객체 폭이 최대 크기만큼 예약된다', () => {
    const big = plan.objects.find(o => o.maxItems >= 12)!
    expect(big).toBeDefined()
    expect(L.objPos.get(big.objectId)!.w).toBeGreaterThanOrEqual(big.maxItems * L.cellW)
  })
  it('모든 자리가 화면 안에 있다', () => {
    for (const r of L.objPos.values()) {
      expect(r.x).toBeGreaterThanOrEqual(0)
      expect(r.y + r.h).toBeLessThanOrEqual(L.height)
    }
  })
  it('셀 폭에 하한이 있다', () => {
    expect(L.cellW).toBeGreaterThanOrEqual(26)
  })

  /* 겹침 금지 — "덮어져 있는 느낌"의 원인들을 좌표 수준에서 차단한다 */

  it('출력 바 띠(height-52 아래)를 아무도 침범하지 않는다', () => {
    const stdoutTop = L.height - 52
    for (const r of L.objPos.values()) expect(r.y + r.h + 14).toBeLessThanOrEqual(stdoutTop) // +14 = 칸 번호
    for (const r of L.varPos.values()) expect(r.y + r.h).toBeLessThanOrEqual(stdoutTop)
    for (const r of L.framePos.values()) expect(r.y + r.h).toBeLessThanOrEqual(stdoutTop)
  })

  it('프레임 카드끼리 세로로 겹치지 않는다', () => {
    const rects = [...L.framePos.values()].sort((a, b) => a.y - b.y)
    for (let i = 1; i < rects.length; i++) {
      if (rects[i].y === rects[i - 1].y) continue // 같은 깊이는 시간상 교대 사용
      expect(rects[i].y).toBeGreaterThanOrEqual(rects[i - 1].y + rects[i - 1].h)
    }
  })

  it('변수 알약이 객체 상자 열(x=560)에 닿지 않는다', () => {
    for (const r of L.varPos.values()) expect(r.x + r.w).toBeLessThanOrEqual(560)
  })
})
