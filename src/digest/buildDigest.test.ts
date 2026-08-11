import { describe, it, expect } from 'vitest'
import loopFixture from '../fixtures/loop.trace.json'
import aliasingFixture from '../fixtures/aliasing.trace.json'
import type { TraceEvent } from '../trace/types'
import { buildDigest } from './buildDigest'

const loop = (loopFixture as { events: TraceEvent[] }).events
const aliasing = (aliasingFixture as { events: TraceEvent[] }).events

describe('buildDigest', () => {
  const digest = buildDigest(loop)

  it('스팬이 트레이스 전체를 순서대로 덮는다', () => {
    let last = -1
    for (const s of digest.spans) {
      expect(s.sourceSeqRange[0]).toBeGreaterThan(last)
      expect(s.sourceSeqRange[1]).toBeGreaterThanOrEqual(s.sourceSeqRange[0])
      last = s.sourceSeqRange[1]
    }
    expect(last).toBe(loop[loop.length - 1].seq)
  })
  it('루프가 iterations 있는 스팬으로 접힌다', () => {
    const folded = digest.spans.find(s => (s.iterations ?? 0) > 1)
    expect(folded).toBeDefined()
    expect(folded!.changedVars).toContain('total')
  })
  it('spanId가 유일하다', () => {
    const ids = digest.spans.map(s => s.spanId)
    expect(new Set(ids).size).toBe(ids.length)
  })
  it('aliasing 트레이스에서 aliasNote가 생성된다', () => {
    const d = buildDigest(aliasing)
    expect(d.aliasNote).toContain('team_a')
    expect(d.aliasNote).toContain('team_b')
  })
  it('LLM 입력 크기가 원본보다 훨씬 작다', () => {
    const raw = JSON.stringify(loop).length
    const compressed = JSON.stringify(digest).length
    expect(compressed).toBeLessThan(raw / 2)
  })
})
