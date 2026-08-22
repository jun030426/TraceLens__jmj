import { describe, it, expect } from 'vitest'
import type { TraceEvent } from '../trace/types'
import { detectCascades } from './cascades'

/* 일직선 사슬 감지 — 같은 함수의 연속 call이 각각 직전 call의 자식인 구간(하강),
   연속 return이 각각 직전 반환의 부모로 이어지는 구간(unwind). 문턱 10을 넘으면
   머리(하강 10 · 값 반환 10 · 나머지 3)만 남기고 접는다. 판정은 트레이스의 사실뿐이다 */

const P = (v: string, t = 'int') => ({ k: 'prim' as const, v, t })
const ev = (over: Partial<TraceEvent>, seq: number): TraceEvent => ({
  seq, kind: 'line', frameId: 0, parentFrameId: null, func: '<module>',
  causedByLine: null, observedAtLine: 1, localsDelta: [], objectsDelta: [], stdout: '',
  ...over,
})

/** countdown 모양 — 모듈 밑으로 depth개의 같은 함수 호출이 일직선으로 내려간다 (반환 없음) */
const descentEvents = (depth: number, func = 'countdown'): TraceEvent[] => {
  const out: TraceEvent[] = [ev({ kind: 'call' }, 0), ev({ observedAtLine: 4 }, 1)]
  for (let k = 1; k <= depth; k++) {
    out.push(ev({
      kind: 'call', frameId: k, parentFrameId: k - 1 === 0 ? 0 : k - 1, func,
      localsDelta: [{ name: 'n', op: 'set', value: P(String(depth - k + 1)) }],
    }, out.length))
    out.push(ev({ frameId: k, func, observedAtLine: 2 }, out.length))
  }
  return out
}

/** fact 모양의 unwind — 가장 깊은 프레임부터 차례로 returned를 실고 반환한다 */
const valueUnwindEvents = (depth: number, func = 'fact'): TraceEvent[] => {
  const out = descentEvents(depth, func)
  for (let k = depth; k >= 1; k--) {
    out.push(ev({
      kind: 'return', frameId: k, parentFrameId: k - 1 === 0 ? 0 : k - 1, func,
      returned: P(String(k)),
    }, out.length))
  }
  out.push(ev({ kind: 'return' }, out.length))
  return out
}

/** 크래시 unwind — 가장 깊은 곳의 발생 뒤 (exception, return) 쌍이 위로 이어진다 */
const crashUnwindEvents = (depth: number, func = 'descend'): TraceEvent[] => {
  const out = descentEvents(depth, func)
  const err = 'ZeroDivisionError: division by zero'
  for (let k = depth; k >= 1; k--) {
    out.push(ev({ kind: 'exception', frameId: k, parentFrameId: k - 1 === 0 ? 0 : k - 1, func, error: err }, out.length))
    out.push(ev({ kind: 'return', frameId: k, parentFrameId: k - 1 === 0 ? 0 : k - 1, func }, out.length))
  }
  out.push(ev({ kind: 'exception', error: err }, out.length))
  out.push(ev({ kind: 'return' }, out.length))
  return out
}

describe('detectCascades: 하강 사슬', () => {
  it('10을 넘는 사슬만 접는다 — 11이면 마지막 1회가 접힌다', () => {
    const events = descentEvents(11)
    const folds = detectCascades(events)
    expect(folds).toHaveLength(1)
    const calls = events.filter(e => e.kind === 'call' && e.func === 'countdown')
    expect(folds[0]).toMatchObject({ kind: 'descent', func: 'countdown', count: 1 })
    expect(folds[0].from).toBe(calls[10].seq)
    expect(folds[0].to).toBe(calls[10].seq)
  })

  it('사슬 10이면 접지 않는다 — fact(10) 회귀', () => {
    expect(detectCascades(descentEvents(10))).toEqual([])
  })

  it('30 깊이는 20을 접고, 접힌 끝은 마지막 call이다 (그 프레임의 line은 밖)', () => {
    const events = descentEvents(30)
    const folds = detectCascades(events)
    expect(folds).toHaveLength(1)
    const calls = events.filter(e => e.kind === 'call' && e.func === 'countdown')
    expect(folds[0]).toMatchObject({ kind: 'descent', count: 20 })
    expect(folds[0].from).toBe(calls[10].seq)
    expect(folds[0].to).toBe(calls[29].seq)
    const lastLine = events[events.length - 1] // 가장 깊은 프레임의 line — 개별 재생돼야 한다
    expect(lastLine.kind).toBe('line')
    expect(lastLine.seq).toBeGreaterThan(folds[0].to)
  })

  it('상호 재귀(a→b→a)는 사슬이 아니다 — 같은 함수가 아니면 끊긴다', () => {
    const out: TraceEvent[] = [ev({ kind: 'call' }, 0)]
    for (let k = 1; k <= 24; k++) {
      out.push(ev({ kind: 'call', frameId: k, parentFrameId: k - 1, func: k % 2 ? 'a' : 'b' }, out.length))
      out.push(ev({ frameId: k, func: k % 2 ? 'a' : 'b', observedAtLine: 2 }, out.length))
    }
    expect(detectCascades(out)).toEqual([])
  })

  it('형제 호출(직전 call의 자식이 아님)은 사슬을 끊는다 — fib의 두 번째 가지', () => {
    // f1이 f2를 부르고 f2가 곧장 반환 → f1이 f3을 다시 부른다: f3의 부모는 f1이지만
    // 직전 call(f2)의 자식이 아니므로 새 사슬이다
    const out: TraceEvent[] = [
      ev({ kind: 'call' }, 0),
      ev({ kind: 'call', frameId: 1, parentFrameId: 0, func: 'fib' }, 1),
      ev({ kind: 'call', frameId: 2, parentFrameId: 1, func: 'fib' }, 2),
      ev({ kind: 'return', frameId: 2, parentFrameId: 1, func: 'fib', returned: P('1') }, 3),
      ev({ kind: 'call', frameId: 3, parentFrameId: 1, func: 'fib' }, 4),
      ev({ kind: 'return', frameId: 3, parentFrameId: 1, func: 'fib', returned: P('0') }, 5),
      ev({ kind: 'return', frameId: 1, parentFrameId: 0, func: 'fib', returned: P('1') }, 6),
      ev({ kind: 'return' }, 7),
    ]
    expect(detectCascades(out)).toEqual([])
  })

  it('루프 빨리감기 구간과 겹치는 사슬은 접지 않는다 — 한 이벤트의 주인은 하나다', () => {
    const events = descentEvents(30)
    const calls = events.filter(e => e.kind === 'call' && e.func === 'countdown')
    const overlap = [{ from: calls[12].seq, to: calls[14].seq }]
    expect(detectCascades(events, overlap)).toEqual([])
  })
})

