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
})
