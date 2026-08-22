import { describe, it, expect } from 'vitest'
import demo from '../fixtures/film-demo.trace.json'
import aliasing from '../fixtures/aliasing.trace.json'
import type { TraceEvent } from '../trace/types'
import type { Motion } from './types'
import { buildStage } from './buildStage'
import { choreograph } from './choreograph'

const demoEvents = (demo as { events: TraceEvent[] }).events
const demoCode = (demo as { code?: string }).code ?? ''
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

describe('choreograph: 반복 배지', () => {
  const shots = choreograph(demoEvents, buildStage(demoEvents), demoCode)
  const all = shots.flatMap(s => s.motions)

  it('반복 중에 회차 배지가 나온다', () => {
    const loops = all.filter(m => m.v === 'loop') as { text: string }[]
    expect(loops.some(l => l.text.includes('회차'))).toBe(true)
  })

  it('압축 샷은 빨리감기 문구를 단다', () => {
    const loops = all.filter(m => m.v === 'loop') as { text: string }[]
    expect(loops.some(l => l.text.includes('빨리감기'))).toBe(true)
  })

  it('반복이 끝나면 배지가 내려간다', () => {
    expect(all.some(m => m.v === 'loopEnd')).toBe(true)
  })
})

describe('choreograph: 학습자 자막', () => {
  const swapCode = 'arr = [5, 2]\nn = 0\nif arr[0] > arr[1]:\n    arr[0], arr[1] = arr[1], arr[0]\n'
  const swapEvents: TraceEvent[] = [
    ev({ kind: 'call', observedAtLine: 1 }, 0),
    ev({
      observedAtLine: 2, causedByLine: 1,
      localsDelta: [{ name: 'arr', op: 'set', value: { k: 'ref', id: 1 } }],
      objectsDelta: [listSet(['5', '2'])],
    }, 1),
    ev({ observedAtLine: 3, causedByLine: 2, localsDelta: [{ name: 'n', op: 'set', value: P('0') }] }, 2),
    ev({ observedAtLine: 4, causedByLine: 3, objectsDelta: [listSet(['2', '5'])] }, 3),
    ev({ kind: 'return', observedAtLine: 4 }, 4),
  ]

  it('setVar 샷은 "{name} = {값}" 자막, 비교가 있으면 비교가 이긴다', () => {
    const shots = choreograph(swapEvents, buildStage(swapEvents), swapCode)
    const cmpShot = shots.find(s => s.seq === 2)!
    expect(cmpShot.caption).toContain('비교')
    expect(cmpShot.caption).toContain('5 > 2')
    expect(cmpShot.caption).toContain('참')
  })

  it('비교 샷은 읽을 시간을 받는다 (BASE보다 길게)', () => {
    const shots = choreograph(swapEvents, buildStage(swapEvents), swapCode)
    expect(shots.find(s => s.seq === 2)!.durationMs).toBeGreaterThan(520)
  })

  it('swap 샷은 직전 참 비교를 이어받는다 — 자막과 비교 echo', () => {
    const shots = choreograph(swapEvents, buildStage(swapEvents), swapCode)
    const swapShot = shots.find(s => s.motions.some(m => m.v === 'swap'))!
    expect(swapShot.caption).toContain('자리')
    expect(swapShot.caption).toContain('5 > 2')
    expect(swapShot.motions.some(m => m.v === 'compare')).toBe(true) // 판단이 행동 위에 머문다
  })

  it('리터럴 탄생 샷은 "칸이 차례로 채워집니다"', () => {
    const shots = choreograph(swapEvents, buildStage(swapEvents), swapCode)
    const birth = shots.find(s => s.motions.some(m => m.v === 'grow'))!
    expect(birth.caption).toContain('차례로')
  })

  it('함수 호출·종료 자막', () => {
    const events: TraceEvent[] = [
      ev({ kind: 'call', observedAtLine: 1 }, 0),
      ev({ kind: 'call', frameId: 1, parentFrameId: 0, func: 'f', observedAtLine: 2 }, 1),
      ev({ kind: 'return', frameId: 1, parentFrameId: 0, func: 'f', observedAtLine: 2 }, 2),
      ev({ kind: 'return', observedAtLine: 3 }, 3),
    ]
    const shots = choreograph(events, buildStage(events))
    expect(shots.find(s => s.motions.some(m => m.v === 'pushFrame' && m.frameId === 1))?.caption).toContain('호출')
    expect(shots.find(s => s.motions.some(m => m.v === 'popFrame' && m.frameId === 1))?.caption).toContain('종료')
  })

  it('압축 샷 자막은 빨리감기', () => {
    const shots = choreograph(demoEvents, buildStage(demoEvents))
    const lapse = shots.find(s => s.timelapse && s.timelapse > 1)!
    expect(lapse.caption).toContain('빨리감기')
  })
})

describe('choreograph: 값의 이동 (travel)', () => {
  const birth = (items: string[], seq: number) =>
    ev({
      observedAtLine: 2, causedByLine: 1,
      localsDelta: [{ name: 'arr', op: 'set', value: { k: 'ref', id: 1 } }],
      objectsDelta: [listSet(items)],
    }, seq)
  const travelsOf = (shots: ReturnType<typeof choreograph>) =>
    shots.flatMap(s => s.motions).filter(m => m.v === 'travel') as {
      from: { kind: string; index?: number }
      to: { kind: string }
      text: string
    }[]

  it('x = arr[1] — 칸에서 알약으로 값이 날아간다', () => {
    const code = 'arr = [5, 7]\nx = arr[1]\n'
    const events: TraceEvent[] = [
      ev({ kind: 'call', observedAtLine: 1 }, 0),
      birth(['5', '7'], 1),
      ev({ observedAtLine: 2, causedByLine: 2, localsDelta: [{ name: 'x', op: 'set', value: P('7') }] }, 2),
      ev({ kind: 'return', observedAtLine: 2 }, 3),
    ]
    const shots = choreograph(events, buildStage(events), code)
    const t = travelsOf(shots)
    expect(t.length).toBe(1)
    expect(t[0].from.kind).toBe('cell')
    expect(t[0].from.index).toBe(1)
    expect(t[0].to.kind).toBe('var')
    expect(t[0].text).toBe('7')
  })

  it('arr[0] = y — 알약에서 칸으로 값이 날아간다', () => {
    const code = 'arr = [5, 7]\ny = 9\narr[0] = y\n'
    const events: TraceEvent[] = [
      ev({ kind: 'call', observedAtLine: 1 }, 0),
      birth(['5', '7'], 1),
      ev({ observedAtLine: 3, causedByLine: 2, localsDelta: [{ name: 'y', op: 'set', value: P('9') }] }, 2),
      ev({ observedAtLine: 3, causedByLine: 3, objectsDelta: [listSet(['9', '7'])] }, 3),
      ev({ kind: 'return', observedAtLine: 3 }, 4),
    ]
    const shots = choreograph(events, buildStage(events), code)
    const t = travelsOf(shots)
    expect(t.length).toBe(1)
    expect(t[0].from.kind).toBe('var')
    expect(t[0].to.kind).toBe('cell')
    expect(t[0].text).toBe('9')
  })

  it('arr.append(y) — 알약에서 새 칸으로 값이 날아간다', () => {
    const code = 'arr = [5]\ny = 3\narr.append(y)\n'
    const events: TraceEvent[] = [
      ev({ kind: 'call', observedAtLine: 1 }, 0),
      birth(['5'], 1),
      ev({ observedAtLine: 3, causedByLine: 2, localsDelta: [{ name: 'y', op: 'set', value: P('3') }] }, 2),
      ev({ observedAtLine: 3, causedByLine: 3, objectsDelta: [listSet(['5', '3'])] }, 3),
      ev({ kind: 'return', observedAtLine: 3 }, 4),
    ]
    const shots = choreograph(events, buildStage(events), code)
    const t = travelsOf(shots)
    expect(t.length).toBe(1)
    expect(t[0].from.kind).toBe('var')
    expect(t[0].to.kind).toBe('cell')
    expect(t[0].text).toBe('3')
  })

  it('식이 끼면 침묵한다 — x = arr[0] + 1', () => {
    const code = 'arr = [5, 7]\nx = arr[0] + 1\n'
    const events: TraceEvent[] = [
      ev({ kind: 'call', observedAtLine: 1 }, 0),
      birth(['5', '7'], 1),
      ev({ observedAtLine: 2, causedByLine: 2, localsDelta: [{ name: 'x', op: 'set', value: P('6') }] }, 2),
      ev({ kind: 'return', observedAtLine: 2 }, 3),
    ]
    const shots = choreograph(events, buildStage(events), code)
    expect(travelsOf(shots).length).toBe(0)
  })

  it('칸이 빠지고 변수가 그 값을 받으면 (popleft) — 칸에서 알약으로', () => {
    const code = 'arr = [1, 2]\nx = arr.pop(0)\n'
    const events: TraceEvent[] = [
      ev({ kind: 'call', observedAtLine: 1 }, 0),
      birth(['1', '2'], 1),
      ev({
        observedAtLine: 2, causedByLine: 2,
        localsDelta: [{ name: 'x', op: 'set', value: P('1') }],
        objectsDelta: [listSet(['2'])],
      }, 2),
      ev({ kind: 'return', observedAtLine: 2 }, 3),
    ]
    const shots = choreograph(events, buildStage(events), code)
    const t = travelsOf(shots)
    expect(t.length).toBe(1)
    expect(t[0].from.kind).toBe('cell')
    expect(t[0].to.kind).toBe('var')
    expect(t[0].text).toBe('1')
  })
})

