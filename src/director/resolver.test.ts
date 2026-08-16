import { describe, it, expect } from 'vitest'
import type { Digest } from '../digest/buildDigest'
import type { Scene, Screenplay } from '../screenplay/types'
import { resolveScreenplay, salvageScreenplay, ValidationError } from './resolver'

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

describe('salvageScreenplay', () => {
  const sDigest: Digest = {
    spans: [
      { spanId: 's0', sourceSeqRange: [0, 0], lines: [1, 1], eventKinds: ['line'], funcs: ['<module>'], changedVars: ['a'] },
      { spanId: 's1', sourceSeqRange: [1, 1], lines: [2, 2], eventKinds: ['line'], funcs: ['<module>'], changedVars: ['b'] },
      { spanId: 's2', sourceSeqRange: [2, 2], lines: [3, 3], eventKinds: ['line'], funcs: ['<module>'], changedVars: ['c'] },
    ],
  }
  const ruleScene = (seq: number, name: string): Scene => ({
    seqStart: seq, seqEnd: seq, primitive: 'variables', focus: [name],
    pacing: 'normal', narration: { template: `${name} 변경`, bindings: {} },
  })
  const rule: Screenplay = {
    chapters: [{ title: '실행', scenes: [ruleScene(0, 'a'), ruleScene(1, 'b'), ruleScene(2, 'c')] }],
  }
  const aiScene = (ref: string) => ({
    spanRef: ref, primitive: 'variables', focus: [], pacing: 'slow',
    narration: { template: 'AI 장면', bindings: {} },
  })

  it('무효 장면만 버리고 빠진 구간을 규칙 장면으로 메꾼다', () => {
    const raw = { chapters: [{ title: '1장', scenes: [aiScene('s0'), aiScene('없는거'), aiScene('s2')] }] }
    const out = salvageScreenplay(raw, sDigest, rule)!
    expect(out).not.toBeNull()
    const flat = out.chapters.flatMap(c => c.scenes)
    expect(flat.map(s => s.seqStart)).toEqual([0, 1, 2])
    expect(flat[1].narration.template).toBe('b 변경')
    expect(flat[0].narration.template).toBe('AI 장면')
    expect(out.chapters[0].title).toBe('1장')
  })

  it('순서를 어긴 장면은 그 장면만 버린다', () => {
    const raw = { chapters: [{ title: '1장', scenes: [aiScene('s2'), aiScene('s0'), aiScene('s1')] }] }
    const out = salvageScreenplay(raw, sDigest, rule)!
    const flat = out.chapters.flatMap(c => c.scenes)
    expect(flat.map(s => s.seqStart)).toEqual([0, 1, 2])
    expect(flat[2].narration.template).toBe('AI 장면')
    expect(flat[0].narration.template).toBe('a 변경')
  })

  it('전부 무효면 null (전체 규칙 폴백)', () => {
    const raw = { chapters: [{ title: '1장', scenes: [aiScene('x'), aiScene('y')] }] }
    expect(salvageScreenplay(raw, sDigest, rule)).toBeNull()
  })
})

describe('direction 파싱', () => {
  const scene = (direction: unknown) => ({
    chapters: [
      { title: 't', scenes: [{ spanRef: 's0', primitive: 'variables', direction, narration: { template: '한 장면' } }] },
    ],
  })
  it('유효 동사만 남기고 중복·미지 동사는 버린다', () => {
    const sp = resolveScreenplay(scene(['zoom', 'explode', 'zoom', 'hold']), digest)
    expect(sp.chapters[0].scenes[0].direction).toEqual(['zoom', 'hold'])
  })
  it('direction이 없거나 배열이 아니면 빈 배열', () => {
    expect(resolveScreenplay(scene(undefined), digest).chapters[0].scenes[0].direction).toEqual([])
    expect(resolveScreenplay(scene('zoom'), digest).chapters[0].scenes[0].direction).toEqual([])
  })
})
