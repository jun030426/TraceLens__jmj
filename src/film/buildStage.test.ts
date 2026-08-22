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

/* 캐스팅 — 변수가 쥔 것만 상자를 받는다 (BFS 영상 피드백) */
describe('buildStage: 캐스팅', () => {
  const P = (v: string, t = 'int') => ({ k: 'prim' as const, v, t })
  const ev = (over: Partial<TraceEvent>, seq: number): TraceEvent => ({
    seq, kind: 'line', frameId: 0, parentFrameId: null, func: '<module>',
    causedByLine: null, observedAtLine: 1, localsDelta: [], objectsDelta: [], stdout: '', ...over,
  })

  it('컨테이너 안에만 있는 객체는 상자를 받지 않는다', () => {
    // 튜플 2개(id 2·3)가 리스트(id 1) 안에만 존재 — 리스트만 변수에 묶임
    const events: TraceEvent[] = [
      ev({ kind: 'call' }, 0),
      ev({
        localsDelta: [{ name: 'a', op: 'set', value: { k: 'ref', id: 1 } }],
        objectsDelta: [
          { op: 'set', obj: { id: 2, type: 'tuple', items: [P('0'), P('0')] } },
          { op: 'set', obj: { id: 3, type: 'tuple', items: [P('1'), P('1')] } },
          { op: 'set', obj: { id: 1, type: 'list', items: [{ k: 'ref', id: 2 }, { k: 'ref', id: 3 }, P('9'), P('8')] } },
        ],
      }, 1),
      ev({ localsDelta: [{ name: 'b', op: 'set', value: P('1') }] }, 2),
    ]
    const plan = buildStage(events)
    expect(plan.objects.map(o => o.objectId)).toEqual([1])
  })

  it('재대입으로 놓인 객체의 수명은 재대입 시점을 넘지 않는다', () => {
    const list = (id: number) => ({ op: 'set' as const, obj: { id, type: 'list', items: [P('1'), P('2'), P('3'), P('4')] } })
    const events: TraceEvent[] = [
      ev({ kind: 'call' }, 0),
      ev({ localsDelta: [{ name: 'a', op: 'set', value: { k: 'ref', id: 1 } }], objectsDelta: [list(1)] }, 1),
      ev({ localsDelta: [{ name: 'a', op: 'set', value: { k: 'ref', id: 2 } }], objectsDelta: [list(2)] }, 2),
      ev({ localsDelta: [{ name: 'b', op: 'set', value: P('1') }] }, 3),
      ev({ localsDelta: [{ name: 'c', op: 'set', value: P('1') }] }, 4),
    ]
    const plan = buildStage(events)
    const old = plan.objects.find(o => o.objectId === 1)!
    const cur = plan.objects.find(o => o.objectId === 2)!
    expect(old.life.to).toBeLessThanOrEqual(2)
    expect(cur.life.to).toBe(4) // 계속 쥐고 있으므로 끝까지
  })

  it('작은 프림 튜플 변수는 상자 대신 인라인 — plan.objects에 없다', () => {
    const events: TraceEvent[] = [
      ev({ kind: 'call' }, 0),
      ev({
        localsDelta: [{ name: 'start', op: 'set', value: { k: 'ref', id: 5 } }],
        objectsDelta: [{ op: 'set', obj: { id: 5, type: 'tuple', items: [P('0'), P('0')] } }],
      }, 1),
    ]
    expect(buildStage(events).objects.length).toBe(0)
  })

  it('함수·클래스에만 묶인 변수는 알약을 받지 않는다', () => {
    const events: TraceEvent[] = [
      ev({ kind: 'call' }, 0),
      ev({
        localsDelta: [{ name: 'deque', op: 'set', value: { k: 'ref', id: 7 } }],
        objectsDelta: [{ op: 'set', obj: { id: 7, type: 'type', unsupported: true } }],
      }, 1),
      ev({ localsDelta: [{ name: 'n', op: 'set', value: P('1') }] }, 2),
    ]
    const plan = buildStage(events)
    expect(plan.variables.map(v => v.name)).toEqual(['n'])
    expect(plan.objects.length).toBe(0)
  })
})