describe('choreograph: 시프트 접지 (pop의 물성)', () => {
  const birth = (items: string[], seq: number) =>
    ev({
      observedAtLine: 2, causedByLine: 1,
      localsDelta: [{ name: 'arr', op: 'set', value: { k: 'ref', id: 1 } }],
      objectsDelta: [listSet(items)],
    }, seq)
  const shiftsOf = (shots: ReturnType<typeof choreograph>) =>
    shots.flatMap(s => s.motions).filter(m => m.v === 'shiftLeft') as {
      objectId: number; index: number; texts: string[]
    }[]

  it('pop(0) — setCell 폭풍 대신 shiftLeft 하나, 샷은 이야기 비트로 느리다', () => {
    const code = 'arr = [7, 8, 9]\nx = arr.pop(0)\n'
    const events: TraceEvent[] = [
      ev({ kind: 'call', observedAtLine: 1 }, 0),
      birth(['7', '8', '9'], 1),
      ev({
        observedAtLine: 2, causedByLine: 2,
        localsDelta: [{ name: 'x', op: 'set', value: P('7') }],
        objectsDelta: [listSet(['8', '9'])],
      }, 2),
      ev({ kind: 'return', observedAtLine: 2 }, 3),
    ]
    const shots = choreograph(events, buildStage(events), code)
    const shifts = shiftsOf(shots)
    expect(shifts.length).toBe(1)
    expect(shifts[0].index).toBe(0)
    expect(shifts[0].texts).toEqual(['8', '9'])
    const shot = shots.find(s => s.motions.some(m => m.v === 'shiftLeft'))!
    expect(shot.motions.some(m => m.v === 'setCell' || m.v === 'shrink')).toBe(false)
    expect(shot.durationMs).toBeGreaterThan(520)
    // travel 출발지는 마지막 칸이 아니라 빠진 칸이다
    const tr = shot.motions.find(m => m.v === 'travel') as { from: { kind: string; index?: number }; text: string }
    expect(tr).toBeTruthy()
    expect(tr.from.kind).toBe('cell')
    expect(tr.from.index).toBe(0)
    expect(tr.text).toBe('7')
  })

  it('del 중간 — index가 삭제 지점이고 자막이 당겨짐을 말한다', () => {
    const events: TraceEvent[] = [
      ev({ kind: 'call', observedAtLine: 1 }, 0),
      birth(['1', '2', '3'], 1),
      ev({ observedAtLine: 3, causedByLine: 2, objectsDelta: [listSet(['1', '3'])] }, 2),
      ev({ kind: 'return', observedAtLine: 3 }, 3),
    ]
    const shots = choreograph(events, buildStage(events))
    const shifts = shiftsOf(shots)
    expect(shifts.length).toBe(1)
    expect(shifts[0].index).toBe(1)
    expect(shifts[0].texts).toEqual(['3'])
    const shot = shots.find(s => s.motions.some(m => m.v === 'shiftLeft'))!
    expect(shot.caption).toContain('당겨')
    expect(shot.caption).not.toMatch(/\d+번/) // 위치는 번호로 부르지 않는다
    expect(shot.caption).not.toContain('맨 앞') // 중간 삭제는 끝이 아니므로 침묵
  })

  it('꼬리 pop은 시프트가 아니다 — 아무도 안 움직이므로 기존 shrink', () => {
    const events: TraceEvent[] = [
      ev({ kind: 'call', observedAtLine: 1 }, 0),
      birth(['1', '2', '3'], 1),
      ev({ observedAtLine: 3, causedByLine: 2, objectsDelta: [listSet(['1', '2'])] }, 2),
      ev({ kind: 'return', observedAtLine: 3 }, 3),
    ]
    const shots = choreograph(events, buildStage(events))
    expect(shiftsOf(shots).length).toBe(0)
    expect(shots.flatMap(s => s.motions).some(m => m.v === 'shrink')).toBe(true)
  })

  it('두 칸 이상 삭제는 접지 실패 — 기존 경로 폴백 (지어내지 않는다)', () => {
    const events: TraceEvent[] = [
      ev({ kind: 'call', observedAtLine: 1 }, 0),
      birth(['1', '2', '3'], 1),
      ev({ observedAtLine: 3, causedByLine: 2, objectsDelta: [listSet(['3'])] }, 2),
      ev({ kind: 'return', observedAtLine: 3 }, 3),
    ]
    const shots = choreograph(events, buildStage(events))
    expect(shiftsOf(shots).length).toBe(0)
  })

  it('값이 중복돼 삭제 지점이 모호하면 최소 k — 값이 같아 어느 쪽이든 정직하다', () => {
    const events: TraceEvent[] = [
      ev({ kind: 'call', observedAtLine: 1 }, 0),
      birth(['2', '2', '3'], 1),
      ev({ observedAtLine: 3, causedByLine: 2, objectsDelta: [listSet(['2', '3'])] }, 2),
      ev({ kind: 'return', observedAtLine: 3 }, 3),
    ]
    const shots = choreograph(events, buildStage(events))
    const shifts = shiftsOf(shots)
    expect(shifts.length).toBe(1)
    expect(shifts[0].index).toBe(0)
  })
})

describe('choreograph: 표기 걷어내기 — 자막이 코드 기호를 쓰지 않는다', () => {
  const birth = (items: string[], seq: number) =>
    ev({
      observedAtLine: 2, causedByLine: 1,
      localsDelta: [{ name: 'arr', op: 'set', value: { k: 'ref', id: 1 } }],
      objectsDelta: [listSet(items)],
    }, seq)

  it('어떤 자막도 대괄호 첨자나 "N번 칸"을 쓰지 않는다 (격자 좌표는 예외)', () => {
    const code = 'arr = [5, 2]\nn = 0\nif arr[0] > arr[1]:\n    arr[0], arr[1] = arr[1], arr[0]\n'
    const events: TraceEvent[] = [
      ev({ kind: 'call', observedAtLine: 1 }, 0),
      birth(['5', '2'], 1),
      ev({ observedAtLine: 3, causedByLine: 2, localsDelta: [{ name: 'n', op: 'set', value: P('0') }] }, 2),
      ev({ observedAtLine: 4, causedByLine: 3, objectsDelta: [listSet(['2', '5'])] }, 3),
      ev({ observedAtLine: 4, causedByLine: 4, objectsDelta: [listSet(['2', '9'])] }, 4),
      ev({ kind: 'return', observedAtLine: 4 }, 5),
    ]
    const caps = choreograph(events, buildStage(events), code).map(s => s.caption ?? '')
    for (const c of caps) {
      expect(c).not.toMatch(/\w\[\d+\]/) // arr[0]
      expect(c).not.toMatch(/\d+번 칸/) // 2번 칸
      expect(c).not.toMatch(/\w\(\)/) // f()
    }
  })

  it('setCell 자막은 배열 이름과 값만 말한다', () => {
    const events: TraceEvent[] = [
      ev({ kind: 'call', observedAtLine: 1 }, 0),
      birth(['5', '2'], 1),
      ev({ observedAtLine: 3, causedByLine: 2, objectsDelta: [listSet(['5', '9'])] }, 2),
      ev({ kind: 'return', observedAtLine: 3 }, 3),
    ]
    const shots = choreograph(events, buildStage(events))
    const cap = shots.find(s => s.motions.some(m => m.v === 'setCell'))!.caption!
    expect(cap).toContain('arr')
    expect(cap).toContain('9')
    expect(cap).not.toMatch(/\[|\]/)
  })

  it('맨 앞이 빠질 때는 "맨 앞"이라 부른다 — 끝은 번호 없이도 지칭할 수 있다', () => {
    const events: TraceEvent[] = [
      ev({ kind: 'call', observedAtLine: 1 }, 0),
      birth(['1', '2', '3'], 1),
      ev({ observedAtLine: 3, causedByLine: 2, objectsDelta: [listSet(['2', '3'])] }, 2),
      ev({ kind: 'return', observedAtLine: 3 }, 3),
    ]
    const shots = choreograph(events, buildStage(events))
    const cap = shots.find(s => s.motions.some(m => m.v === 'shiftLeft'))!.caption!
    expect(cap).toContain('맨 앞')
  })

  it('함수 호출·종료 자막에서 괄호가 빠진다', () => {
    const events: TraceEvent[] = [
      ev({ kind: 'call', observedAtLine: 1 }, 0),
      ev({ kind: 'call', frameId: 1, parentFrameId: 0, func: 'f', observedAtLine: 2 }, 1),
      ev({ kind: 'return', frameId: 1, parentFrameId: 0, func: 'f', observedAtLine: 2 }, 2),
      ev({ kind: 'return', observedAtLine: 3 }, 3),
    ]
    const shots = choreograph(events, buildStage(events))
    const push = shots.find(s => s.motions.some(m => m.v === 'pushFrame' && m.frameId === 1))!.caption!
    expect(push).toContain('f 호출')
    expect(push).not.toContain('f()')
  })
})

