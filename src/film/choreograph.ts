import type { TraceEvent, Value, ObjectSnap } from '../trace/types'
import { buildDigest } from '../digest/buildDigest'
import type { CompareTarget, Motion, Shot, StagePlan } from './types'

const BASE_MS = 520
const SLOW_MS = 1100
const LAPSE_MS = 900
const FULL_ITERATIONS = 10 // 반복은 10회까지 온전히 보여주고, 그 이후는 압축한다

const capText = (s: string, n = 12) => (s.length > n ? s.slice(0, n - 1) + '…' : s)

// 값의 압축 표기 — ref는 1단계까지 들여다본다: "(0, 0)", "[0,0,1,0]", "{a: 1}".
// "tuple"이라는 글자는 아무것도 가르치지 않는다. 값은 전부 트레이스 스냅에서 온다.
const shortText = (v: Value, objects: Map<number, ObjectSnap>, depth = 0): string => {
  if (v.k === 'prim') return capText(v.v)
  const o = objects.get(v.id)
  if (!o) return '객체'
  if (depth >= 1) return o.type
  if (o.items) {
    const [open, close] = o.type === 'tuple' ? ['(', ')'] : o.type === 'set' ? ['{', '}'] : ['[', ']']
    return capText(open + o.items.map(x => shortText(x, objects, 1)).join(', ') + close)
  }
  if (o.entries) {
    return capText('{' + o.entries.map(([k, x]) => `${k}: ${shortText(x, objects, 1)}`).join(', ') + '}')
  }
  return o.type
}

// 객체의 현재 칸별 표시 문자열 — 리스트는 값, dict는 "키: 값"
const textsOf = (obj: ObjectSnap, objects: Map<number, ObjectSnap>): string[] => {
  const size = (obj.items?.length ?? 0) + (obj.entries?.length ?? 0)
  return Array.from({ length: size }, (_, i) => {
    const item = obj.items?.[i]
    if (item) return shortText(item, objects)
    const entry = obj.entries?.[i]
    if (entry) return `${entry[0]}: ${shortText(entry[1], objects)}`
    return ''
  })
}

/* ── 비교 감지 — 소스 라인의 비교식을 트레이스 값으로 접지한다.
   양변이 실제 값으로 해석될 때만 발화한다: 못 하면 침묵 (지어내지 않는다) ── */

const CMP_RE = /([A-Za-z_]\w*(?:\[[^\]]+\])?|-?\d+(?:\.\d+)?)\s*(<=|>=|==|!=|<|>)\s*([A-Za-z_]\w*(?:\[[^\]]+\])?|-?\d+(?:\.\d+)?)/

const stripNoise = (line: string) => line.split('#')[0].replace(/'[^']*'|"[^"]*"/g, '""')

type Operand = { text: string; num: number | null; target?: CompareTarget }

function resolveOperand(
  raw: string,
  frameId: number,
  locals: Map<string, Value>,
  objects: Map<number, ObjectSnap>,
): Operand | null {
  const s = raw.trim()
  if (/^-?\d+(\.\d+)?$/.test(s)) return { text: s, num: Number(s) }
  const m = s.match(/^([A-Za-z_]\w*)(?:\[([^\]]+)\])?$/)
  if (!m) return null
  const v = locals.get(`${frameId}:${m[1]}`)
  if (!v) return null
  if (!m[2]) {
    if (v.k !== 'prim') return null
    return {
      text: v.v,
      num: v.t === 'int' || v.t === 'float' ? Number(v.v) : null,
      target: { kind: 'var', varKey: `${frameId}:${m[1]}` },
    }
  }
  if (v.k !== 'ref') return null
  const obj = objects.get(v.id)
  if (!obj?.items) return null
  // 첨자: 리터럴, 지역 int, 또는 지역 int ± 리터럴 (arr[j+1])
  const sub = m[2].replace(/\s+/g, '').match(/^([A-Za-z_]\w*|\d+)(?:([+-])(\d+))?$/)
  if (!sub) return null
  let base: number | null = null
  if (/^\d+$/.test(sub[1])) base = Number(sub[1])
  else {
    const iv = locals.get(`${frameId}:${sub[1]}`)
    if (iv?.k === 'prim' && iv.t === 'int') base = Number(iv.v)
  }
  if (base === null) return null
  const idx = base + (sub[2] === '-' ? -Number(sub[3]) : Number(sub[3] ?? 0))
  const item = obj.items[idx]
  if (!item || item.k !== 'prim') return null
  return {
    text: item.v,
    num: item.t === 'int' || item.t === 'float' ? Number(item.v) : null,
    target: { kind: 'cell', objectId: v.id, index: idx },
  }
}