describe('detectCascades: unwind 사슬', () => {
  it('값 반환 사슬은 머리 10을 남긴다 — 반환 칩이 매회 새 값이다', () => {
    const events = valueUnwindEvents(15)
    const folds = detectCascades(events)
    const rets = events.filter(e => e.kind === 'return' && e.func === 'fact')
    const unwind = folds.find(f => f.kind === 'unwindValue')!
    expect(unwind).toMatchObject({ kind: 'unwindValue', func: 'fact', count: 5 })
    expect(unwind.from).toBe(rets[10].seq)
    expect(unwind.to).toBe(rets[14].seq)
  })

  it('unwind 15는 하강 15와 함께 각각 접힌다 — 두 fold는 겹치지 않는다', () => {
    const folds = detectCascades(valueUnwindEvents(15))
    expect(folds.map(f => f.kind).sort()).toEqual(['descent', 'unwindValue'])
    const [a, b] = [...folds].sort((x, y) => x.from - y.from)
    expect(a.to).toBeLessThan(b.from)
  })

  it('unwind 10이면 접지 않는다 — fact(10) 회귀', () => {
    expect(detectCascades(valueUnwindEvents(10)).filter(f => f.kind !== 'descent')).toEqual([])
  })

  it('크래시 unwind는 머리 3을 남기고, 접힌 시작은 그 단계의 exception부터다', () => {
    const events = crashUnwindEvents(15)
    const folds = detectCascades(events)
    const crash = folds.find(f => f.kind === 'unwindCrash')!
    expect(crash).toMatchObject({ kind: 'unwindCrash', func: 'descend', count: 12 })
    const rets = events.filter(e => e.kind === 'return' && e.func === 'descend')
    const excs = events.filter(e => e.kind === 'exception' && e.func === 'descend')
    // 머리 = 가장 깊은 3프레임의 (전파, 닫힘) — 4번째 프레임의 전파부터 접힌다
    expect(crash.from).toBe(excs[3].seq)
    expect(crash.to).toBe(rets[14].seq)
  })

  it('returned 없는 조용한 unwind는 머리 3 — 같은 문장의 반복은 3이면 선다', () => {
    const out = descentEvents(15, 'noisy')
    for (let k = 15; k >= 1; k--) {
      out.push(ev({ kind: 'return', frameId: k, parentFrameId: k - 1 === 0 ? 0 : k - 1, func: 'noisy' }, out.length))
    }
    const quiet = detectCascades(out).find(f => f.kind === 'unwindQuiet')!
    expect(quiet).toMatchObject({ kind: 'unwindQuiet', count: 12 })
  })

  it('line이 끼면 사슬이 끊긴다 — try/except가 잡는 장면은 접히지 않는다', () => {
    // 12프레임 크래시 unwind 중 8번째에서 잡힌다: exception 뒤 line이 오면 그 앞까지가 사슬이고
    // (7단계 ≤ 10) 접히지 않는다. 잡는 장면의 이벤트는 어떤 fold에도 들어가지 않는다
    const out = descentEvents(12, 'descend')
    const err = 'ZeroDivisionError: division by zero'
    for (let k = 12; k >= 6; k--) {
      out.push(ev({ kind: 'exception', frameId: k, parentFrameId: k - 1, func: 'descend', error: err }, out.length))
      if (k === 6) out.push(ev({ frameId: k, func: 'descend', observedAtLine: 5 }, out.length)) // except 절
      else out.push(ev({ kind: 'return', frameId: k, parentFrameId: k - 1, func: 'descend' }, out.length))
    }
    const folds = detectCascades(out)
    expect(folds.filter(f => f.kind !== 'descent')).toEqual([])
  })
})