describe('choreograph: 정직성 표시 — 화면은 자기가 아는 것만 말한다', () => {
  const bigList = (items: string[], n: number, seq: number) =>
    ev({
      observedAtLine: 2, causedByLine: 1,
      localsDelta: [{ name: 'arr', op: 'set', value: { k: 'ref', id: 1 } }],
      objectsDelta: [{ op: 'set' as const, obj: { id: 1, type: 'list', items: items.map(v => P(v)), n, truncated: n > items.length } }],
    }, seq)
  const partialsOf = (shots: ReturnType<typeof choreograph>) =>
    shots.flatMap(s => s.motions).filter(m => m.v === 'partial') as { shown: number; total?: number }[]

  it('잘린 리스트는 "20 / 500"을 밝힌다', () => {
    const events: TraceEvent[] = [
      ev({ kind: 'call', observedAtLine: 1 }, 0),
      bigList(['1', '2', '3'], 500, 1),
      ev({ kind: 'return', observedAtLine: 2 }, 2),
    ]
    const p = partialsOf(choreograph(events, buildStage(events)))
    expect(p.length).toBe(1)
    expect(p[0]).toMatchObject({ shown: 3, total: 500 })
  })

  it('잘리지 않은 리스트는 아무 말도 하지 않는다', () => {
    const events: TraceEvent[] = [
      ev({ kind: 'call', observedAtLine: 1 }, 0),
      bigList(['1', '2', '3'], 3, 1),
      ev({ kind: 'return', observedAtLine: 2 }, 2),
    ]
    const p = partialsOf(choreograph(events, buildStage(events)))
    expect(p.every(x => x.total === x.shown)).toBe(true)
  })

  it('잘린 리스트에는 정렬 완성을 선언하지 않는다 — 일부를 보고 전체를 말할 수 없다', () => {
    const events: TraceEvent[] = [
      ev({ kind: 'call', observedAtLine: 1 }, 0),
      bigList(['1', '2', '3'], 500, 1), // 보이는 3칸은 오름차순이지만 500개 중 일부다
      ev({ kind: 'return', observedAtLine: 2 }, 2),
    ]
    const shots = choreograph(events, buildStage(events))
    expect(shots.flatMap(s => s.motions).some(m => m.v === 'sortedSweep')).toBe(false)
    expect(shots.some(s => (s.caption ?? '').includes('정렬 완성'))).toBe(false)
  })

  it('잘리지 않았고 실제로 정렬로 끝났으면 정렬 완성은 그대로 나온다 (가드가 과잉이지 않다)', () => {
    const events: TraceEvent[] = [
      ev({ kind: 'call', observedAtLine: 1 }, 0),
      bigList(['3', '1', '2'], 3, 1), // 흐트러진 상태를 거쳐야 정렬의 증거가 된다
      bigList(['1', '2', '3'], 3, 2),
      ev({ kind: 'return', observedAtLine: 2 }, 3),
    ]
    const shots = choreograph(events, buildStage(events))
    expect(shots.flatMap(s => s.motions).some(m => m.v === 'sortedSweep')).toBe(true)
  })
})

describe('choreograph: 저울 데이터·정렬 스윕', () => {
  it('접지된 비교는 a·op·b·verdict 구조 필드를 싣는다', () => {
    const code = 'arr = [5, 2]\nn = 0\nif arr[0] > arr[1]:\n    pass\n'
    const events: TraceEvent[] = [
      ev({ kind: 'call', observedAtLine: 1 }, 0),
      ev({
        observedAtLine: 2, causedByLine: 1,
        localsDelta: [{ name: 'arr', op: 'set', value: { k: 'ref', id: 1 } }],
        objectsDelta: [listSet(['5', '2'])],
      }, 1),
      ev({ observedAtLine: 3, causedByLine: 2, localsDelta: [{ name: 'n', op: 'set', value: P('0') }] }, 2),
      ev({ kind: 'return', observedAtLine: 3 }, 3),
    ]
    const shots = choreograph(events, buildStage(events), code)
    const cmp = shots.flatMap(s => s.motions).find(m => m.v === 'compare') as
      | { a?: string; op?: string; b?: string; verdict?: boolean }
      | undefined
    expect(cmp).toBeDefined()
    expect(cmp!.a).toBe('5')
    expect(cmp!.op).toBe('>')
    expect(cmp!.b).toBe('2')
    expect(cmp!.verdict).toBe(true)
  })

  const endState = (final: string[]) => {
    const events: TraceEvent[] = [
      ev({ kind: 'call', observedAtLine: 1 }, 0),
      ev({
        observedAtLine: 2, causedByLine: 1,
        localsDelta: [{ name: 'a', op: 'set', value: { k: 'ref', id: 1 } }],
        objectsDelta: [listSet(['3', '1', '2'])],
      }, 1),
      ev({ observedAtLine: 3, causedByLine: 2, objectsDelta: [listSet(final)] }, 2),
      ev({ kind: 'return', observedAtLine: 3 }, 3),
    ]
    return choreograph(events, buildStage(events))
  }

  it('오름차순으로 끝난 숫자 리스트는 커튼콜에서 sortedSweep을 받는다', () => {
    const shots = endState(['1', '2', '3'])
    const last = shots[shots.length - 1]
    expect(last.motions.some(m => m.v === 'sortedSweep')).toBe(true)
    expect(last.caption).toContain('정렬 완성')
  })

  it('정렬되지 않은 채 끝나면 스윕은 없다 — 지어내지 않는다', () => {
    const shots = endState(['2', '3', '1'])
    expect(shots.flatMap(s => s.motions).some(m => m.v === 'sortedSweep')).toBe(false)
  })
})

/* 끝이 오름차순인 것은 정렬의 결과일 뿐 증거가 아니다 — 증거는 재배열이다.
   "같은 원소 구성으로 다른 순서였던 적이 있다"가 스윕의 조건에 더해진다 */
describe('choreograph: 정렬 완성은 재배열을 본다', () => {
  const listAt = (items: string[], seq: number, first = false) =>
    ev({
      observedAtLine: seq + 1, causedByLine: seq,
      ...(first ? { localsDelta: [{ name: 'a', op: 'set' as const, value: { k: 'ref' as const, id: 1 } }] } : {}),
      objectsDelta: [listSet(items)],
    }, seq)
  const run = (states: string[][]) => {
    const events: TraceEvent[] = [
      ev({ kind: 'call', observedAtLine: 1 }, 0),
      ...states.map((st, i) => listAt(st, i + 1, i === 0)),
      ev({ kind: 'return', observedAtLine: states.length + 1 }, states.length + 1),
    ]
    return choreograph(events, buildStage(events))
  }
  const swept = (states: string[][]) => run(states).flatMap(s => s.motions).some(m => m.v === 'sortedSweep')

  it('처음부터 오름차순이고 한 번도 안 바뀐 리스트는 침묵한다', () => {
    expect(swept([['1', '2', '3']])).toBe(false)
  })

  it('쌓기만 한 오름차순 리스트는 침묵한다 — 만든 것은 정렬이 아니다', () => {
    expect(swept([['1'], ['1', '2'], ['1', '2', '3']])).toBe(false)
  })

  it('원소를 갈아끼워 오름차순이 된 리스트는 침묵한다 — 재배열이 아니다', () => {
    expect(swept([['9', '1', '2'], ['0', '1', '2']])).toBe(false)
  })

  it('흐트러진 상태를 거쳐 오름차순으로 끝나면 스윕이 나온다', () => {
    expect(swept([['3', '1', '2'], ['1', '3', '2'], ['1', '2', '3']])).toBe(true)
  })

  it('쌓은 뒤 정렬하면 스윕이 나온다 — 쌓기가 끝난 시점의 흐트러짐이 증거다', () => {
    expect(swept([['3'], ['3', '1'], ['3', '1', '2'], ['1', '2', '3']])).toBe(true)
  })

  it('재배열 뒤 원소가 갈리면 증거가 무효가 된다', () => {
    // [3,1,2] → [1,2,3] (정렬) → [0,2,3] (원소 교체) : 지금 구성으로는 흐트러진 적이 없다
    expect(swept([['3', '1', '2'], ['1', '2', '3'], ['0', '2', '3']])).toBe(false)
  })
})

describe('choreograph: 인덱스 포인터', () => {
  it('소스에 arr[j]로 쓰인 변수만 포인터가 된다 — n은 알약으로 남는다', () => {
    const code = 'arr = [5, 2]\nn = 2\nj = 0\nif arr[j] > arr[j + 1]:\n    pass\n'
    const events: TraceEvent[] = [
      ev({ kind: 'call', observedAtLine: 1 }, 0),
      ev({
        observedAtLine: 2, causedByLine: 1,
        localsDelta: [{ name: 'arr', op: 'set', value: { k: 'ref', id: 1 } }],
        objectsDelta: [listSet(['5', '2'])],
      }, 1),
      ev({ observedAtLine: 3, causedByLine: 2, localsDelta: [{ name: 'n', op: 'set', value: P('2') }] }, 2),
      ev({ observedAtLine: 4, causedByLine: 3, localsDelta: [{ name: 'j', op: 'set', value: P('0') }] }, 3),
      ev({ kind: 'return', observedAtLine: 4 }, 4),
    ]
    const shots = choreograph(events, buildStage(events), code)
    const ptrs = shots.flatMap(s => s.motions).filter(m => m.v === 'pointer') as {
      varKey: string
      objectId: number
    }[]
    expect(ptrs.map(p => p.varKey)).toEqual(['0:j'])
    expect(ptrs[0].objectId).toBe(1)
  })

  it('코드가 없으면 포인터도 없다 — 접지 실패는 침묵', () => {
    const events: TraceEvent[] = [
      ev({ kind: 'call', observedAtLine: 1 }, 0),
      ev({ observedAtLine: 2, localsDelta: [{ name: 'j', op: 'set', value: P('0') }] }, 1),
      ev({ kind: 'return', observedAtLine: 2 }, 2),
    ]
    const shots = choreograph(events, buildStage(events))
    expect(shots.flatMap(s => s.motions).some(m => m.v === 'pointer')).toBe(false)
  })
})

