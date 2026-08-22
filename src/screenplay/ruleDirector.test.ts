import { describe, it, expect } from 'vitest'
import aliasingFixture from '../fixtures/aliasing.trace.json'
import loopFixture from '../fixtures/loop.trace.json'
import { buildScreenplay } from './ruleDirector'
import type { TraceEvent } from '../trace/types'

const aliasing = (aliasingFixture as { events: TraceEvent[] }).events
const loop = (loopFixture as { events: TraceEvent[] }).events

describe('buildScreenplay', () => {
  it('모든 장면의 seq 구간이 단조 증가하고 트레이스 안에 있다', () => {
    const sp = buildScreenplay(aliasing)
    let last = -1
    for (const ch of sp.chapters) for (const sc of ch.scenes) {
      expect(sc.seqStart).toBeGreaterThan(last)
      expect(sc.seqEnd).toBeLessThan(aliasing.length)
      last = sc.seqEnd
    }
  })
  it('aliasing 트레이스에서 objectGraph 장면이 나온다', () => {
    const sp = buildScreenplay(aliasing)
    const prims = sp.chapters.flatMap(c => c.scenes).map(s => s.primitive)
    expect(prims).toContain('objectGraph')
  })
  it('루프 트레이스에서 fast(접기) 장면이 나온다', () => {
    const sp = buildScreenplay(loop)
    const fast = sp.chapters.flatMap(c => c.scenes).find(s => s.pacing === 'fast')
    expect(fast).toBeDefined()
    expect(fast!.repeat).toBeGreaterThan(1)
  })
  it('call 없는 코드는 챕터 1개', () => {
    const sp = buildScreenplay(loop.filter(e => e.kind !== 'call' && e.kind !== 'return'))
    expect(sp.chapters.length).toBe(1)
  })
  it('narration 템플릿은 값 문자열을 직접 포함하지 않는다 (바인딩 강제)', () => {
    const sp = buildScreenplay(aliasing)
    for (const sc of sp.chapters.flatMap(c => c.scenes)) {
      if (sc.narration.template.includes('{value}'))
        expect(sc.narration.bindings.value).toBeDefined()
    }
  })
})