function detectCompare(
  rawLine: string,
  frameId: number,
  locals: Map<string, Value>,
  objects: Map<number, ObjectSnap>,
): Motion | null {
  const m = stripNoise(rawLine).match(CMP_RE)
  if (!m) return null
  const a = resolveOperand(m[1], frameId, locals, objects)
  const b = resolveOperand(m[3], frameId, locals, objects)
  if (!a || !b) return null
  const targets = [a.target, b.target].filter((t): t is CompareTarget => !!t)
  if (targets.length === 0) return null
  let verdict = ''
  if (a.num !== null && b.num !== null && Number.isFinite(a.num) && Number.isFinite(b.num)) {
    const op = m[2]
    const res =
      op === '<' ? a.num < b.num
      : op === '>' ? a.num > b.num
      : op === '<=' ? a.num <= b.num
      : op === '>=' ? a.num >= b.num
      : op === '==' ? a.num === b.num
      : a.num !== b.num
    verdict = res ? ' → 참' : ' → 거짓'
  }
  return { v: 'compare', text: `${a.text} ${m[2]} ${b.text}${verdict}`, targets }
}

// 2패스 — 실행 사건을 "무엇이 어떻게 움직이는가"로 번역한다.
export function choreograph(events: TraceEvent[], plan: StagePlan, code?: string): Shot[] {
  const digest = buildDigest(events)
  const srcLines = (code ?? '').split('\n')
  const locals = new Map<string, Value>() // `${frameId}:${name}` → 최신 값 (compare 접지용)
  const varsSeen = new Set<string>()
  const frameVars = new Map<number, Set<string>>() // frameId → 화면에 올라간 그 프레임의 변수들
  const refCount = new Map<number, Set<string>>()
  const objects = new Map<number, ObjectSnap>()
  const prevTexts = new Map<number, string[]>() // objectId → 직전 상태의 칸별 표시 문자열

  // 캐스팅은 buildStage가 판정했다 — 여기서는 명단에 있는 것만 무대에 올린다.
  // objects·locals 맵은 전체를 계속 추적한다 (요약 텍스트·compare 접지에 필요).
  const castObjects = new Set(plan.objects.map(o => o.objectId))
  const castVars = new Set(plan.variables.map(v => v.varKey))
  const lifeEndOf = new Map(plan.objects.map(o => [o.objectId, o.life.to]))
  const entered = new Set<number>() // enterObj까지 마친 상자
  const exited = new Set<number>()

  // 10회를 넘는 반복 구간의 "11회차부터 끝까지"를 한 샷으로 압축한다
  const lapse: { from: number; to: number; count: number }[] = []
  for (const s of digest.spans) {
    if (!s.iterations || s.iterations <= FULL_ITERATIONS) continue
    const [a, b] = s.sourceSeqRange
    const perIter = Math.max(1, Math.floor((b - a + 1) / s.iterations))
    const cut = a + perIter * FULL_ITERATIONS
    if (cut < b) lapse.push({ from: cut, to: b, count: s.iterations - FULL_ITERATIONS })
  }
  const lapseAt = (seq: number) => lapse.find(l => seq >= l.from && seq <= l.to)

  // 반복 배지 — 접힘은 헤더 라인의 3회차 방문부터 시작되므로 seen은 2에서 출발한다.
  // 헤더 라인 = 접힘 시작 이벤트의 관측 라인 (몸통보다 먼저 3회차에 도달하는 줄)
  const loopSpans = digest.spans
    .filter(s => (s.iterations ?? 0) > 1)
    .map(s => ({ from: s.sourceSeqRange[0], to: s.sourceSeqRange[1], total: s.iterations!, headerLine: s.lines[1], seen: 2 }))
  let badgeOn = false

  const shots: Shot[] = []

  // 압축 구간은 상태만 따라가며 모으고, 빠져나올 때 한 샷으로 "정산"한다 —
  // 칸·변수를 실제 최종 값으로 맞추므로 '…' 같은 잔상이 남지 않는다
  let pendingLapse: { from: number; startSeq: number; count: number } | null = null
  const flushLapse = (p: { startSeq: number; count: number }): Shot => {
    const motions: Motion[] = [{ v: 'loop', text: `남은 ${p.count}회 빨리감기` }]
    for (const [id, obj] of objects) {
      if (!castObjects.has(id)) continue
      const texts = textsOf(obj, objects)
      const prev = prevTexts.get(id)
      if (!prev) {
        motions.push({ v: 'enterObj', objectId: id })
        entered.add(id)
        for (let i = 0; i < texts.length; i++) motions.push({ v: 'grow', objectId: id, index: i, text: texts[i] })
      } else {
        for (let i = 0; i < Math.min(prev.length, texts.length); i++)
          if (texts[i] !== prev[i]) motions.push({ v: 'setCell', objectId: id, index: i, text: texts[i] })
        for (let i = prev.length; i < texts.length; i++) motions.push({ v: 'grow', objectId: id, index: i, text: texts[i] })
        for (let i = texts.length; i < prev.length; i++) motions.push({ v: 'shrink', objectId: id, index: i })
      }
      prevTexts.set(id, texts)
    }
    for (const id of [...prevTexts.keys()]) {
      if (!objects.has(id)) {
        motions.push({ v: 'exitObj', objectId: id })
        prevTexts.delete(id)
      }
    }
    // 변수 값도 정산한다 — 루프 변수가 낡은 값으로 남으면 그것도 거짓말이다
    for (const [key, v] of locals) {
      if (v.k !== 'prim') continue
      if (!varsSeen.has(key) || !castVars.has(key)) continue
      motions.push({ v: 'setVar', varKey: key, text: shortText(v, objects) })
    }
    const target = [...objects.entries()]
      .filter(([id]) => castObjects.has(id))
      .sort((a, b) => (b[1].items?.length ?? 0) - (a[1].items?.length ?? 0))[0]
    return {
      seq: p.startSeq,
      motions,
      durationMs: LAPSE_MS,
      focus: target ? { kind: 'object', objectId: target[0] } : null,
      timelapse: p.count,
    }
  }

  for (const e of events) {
    for (const d of e.objectsDelta) {
      if (d.op === 'set' && d.obj) objects.set(d.obj.id, d.obj)
      else if (d.id !== undefined) objects.delete(d.id)
    }
    // 델타를 먼저 반영한다 — 이 이벤트의 델타는 "직전 라인이 일으켜 이 라인 경계에서 관측"된 것이므로,
    // 반영 후 상태가 곧 지금 라인의 조건식이 보는 상태다
    for (const d of e.localsDelta) {
      const key = `${e.frameId}:${d.name}`
      if (d.op === 'delete') locals.delete(key)
      else if (d.value) locals.set(key, d.value)
    }

    const inLapse = lapseAt(e.seq)
    if (inLapse) {
      if (!pendingLapse || pendingLapse.from !== inLapse.from) {
        if (pendingLapse) shots.push(flushLapse(pendingLapse))
        pendingLapse = { from: inLapse.from, startSeq: e.seq, count: inLapse.count }
      }
      continue
    }
    if (pendingLapse) {
      shots.push(flushLapse(pendingLapse))
      pendingLapse = null
      badgeOn = true
    }

    const motions: Motion[] = []
    let slow = false

    // 수명이 다한 상자는 내려간다 — 놓인 자리를 물려받을 후임과 겹치지 않게
    for (const id of entered) {
      if (exited.has(id)) continue
      const end = lifeEndOf.get(id)
      if (end !== undefined && end < e.seq) {
        motions.push({ v: 'exitObj', objectId: id })
        exited.add(id)
      }
    }

    // "반복문이 돌고 있다"의 상시 표시 — 헤더 라인을 다시 밟을 때마다 회차가 오른다
    const inLoop = loopSpans.find(l => e.seq >= l.from && e.seq <= l.to)
    if (inLoop && e.kind === 'line' && e.observedAtLine === inLoop.headerLine) {
      inLoop.seen += 1
      motions.push({ v: 'loop', text: `반복 ${inLoop.seen}회차 / 총 ${inLoop.total}회` })
      badgeOn = true
    } else if (!inLoop && badgeOn) {
      motions.push({ v: 'loopEnd' })
      badgeOn = false
    }

    if (code && e.kind === 'line') {
      const cmp = detectCompare(srcLines[e.observedAtLine - 1] ?? '', e.frameId, locals, objects)
      if (cmp) motions.push(cmp)
    }

    if (e.kind === 'call') motions.push({ v: 'pushFrame', frameId: e.frameId })
    if (e.kind === 'return') {
      motions.push({ v: 'popFrame', frameId: e.frameId })
      // 반환된 프레임의 지역 변수는 무대에서 내린다 — 남겨두면 잔상이 된다.
      // 단, 모듈 프레임은 남긴다: 마지막 장면은 프로그램의 최종 상태를 보여줘야 한다.
      if (e.parentFrameId !== null) {
        for (const key of frameVars.get(e.frameId) ?? []) {
          motions.push({ v: 'exitVar', varKey: key })
          varsSeen.delete(key)
        }
        frameVars.delete(e.frameId)
      }
    }
    if (e.kind === 'exception') {
      // 예외는 실패가 아니라 콘텐츠 — 흔들고, 무엇이 터졌는지 무대에 적는다
      motions.push({ v: 'shake', frameId: e.frameId })
      motions.push({ v: 'raise', frameId: e.frameId, text: e.error ?? '예외 발생' })
      slow = true
    }

    for (const d of e.objectsDelta) {
      if (d.op !== 'set' || !d.obj) continue
      if (!castObjects.has(d.obj.id)) continue // 조연은 부모 칸의 요약 텍스트가 전부다
      const texts = textsOf(d.obj, objects)
      const size = texts.length
      const prev = prevTexts.get(d.obj.id)

      if (!prev) {
        motions.push({ v: 'enterObj', objectId: d.obj.id })
        entered.add(d.obj.id)
        // 리터럴로 이미 원소를 가진 채 태어난 객체 — 그 칸들도 채워야 한다.
        // 안 그러면 상자만 나타나고 안이 영원히 빈 채로 남는다.
        for (let i = 0; i < size; i++) motions.push({ v: 'grow', objectId: d.obj.id, index: i, text: texts[i] })
      } else if (size > prev.length) {
        // dict·set도 칸이 차오르는 순서를 보여준다 — 리스트는 값만, dict는 키: 값
        for (let i = 0; i < prev.length; i++)
          if (texts[i] !== prev[i]) motions.push({ v: 'setCell', objectId: d.obj.id, index: i, text: texts[i] })
        for (let i = prev.length; i < size; i++) motions.push({ v: 'grow', objectId: d.obj.id, index: i, text: texts[i] })
      } else if (size === prev.length && size > 0) {
        // 바뀐 칸"들"을 정확히 짚는다 — 마지막 칸만 갱신하면 정렬·중간 대입이 거짓말이 된다
        const changed: number[] = []
        for (let i = 0; i < size; i++) if (texts[i] !== prev[i]) changed.push(i)
        if (
          changed.length === 2 &&
          texts[changed[0]] === prev[changed[1]] &&
          texts[changed[1]] === prev[changed[0]]
        ) {
          // 정확히 두 칸이 서로 값을 교환 — 정렬의 심장. 칸이 실제로 자리를 바꾼다
          motions.push({
            v: 'swap', objectId: d.obj.id,
            i: changed[0], k: changed[1],
            iText: texts[changed[0]], kText: texts[changed[1]],
          })
          slow = true
        } else {
          for (const i of changed) motions.push({ v: 'setCell', objectId: d.obj.id, index: i, text: texts[i] })
        }
      } else if (size < prev.length) {
        for (let i = 0; i < size; i++)
          if (texts[i] !== prev[i]) motions.push({ v: 'setCell', objectId: d.obj.id, index: i, text: texts[i] })
        for (let i = size; i < prev.length; i++) motions.push({ v: 'shrink', objectId: d.obj.id, index: i })
      }
      prevTexts.set(d.obj.id, texts)
    }

    for (const d of e.localsDelta) {
      const varKey = `${e.frameId}:${d.name}`
      if (!castVars.has(varKey)) continue // 함수·클래스에 묶인 이름은 데이터가 아니다
      if (d.op === 'delete') {
        motions.push({ v: 'exitVar', varKey })
        varsSeen.delete(varKey)
        continue
      }
      if (!varsSeen.has(varKey)) {
        varsSeen.add(varKey)
        const set = frameVars.get(e.frameId) ?? new Set<string>()
        set.add(varKey)
        frameVars.set(e.frameId, set)
        motions.push({ v: 'enterVar', varKey })
      }
      if (d.value?.k === 'ref' && castObjects.has(d.value.id)) {
        const holders = refCount.get(d.value.id) ?? new Set<string>()
        holders.add(varKey)
        refCount.set(d.value.id, holders)
        const alias = holders.size > 1
        if (alias) slow = true
        motions.push({ v: 'bind', varKey, objectId: d.value.id, alias })
      } else if (d.value?.k === 'ref') {
        // 상자 없는 참조(작은 튜플 등)는 알약 값으로 인라인 — "(1, 1)"
        motions.push({ v: 'setVar', varKey, text: shortText(d.value, objects) })
      } else if (d.value) {
        motions.push({ v: 'setVar', varKey, text: shortText(d.value, objects) })
      }
    }

    if (e.stdout) motions.push({ v: 'stdout', text: e.stdout })
    if (motions.length === 0) continue

    const focusObj = motions.find(m => m.v === 'grow' || m.v === 'bind' || m.v === 'enterObj') as
      | { objectId: number }
      | undefined
    shots.push({
      seq: e.seq,
      motions,
      durationMs: slow ? SLOW_MS : BASE_MS,
      focus: focusObj ? { kind: 'object', objectId: focusObj.objectId } : { kind: 'frame', frameId: e.frameId },
    })
  }
  // 트레이스가 압축 구간에서 끝나면 정산 샷으로 마무리한다
  if (pendingLapse) shots.push(flushLapse(pendingLapse))

  return shots
}
