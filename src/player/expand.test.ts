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
  it('fast 장면은 접히고 실제 반복 횟수(5회)가 붙는다', () => {
    const fast = steps.filter(s => s.durationMs === PACING_MS.fast)
    expect(fast.length).toBeLessThanOrEqual(4)
    // loop fixture는 range(5) — 몸통이 정확히 5회 실행되므로 "총 5회 반복"이어야 한다
    expect(fast.some(s => s.narration.includes('총 5회 반복'))).toBe(true)
  })
  it('chapterIndex가 존재한다', () => {
    expect(new Set(steps.map(s => s.chapterIndex)).size).toBeGreaterThanOrEqual(1)
  })

  it('바인딩 시점에 변수가 아직 없으면 몇 스냅 앞의 첫 값으로 치환한다 (? 금지)', () => {
    // "X가 {v}로 초기화됩니다"를 대입 관측 직전 스팬에 붙이는 AI 습관 — 값은 다음 스냅에 있다
    const first = snaps[0]
    const sp = {
      chapters: [
        {
          title: 't',
          scenes: [
            {
              seqStart: first.seq,
              seqEnd: first.seq,
              primitive: 'variables' as const,
              focus: [],
              pacing: 'normal' as const,
              narration: { template: 'total이 {v}가 됩니다', bindings: { v: { seq: first.seq, name: 'total' } } },
            },
          ],
        },
      ],
    }
    const out = expandScreenplay(sp, snaps)
    expect(out[0].narration).not.toContain('?')
    expect(out[0].narration).toMatch(/total이 .+가 됩니다/)
  })
})
