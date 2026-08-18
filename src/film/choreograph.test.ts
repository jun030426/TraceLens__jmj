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

describe('choreograph: 반복 배지', () => {
  const shots = choreograph(demoEvents, buildStage(demoEvents))
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

describe('choreograph: 정직한 배지·최종값', () => {
  it('반복 배지는 카운트업만 — 모순되는 총계를 달지 않는다', () => {
    const shots = choreograph(demoEvents, buildStage(demoEvents))
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