describe('buildStage: 격자 판정', () => {
  const P = (v: string, t = 'int') => ({ k: 'prim' as const, v, t })
  const ev = (over: Partial<TraceEvent>, seq: number): TraceEvent => ({
    seq, kind: 'line', frameId: 0, parentFrameId: null, func: '<module>',
    causedByLine: null, observedAtLine: 1, localsDelta: [], objectsDelta: [], stdout: '', ...over,
  })
  const row = (id: number, vals: string[]) => ({ op: 'set' as const, obj: { id, type: 'list', items: vals.map(v => P(v)) } })
  const outer = (id: number, rowIds: number[]) => ({
    op: 'set' as const, obj: { id, type: 'list', items: rowIds.map(rid => ({ k: 'ref' as const, id: rid })) },
  })

  it('균일한 2차원 프림 리스트는 격자가 된다 (0/1이면 binary)', () => {
    const events: TraceEvent[] = [
      ev({ kind: 'call' }, 0),
      ev({
        localsDelta: [{ name: 'maze', op: 'set', value: { k: 'ref', id: 1 } }],
        objectsDelta: [row(11, ['0', '0', '1', '0']), row(12, ['1', '0', '1', '0']), row(13, ['0', '0', '0', '0']), row(14, ['0', '1', '1', '0']), outer(1, [11, 12, 13, 14])],
      }, 1),
    ]
    const plan = buildStage(events)
    const maze = plan.objects.find(o => o.objectId === 1)!
    expect(maze.grid).toEqual({ rows: 4, cols: 4, binary: true })
  })

  it('숫자 DP 테이블은 binary가 아니다', () => {
    const events: TraceEvent[] = [
      ev({ kind: 'call' }, 0),
      ev({
        localsDelta: [{ name: 'dp', op: 'set', value: { k: 'ref', id: 2 } }],
        objectsDelta: [row(21, ['0', '5']), row(22, ['3', '9']), outer(2, [21, 22])],
      }, 1),
    ]
    expect(buildStage(events).objects.find(o => o.objectId === 2)!.grid).toEqual({ rows: 2, cols: 2, binary: false })
  })

  it('행 길이가 다르면 격자가 아니다', () => {
    const events: TraceEvent[] = [
      ev({ kind: 'call' }, 0),
      ev({
        localsDelta: [{ name: 'a', op: 'set', value: { k: 'ref', id: 3 } }],
        objectsDelta: [row(31, ['0', '1']), row(32, ['0', '1', '2']), outer(3, [31, 32])],
      }, 1),
    ]
    expect(buildStage(events).objects.find(o => o.objectId === 3)!.grid).toBeUndefined()
  })

  it('1차원 프림 리스트는 격자가 아니다', () => {
    const events: TraceEvent[] = [
      ev({ kind: 'call' }, 0),
      ev({ localsDelta: [{ name: 'a', op: 'set', value: { k: 'ref', id: 4 } }], objectsDelta: [row(4, ['1', '2', '3', '4'])] }, 1),
    ]
    expect(buildStage(events).objects.find(o => o.objectId === 4)!.grid).toBeUndefined()
  })
})

