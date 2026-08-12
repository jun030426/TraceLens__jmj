import { describe, it, expect } from 'vitest'
import demo from '../fixtures/film-demo.trace.json'
import aliasing from '../fixtures/aliasing.trace.json'
import type { TraceEvent } from '../trace/types'
import { buildStage } from './buildStage'

const demoEvents = (demo as { events: TraceEvent[] }).events
const aliasEvents = (aliasing as { events: TraceEvent[] }).events

describe('buildStage', () => {
  const plan = buildStage(demoEvents)

  it('등장인물을 모두 수집한다', () => {
    expect(plan.objects.length).toBeGreaterThan(0)
    expect(plan.variables.length).toBeGreaterThan(0)
    expect(plan.frames.length).toBeGreaterThan(0)
  })

  it('생몰 구간이 유효하다 (from <= to, 트레이스 범위 안)', () => {
    const last = demoEvents[demoEvents.length - 1].seq
    for (const o of plan.objects) {
      expect(o.life.from).toBeLessThanOrEqual(o.life.to)
      expect(o.life.to).toBeLessThanOrEqual(last)
    }
  })

  it('리스트의 최대 크기를 기록한다 (build_squares는 12칸까지 자람)', () => {
    expect(plan.maxListLength).toBeGreaterThanOrEqual(12)
  })

  it('재귀 프레임에 recursionIndex가 매겨진다 (total_of)', () => {
    const rec = plan.frames.filter(f => f.func === 'total_of')
    expect(rec.length).toBeGreaterThan(1)
    expect(Math.max(...rec.map(f => f.recursionIndex))).toBeGreaterThan(0)
  })

  it('최대 스택 깊이가 재귀를 반영한다', () => {
    expect(plan.maxStackDepth).toBeGreaterThanOrEqual(3)
  })

  it('주연을 고른다', () => {
    expect(plan.leadObjectId).not.toBeNull()
  })

  it('슬롯이 겹치지 않는다 — 같은 슬롯을 쓰는 객체는 생몰이 안 겹친다', () => {
    const bySlot = new Map<number, typeof plan.objects>()
    for (const o of plan.objects) bySlot.set(o.slot, [...(bySlot.get(o.slot) ?? []), o])
    for (const group of bySlot.values()) {
      const sorted = [...group].sort((a, b) => a.life.from - b.life.from)
      for (let i = 1; i < sorted.length; i++) {
        expect(sorted[i].life.from).toBeGreaterThan(sorted[i - 1].life.to)
      }
    }
    expect(plan.slotCount).toBeLessThanOrEqual(plan.objects.length)
  })

  it('별칭을 referencedBy로 잡는다', () => {
    const p = buildStage(aliasEvents)
    const shared = p.objects.find(o => o.referencedBy.length > 1)
    expect(shared).toBeDefined()
    expect(shared!.referencedBy.some(k => k.endsWith(':team_a'))).toBe(true)
    expect(shared!.referencedBy.some(k => k.endsWith(':team_b'))).toBe(true)
  })
})
