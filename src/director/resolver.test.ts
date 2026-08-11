import { describe, it, expect } from 'vitest'
import type { Digest } from '../digest/buildDigest'
import { resolveScreenplay, ValidationError } from './resolver'

const digest: Digest = {
  spans: [
    { spanId: 's0', sourceSeqRange: [0, 0], lines: [1, 1], eventKinds: ['call'], funcs: ['<module>'], changedVars: [] },
    { spanId: 's1', sourceSeqRange: [1, 1], lines: [1, 2], eventKinds: ['line'], funcs: ['<module>'], changedVars: ['a'] },
    { spanId: 'loop_0', sourceSeqRange: [2, 8], lines: [2, 3], eventKinds: ['line'], funcs: ['<module>'], changedVars: ['i'], iterations: 7 },
    { spanId: 's2', sourceSeqRange: [9, 9], lines: [4, 4], eventKinds: ['return'], funcs: ['<module>'], changedVars: [] },
  ],
}

const good = {
  chapters: [
    { title: '준비', scenes: [
      { spanRef: 's0', primitive: 'variables', narration: { template: '실행을 시작합니다' } },
      { spanRef: 's1', primitive: 'variables', focus: ['a'], pacing: 'slow',
        narration: { template: 'a이(가) {v}로 설정됩니다', bindings: { v: { name: 'a' } } } },
    ] },
    { title: '반복', scenes: [
      { spanRef: 'loop_0', primitive: 'variables', pacing: 'fast', narration: { template: '반복이 진행됩니다' } },
      { spanRef: 's2', primitive: 'callStack', narration: { template: '실행이 끝났습니다' } },
    ] },
  ],
}

describe('resolveScreenplay', () => {
  it('정상 대본을 Screenplay로 치환한다 (seq는 리졸버가 부여)', () => {
    const sp = resolveScreenplay(good, digest)
    expect(sp.chapters.length).toBe(2)
    const s1 = sp.chapters[0].scenes[1]
    expect(s1.seqStart).toBe(1)
    expect(s1.narration.bindings.v).toEqual({ seq: 1, name: 'a' })
    const loop = sp.chapters[1].scenes[0]
    expect(loop.seqEnd).toBe(8)
    expect(loop.repeat).toBe(7)
    expect(loop.pacing).toBe('fast')
  })
  it('없는 spanRef는 거부한다', () => {
    const bad = { chapters: [{ title: 'x', scenes: [{ spanRef: 'ghost', primitive: 'variables', narration: { template: 't' } }] }] }
    expect(() => resolveScreenplay(bad, digest)).toThrow(ValidationError)
  })
  it('실행 순서를 어기는 배열은 거부한다', () => {
    const bad = { chapters: [{ title: 'x', scenes: [
      { spanRef: 's2', primitive: 'variables', narration: { template: 't' } },
      { spanRef: 's0', primitive: 'variables', narration: { template: 't' } },
    ] }] }
    expect(() => resolveScreenplay(bad, digest)).toThrow(/순서/)
  })
  it('허용되지 않은 primitive는 거부한다', () => {
    const bad = { chapters: [{ title: 'x', scenes: [{ spanRef: 's0', primitive: '3d-hologram', narration: { template: 't' } }] }] }
    expect(() => resolveScreenplay(bad, digest)).toThrow(/primitive/)
  })
  it('바인딩 없는 {플레이스홀더}는 거부한다', () => {
    const bad = { chapters: [{ title: 'x', scenes: [
      { spanRef: 's0', primitive: 'variables', narration: { template: '{x}가 변합니다' } },
    ] }] }
    expect(() => resolveScreenplay(bad, digest)).toThrow(/바인딩/)
  })
})
