import { describe, it, expect } from 'vitest'
import type { TraceEvent } from './types'
import { buildSnapshots, aliasGroups } from './snapshots'

const ev = (p: Partial<TraceEvent>): TraceEvent => ({
  seq: 0, kind: 'line', frameId: 0, parentFrameId: null, func: '<module>',
  causedByLine: null, observedAtLine: 1, localsDelta: [], objectsDelta: [], stdout: '', ...p,
})

describe('buildSnapshots', () => {
  const events: TraceEvent[] = [
    ev({ seq: 0, observedAtLine: 1 }),
    ev({ seq: 1, causedByLine: 1, observedAtLine: 2,
      localsDelta: [{ name: 'a', op: 'set', value: { k: 'ref', id: 7 } }],
      objectsDelta: [{ op: 'set', obj: { id: 7, type: 'list', items: [{ k: 'prim', v: "'kim'", t: 'str' }] } }] }),
    ev({ seq: 2, causedByLine: 2, observedAtLine: 3,
      localsDelta: [{ name: 'b', op: 'set', value: { k: 'ref', id: 7 } }] }),
    ev({ seq: 3, kind: 'call', frameId: 1, parentFrameId: 0, func: 'f', observedAtLine: 5 }),
    ev({ seq: 4, frameId: 1, func: 'f', observedAtLine: 6,
      localsDelta: [{ name: 'x', op: 'set', value: { k: 'prim', v: '1', t: 'int' } }] }),
    ev({ seq: 5, kind: 'return', frameId: 1, parentFrameId: 0, func: 'f', observedAtLine: 6 }),
    ev({ seq: 6, causedByLine: 3, observedAtLine: 4, stdout: 'hi\n',
      localsDelta: [{ name: 'b', op: 'delete' }] }),
  ]
  const snaps = buildSnapshots(events)

  it('스택이 call/return을 따라간다', () => {
    expect(snaps[3].stack.map(f => f.func)).toEqual(['<module>', 'f'])
    expect(snaps[5].stack.map(f => f.func)).toEqual(['<module>'])
  })
  it('locals가 프레임별로 누적된다', () => {
    expect(snaps[2].stack[0].locals.get('a')).toEqual({ k: 'ref', id: 7 })
    expect(snaps[4].stack[1].locals.get('x')).toEqual({ k: 'prim', v: '1', t: 'int' })
  })
  it('delete가 적용된다', () => {
    expect(snaps[6].stack[0].locals.has('b')).toBe(false)
  })
  it('stdout이 누적된다', () => {
    expect(snaps[6].stdout).toBe('hi\n')
  })
  it('aliasing을 감지한다', () => {
    expect(aliasGroups(snaps[2])).toEqual([{ id: 7, names: ['a', 'b'] }])
  })
  it('line은 causedByLine 우선', () => {
    expect(snaps[1].line).toBe(1)
    expect(snaps[0].line).toBe(1)
  })
})
