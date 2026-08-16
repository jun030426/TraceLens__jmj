import { describe, it, expect } from 'vitest'
import demo from '../fixtures/film-demo.trace.json'
import aliasing from '../fixtures/aliasing.trace.json'
import type { TraceEvent } from '../trace/types'
import { buildStage } from './buildStage'
import { choreograph } from './choreograph'

const demoEvents = (demo as { events: TraceEvent[] }).events
const aliasEvents = (aliasing as { events: TraceEvent[] }).events

/* 합성 이벤트 헬퍼 — 특정 문법 상황을 최소 트레이스로 재현한다 */
const P = (v: string, t = 'int') => ({ k: 'prim' as const, v, t })
const ev = (over: Partial<TraceEvent>, seq: number): TraceEvent => ({
  seq,
  kind: 'line',
  frameId: 0,
  parentFrameId: null,
  func: '<module>',
  causedByLine: null,
  observedAtLine: 1,
  localsDelta: [],
  objectsDelta: [],
  stdout: '',
  ...over,
})
const listSet = (items: string[]) => ({
  op: 'set' as const,
  obj: { id: 1, type: 'list', items: items.map(v => P(v)) },
})

describe('choreograph', () => {
  const shots = choreograph(demoEvents, buildStage(demoEvents))

  it('샷 seq가 단조 증가한다', () => {
    for (let i = 1; i < shots.length; i++) expect(shots[i].seq).toBeGreaterThan(shots[i - 1].seq)
  })

  it('원본보다 짧다 — 10회 규칙으로 압축된다', () => {
    expect(shots.length).toBeGreaterThan(0)
    expect(shots.length).toBeLessThan(demoEvents.length)
  })

  it('반복이 10회를 넘으면 timelapse 샷이 생긴다 (range(12))', () => {
    const lapse = shots.filter(s => s.timelapse && s.timelapse > 1)
    expect(lapse.length).toBeGreaterThan(0)
  })

  it('리스트가 자라는 순간에 grow 모션이 있다', () => {
    expect(shots.some(s => s.motions.some(m => m.v === 'grow'))).toBe(true)
  })

  it('함수 호출·반환이 프레임 모션으로 나온다', () => {
    expect(shots.some(s => s.motions.some(m => m.v === 'pushFrame'))).toBe(true)
    expect(shots.some(s => s.motions.some(m => m.v === 'popFrame'))).toBe(true)
  })

  it('출력이 stdout 모션으로 나온다', () => {
    expect(shots.some(s => s.motions.some(m => m.v === 'stdout'))).toBe(true)
  })

  it('별칭 순간은 alias 플래그와 긴 지속시간을 갖는다', () => {
    const aliasShots = choreograph(aliasEvents, buildStage(aliasEvents))
    const bind = aliasShots.flatMap(s => s.motions.map(m => ({ m, s }))).find(x => x.m.v === 'bind' && x.m.alias)
    expect(bind).toBeDefined()
    expect(bind!.s.durationMs).toBeGreaterThan(520)
  })

  it('모든 샷에 최소 하나의 모션이 있다 (빈 샷 금지)', () => {
    for (const s of shots) expect(s.motions.length).toBeGreaterThan(0)
  })

  it('리터럴로 태어난 리스트의 칸도 채워진다 (빈 상자 금지)', () => {
    // team_a = ["kim", "lee"] 처럼 처음부터 원소를 가진 객체
    const aliasShots = choreograph(aliasEvents, buildStage(aliasEvents))
    const texts = aliasShots
      .flatMap(s => s.motions)
      .filter(m => m.v === 'grow')
      .map(m => (m as { text: string }).text)
    expect(texts.some(t => t.includes('kim'))).toBe(true)
    expect(texts.some(t => t.includes('lee'))).toBe(true)
  })
})

describe('choreograph: 정밀 칸 diff', () => {
  it('크기가 같아도 바뀐 칸을 전부 짚는다 (0번과 2번)', () => {
    const events: TraceEvent[] = [
      ev({ kind: 'call' }, 0),
      ev({ localsDelta: [{ name: 'a', op: 'set', value: { k: 'ref', id: 1 } }], objectsDelta: [listSet(['1', '2', '3'])] }, 1),
      ev({ objectsDelta: [listSet(['9', '2', '7'])] }, 2),
    ]
    const shots = choreograph(events, buildStage(events))
    const cells = shots.flatMap(s => s.motions).filter(m => m.v === 'setCell') as { index: number; text: string }[]
    expect(cells.map(c => [c.index, c.text])).toEqual(expect.arrayContaining([[0, '9'], [2, '7']]))
    expect(cells.some(c => c.index === 1)).toBe(false)
  })

  it('크기가 줄면 사라진 칸에 shrink가 나온다', () => {
    const events: TraceEvent[] = [
      ev({ kind: 'call' }, 0),
      ev({ localsDelta: [{ name: 'a', op: 'set', value: { k: 'ref', id: 1 } }], objectsDelta: [listSet(['1', '2'])] }, 1),
      ev({ objectsDelta: [listSet(['1'])] }, 2),
    ]
    const shots = choreograph(events, buildStage(events))
    const shrink = shots.flatMap(s => s.motions).find(m => m.v === 'shrink')
    expect(shrink).toMatchObject({ objectId: 1, index: 1 })
  })
})

describe('choreograph: raise', () => {
  it('예외 이벤트에 raise 모션이 나오고 오류명이 담긴다', () => {
    const events: TraceEvent[] = [
      ev({ kind: 'call' }, 0),
      ev({ localsDelta: [{ name: 'a', op: 'set', value: P('1') }] }, 1),
      ev({ kind: 'exception', error: 'IndexError: list index out of range', observedAtLine: 2 }, 2),
    ]
    const shots = choreograph(events, buildStage(events))
    const raise = shots.flatMap(s => s.motions).find(m => m.v === 'raise')
    expect(raise).toBeDefined()
    expect((raise as { text: string }).text).toContain('IndexError')
  })
})