describe('choreograph: 정직한 배지·최종값', () => {
  it('반복 배지는 카운트업만 — 모순되는 총계를 달지 않는다', () => {
    const shots = choreograph(demoEvents, buildStage(demoEvents), demoCode)
    const loops = shots.flatMap(s => s.motions).filter(m => m.v === 'loop') as { text: string }[]
    expect(loops.some(l => l.text.includes('회차'))).toBe(true)
    expect(loops.every(l => !l.text.includes('총'))).toBe(true)
  })

  it('실행 종료 샷에서 살아있는 변수의 최종값이 정산된다', () => {
    const events: TraceEvent[] = [
      ev({ kind: 'call', observedAtLine: 1 }, 0),
      ev({ observedAtLine: 2, localsDelta: [{ name: 'x', op: 'set', value: P('1') }] }, 1),
      ev({ observedAtLine: 3, localsDelta: [{ name: 'x', op: 'set', value: P('2') }] }, 2),
      ev({ kind: 'return', observedAtLine: 3 }, 3),
    ]
    const shots = choreograph(events, buildStage(events))
    const final = shots.find(s => s.motions.some(m => m.v === 'popFrame'))!
    const settled = final.motions.find(m => m.v === 'setVar') as { text: string } | undefined
    expect(settled?.text).toBe('2')
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

describe('choreograph: swap', () => {
  it('전위 교환이 swap 모션이 되고 느리게 재생된다', () => {
    const events: TraceEvent[] = [
      ev({ kind: 'call' }, 0),
      ev({ localsDelta: [{ name: 'a', op: 'set', value: { k: 'ref', id: 1 } }], objectsDelta: [listSet(['5', '4', '9'])] }, 1),
      ev({ objectsDelta: [listSet(['4', '5', '9'])] }, 2),
    ]
    const shots = choreograph(events, buildStage(events))
    const hit = shots.flatMap(s => s.motions.map(m => ({ m, s }))).find(x => x.m.v === 'swap')
    expect(hit).toBeDefined()
    expect(hit!.m).toMatchObject({ objectId: 1, i: 0, k: 1, iText: '4', kText: '5' })
    expect(hit!.s.durationMs).toBeGreaterThan(520)
    expect(hit!.s.motions.some(m => m.v === 'setCell')).toBe(false)
  })
})

describe('choreograph: compare', () => {
  it('if a > b 라인에서 값·부등호·판정이 나온다', () => {
    const code = 'a = 5\nb = 4\nif a > b:\n    c = 1\n'
    const events: TraceEvent[] = [
      ev({ kind: 'call' }, 0),
      ev({ causedByLine: 1, observedAtLine: 2, localsDelta: [{ name: 'a', op: 'set', value: P('5') }] }, 1),
      ev({ causedByLine: 2, observedAtLine: 3, localsDelta: [{ name: 'b', op: 'set', value: P('4') }] }, 2),
      ev({ causedByLine: 3, observedAtLine: 4, localsDelta: [{ name: 'c', op: 'set', value: P('1') }] }, 3),
    ]
    const shots = choreograph(events, buildStage(events), code)
    const cmp = shots.flatMap(s => s.motions).find(m => m.v === 'compare') as
      | { text: string; targets: unknown[] }
      | undefined
    expect(cmp).toBeDefined()
    expect(cmp!.text).toBe('5 > 4 → 참')
    expect(cmp!.targets.length).toBe(2)
  })

  it('첨자 비교 arr[j] > arr[j+1]가 칸 타깃으로 접지된다', () => {
    const code = 'arr = [5, 4]\nj = 0\nif arr[j] > arr[j + 1]:\n    pass\n'
    const events: TraceEvent[] = [
      ev({ kind: 'call' }, 0),
      ev(
        {
          observedAtLine: 2,
          localsDelta: [{ name: 'arr', op: 'set', value: { k: 'ref', id: 1 } }],
          objectsDelta: [listSet(['5', '4'])],
        },
        1,
      ),
      ev({ observedAtLine: 3, localsDelta: [{ name: 'j', op: 'set', value: P('0') }] }, 2),
      ev({ observedAtLine: 4 }, 3),
    ]
    const shots = choreograph(events, buildStage(events), code)
    const cmp = shots.flatMap(s => s.motions).find(m => m.v === 'compare') as
      | { text: string; targets: { kind: string; objectId?: number; index?: number }[] }
      | undefined
    expect(cmp).toBeDefined()
    expect(cmp!.text).toBe('5 > 4 → 참')
    expect(cmp!.targets).toEqual([
      { kind: 'cell', objectId: 1, index: 0 },
      { kind: 'cell', objectId: 1, index: 1 },
    ])
  })

  it('접지가 안 되면 침묵한다', () => {
    const code = 'if x > y:\n    pass\n'
    const events: TraceEvent[] = [ev({ kind: 'call' }, 0), ev({ observedAtLine: 1 }, 1)]
    const shots = choreograph(events, buildStage(events), code)
    expect(shots.flatMap(s => s.motions).some(m => m.v === 'compare')).toBe(false)
  })
})

describe('choreograph: 캐스팅 가드', () => {
  it('컨테이너 안에만 있는 객체는 모션이 없고, 부모 칸에 요약 텍스트가 들어간다', () => {
    const events: TraceEvent[] = [
      ev({ kind: 'call' }, 0),
      ev({
        localsDelta: [{ name: 'a', op: 'set', value: { k: 'ref', id: 1 } }],
        objectsDelta: [
          { op: 'set', obj: { id: 2, type: 'tuple', items: [P('0'), P('0')] } },
          { op: 'set', obj: { id: 1, type: 'list', items: [{ k: 'ref', id: 2 }, P('9')] } },
        ],
      }, 1),
    ]
    const shots = choreograph(events, buildStage(events))
    const all = shots.flatMap(s => s.motions)
    expect(all.some(m => 'objectId' in m && m.objectId === 2)).toBe(false)
    const grow0 = all.find(m => m.v === 'grow' && m.index === 0) as { text: string }
    expect(grow0.text).toBe('(0, 0)')
  })

  it('작은 프림 튜플 대입은 끈 대신 알약 값 "(1, 1)"이 된다', () => {
    const events: TraceEvent[] = [
      ev({ kind: 'call' }, 0),
      ev({
        localsDelta: [{ name: 'pos', op: 'set', value: { k: 'ref', id: 5 } }],
        objectsDelta: [{ op: 'set', obj: { id: 5, type: 'tuple', items: [P('1'), P('1')] } }],
      }, 1),
    ]
    const shots = choreograph(events, buildStage(events))
    const all = shots.flatMap(s => s.motions)
    expect(all.some(m => m.v === 'bind')).toBe(false)
    expect(all).toEqual(expect.arrayContaining([{ v: 'setVar', varKey: '0:pos', text: '(1, 1)' }]))
  })

  it('재대입으로 놓인 상자는 exitObj로 내려간다 — 계속 쥔 상자는 남는다', () => {
    const list = (id: number) => ({ op: 'set' as const, obj: { id, type: 'list', items: [P('1'), P('2'), P('3'), P('4')] } })
    const events: TraceEvent[] = [
      ev({ kind: 'call' }, 0),
      ev({ localsDelta: [{ name: 'keep', op: 'set', value: { k: 'ref', id: 9 } }], objectsDelta: [list(9)] }, 1),
      ev({ localsDelta: [{ name: 'a', op: 'set', value: { k: 'ref', id: 1 } }], objectsDelta: [list(1)] }, 2),
      ev({ localsDelta: [{ name: 'a', op: 'set', value: { k: 'ref', id: 2 } }], objectsDelta: [list(2)] }, 3),
      ev({ localsDelta: [{ name: 'b', op: 'set', value: P('1') }] }, 4),
      ev({ localsDelta: [{ name: 'c', op: 'set', value: P('1') }] }, 5),
    ]
    const shots = choreograph(events, buildStage(events))
    const exits = shots.flatMap(s => s.motions).filter(m => m.v === 'exitObj') as { objectId: number }[]
    expect(exits.map(x => x.objectId)).toContain(1)
    expect(exits.map(x => x.objectId)).not.toContain(9)
    expect(exits.map(x => x.objectId)).not.toContain(2)
  })

  it('함수·클래스 변수는 알약 모션이 없다', () => {
    const events: TraceEvent[] = [
      ev({ kind: 'call' }, 0),
      ev({
        localsDelta: [{ name: 'deque', op: 'set', value: { k: 'ref', id: 7 } }],
        objectsDelta: [{ op: 'set', obj: { id: 7, type: 'type', unsupported: true } }],
      }, 1),
    ]
    const shots = choreograph(events, buildStage(events))
    const all = shots.flatMap(s => s.motions)
    expect(all.some(m => m.v === 'enterVar' || m.v === 'setVar' || m.v === 'bind')).toBe(false)
  })
})

describe('choreograph: 잔상 제거', () => {
  it('함수가 반환되면 그 프레임의 지역 변수들이 exitVar로 내려간다', () => {
    const events: TraceEvent[] = [
      ev({ kind: 'call' }, 0),
      ev({ kind: 'call', frameId: 1, parentFrameId: 0, func: 'f' }, 1),
      ev({ frameId: 1, func: 'f', localsDelta: [{ name: 'x', op: 'set', value: P('7') }] }, 2),
      ev({ kind: 'return', frameId: 1, parentFrameId: 0, func: 'f' }, 3),
      ev({ localsDelta: [{ name: 'r', op: 'set', value: P('7') }] }, 4),
    ]
    const shots = choreograph(events, buildStage(events))
    const returnShot = shots.find(s => s.motions.some(m => m.v === 'popFrame'))!
    expect(returnShot.motions).toEqual(expect.arrayContaining([{ v: 'exitVar', varKey: '1:x' }]))
  })

  it('프로그램(모듈) 종료는 변수를 내리지 않는다 — 마지막 장면은 최종 상태를 보여줘야 한다', () => {
    const events: TraceEvent[] = [
      ev({ kind: 'call' }, 0),
      ev({ localsDelta: [{ name: 'a', op: 'set', value: P('1') }] }, 1),
      ev({ kind: 'return' }, 2),
    ]
    const shots = choreograph(events, buildStage(events))
    expect(shots.flatMap(s => s.motions).some(m => m.v === 'exitVar')).toBe(false)
  })

  it('압축(빨리감기) 샷이 끝나면 칸들이 실제 최종 값으로 맞춰진다 — … 잔상 금지', () => {
    const shots = choreograph(demoEvents, buildStage(demoEvents))
    const lapse = shots.find(s => s.timelapse && s.timelapse > 1)!
    expect(lapse).toBeDefined()
    // range(12): 10회까지 온전히 재생(칸 0~9) → 압축 구간에서 칸 10·11이 자란다
    const grows = lapse.motions.filter(m => m.v === 'grow') as { index: number; text: string }[]
    expect(grows.map(g => g.index)).toEqual(expect.arrayContaining([10, 11]))
    expect(shots.flatMap(s => s.motions).some(m => 'text' in m && m.text === '…')).toBe(false)
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

describe('choreograph: 격자', () => {
  const row = (id: number, vals: string[]) => ({ op: 'set' as const, obj: { id, type: 'list', items: vals.map(v => P(v)) } })
  const outer = (id: number, rowIds: number[]) => ({
    op: 'set' as const, obj: { id, type: 'list', items: rowIds.map(rid => ({ k: 'ref' as const, id: rid })) },
  })
  const coord = (id: number, r: string, c: string) => ({ op: 'set' as const, obj: { id, type: 'tuple', items: [P(r), P(c)] } })
  const mazeEvent = (seq: number) => ev({
    localsDelta: [{ name: 'maze', op: 'set', value: { k: 'ref', id: 1 } }],
    objectsDelta: [row(11, ['0', '1']), row(12, ['0', '0']), outer(1, [11, 12])],
  }, seq)

  it('격자 최초 등장에 전 칸 gridCell이 벽 플래그와 함께 나온다', () => {
    const events: TraceEvent[] = [ev({ kind: 'call' }, 0), mazeEvent(1)]
    const shots = choreograph(events, buildStage(events))
    const cells = shots.flatMap(s => s.motions).filter(m => m.v === 'gridCell') as { r: number; c: number; wall: boolean }[]
    expect(cells.length).toBe(4)
    expect(cells.find(c => c.r === 0 && c.c === 1)!.wall).toBe(true)
    expect(cells.find(c => c.r === 1 && c.c === 0)!.wall).toBe(false)
    expect(shots.flatMap(s => s.motions).some(m => m.v === 'grow')).toBe(false) // 상자 diff는 스킵
  })

  it('방문 집합에 좌표가 들어오면 gridVisit이 칠해진다', () => {
    const events: TraceEvent[] = [
      ev({ kind: 'call' }, 0),
      mazeEvent(1),
      ev({ localsDelta: [{ name: 'visited', op: 'set', value: { k: 'ref', id: 5 } }], objectsDelta: [{ op: 'set', obj: { id: 5, type: 'set', items: [] } }] }, 2),
      ev({ objectsDelta: [coord(21, '1', '0'), { op: 'set', obj: { id: 5, type: 'set', items: [{ k: 'ref', id: 21 }] } }] }, 3),
    ]
    const shots = choreograph(events, buildStage(events))
    const visits = shots.flatMap(s => s.motions).filter(m => m.v === 'gridVisit') as { objectId: number; r: number; c: number }[]
    expect(visits).toEqual([{ v: 'gridVisit', objectId: 1, r: 1, c: 0 }])
  })

  it('좌표 튜플 변수 대입은 커서를 움직인다', () => {
    const events: TraceEvent[] = [
      ev({ kind: 'call' }, 0),
      mazeEvent(1),
      ev({ localsDelta: [{ name: 'position', op: 'set', value: { k: 'ref', id: 31 } }], objectsDelta: [coord(31, '1', '1')] }, 2),
    ]
    const shots = choreograph(events, buildStage(events))
    const cursor = shots.flatMap(s => s.motions).find(m => m.v === 'gridCursor')
    expect(cursor).toEqual({ v: 'gridCursor', objectId: 1, r: 1, c: 1 })
  })

  it('좌표 리스트는 경로 선이 된다', () => {
    const events: TraceEvent[] = [
      ev({ kind: 'call' }, 0),
      mazeEvent(1),
      ev({
        localsDelta: [{ name: 'path', op: 'set', value: { k: 'ref', id: 7 } }],
        objectsDelta: [coord(41, '0', '0'), coord(42, '1', '0'), { op: 'set', obj: { id: 7, type: 'list', items: [{ k: 'ref', id: 41 }, { k: 'ref', id: 42 }] } }],
      }, 2),
    ]
    const shots = choreograph(events, buildStage(events))
    const trail = shots.flatMap(s => s.motions).find(m => m.v === 'gridTrail') as { points: [number, number][] } | undefined
    expect(trail).toBeDefined()
    expect(trail!.points).toEqual([[0, 0], [1, 0]])
  })

  it('안쪽 행이 바뀌면 그 칸만 gridCell이 나온다 (DP 테이블)', () => {
    const events: TraceEvent[] = [
      ev({ kind: 'call' }, 0),
      ev({
        localsDelta: [{ name: 'dp', op: 'set', value: { k: 'ref', id: 2 } }],
        objectsDelta: [row(51, ['0', '0']), row(52, ['0', '0']), outer(2, [51, 52])],
      }, 1),
      ev({ objectsDelta: [row(52, ['0', '9'])] }, 2),
    ]
    const shots = choreograph(events, buildStage(events))
    const last = shots[shots.length - 1].motions.filter(m => m.v === 'gridCell') as { r: number; c: number; text: string }[]
    expect(last).toEqual([{ v: 'gridCell', objectId: 2, r: 1, c: 1, text: '9', wall: false, flash: true }])
  })
})

describe('choreograph: 문자열 격자', () => {
  it('문자열 행 격자는 글자 단위로 칸이 채워진다', () => {
    const events: TraceEvent[] = [
      ev({ kind: 'call' }, 0),
      ev({
        localsDelta: [{ name: 'maze', op: 'set', value: { k: 'ref', id: 2 } }],
        objectsDelta: [{ op: 'set', obj: { id: 2, type: 'list', items: [P("'S.'", 'str'), P("'#G'", 'str')] } }],
      }, 1),
    ]
    const shots = choreograph(events, buildStage(events, { grid: ['maze'] }))
    const cells = shots.flatMap(s => s.motions).filter(m => m.v === 'gridCell') as { r: number; c: number; text: string }[]
    expect(cells.length).toBe(4)
    expect(cells.find(x => x.r === 0 && x.c === 0)!.text).toBe('S')
    expect(cells.find(x => x.r === 1 && x.c === 0)!.text).toBe('#')
    expect(cells.find(x => x.r === 1 && x.c === 1)!.text).toBe('G')
  })
})

describe('choreograph: 상자 이름표', () => {
  it('변수가 상자를 쥐면 그 이름이 라벨로 걸린다', () => {
    const events: TraceEvent[] = [
      ev({ kind: 'call' }, 0),
      ev({ localsDelta: [{ name: 'nums', op: 'set', value: { k: 'ref', id: 1 } }], objectsDelta: [listSet(['1', '2', '3', '4'])] }, 1),
    ]
    const shots = choreograph(events, buildStage(events))
    const labels = shots.flatMap(s => s.motions).filter(m => m.v === 'label') as { objectId: number; text: string }[]
    expect(labels).toEqual(expect.arrayContaining([{ v: 'label', objectId: 1, text: 'nums' }]))
  })

  it('재대입하면 옛 상자 라벨에서 이름이 빠진다', () => {
    const list = (id: number) => ({ op: 'set' as const, obj: { id, type: 'list', items: ['1', '2', '3', '4'].map(v => P(v)) } })
    const events: TraceEvent[] = [
      ev({ kind: 'call' }, 0),
      ev({ localsDelta: [{ name: 'a', op: 'set', value: { k: 'ref', id: 1 } }], objectsDelta: [list(1)] }, 1),
      ev({ localsDelta: [{ name: 'a', op: 'set', value: { k: 'ref', id: 2 } }], objectsDelta: [list(2)] }, 2),
    ]
    const shots = choreograph(events, buildStage(events))
    const labels = shots.flatMap(s => s.motions).filter(m => m.v === 'label') as { objectId: number; text: string }[]
    expect(labels).toEqual(
      expect.arrayContaining([
        { v: 'label', objectId: 1, text: 'a' },
        { v: 'label', objectId: 1, text: '' },
        { v: 'label', objectId: 2, text: 'a' },
      ]),
    )
  })

  it('별칭이면 두 이름이 함께 걸린다 — "a · b"', () => {
    const events: TraceEvent[] = [
      ev({ kind: 'call' }, 0),
      ev({ localsDelta: [{ name: 'a', op: 'set', value: { k: 'ref', id: 1 } }], objectsDelta: [listSet(['1', '2', '3', '4'])] }, 1),
      ev({ localsDelta: [{ name: 'b', op: 'set', value: { k: 'ref', id: 1 } }] }, 2),
    ]
    const shots = choreograph(events, buildStage(events))
    const labels = shots.flatMap(s => s.motions).filter(m => m.v === 'label') as { text: string }[]
    expect(labels.some(l => l.text === 'a · b')).toBe(true)
  })

  it('격자 칸 변경만 flash — 초기 채움은 아니다', () => {
    const row = (id: number, vals: string[]) => ({ op: 'set' as const, obj: { id, type: 'list', items: vals.map(v => P(v)) } })
    const events: TraceEvent[] = [
      ev({ kind: 'call' }, 0),
      ev({
        localsDelta: [{ name: 'dp', op: 'set', value: { k: 'ref', id: 2 } }],
        objectsDelta: [row(21, ['0', '0']), row(22, ['0', '0']), { op: 'set', obj: { id: 2, type: 'list', items: [{ k: 'ref', id: 21 }, { k: 'ref', id: 22 }] } }],
      }, 1),
      ev({ objectsDelta: [row(22, ['0', '7'])] }, 2),
    ]
    const shots = choreograph(events, buildStage(events))
    const cells = shots.flatMap(s => s.motions).filter(m => m.v === 'gridCell') as { flash?: boolean; text: string }[]
    expect(cells.filter(c => c.flash).map(c => c.text)).toEqual(['7'])
  })
})

/* 재귀의 알약 접기 — 한 이름이 여러 살아있는 프레임에 동시에 있으면, 그 이름을 가진
   가장 깊은 프레임의 것만 알약으로 남고 나머지는 각자의 프레임 카드가 든다.
   판정은 사실이므로 의미층이 소유하고, 바뀔 때만 방출한다 (label·partial과 같은 패턴) */
describe('choreograph: 이름이 겹치면 카드가 든다', () => {
  // fact(3) 축소판 — n이 프레임 1·2·3에 차례로 태어난다
  const recursionEvents: TraceEvent[] = [
    ev({ kind: 'call' }, 0),
    ev({ kind: 'call', frameId: 1, parentFrameId: 0, func: 'f', localsDelta: [{ name: 'n', op: 'set', value: P('3') }] }, 1),
    ev({ kind: 'call', frameId: 2, parentFrameId: 1, func: 'f', localsDelta: [{ name: 'n', op: 'set', value: P('2') }] }, 2),
    ev({ kind: 'call', frameId: 3, parentFrameId: 2, func: 'f', localsDelta: [{ name: 'n', op: 'set', value: P('1') }] }, 3),
    ev({ kind: 'return', frameId: 3, parentFrameId: 2, func: 'f' }, 4),
    ev({ kind: 'return', frameId: 2, parentFrameId: 1, func: 'f' }, 5),
    ev({ kind: 'return', frameId: 1, parentFrameId: 0, func: 'f' }, 6),
    ev({ kind: 'return' }, 7),
  ]
  const recShots = choreograph(recursionEvents, buildStage(recursionEvents))
  const folds = (seqOf: (s: (typeof recShots)[number]) => boolean) =>
    recShots.find(seqOf)!.motions.filter(m => m.v === 'foldVars')

  it('두 번째 호출에서 첫 프레임의 n이 카드로 물러난다', () => {
    expect(folds(s => s.motions.some(m => m.v === 'pushFrame' && m.frameId === 2))).toEqual([
      { v: 'foldVars', frameId: 1, varKeys: ['1:n'], texts: ['n = 3'] },
    ])
  })

  it('세 번째 호출에서는 두 번째 프레임만 새로 접힌다 — 바뀐 것만 방출한다', () => {
    expect(folds(s => s.motions.some(m => m.v === 'pushFrame' && m.frameId === 3))).toEqual([
      { v: 'foldVars', frameId: 2, varKeys: ['2:n'], texts: ['n = 2'] },
    ])
  })

  it('되돌아오면 다음으로 깊은 n이 알약으로 복귀한다 — 그 카드는 비워진다', () => {
    expect(folds(s => s.motions.some(m => m.v === 'popFrame' && m.frameId === 3))).toEqual([
      { v: 'foldVars', frameId: 2, varKeys: [], texts: [] },
    ])
  })

  it('이름이 겹치지 않으면 아무것도 접지 않는다 — 평범한 중첩 호출은 그대로다', () => {
    const events: TraceEvent[] = [
      ev({ kind: 'call' }, 0),
      ev({ localsDelta: [{ name: 'total', op: 'set', value: P('0') }] }, 1),
      ev({ kind: 'call', frameId: 1, parentFrameId: 0, func: 'helper', localsDelta: [{ name: 'x', op: 'set', value: P('2') }] }, 2),
      ev({ kind: 'return', frameId: 1, parentFrameId: 0, func: 'helper' }, 3),
      ev({ kind: 'return' }, 4),
    ]
    const shots = choreograph(events, buildStage(events))
    expect(shots.flatMap(s => s.motions).filter(m => m.v === 'foldVars')).toEqual([])
  })

  it('겹치는 이름만 접는다 — 같은 프레임의 유일한 이름은 알약으로 남는다', () => {
    const events: TraceEvent[] = [
      ev({ kind: 'call' }, 0),
      ev({
        kind: 'call', frameId: 1, parentFrameId: 0, func: 'f',
        localsDelta: [{ name: 'n', op: 'set', value: P('3') }, { name: 'acc', op: 'set', value: P('9') }],
      }, 1),
      ev({ kind: 'call', frameId: 2, parentFrameId: 1, func: 'f', localsDelta: [{ name: 'n', op: 'set', value: P('2') }] }, 2),
      ev({ kind: 'return', frameId: 2, parentFrameId: 1, func: 'f' }, 3),
      ev({ kind: 'return', frameId: 1, parentFrameId: 0, func: 'f' }, 4),
      ev({ kind: 'return' }, 5),
    ]
    const shots = choreograph(events, buildStage(events))
    const all = shots.flatMap(s => s.motions).filter(m => m.v === 'foldVars')
    expect(all).toEqual([
      { v: 'foldVars', frameId: 1, varKeys: ['1:n'], texts: ['n = 3'] },
      { v: 'foldVars', frameId: 1, varKeys: [], texts: [] },
    ])
  })

  it('카드의 값은 등장 순으로 적는다 — 알파벳이 아니라 매개변수 서명 순', () => {
    // 폭에 밀려 하나만 남을 때 알파벳 순이면 acc가 남고 n이 접힌다 — 재귀에서 읽을 값은 n이다
    const events: TraceEvent[] = [
      ev({ kind: 'call' }, 0),
      ev({
        kind: 'call', frameId: 1, parentFrameId: 0, func: 'go',
        localsDelta: [{ name: 'n', op: 'set', value: P('7') }, { name: 'acc', op: 'set', value: P('1') }],
      }, 1),
      ev({
        kind: 'call', frameId: 2, parentFrameId: 1, func: 'go',
        localsDelta: [{ name: 'n', op: 'set', value: P('6') }, { name: 'acc', op: 'set', value: P('7') }],
      }, 2),
      ev({ kind: 'return', frameId: 2, parentFrameId: 1, func: 'go' }, 3),
      ev({ kind: 'return', frameId: 1, parentFrameId: 0, func: 'go' }, 4),
      ev({ kind: 'return' }, 5),
    ]
    const shots = choreograph(events, buildStage(events))
    expect(shots.flatMap(s => s.motions).find(m => m.v === 'foldVars')).toEqual({
      v: 'foldVars', frameId: 1, varKeys: ['1:n', '1:acc'], texts: ['n = 7', 'acc = 1'],
    })
  })
})

/* 반환값 — 닫히는 프레임 카드에서 값 칩이 떠서 부모 카드로 내려앉는다.
   사실은 트레이서의 returned이고(예외 unwind·None은 애초에 오지 않는다), 여기서는 옮기기만 한다 */
describe('choreograph: 반환값은 카드에서 카드로 내려간다', () => {
  const call = (fid: number, parent: number, seq: number, name: string, v: string): TraceEvent =>
    ev({ kind: 'call', frameId: fid, parentFrameId: parent, func: 'f', localsDelta: [{ name, op: 'set', value: P(v) }] }, seq)

  it('반환값이 있으면 returnValue 모션과 자막이 나온다', () => {
    const events: TraceEvent[] = [
      ev({ kind: 'call' }, 0),
      call(1, 0, 1, 'x', '3'),
      ev({ kind: 'return', frameId: 1, parentFrameId: 0, func: 'f', returned: P('6') }, 2),
      ev({ localsDelta: [{ name: 'r', op: 'set', value: P('6') }] }, 3),
      ev({ kind: 'return' }, 4),
    ]
    const shots = choreograph(events, buildStage(events))
    const ret = shots.find(s => s.motions.some(m => m.v === 'popFrame'))!
    expect(ret.motions).toEqual(
      expect.arrayContaining([{ v: 'returnValue', frameId: 1, toFrameId: 0, text: '6' }]),
    )
    expect(ret.caption).toBe('f가 돌려준 값: 6')
  })

  it('반환값이 없으면 침묵한다 — 자막도 종료 그대로다', () => {
    const events: TraceEvent[] = [
      ev({ kind: 'call' }, 0),
      call(1, 0, 1, 'x', '3'),
      ev({ kind: 'return', frameId: 1, parentFrameId: 0, func: 'f' }, 2),
      ev({ kind: 'return' }, 3),
    ]
    const shots = choreograph(events, buildStage(events))
    const ret = shots.find(s => s.motions.some(m => m.v === 'popFrame'))!
    expect(ret.motions.some(m => m.v === 'returnValue')).toBe(false)
    expect(ret.caption).toBe('f 종료 — 작업 공간이 닫힙니다')
  })

  it('반환 샷은 읽을 시간을 받는다 — 값 없는 종료 샷보다 길다', () => {
    const base: TraceEvent[] = [ev({ kind: 'call' }, 0), call(1, 0, 1, 'x', '3')]
    const shotsWith = choreograph(
      [...base, ev({ kind: 'return', frameId: 1, parentFrameId: 0, func: 'f', returned: P('6') }, 2), ev({ kind: 'return' }, 3)],
      buildStage(base),
    )
    const shotsWithout = choreograph(
      [...base, ev({ kind: 'return', frameId: 1, parentFrameId: 0, func: 'f' }, 2), ev({ kind: 'return' }, 3)],
      buildStage(base),
    )
    const popOf = (sh: typeof shotsWith) => sh.find(s => s.motions.some(m => m.v === 'popFrame'))!
    expect(popOf(shotsWith).durationMs).toBeGreaterThan(popOf(shotsWithout).durationMs)
  })

  it('컨테이너 반환은 요약 텍스트로 적는다', () => {
    const events: TraceEvent[] = [
      ev({ kind: 'call' }, 0),
      ev({ kind: 'call', frameId: 1, parentFrameId: 0, func: 'make' }, 1),
      ev({
        kind: 'return', frameId: 1, parentFrameId: 0, func: 'make',
        returned: { k: 'ref', id: 9 },
        objectsDelta: [{ op: 'set', obj: { id: 9, type: 'list', items: [P('1'), P('2')] } }],
      }, 2),
      ev({ localsDelta: [{ name: 'xs', op: 'set', value: { k: 'ref', id: 9 } }] }, 3),
      ev({ kind: 'return' }, 4),
    ]
    const shots = choreograph(events, buildStage(events))
    const rv = shots.flatMap(s => s.motions).find(m => m.v === 'returnValue')
    expect(rv).toEqual({ v: 'returnValue', frameId: 1, toFrameId: 0, text: '[1, 2]' })
  })

  it('재귀 unwind는 값이 커지며 되돌아온다', () => {
    const events: TraceEvent[] = [
      ev({ kind: 'call' }, 0),
      call(1, 0, 1, 'n', '3'),
      call(2, 1, 2, 'n', '2'),
      call(3, 2, 3, 'n', '1'),
      ev({ kind: 'return', frameId: 3, parentFrameId: 2, func: 'f', returned: P('1') }, 4),
      ev({ kind: 'return', frameId: 2, parentFrameId: 1, func: 'f', returned: P('2') }, 5),
      ev({ kind: 'return', frameId: 1, parentFrameId: 0, func: 'f', returned: P('6') }, 6),
      ev({ kind: 'return' }, 7),
    ]
    const shots = choreograph(events, buildStage(events))
    const rvs = shots.flatMap(s => s.motions).filter(m => m.v === 'returnValue')
    expect(rvs).toEqual([
      { v: 'returnValue', frameId: 3, toFrameId: 2, text: '1' },
      { v: 'returnValue', frameId: 2, toFrameId: 1, text: '2' },
      { v: 'returnValue', frameId: 1, toFrameId: 0, text: '6' },
    ])
  })
})

/* 반복 배지는 소스에 접지한다 — 다이제스트 압축 스팬은 반복문의 생애가 아니다.
   회차는 몸통이 실행된 횟수이고 1부터 센다 (헤더 방문 수는 소진 검사까지 세어 하나 더 나온다) */
describe('choreograph: 반복 배지는 사실대로 센다', () => {
  const src = (...lines: string[]) => lines.join('\n')
  const badges = (code: string, lines: number[]) => {
    const events: TraceEvent[] = [
      ev({ kind: 'call', observedAtLine: 1 }, 0),
      ...lines.map((l, k) => ev({ observedAtLine: l, causedByLine: l }, k + 1)),
      ev({ kind: 'return', observedAtLine: lines[lines.length - 1] }, lines.length + 1),
    ]
    const shots = choreograph(events, buildStage(events), code)
    return shots
      .flatMap(s => s.motions)
      .filter(m => m.v === 'loop' || m.v === 'loopEnd')
      .map(m => (m.v === 'loop' ? m.text : '—'))
  }

  const single = src('total = 0', 'for i in range(4):', '    total = total + i', 'print(total)')
  // 헤더(2) ↔ 몸통(3)을 네 번, 마지막 헤더 방문은 소진 검사, 그리고 루프 밖(4)
  const singleLines = [1, 2, 3, 2, 3, 2, 3, 2, 3, 2, 4]

  it('4바퀴 도는 반복문은 1·2·3·4회차로 센다', () => {
    expect(badges(single, singleLines)).toEqual([
      'i 반복 1회차', 'i 반복 2회차', 'i 반복 3회차', 'i 반복 4회차', '—',
    ])
  })

  it('for 반복문은 변수 이름을 달고 while은 숫자만 단다', () => {
    const w = src('n = 3', 'while n > 0:', '    n = n - 1', 'print(n)')
    expect(badges(w, [1, 2, 3, 2, 3, 2, 4])).toEqual(['반복 1회차', '반복 2회차', '—'])
  })

  it('튜플 언패킹 반복문도 이름을 단다 — 이름 없는 while과 섞여도 구분된다', () => {
    // BFS의 모양: while 바깥(이름 없음) + for dr, dc 안쪽. 둘 다 숫자만이면 4 → 1 → 2가
    // 근거 없이 널뛰는 것으로 보인다
    const bfs = src('while queue:', '    pos = queue.pop()', '    for dr, dc in moves:', '        pass')
    expect(badges(bfs, [1, 2, 3, 4, 3, 4, 3, 1, 2, 3, 4, 3, 1])).toEqual([
      '반복 1회차',
      'dr, dc 반복 1회차',
      'dr, dc 반복 2회차',
      '반복 1회차',
      '반복 2회차',
      'dr, dc 반복 1회차',
      '반복 2회차',
    ])
  })

  it('중첩 반복문에서 안쪽은 바깥이 한 바퀴 돌 때마다 다시 1부터 센다', () => {
    const nested = src('for i in range(2):', '    for j in range(2):', '        pass')
    const out = badges(nested, [1, 2, 3, 2, 3, 2, 1, 2, 3, 2, 3, 2, 1])
    expect(out.filter(t => t.startsWith('j'))).toEqual([
      'j 반복 1회차', 'j 반복 2회차', 'j 반복 1회차', 'j 반복 2회차',
    ])
    // 바깥 헤더를 밟는 순간에도 배지는 지금 도는 반복문을 말한다 — 그때 i는 아직 1회차까지
    // 돌았고(회차는 몸통에 들어설 때 오른다) 다음 샷에 2회차가 된다
    expect(out.filter(t => t.startsWith('i'))).toEqual([
      'i 반복 1회차', 'i 반복 1회차', 'i 반복 2회차', 'i 반복 2회차',
    ])
  })

  it('반복문 밖으로 나갈 때만 배지가 내려간다 — 도는 중에 끝났다고 하지 않는다', () => {
    const out = badges(single, singleLines)
    expect(out.filter(t => t === '—')).toHaveLength(1)
    expect(out[out.length - 1]).toBe('—')
  })

  it('코드가 없으면 배지가 없다 — 근거 없이 숫자를 만들지 않는다', () => {
    const events: TraceEvent[] = [
      ev({ kind: 'call', observedAtLine: 1 }, 0),
      ...[1, 2, 3, 2, 3, 2, 4].map((l, k) => ev({ observedAtLine: l, causedByLine: l }, k + 1)),
      ev({ kind: 'return', observedAtLine: 4 }, 8),
    ]
    const shots = choreograph(events, buildStage(events))
    expect(shots.flatMap(s => s.motions).some(m => m.v === 'loop' || m.v === 'loopEnd')).toBe(false)
  })
})

/* 저울은 "판단"의 은유다 — 조건의 한 조각에 참/거짓 도장을 찍으면, 참이라 해놓고
   몸통이 안 도는 샷이 나온다 (실측 BFS: 32번 중 21번). 판단식 전체를 덮을 때만 발화한다 */
describe('choreograph: 저울은 조건 전체를 볼 때만 내려온다', () => {
  const withCode = (code: string, line: number, deltas: [string, string][]) => {
    const events: TraceEvent[] = [
      ev({ kind: 'call', observedAtLine: 1 }, 0),
      ev({
        observedAtLine: line - 1 < 1 ? 1 : line - 1,
        localsDelta: deltas.map(([name, v]) => ({ name, op: 'set' as const, value: P(v) })),
      }, 1),
      ev({ observedAtLine: line, causedByLine: line - 1 }, 2),
      ev({ kind: 'return', observedAtLine: line }, 3),
    ]
    return choreograph(events, buildStage(events), code)
      .flatMap(s2 => s2.motions)
      .filter(m => m.v === 'compare')
  }

  it('and로 이어진 조건은 침묵한다 — 첫 절만 접지하고 판단을 선언할 수 없다', () => {
    const code = ['nr = 0', 'nc = 0', 'if 0 <= nr < 4 and 0 <= nc < 4:', '    pass'].join('\n')
    expect(withCode(code, 3, [['nr', '0'], ['nc', '0']])).toEqual([])
  })

  it('체인 비교도 침묵한다 — 0 <= nr만 보고 < 4를 빠뜨린다', () => {
    const code = ['nr = 5', 'if 0 <= nr < 4:', '    pass'].join('\n')
    expect(withCode(code, 2, [['nr', '5']])).toEqual([])
  })

  it('조건이 단일 비교면 그대로 저울이 내려온다 (가드가 과잉이지 않다)', () => {
    const code = ['n = 3', 'if n <= 1:', '    pass'].join('\n')
    const cmp = withCode(code, 2, [['n', '3']])
    expect(cmp).toHaveLength(1)
    expect(cmp[0]).toMatchObject({ text: '3 <= 1 → 거짓', verdict: false })
  })

  it('while의 단일 조건도 저울을 받는다', () => {
    const code = ['n = 3', 'while n > 0:', '    pass'].join('\n')
    expect(withCode(code, 2, [['n', '3']])).toHaveLength(1)
  })
})

/* 좌표 튜플도 저울의 양팔이 된다 — 알약이 이미 (0, 0)이라 말하고 있는데
   저울만 그 값을 못 드는 것은 계약이 아니라 결함이었다 */
describe('choreograph: 튜플 비교도 저울이 든다', () => {
  const tup = (id: number, items: string[], t = 'int') => ({
    op: 'set' as const,
    obj: { id, type: 'tuple', items: items.map(v => P(v, t)) },
  })
  const run = (code: string, line: number, objs: ReturnType<typeof tup>[], binds: [string, number][]) => {
    const events: TraceEvent[] = [
      ev({ kind: 'call', observedAtLine: 1 }, 0),
      ev({
        observedAtLine: line - 1 < 1 ? 1 : line - 1,
        objectsDelta: objs,
        localsDelta: binds.map(([name, id]) => ({ name, op: 'set' as const, value: { k: 'ref' as const, id } })),
      }, 1),
      ev({ observedAtLine: line, causedByLine: line - 1 }, 2),
      ev({ kind: 'return', observedAtLine: line }, 3),
    ]
    return choreograph(events, buildStage(events), code)
      .flatMap(x => x.motions)
      .filter(m => m.v === 'compare') as Extract<Motion, { v: 'compare' }>[]
  }
  const code = ['pos = (0, 0)', 'goal = (3, 3)', 'if pos == goal:', '    pass'].join('\n')

  it('좌표가 다르면 거짓 도장을 찍는다', () => {
    const c = run(code, 3, [tup(7, ['0', '0']), tup(8, ['3', '3'])], [['pos', 7], ['goal', 8]])
    expect(c).toHaveLength(1)
    expect(c[0]).toMatchObject({ a: '(0, 0)', op: '==', b: '(3, 3)', verdict: false })
  })

  it('좌표가 같으면 참 도장을 찍는다', () => {
    const c = run(code, 3, [tup(7, ['3', '3']), tup(8, ['3', '3'])], [['pos', 7], ['goal', 8]])
    expect(c[0]).toMatchObject({ verdict: true })
  })

  it('길이가 다르면 거짓이다', () => {
    const c = run(code, 3, [tup(7, ['3', '3', '3']), tup(8, ['3', '3'])], [['pos', 7], ['goal', 8]])
    expect(c[0]).toMatchObject({ verdict: false })
  })

  it('같은 자리의 타입이 다르면 도장을 찍지 않는다 — 파이썬의 ==가 참인데 repr은 다르다', () => {
    const events: TraceEvent[] = [
      ev({ kind: 'call', observedAtLine: 1 }, 0),
      ev({
        observedAtLine: 2,
        objectsDelta: [
          { op: 'set', obj: { id: 7, type: 'tuple', items: [P('1', 'int'), P('1', 'int')] } },
          { op: 'set', obj: { id: 8, type: 'tuple', items: [P('1.0', 'float'), P('1', 'int')] } },
        ],
        localsDelta: [
          { name: 'pos', op: 'set', value: { k: 'ref', id: 7 } },
          { name: 'goal', op: 'set', value: { k: 'ref', id: 8 } },
        ],
      }, 1),
      ev({ observedAtLine: 3, causedByLine: 2 }, 2),
      ev({ kind: 'return', observedAtLine: 3 }, 3),
    ]
    const c = choreograph(events, buildStage(events), code)
      .flatMap(x => x.motions)
      .filter(m => m.v === 'compare') as Extract<Motion, { v: 'compare' }>[]
    expect(c).toHaveLength(1)
    expect(c[0].verdict).toBeUndefined()
  })

  it('잘린 상자는 도장을 찍지 않는다 — 20칸을 보고 500칸이 같다고 말할 수 없다', () => {
    const big = (id: number) => ({
      op: 'set' as const,
      obj: { id, type: 'list', items: [P('1'), P('2')], n: 500, truncated: true },
    })
    const c = run(['a = []', 'b = []', 'if a == b:', '    pass'].join('\n'), 3,
      [big(7), big(8)], [['a', 7], ['b', 8]])
    expect(c[0]?.verdict).toBeUndefined()
  })

  it('부등호는 저울을 내주지 않는다 — 사전식 순서는 기울기로 그릴 수 없다', () => {
    const lt = ['pos = (0, 0)', 'goal = (3, 3)', 'if pos < goal:', '    pass'].join('\n')
    expect(run(lt, 3, [tup(7, ['0', '0']), tup(8, ['3', '3'])], [['pos', 7], ['goal', 8]])).toEqual([])
  })
})

/* 터진 실행의 마무리 — 잡히지 않은 예외로 끝나면 마지막 자막이 멈춤을 말하고 축하를 내지 않는다.
   판정은 상태 기반: exception이 세우고 이후의 line이 지운다 (잡힌 예외는 except 절 line이 낀다) */
describe('choreograph: 터진 실행은 멈춤으로 끝난다', () => {
  it('잡히지 않은 예외 — 마지막 샷이 crashEnd와 멈춤 자막을 싣는다', () => {
    const events: TraceEvent[] = [
      ev({ kind: 'call', observedAtLine: 1 }, 0),
      ev({ localsDelta: [{ name: 'total', op: 'set', value: P('5600') }] }, 1),
      ev({ kind: 'exception', observedAtLine: 4, error: 'IndexError: list index out of range' }, 2),
      ev({ kind: 'return', observedAtLine: 4 }, 3),
    ]
    const shots = choreograph(events, buildStage(events))
    const last = shots[shots.length - 1]
    expect(last.motions.some(m => m.v === 'crashEnd')).toBe(true)
    expect(last.caption).toBe('여기서 실행이 멈췄습니다 — IndexError: list index out of r…')
  })

  it('잡힌 예외 — except 절의 line이 끼므로 정상 마감으로 돌아온다', () => {
    const events: TraceEvent[] = [
      ev({ kind: 'call', observedAtLine: 1 }, 0),
      ev({ kind: 'exception', observedAtLine: 3, error: 'ZeroDivisionError: division by zero' }, 1),
      ev({ observedAtLine: 5, localsDelta: [{ name: 'r', op: 'set', value: P('-1') }] }, 2),
      ev({ kind: 'return', observedAtLine: 5 }, 3),
    ]
    const shots = choreograph(events, buildStage(events))
    const last = shots[shots.length - 1]
    expect(last.motions.some(m => m.v === 'crashEnd')).toBe(false)
    expect(last.caption).toBe('실행 종료 — 최종 상태입니다')
  })

  it('정렬을 마친 뒤 터져도 축하는 없다 — 마지막 인상은 멈춤이어야 한다', () => {
    const events: TraceEvent[] = [
      ev({ kind: 'call', observedAtLine: 1 }, 0),
      ev({
        observedAtLine: 2,
        localsDelta: [{ name: 'a', op: 'set', value: { k: 'ref', id: 1 } }],
        objectsDelta: [listSet(['3', '1', '2'])],
      }, 1),
      ev({ observedAtLine: 3, objectsDelta: [listSet(['1', '2', '3'])] }, 2),
      ev({ kind: 'exception', observedAtLine: 4, error: 'ValueError: boom' }, 3),
      ev({ kind: 'return', observedAtLine: 4 }, 4),
    ]
    const shots = choreograph(events, buildStage(events))
    const all = shots.flatMap(x => x.motions)
    expect(all.some(m => m.v === 'sortedSweep')).toBe(false)
    expect(all.some(m => m.v === 'crashEnd')).toBe(true)
  })
})
