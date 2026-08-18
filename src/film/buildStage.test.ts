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