describe('buildStage: staging 힌트', () => {
  const P = (v: string, t = 'int') => ({ k: 'prim' as const, v, t })
  const ev = (over: Partial<TraceEvent>, seq: number): TraceEvent => ({
    seq, kind: 'line', frameId: 0, parentFrameId: null, func: '<module>',
    causedByLine: null, observedAtLine: 1, localsDelta: [], objectsDelta: [], stdout: '', ...over,
  })
  const row = (id: number, vals: string[]) => ({ op: 'set' as const, obj: { id, type: 'list', items: vals.map(v => P(v)) } })
  const outer = (id: number, rowIds: number[]) => ({
    op: 'set' as const, obj: { id, type: 'list', items: rowIds.map(rid => ({ k: 'ref' as const, id: rid })) },
  })
  const primMaze = (): TraceEvent[] => [
    ev({ kind: 'call' }, 0),
    ev({
      localsDelta: [{ name: 'maze', op: 'set', value: { k: 'ref', id: 1 } }],
      objectsDelta: [row(11, ['0', '1']), row(12, ['0', '0']), outer(1, [11, 12])],
    }, 1),
  ]
  const strMaze = (rows: string[]): TraceEvent[] => [
    ev({ kind: 'call' }, 0),
    ev({
      localsDelta: [{ name: 'maze', op: 'set', value: { k: 'ref', id: 2 } }],
      objectsDelta: [{ op: 'set', obj: { id: 2, type: 'list', items: rows.map(s => P(`'${s}'`, 'str')) } }],
    }, 1),
  ]

  it('noGrid는 규칙이 격자로 본 것을 상자로 강제한다', () => {
    const plan = buildStage(primMaze(), { noGrid: ['maze'] })
    expect(plan.objects.find(o => o.objectId === 1)!.grid).toBeUndefined()
  })

  it('grid 힌트는 같은 길이 문자열 행 리스트를 격자로 연다', () => {
    const plan = buildStage(strMaze(['S.#', '..#', '#.G']), { grid: ['maze'] })
    expect(plan.objects.find(o => o.objectId === 2)!.grid).toEqual({ rows: 3, cols: 3, binary: false })
  })

  it('힌트가 없으면 문자열 리스트는 상자다', () => {
    const plan = buildStage(strMaze(['S.#', '..#', '#.G']))
    expect(plan.objects.find(o => o.objectId === 2)!.grid).toBeUndefined()
  })

  it('자격 미달(들쭉 길이)은 grid 힌트가 있어도 무시된다', () => {
    const plan = buildStage(strMaze(['S.#', '..']), { grid: ['maze'] })
    expect(plan.objects.find(o => o.objectId === 2)!.grid).toBeUndefined()
  })
})

/* 프레임 수명 — 반환하지 않은 프레임은 스택에 살아 있는 것이 사실이다.
   수명을 마지막 관측에서 끊으면 무한 재귀(트레이서 사망)의 스택 창이 카드 한 장짜리가 된다 */
describe('buildStage: 반환 없는 프레임의 수명', () => {
  const P = (v: string, t = 'int') => ({ k: 'prim' as const, v, t })
  const ev = (over: Partial<TraceEvent>, seq: number): TraceEvent => ({
    seq, kind: 'line', frameId: 0, parentFrameId: null, func: '<module>',
    causedByLine: null, observedAtLine: 1, localsDelta: [], objectsDelta: [], stdout: '',
    ...over,
  })

  it('반환 없이 끝난 프레임은 마지막 이벤트까지 산다 — 스택의 사실', () => {
    // countdown 축소판: 하강만 있고 아무도 반환하지 못한 채 기록이 끝난다
    const events: TraceEvent[] = [
      ev({ kind: 'call' }, 0),
      ev({ observedAtLine: 4 }, 1),
      ev({ kind: 'call', frameId: 1, parentFrameId: 0, func: 'countdown', localsDelta: [{ name: 'n', op: 'set', value: P('2') }] }, 2),
      ev({ frameId: 1, func: 'countdown', observedAtLine: 2 }, 3),
      ev({ kind: 'call', frameId: 2, parentFrameId: 1, func: 'countdown', localsDelta: [{ name: 'n', op: 'set', value: P('1') }] }, 4),
      ev({ frameId: 2, func: 'countdown', observedAtLine: 2 }, 5),
    ]
    const plan = buildStage(events)
    for (const f of plan.frames) expect(f.life.to).toBe(5)
  })

  it('반환한 프레임의 수명은 그 반환까지다 — 기존 그대로', () => {
    const events: TraceEvent[] = [
      ev({ kind: 'call' }, 0),
      ev({ kind: 'call', frameId: 1, parentFrameId: 0, func: 'f', localsDelta: [{ name: 'x', op: 'set', value: P('1') }] }, 1),
      ev({ kind: 'return', frameId: 1, parentFrameId: 0, func: 'f' }, 2),
      ev({ observedAtLine: 3 }, 3),
      ev({ kind: 'return' }, 4),
    ]
    const plan = buildStage(events)
    expect(plan.frames.find(f => f.frameId === 1)!.life.to).toBe(2)
    expect(plan.frames.find(f => f.frameId === 0)!.life.to).toBe(4)
  })
})
