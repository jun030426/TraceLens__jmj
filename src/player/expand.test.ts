import { describe, it, expect } from 'vitest'
import loopFixture from '../fixtures/loop.trace.json'
import type { TraceEvent } from '../trace/types'
import { buildSnapshots } from '../trace/snapshots'
import { buildScreenplay } from '../screenplay/ruleDirector'
import { expandScreenplay, PACING_MS } from './expand'

const events = (loopFixture as { events: TraceEvent[] }).events
const snaps = buildSnapshots(events)
const steps = expandScreenplay(buildScreenplay(events), snaps)

describe('expandScreenplay', () => {
  it('스텝 seq가 단조 증가한다', () => {
    for (let i = 1; i < steps.length; i++) expect(steps[i].seq).toBeGreaterThan(steps[i - 1].seq)
  })
  it('narration에 미치환 {키}가 남지 않는다', () => {
    for (const s of steps) expect(s.narration).not.toMatch(/\{[a-z]+\}/i)
  })
  it('값이 치환된다 (total 설정 스텝에 실제 숫자)', () => {
    const set = steps.find(s => s.narration.includes('total이(가)'))
    expect(set).toBeDefined()
    expect(set!.narration).toMatch(/[0-9]/)
  })
  it('fast 장면은 접히고 ×N이 붙는다', () => {
    const fast = steps.filter(s => s.durationMs === PACING_MS.fast)
    expect(fast.length).toBeLessThanOrEqual(4)
    expect(fast.some(s => /×\d+회/.test(s.narration))).toBe(true)
  })
  it('chapterIndex가 존재한다', () => {
    expect(new Set(steps.map(s => s.chapterIndex)).size).toBeGreaterThanOrEqual(1)
  })
})
