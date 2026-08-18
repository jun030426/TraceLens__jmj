import type { TraceEvent, Value, ObjectSnap } from '../trace/types'
import { buildDigest } from '../digest/buildDigest'
import type { CompareTarget, Motion, Shot, StagePlan } from './types'

const BASE_MS = 520
const SLOW_MS = 1100
const MED_MS = 850 // 비교(판단)는 읽을 시간을 받는다 — "5 > 2 → 참"이 읽히기 전에 사라지면 없는 것과 같다
const LAPSE_MS = 900
const FULL_ITERATIONS = 10 // 반복은 10회까지 온전히 보여주고, 그 이후는 압축한다

const capText = (s: string, n = 12) => (s.length > n ? s.slice(0, n - 1) + '…' : s)

/* ── 학습자 자막 — 모션에서 결정적으로 생성하는 한 문장. 화면과 자막이 원리적으로
   일치한다 (대본과 필름의 압축 규칙이 달라 생기는 "자막 딴소리"의 구조적 해결).
   조사 활용이 필요 없는 템플릿("x = 5")로 어색한 한국어를 피한다 ── */

type NameCtx = {
  varName: (key: string) => string
  objName: (id: number) => string
  frameFunc: (id: number) => string
}

function captionOf(motions: Motion[], names: NameCtx): string | undefined {
  const find = <V extends Motion['v']>(v: V) =>
    motions.find(m => m.v === v) as Extract<Motion, { v: V }> | undefined
  const all = <V extends Motion['v']>(v: V) =>
    motions.filter(m => m.v === v) as Extract<Motion, { v: V }>[]

  const raise = find('raise')
  if (raise) return `오류 발생: ${capText(raise.text, 44)}`
  const swap = find('swap')
  if (swap) {
    const cmp = find('compare') // 직전 판단의 echo — 인과가 자막에 남는다
    const head = cmp ? `${cmp.text.replace(' → 참', '')} 참 — ` : `${names.objName(swap.objectId)}: `
    return `${head}${swap.i}번 칸과 ${swap.k}번 칸이 자리를 바꿉니다`
  }
  const cmp = find('compare')
  if (cmp) return `비교: ${cmp.text}`
  const push = find('pushFrame')
  if (push) {
    const f = names.frameFunc(push.frameId)
    return f === '<module>' ? '실행 시작' : `${f}() 호출 — 새 작업 공간이 열립니다`
  }
  const pop = find('popFrame')
  if (pop) {
    const f = names.frameFunc(pop.frameId)
    return f === '<module>' ? '실행 종료 — 최종 상태입니다' : `${f}() 종료 — 작업 공간이 닫힙니다`
  }
  const gflash = all('gridCell').filter(g => g.flash)
  if (gflash.length === 1) return `표 [${gflash[0].r}, ${gflash[0].c}] = ${gflash[0].text}`
  if (gflash.length > 1) return `표 ${gflash.length}칸 갱신`
  const visits = all('gridVisit')
  if (visits.length === 1) return `(${visits[0].r}, ${visits[0].c}) 방문 표시`
  if (visits.length > 1) return `${visits.length}칸 방문 표시`
  const grows = all('grow')
  if (grows.length > 1) return `${names.objName(grows[0].objectId)} 칸이 차례로 채워집니다 (${grows.length}칸)`
  if (grows.length === 1) return `${names.objName(grows[0].objectId)} 새 칸에 ${grows[0].text} 추가`
  const shrink = find('shrink')
  if (shrink) return `${names.objName(shrink.objectId)} ${shrink.index}번 칸이 빠집니다`
  const cells = all('setCell')
  if (cells.length === 1) return `${names.objName(cells[0].objectId)}[${cells[0].index}] = ${cells[0].text}`
  if (cells.length > 1)
    return `${names.objName(cells[0].objectId)} ${cells.map(c => `${c.index}번`).join('·')} 칸 갱신`
  const bind = find('bind')
  if (bind) {
    if (bind.alias) return `${names.varName(bind.varKey)}도 같은 상자를 가리킵니다 (별칭)`
    return find('enterObj') ? `${names.varName(bind.varKey)} ← 새 상자` : `${names.varName(bind.varKey)} ← 상자`
  }
  const sets = all('setVar')
  if (sets.length)
    return sets.slice(0, 2).map(s => `${names.varName(s.varKey)} = ${s.text}`).join(', ')
  const cursor = find('gridCursor')
  if (cursor) return `커서가 (${cursor.r}, ${cursor.c})로 이동`
  const out = find('stdout')
  if (out) return `출력: ${capText(out.text.trim(), 44)}`
  const loop = find('loop')
  if (loop) return loop.text
  const enter = find('enterVar')
  if (enter) return `${names.varName(enter.varKey)} 등장`
  return undefined
}

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

  // 상자 이름표 — 끈을 따라가지 않아도 어느 상자가 maze인지 보이게, 쥔 변수명을 상자에 건다.
  // 보유가 바뀔 때마다(재대입·별칭·반환) 라벨을 다시 쓴다. 별칭이면 "a · b".
  const holderKeys = new Map<number, Set<string>>() // castObj → 쥔 varKey들
  const varHeld = new Map<string, number>() // castVar varKey → objectId

  // 자막용 이름 — 값·이름은 전부 계획(캐스팅)과 보유 관계에서 온다
  const varNameMap = new Map(plan.variables.map(v => [v.varKey, v.name]))
  const frameFuncMap = new Map(plan.frames.map(f => [f.frameId, f.func]))
  const nameCtx: NameCtx = {
    varName: key => varNameMap.get(key) ?? key.slice(key.indexOf(':') + 1),
    objName: id => {
      const held = [...new Set([...(holderKeys.get(id) ?? [])].map(k => k.slice(k.indexOf(':') + 1)))]
      if (held.length) return capText(held.join(' · '), 18)
      const ref = plan.objects.find(o => o.objectId === id)?.referencedBy[0]
      return ref ? ref.slice(ref.indexOf(':') + 1) : '상자'
    },
    frameFunc: id => frameFuncMap.get(id) ?? '',
  }

  // 비교(판단) → 교환(행동)의 인과 사슬 — 직전 참 비교를 기억했다가 swap 샷에 echo한다
  let lastCmp: { text: string; objectId: number; shotIdx: number } | null = null
  const relabel = (id: number, motions: Motion[]) => {
    const names = [...new Set([...(holderKeys.get(id) ?? [])].map(k => k.slice(k.indexOf(':') + 1)))]
    motions.push({ v: 'label', objectId: id, text: capText(names.join(' · '), 24) })
  }
  const releaseHold = (varKey: string, motions: Motion[]) => {
    const prev = varHeld.get(varKey)
    if (prev === undefined) return
    varHeld.delete(varKey)
    if (holderKeys.get(prev)?.delete(varKey)) relabel(prev, motions)
  }
  const takeHold = (varKey: string, objectId: number, motions: Motion[]) => {
    if (varHeld.get(varKey) === objectId) return
    releaseHold(varKey, motions)
    varHeld.set(varKey, objectId)
    const keys = holderKeys.get(objectId) ?? new Set<string>()
    keys.add(varKey)
    holderKeys.set(objectId, keys)
    relabel(objectId, motions)
  }

  /* ── 격자 — 대표 시각화 2호. 판정은 buildStage, 여기서는 diff를 모션으로 번역한다 ── */
  const gridInfo = new Map(plan.objects.filter(o => o.grid).map(o => [o.objectId, o.grid!]))
  const rowToGrid = new Map<number, { gridId: number; r: number }>() // 안쪽 행 id → 격자 좌표 (DP 갱신 통로)
  const prevGrid = new Map<number, string[][]>()
  const prevCoords = new Map<number, Set<string>>() // 방문 set id → "r,c" 집합
  const prevTrail = new Map<number, string>() // 경로 list id → 직전 points 직렬화

  // 좌표 튜플 = 2칸 int 프림 튜플. 값은 전부 트레이스 스냅에서 온다.
  const coordOf = (v: Value): [number, number] | null => {
    if (v.k !== 'ref') return null
    const s = objects.get(v.id)
    if (s?.type !== 'tuple' || s.items?.length !== 2) return null
    const [a, b] = s.items
    if (a.k !== 'prim' || b.k !== 'prim' || a.t !== 'int' || b.t !== 'int') return null
    return [Number(a.v), Number(b.v)]
  }
  // 이 좌표를 범위 안에 담는, 무대에 올라와 있는 격자
  const gridAt = (rc: [number, number]): number | null => {
    for (const [id, g] of gridInfo) {
      if (!entered.has(id) || exited.has(id)) continue
      if (rc[0] >= 0 && rc[0] < g.rows && rc[1] >= 0 && rc[1] < g.cols) return id
    }
    return null
  }
  const gridTextsOf = (gridId: number): string[][] => {
    const g = gridInfo.get(gridId)!
    const outer = objects.get(gridId)
    return Array.from({ length: g.rows }, (_, r) => {
      const rowVal = outer?.items?.[r]
      // 문자열 행 격자 (["S.#", …]) — repr 따옴표를 벗기고 글자 단위로 칸을 채운다
      if (rowVal?.k === 'prim') {
        const chars = rowVal.v.slice(1, -1)
        return Array.from({ length: g.cols }, (_, c) => chars[c] ?? '')
      }
      const rowSnap = rowVal?.k === 'ref' ? objects.get(rowVal.id) : undefined
      return Array.from({ length: g.cols }, (_, c) => {
        const cell = rowSnap?.items?.[c]
        return cell?.k === 'prim' ? capText(cell.v) : ''
      })
    })
  }
  // 격자 칸 diff → gridCell 모션 (초기 채움 포함)
  const emitGridDiff = (gridId: number, motions: Motion[]) => {
    const g = gridInfo.get(gridId)!
    const texts = gridTextsOf(gridId)
    const prev = prevGrid.get(gridId)
    for (let r = 0; r < g.rows; r++) {
      for (let c = 0; c < g.cols; c++) {
        if (prev && prev[r]?.[c] === texts[r][c]) continue
        motions.push({
          v: 'gridCell', objectId: gridId, r, c,
          text: texts[r][c],
          wall: g.binary && texts[r][c] !== '0',
          ...(prev ? { flash: true } : {}), // 변경만 번쩍인다 — 초기 채움 수백 칸이 다 같이 튀면 소음
        })
      }
    }
    prevGrid.set(gridId, texts)
  }
  // 방문 set diff → gridVisit / gridUnvisit
  const emitVisitDiff = (setId: number, snap: ObjectSnap, motions: Motion[]) => {
    const coords = (snap.items ?? []).map(coordOf)
    if (coords.length === 0 || coords.some(c => c === null)) return
    const gid = gridAt(coords[0] as [number, number])
    if (gid === null) return
    const g = gridInfo.get(gid)!
    if (!coords.every(c => c![0] >= 0 && c![0] < g.rows && c![1] >= 0 && c![1] < g.cols)) return
    const now = new Set(coords.map(c => `${c![0]},${c![1]}`))
    const before = prevCoords.get(setId) ?? new Set<string>()
    for (const key of now) {
      if (before.has(key)) continue
      const [r, c] = key.split(',').map(Number)
      motions.push({ v: 'gridVisit', objectId: gid, r, c })
    }
    for (const key of before) {
      if (now.has(key)) continue
      const [r, c] = key.split(',').map(Number)
      motions.push({ v: 'gridUnvisit', objectId: gid, r, c })
    }
    prevCoords.set(setId, now)
  }
  // 좌표 리스트 → 경로 선
  const emitTrailDiff = (listId: number, snap: ObjectSnap, motions: Motion[]) => {
    const coords = (snap.items ?? []).map(coordOf)
    if (coords.length === 0 || coords.some(c => c === null)) return
    const gid = gridAt(coords[0] as [number, number])
    if (gid === null) return
    const g = gridInfo.get(gid)!
    if (!coords.every(c => c![0] >= 0 && c![0] < g.rows && c![1] >= 0 && c![1] < g.cols)) return
    const points = coords as [number, number][]
    const key = points.map(p => p.join(',')).join(';')
    if (prevTrail.get(listId) === key) return
    prevTrail.set(listId, key)
    motions.push({ v: 'gridTrail', objectId: gid, points })
  }

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
    // 격자·오버레이도 정산한다 — 빨리감기 뒤에도 격자는 진실을 보여야 한다
    for (const gridId of gridInfo.keys()) {
      if (entered.has(gridId) && !exited.has(gridId)) emitGridDiff(gridId, motions)
    }
    for (const [id, obj] of objects) {
      if (!castObjects.has(id) || gridInfo.has(id)) continue
      if (obj.type === 'set') emitVisitDiff(id, obj, motions)
      else if (obj.type === 'list') emitTrailDiff(id, obj, motions)
    }
    for (const [id, obj] of objects) {
      if (!castObjects.has(id) || gridInfo.has(id)) continue
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
      caption: `남은 ${p.count}회 빨리감기`,
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
    // 배지는 카운트업만 — seen(헤더 방문 수)과 총계(구간 최소 방문 수)는 단위가 달라
    // "5회차 / 총 4회" 같은 모순을 만들었다. 거짓말할 수 있는 숫자는 화면에 올리지 않는다.
    const inLoop = loopSpans.find(l => e.seq >= l.from && e.seq <= l.to)
    if (inLoop && e.kind === 'line' && e.observedAtLine === inLoop.headerLine) {
      inLoop.seen += 1
      motions.push({ v: 'loop', text: `반복 ${inLoop.seen}회차` })
      badgeOn = true
    } else if (!inLoop && badgeOn) {
      motions.push({ v: 'loopEnd' })
      badgeOn = false
    }

    if (code && e.kind === 'line') {
      const cmp = detectCompare(srcLines[e.observedAtLine - 1] ?? '', e.frameId, locals, objects)
      if (cmp) {
        motions.push(cmp)
        const cell = cmp.v === 'compare' ? cmp.targets.find(t => t.kind === 'cell') : undefined
        if (cell && cmp.v === 'compare' && cmp.text.endsWith('참'))
          lastCmp = { text: cmp.text, objectId: cell.objectId, shotIdx: shots.length }
      }
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
          releaseHold(key, motions)
        }
        frameVars.delete(e.frameId)
      } else {
        // 실행의 마지막 — 살아있는 변수의 최종값을 정산한다. 압축·접힘을 지나며
        // 화면이 낡은 값을 들고 있어도, 마지막 프레임만은 반드시 진실이어야 한다.
        for (const [key, v] of locals) {
          if (v.k !== 'prim' || !varsSeen.has(key) || !castVars.has(key)) continue
          motions.push({ v: 'setVar', varKey: key, text: shortText(v, objects) })
        }
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
      // 격자 본체 — 한 줄 상자 diff 대신 격자 diff
      if (gridInfo.has(d.obj.id)) {
        const gid = d.obj.id
        d.obj.items?.forEach((it, r) => {
          if (it.k === 'ref') rowToGrid.set(it.id, { gridId: gid, r })
        })
        if (!prevGrid.has(gid)) {
          motions.push({ v: 'enterObj', objectId: gid })
          entered.add(gid)
        }
        emitGridDiff(gid, motions)
        continue
      }
      // 격자의 안쪽 행 — 조연이지만 격자 갱신(DP 테이블)의 통로다
      const rowRef = rowToGrid.get(d.obj.id)
      if (rowRef) {
        if (entered.has(rowRef.gridId) && !exited.has(rowRef.gridId)) emitGridDiff(rowRef.gridId, motions)
        continue
      }
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
          // 직전 참 비교가 이 상자를 짚었다면 판단을 행동 위에 다시 올린다 —
          // "왜 바꾸는가"가 교환이 재생되는 동안 화면에 남는다
          if (
            lastCmp &&
            lastCmp.objectId === d.obj.id &&
            shots.length - lastCmp.shotIdx <= 2 &&
            !motions.some(m => m.v === 'compare')
          ) {
            motions.push({
              v: 'compare', text: lastCmp.text,
              targets: [
                { kind: 'cell', objectId: d.obj.id, index: changed[0] },
                { kind: 'cell', objectId: d.obj.id, index: changed[1] },
              ],
            })
            lastCmp = null
          }
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

      // 격자 오버레이 — 좌표 set은 방문 칠, 좌표 list는 경로 선 (상자 뷰와 병행:
      // 자료구조 뷰와 공간 뷰의 대응 자체가 가르침이다)
      if (d.obj.type === 'set') emitVisitDiff(d.obj.id, d.obj, motions)
      else if (d.obj.type === 'list') emitTrailDiff(d.obj.id, d.obj, motions)
    }

    for (const d of e.localsDelta) {
      const varKey = `${e.frameId}:${d.name}`
      if (!castVars.has(varKey)) continue // 함수·클래스에 묶인 이름은 데이터가 아니다
      if (d.op === 'delete') {
        motions.push({ v: 'exitVar', varKey })
        varsSeen.delete(varKey)
        releaseHold(varKey, motions)
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
        takeHold(varKey, d.value.id, motions)
      } else if (d.value?.k === 'ref') {
        // 상자 없는 참조(작은 튜플 등)는 알약 값으로 인라인 — "(1, 1)"
        motions.push({ v: 'setVar', varKey, text: shortText(d.value, objects) })
        releaseHold(varKey, motions)
        // 좌표 튜플이면 격자 위의 커서도 움직인다 — 마지막 대입이 커서를 가진다
        const rc = coordOf(d.value)
        if (rc) {
          const gid = gridAt(rc)
          if (gid !== null) motions.push({ v: 'gridCursor', objectId: gid, r: rc[0], c: rc[1] })
        }
      } else if (d.value) {
        motions.push({ v: 'setVar', varKey, text: shortText(d.value, objects) })
        releaseHold(varKey, motions)
      }
    }

    if (e.stdout) motions.push({ v: 'stdout', text: e.stdout })
    if (motions.length === 0) continue

    const focusObj = motions.find(m => m.v === 'grow' || m.v === 'bind' || m.v === 'enterObj') as
      | { objectId: number }
      | undefined
    const hasCmp = motions.some(m => m.v === 'compare')
    shots.push({
      seq: e.seq,
      motions,
      durationMs: slow ? SLOW_MS : hasCmp ? MED_MS : BASE_MS,
      focus: focusObj ? { kind: 'object', objectId: focusObj.objectId } : { kind: 'frame', frameId: e.frameId },
      caption: captionOf(motions, nameCtx),
    })
  }
  // 트레이스가 압축 구간에서 끝나면 정산 샷으로 마무리한다
  if (pendingLapse) shots.push(flushLapse(pendingLapse))

  return shots
}
