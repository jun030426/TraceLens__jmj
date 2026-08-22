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
    return `${head}두 값이 자리를 바꿉니다`
  }
  const tr = find('travel')
  if (tr) {
    const end = (t: CompareTarget) =>
      t.kind === 'cell' ? names.objName(t.objectId) : names.varName(t.varKey)
    return `${tr.text} 이동: ${end(tr.from)} → ${end(tr.to)}`
  }
  const cmp = find('compare')
  if (cmp) return `비교: ${cmp.text}`
  const push = find('pushFrame')
  if (push) {
    const f = names.frameFunc(push.frameId)
    return f === '<module>' ? '실행 시작' : `${f} 호출 — 새 작업 공간이 열립니다`
  }
  // 값에 조사를 붙이지 않는다 — 을/를은 값의 마지막 소리에 달리는데 값은 숫자·문자열·상자
  // 무엇이든 될 수 있다. 콜론 형식은 기존 자막들과 같은 어법이다 ("비교: …", "출력: …")
  const rv = find('returnValue')
  if (rv) return `${names.frameFunc(rv.frameId)}가 돌려준 값: ${rv.text}`
  const pop = find('popFrame')
  if (pop) {
    const f = names.frameFunc(pop.frameId)
    if (f === '<module>') return find('sortedSweep') ? '실행 종료 — 정렬 완성!' : '실행 종료 — 최종 상태입니다'
    return `${f} 종료 — 작업 공간이 닫힙니다`
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
  // 위치는 번호로 부르지 않는다 — 화면이 어느 칸인지 짚어주므로 자막은 무엇이 일어났는지만
  // 말한다. 끝(맨 앞)은 이름이 있으니 부르고, 중간은 침묵한다 (서수 번역은 0/1 혼동을 만든다)
  const shift = find('shiftLeft')
  if (shift) {
    const who = shift.index === 0 ? '맨 앞 값' : '한 값'
    return `${names.objName(shift.objectId)} ${who}이 빠지고 뒤가 한 칸 당겨집니다`
  }
  const shrink = find('shrink')
  if (shrink) return `${names.objName(shrink.objectId)} 칸 하나가 빠집니다`
  const cells = all('setCell')
  if (cells.length === 1) return `${names.objName(cells[0].objectId)} 한 칸 = ${cells[0].text}`
  if (cells.length > 1) return `${names.objName(cells[0].objectId)} ${cells.length}칸 갱신`
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
  if (find('loopEnd')) return '반복 구간이 끝났습니다'
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

// 한 칸 삭제 + 당겨짐 판정 — next가 prev에서 정확히 원소 하나(k)를 뺀 모양일 때 그 k.
// 꼬리 삭제(k === next.length)는 아무도 움직이지 않으므로 시프트가 아니다 (기존 shrink가 정직).
// 값 중복으로 k가 모호하면 최소 k — 값이 같아 어느 쪽이든 화면은 거짓말하지 않는다.
const shiftIndexOf = (prev: string[], next: string[]): number | null => {
  if (next.length !== prev.length - 1) return null
  let m = 0 // head가 일치하는 한계 — 이보다 큰 k는 불가능
  while (m < next.length && next[m] === prev[m]) m++
  if (m === next.length) return null
  let t = next.length // +1 정렬이 끝까지 성립하기 시작하는 최소 지점
  while (t > 0 && next[t - 1] === prev[t]) t--
  return t <= m ? t : null
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

/** 그 줄이 실제로 판단하는 식 — if/elif/while의 조건, 대입이면 우변. 저울은 이 전체를
    덮을 때만 내려온다 (조건의 한 조각에 도장을 찍으면 화면이 판단과 반대로 움직인다). */
const judgedExpr = (line: string): string => {
  const t = stripNoise(line).trim()
  const c = /^(?:el)?if\s+(.*):$/.exec(t) ?? /^while\s+(.*):$/.exec(t)
  if (c) return c[1].trim()
  const a = /^[A-Za-z_]\w*(?:\[[^\]]+\])?\s*=\s*(.*)$/.exec(t)
  if (a) return a[1].trim()
  return t
}
const squash = (t: string) => t.replace(/\s+/g, ' ').trim()

function detectCompare(
  rawLine: string,
  frameId: number,
  locals: Map<string, Value>,
  objects: Map<number, ObjectSnap>,
): Motion | null {
  const m = stripNoise(rawLine).match(CMP_RE)
  if (!m) return null
  // 접지에 성공한 것과 그 접지가 판단 전체를 덮는 것은 다른 문제다. `and`로 이어지거나
  // 체인된 조건(0 <= nr < 4)에서 첫 절만 보고 참/거짓을 찍으면, 참이라 해놓고 몸통이
  // 안 도는 샷이 나온다 (실측 BFS: 32번 중 21번). 전체를 못 덮으면 침묵한다.
  if (squash(m[0]) !== squash(judgedExpr(rawLine))) return null
  const a = resolveOperand(m[1], frameId, locals, objects)
  const b = resolveOperand(m[3], frameId, locals, objects)
  if (!a || !b) return null
  const targets = [a.target, b.target].filter((t): t is CompareTarget => !!t)
  if (targets.length === 0) return null
  let verdict: boolean | undefined
  if (a.num !== null && b.num !== null && Number.isFinite(a.num) && Number.isFinite(b.num)) {
    const op = m[2]
    verdict =
      op === '<' ? a.num < b.num
      : op === '>' ? a.num > b.num
      : op === '<=' ? a.num <= b.num
      : op === '>=' ? a.num >= b.num
      : op === '==' ? a.num === b.num
      : a.num !== b.num
  }
  const tail = verdict === undefined ? '' : verdict ? ' → 참' : ' → 거짓'
  return {
    v: 'compare',
    text: `${a.text} ${m[2]} ${b.text}${tail}`,
    targets,
    a: a.text, op: m[2], b: b.text,
    ...(verdict === undefined ? {} : { verdict }),
  }
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
  // 정렬의 증거는 재배열이다 — 끝이 오름차순인 것은 결과일 뿐 증거가 아니다.
  // 상태가 올 때마다 원소 다중집합 서명을 만들어 ① 서명이 바뀌면 증거를 지우고(원소가 갈리면
  // 이전의 순서는 지금 구성에 대한 증거가 아니다) ② 오름차순이 아닌 상태를 보면 증거를 세운다.
  // 같은 다중집합에서 오름차순 배열은 유일하므로 "다른 순서" ⟺ "오름차순이 아님"이고,
  // 그래서 상태 이력을 들고 있을 필요 없이 O(1) 메모리로 판정된다.
  const bagSig = new Map<number, string>() // objectId → 직전 원소 다중집합 서명
  const shuffled = new Map<number, boolean>() // objectId → 지금 구성으로 흐트러졌던 적이 있다
  const ascending = (texts: string[]) => {
    const nums = texts.map(Number)
    return nums.every(v => Number.isFinite(v)) && nums.every((v, k) => k === 0 || nums[k - 1] <= v)
  }
  const noteOrder = (id: number, texts: string[]) => {
    const sig = [...texts].sort().join('\u0000')
    if (bagSig.get(id) !== sig) {
      bagSig.set(id, sig)
      shuffled.set(id, false)
    }
    if (!ascending(texts)) shuffled.set(id, true)
  }
  // 화면이 전부를 보여주지 못하는 상자 — 잘림(shown/total)이거나 안을 볼 수 없음(total 없음).
  // 상태가 바뀔 때만 모션으로 알린다 (label 모션과 같은 패턴이라 스크럽에 안전)
  const prevPartial = new Map<number, string>()
  const emitPartial = (snap: ObjectSnap, motions: Motion[]) => {
    const shown = (snap.items?.length ?? 0) + (snap.entries?.length ?? 0)
    const opaque = !!snap.unsupported || (!!snap.truncated && shown === 0)
    const cut = !!snap.truncated && shown > 0
    const key = opaque ? 'opaque' : cut ? `${shown}/${snap.n ?? ''}` : ''
    if (prevPartial.get(snap.id) === key) return
    prevPartial.set(snap.id, key)
    if (opaque) motions.push({ v: 'partial', objectId: snap.id, shown: 0 })
    else if (cut) motions.push({ v: 'partial', objectId: snap.id, shown, total: snap.n })
    else motions.push({ v: 'partial', objectId: snap.id, shown, total: shown }) // 다시 온전해졌다 — 꼬리표 해제
  }

  // 캐스팅은 buildStage가 판정했다 — 여기서는 명단에 있는 것만 무대에 올린다.
  // objects·locals 맵은 전체를 계속 추적한다 (요약 텍스트·compare 접지에 필요).
  const castObjects = new Set(plan.objects.map(o => o.objectId))
  const castVars = new Set(plan.variables.map(v => v.varKey))
  const entered = new Set<number>() // enterObj까지 마친 상자
  const exited = new Set<number>()
  const heldOnce = new Set<number>() // 한 번이라도 이름이 쥐었던 상자 — 보유 기반 퇴장의 대상

  // 상자 이름표 — 끈을 따라가지 않아도 어느 상자가 maze인지 보이게, 쥔 변수명을 상자에 건다.
  // 보유가 바뀔 때마다(재대입·별칭·반환) 라벨을 다시 쓴다. 별칭이면 "a · b".
  const holderKeys = new Map<number, Set<string>>() // castObj → 쥔 varKey들
  const varHeld = new Map<string, number>() // castVar varKey → objectId

  // 자막용 이름 — 값·이름은 전부 계획(캐스팅)과 보유 관계에서 온다
  const varNameMap = new Map(plan.variables.map(v => [v.varKey, v.name]))
  const frameFuncMap = new Map(plan.frames.map(f => [f.frameId, f.func]))

  // ── 이름이 겹치면 카드가 든다 ──
  // 한 이름이 여러 살아있는 프레임에 동시에 있으면(=재귀), 그 이름을 가진 **가장 깊은**
  // 프레임의 것만 알약으로 남고 나머지는 각자의 프레임 카드가 든다. "한 값은 화면에
  // 한 번만"의 두 번째 사례다 (첫 사례: 상자를 쥔 변수는 상자 이름표가 대신 말한다).
  // 판정은 트레이스의 사실이므로 여기(의미층)가 소유하고, 구성·렌더는 받아 쓴다 —
  // 두 층이 같은 판정을 따로 하면 조용히 어긋난다.
  // 알약이 되는 것만 대상이다: prim 값을 쥔 변수 (ref는 이미 상자 이름표가 든다).
  const frameDepth = new Map(plan.frames.map(f => [f.frameId, f.depth]))
  const prevFold = new Map<number, string>() // frameId → 직전 방출 서명 (바뀔 때만 방출)
  const emitFolds = (motions: Motion[]) => {
    const byName = new Map<string, number[]>() // 이름 → 그 이름을 가진 살아있는 프레임들
    for (const [fid, keys] of frameVars)
      for (const k of keys) {
        if (locals.get(k)?.k !== 'prim') continue
        const name = k.slice(k.indexOf(':') + 1)
        byName.set(name, [...(byName.get(name) ?? []), fid])
      }
    const folded = new Map<number, Set<string>>()
    for (const [name, fids] of byName) {
      if (fids.length < 2) continue
      const deepest = fids.reduce((a, b) => ((frameDepth.get(b) ?? 0) > (frameDepth.get(a) ?? 0) ? b : a))
      for (const fid of fids) if (fid !== deepest) (folded.get(fid) ?? folded.set(fid, new Set()).get(fid)!).add(`${fid}:${name}`)
    }
    for (const fid of frameVars.keys()) {
      // 순서는 알파벳이 아니라 **등장 순**이다 — 매개변수는 서명 순으로 들어오므로
      // 카드가 폭에 밀려 하나만 남길 때 첫 매개변수가 남는다 (알파벳 순은 acc를 남기고 n을 접었다)
      const foldedHere = folded.get(fid)
      const varKeys = [...(frameVars.get(fid) ?? [])].filter(k => foldedHere?.has(k))
      const texts = varKeys.map(k => {
        const v = locals.get(k)!
        return `${varNameMap.get(k) ?? k.slice(k.indexOf(':') + 1)} = ${shortText(v, objects)}`
      })
      const sig = texts.join(' · ')
      if ((prevFold.get(fid) ?? '') === sig) continue
      prevFold.set(fid, sig)
      motions.push({ v: 'foldVars', frameId: fid, varKeys, texts })
    }
  }
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
  let lastCmp: { text: string; a?: string; op?: string; b?: string; objectId: number; shotIdx: number } | null = null

  // 인덱스 포인터 — 소스에 `NAME[IDX]`로 쓰인 변수는 "그 배열의 위치"다.
  // 알약(값 표시)이 아니라 배열 아래 화살표로 살아야 시선이 조인을 안 해도 된다.
  // 판정은 정적·결정적: 코드에 실제로 그렇게 쓰였을 때만 (지어내지 않는다)
  const pointerOf = new Map<string, number>() // varKey → objectId
  if (code) {
    const subRe = /([A-Za-z_]\w*)\s*\[\s*([A-Za-z_]\w*)/g
    let sm: RegExpExecArray | null
    while ((sm = subRe.exec(code))) {
      const arrName = sm[1]
      const idxName = sm[2]
      for (const v of plan.variables) {
        if (v.name !== idxName || pointerOf.has(v.varKey)) continue
        const arrKey = `${v.frameId}:${arrName}`
        const obj = plan.objects.find(o => !o.grid && o.referencedBy.includes(arrKey))
        if (obj) pointerOf.set(v.varKey, obj.objectId)
      }
    }
  }
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
    heldOnce.add(objectId)
    if (exited.has(objectId)) {
      // 잊혔던 상자를 다시 이름이 쥐었다 (중첩 참조에서 꺼내기 등) — 부활
      exited.delete(objectId)
      motions.push({ v: 'enterObj', objectId })
    }
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

  // 반복 배지 — **사용자 소스의 반복문**에 접지한다. 다이제스트의 압축 스팬은 "보여주는
  // 방식"이지 반복문의 생애가 아니어서, 그것을 반복문으로 착각하면 4바퀴 도는 루프가
  // 3·4·5회차로 읽히고(접힘이 3회차 방문부터라 카운트를 2에서 출발시키는 보정이 들어갔다)
  // 정렬 한복판에서 "반복 구간이 끝났습니다"가 뜬다 (실측). 반복문의 모양은 값·순서가
  // 아니라 코드의 어휘이므로 소스에서 읽어도 값의 신뢰성 축은 다치지 않는다.
  type SrcLoop = { header: number; end: number; name?: string }
  const parseLoops = (lines: string[]): SrcLoop[] => {
    const out: SrcLoop[] = []
    const indentOf = (t: string) => t.length - t.trimStart().length
    const skip = (t: string) => t.trim() === '' || t.trim().startsWith('#')
    lines.forEach((line, i) => {
      const m = /^(\s*)(for|while)\b(.*):\s*(#.*)?$/.exec(line)
      if (!m) return
      const ind = m[1].length
      let end = 0
      for (let k = i + 1; k < lines.length; k++) {
        if (skip(lines[k])) continue
        if (indentOf(lines[k]) <= ind) break
        end = k + 1
      }
      if (!end) return // 몸통을 못 찾았다 (한 줄 루프 등) — 지어내지 않고 침묵
      // 튜플 언패킹(`for dr, dc in ...`)까지 읽는다 — BFS처럼 바깥이 `while`(이름 없음)이면
      // 둘 다 숫자만 남아 4 → 1 → 2가 근거 없이 널뛰는 것으로 보인다 (실측)
      const t =
        m[2] === 'for' ? /^\s*([A-Za-z_]\w*(?:\s*,\s*[A-Za-z_]\w*)*)\s+in\s/.exec(m[3]) : null
      out.push({ header: i + 1, end, ...(t ? { name: t[1].replace(/\s*,\s*/g, ', ') } : {}) })
    })
    return out
  }
  const srcLoops = code ? parseLoops(srcLines) : []
  const parentFrame = new Map(plan.frames.map(f => [f.frameId, f.parentFrameId]))
  const loopRun = new Map<string, { n: number; armed: boolean }>() // `${frameId}:${header}`
  const loopKey = (fid: number, header: number) => `${fid}:${header}`
  /** 이 이벤트 시점의 배지 문구. 회차는 **몸통이 실행된 횟수**다 — 헤더 줄을 밟으면 장전하고
      몸통 줄에 들어설 때 오른다 (헤더 방문 수를 세면 마지막 소진 검사까지 세어 4바퀴가 5가 된다).
      범위 밖으로 나가면 그 반복문은 끝났고 카운터는 리셋된다 (중첩에서 안쪽이 다시 1부터).
      반복 안에서 함수를 부르면 호출 스택을 거슬러 찾는다 — 현재 프레임만 보면
      `for x in xs: helper(x)`가 회차마다 배지 켜짐/꺼짐을 반복한다. */
  const badgeAt = (e: TraceEvent): string | null => {
    if (srcLoops.length === 0) return null
    if (e.kind === 'return' && e.parentFrameId !== null)
      for (const l of srcLoops) loopRun.delete(loopKey(e.frameId, l.header))
    if (e.kind === 'line') {
      const line = e.observedAtLine
      for (const l of srcLoops) {
        const key = loopKey(e.frameId, l.header)
        if (line < l.header || line > l.end) {
          loopRun.delete(key)
          continue
        }
        const st = loopRun.get(key) ?? { n: 0, armed: false }
        if (line === l.header) st.armed = true
        else if (st.armed) {
          st.n += 1
          st.armed = false
        }
        loopRun.set(key, st)
      }
    }
    let fid: number | null = e.frameId
    const seen = new Set<number>()
    while (fid !== null && !seen.has(fid)) {
      seen.add(fid)
      let best: SrcLoop | null = null
      for (const l of srcLoops) {
        const st = loopRun.get(loopKey(fid, l.header))
        if (!st || st.n === 0) continue
        if (!best || l.header > best.header) best = l
      }
      if (best) return `${best.name ? best.name + ' ' : ''}반복 ${loopRun.get(loopKey(fid, best.header))!.n}회차`
      fid = parentFrame.get(fid) ?? null
    }
    return null
  }
  let prevBadge: string | null | undefined = null

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
      emitPartial(obj, motions) // 빨리감기 뒤에도 "전부가 아니다"는 사실은 정산돼야 한다
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
      noteOrder(id, texts)
    }
    for (const id of [...prevTexts.keys()]) {
      if (!objects.has(id)) {
        motions.push({ v: 'exitObj', objectId: id })
        prevTexts.delete(id)
      }
    }
    // 변수 값도 정산한다 — 루프 변수가 낡은 값으로 남으면 그것도 거짓말이다
    for (const [key, v] of locals) {
      if (v.k !== 'prim' || !castVars.has(key)) continue
      if (!varsSeen.has(key)) {
        // 압축 구간 안에서 태어난 변수 — 등장을 정산하지 않으면 빈 알약이 남는다
        varsSeen.add(key)
        const fid = Number(key.slice(0, key.indexOf(':')))
        const set = frameVars.get(fid) ?? new Set<string>()
        set.add(key)
        frameVars.set(fid, set)
        motions.push({ v: 'enterVar', varKey: key })
      }
      motions.push({ v: 'setVar', varKey: key, text: shortText(v, objects) })
    }
    emitFolds(motions)
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

    // 배지 상태는 압축 구간에서도 따라간다 — 세지 않으면 빨리감기 뒤 회차가 건너뛴다
    const badge = badgeAt(e)
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
      prevBadge = undefined // 빨리감기 문구가 배지를 덮었다 — 다음 상태를 반드시 다시 쓴다
    }

    const motions: Motion[] = []
    let slow = false

    // "반복문이 돌고 있다"의 상시 표시 — 배지는 카운트업만 한다. 단위가 다른 총계는 달지
    // 않는다 ("5회차 / 총 4회" 같은 모순 금지). 바뀔 때만 방출하므로 같은 회차가 여러 샷에
    // 걸쳐도 배지는 가만히 있는다
    if (badge !== prevBadge) {
      motions.push(badge ? { v: 'loop', text: badge } : { v: 'loopEnd' })
      prevBadge = badge
    }

    if (code && e.kind === 'line') {
      const cmp = detectCompare(srcLines[e.observedAtLine - 1] ?? '', e.frameId, locals, objects)
      if (cmp) {
        motions.push(cmp)
        const cell = cmp.v === 'compare' ? cmp.targets.find(t => t.kind === 'cell') : undefined
        if (cell && cmp.v === 'compare' && cmp.verdict === true)
          lastCmp = { text: cmp.text, a: cmp.a, op: cmp.op, b: cmp.b, objectId: cell.objectId, shotIdx: shots.length }
      }
    }

    if (e.kind === 'call') motions.push({ v: 'pushFrame', frameId: e.frameId })
    if (e.kind === 'return') {
      motions.push({ v: 'popFrame', frameId: e.frameId })
      // 값이 카드에서 카드로 내려간다 — 사실은 트레이서의 returned이고 여기서는 옮기기만 한다.
      // 예외 unwind와 None은 트레이서가 이미 걸렀으므로 여기 도착한 것은 전부 진짜 반환이다
      if (e.returned && e.parentFrameId !== null)
        motions.push({
          v: 'returnValue', frameId: e.frameId, toFrameId: e.parentFrameId,
          text: shortText(e.returned, objects),
        })
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
        // 정렬 완성의 마침표 — 실제로 오름차순으로 끝난 숫자 리스트에만 스윕을 준다
        for (const [id, texts] of prevTexts) {
          if (!entered.has(id) || exited.has(id) || gridInfo.has(id)) continue
          // 잘린 리스트는 제외 — 보이는 20칸이 오름차순이라고 500개가 정렬됐다고 말할 수 없다.
          // 판정은 지금 스냅샷에서 직접 읽는다 (잘렸다가 줄어들면 그때는 다시 전부를 보는 것이다)
          if (objects.get(id)?.truncated) continue
          if (texts.length < 3) continue
          // 지금 원소 구성으로 흐트러진 적이 없으면 이 리스트는 정렬된 것이 아니라 원래
          // 그랬거나 그렇게 만들어진 것이다 — 하지 않은 일을 선언하지 않는다
          if (!shuffled.get(id)) continue
          if (ascending(texts)) motions.push({ v: 'sortedSweep', objectId: id })
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
      emitPartial(d.obj, motions)
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
              a: lastCmp.a, op: lastCmp.op, b: lastCmp.b, verdict: true,
            })
            lastCmp = null
          }
          slow = true
        } else {
          for (const i of changed) motions.push({ v: 'setCell', objectId: d.obj.id, index: i, text: texts[i] })
        }
      } else if (size < prev.length) {
        const k = shiftIndexOf(prev, texts)
        if (k !== null) {
          // 한 칸이 빠지고 뒤가 당겨졌다 — 칸별 텍스트 교체가 아니라 토큰들이 미끄러진다.
          // 값이 떠나고 줄이 닫히는 이야기 비트이므로 샷도 느리게 잡는다
          motions.push({ v: 'shiftLeft', objectId: d.obj.id, index: k, texts: texts.slice(k) })
          slow = true
        } else {
          for (let i = 0; i < size; i++)
            if (texts[i] !== prev[i]) motions.push({ v: 'setCell', objectId: d.obj.id, index: i, text: texts[i] })
          for (let i = size; i < prev.length; i++) motions.push({ v: 'shrink', objectId: d.obj.id, index: i })
        }
      }
      prevTexts.set(d.obj.id, texts)
      noteOrder(d.obj.id, texts)

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
        const ptrObj = pointerOf.get(varKey)
        if (ptrObj !== undefined) motions.push({ v: 'pointer', varKey, objectId: ptrObj })
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

    // 잊혀진 상자는 내려간다 — 어떤 이름도 쥐지 않으면 학습자의 세계에서 죽은 것이다.
    // (트레이서는 객체 삭제를 보내지 않고 plan의 life.to는 '마지막 수정'일 뿐이라,
    //  보유(holder)가 유일하게 정직한 죽음 신호다)
    for (const id of heldOnce) {
      if (!entered.has(id) || exited.has(id)) continue
      if ((holderKeys.get(id)?.size ?? 0) === 0) {
        motions.push({ v: 'exitObj', objectId: id })
        exited.add(id)
      }
    }

    // ── 값의 이동 — 출발지를 알 수 있으면 값은 순간이동하지 않고 날아간다.
    // 비교 접지와 같은 보수성: 해석이 안 되면 침묵한다. 샷당 여행은 1회, swap과는 겹치지 않는다.
    travel: if (!motions.some(m => m.v === 'swap')) {
      // ① 칸이 빠지고 같은 샷에 변수가 값을 받는다 (pop 계열) — 라인 접지 없이도 확실한 짝.
      // 시프트가 있으면 떠난 자리는 마지막 칸이 아니라 빠진 칸(index)이다
      const goneM = (motions.find(m => m.v === 'shiftLeft') ?? motions.find(m => m.v === 'shrink')) as
        | { objectId: number; index: number }
        | undefined
      const recvM = motions.find(m => m.v === 'setVar' || m.v === 'bind') as
        | { varKey: string; text?: string }
        | undefined
      if (goneM && recvM && !gridInfo.has(goneM.objectId)) {
        motions.push({
          v: 'travel',
          from: { kind: 'cell', objectId: goneM.objectId, index: goneM.index },
          to: { kind: 'var', varKey: recvM.varKey },
          text: recvM.text ?? '',
        })
        break travel
      }
      if (!code || e.kind !== 'line' || !e.causedByLine) break travel
      const src = stripNoise(srcLines[e.causedByLine - 1] ?? '').trim()
      // ② 읽기: x = NAME[i] — 칸의 값이 알약으로
      const rd = src.match(/^([A-Za-z_]\w*)\s*=\s*([A-Za-z_]\w*\[[^\]]+\])$/)
      if (rd) {
        const setM = motions.find(m => m.v === 'setVar' && m.varKey === `${e.frameId}:${rd[1]}`) as
          | { varKey: string; text: string }
          | undefined
        const op = resolveOperand(rd[2], e.frameId, locals, objects)
        if (setM && op?.target?.kind === 'cell' && capText(op.text) === setM.text && !gridInfo.has(op.target.objectId)) {
          motions.push({ v: 'travel', from: op.target, to: { kind: 'var', varKey: setM.varKey }, text: setM.text })
          break travel
        }
      }
      // ③ 쓰기: NAME[i] = y — 알약의 값이 칸으로
      const wr = src.match(/^([A-Za-z_]\w*\[[^\]]+\])\s*=\s*([A-Za-z_]\w*)$/)
      if (wr) {
        const from = resolveOperand(wr[2], e.frameId, locals, objects)
        const dst = resolveOperand(wr[1], e.frameId, locals, objects) // 델타 반영 후 = 새 칸 값
        if (
          from?.target?.kind === 'var' && dst?.target?.kind === 'cell' &&
          from.text === dst.text && !gridInfo.has(dst.target.objectId) &&
          motions.some(m => (m.v === 'setCell' || m.v === 'grow') &&
            m.objectId === (dst.target as { objectId: number }).objectId &&
            m.index === (dst.target as { index: number }).index)
        ) {
          motions.push({ v: 'travel', from: from.target, to: dst.target, text: capText(from.text) })
          break travel
        }
      }
      // ④ 붙이기: NAME.append(y) — 알약의 값이 새 칸으로
      const ap = src.match(/^([A-Za-z_]\w*)\.append\(\s*([A-Za-z_]\w*)\s*\)$/)
      if (ap) {
        const from = resolveOperand(ap[2], e.frameId, locals, objects)
        const growM = motions.find(m => m.v === 'grow') as { objectId: number; index: number; text: string } | undefined
        const ref = locals.get(`${e.frameId}:${ap[1]}`)
        if (
          from?.target?.kind === 'var' && growM && ref?.k === 'ref' && ref.id === growM.objectId &&
          capText(from.text) === growM.text && !gridInfo.has(growM.objectId)
        ) {
          motions.push({
            v: 'travel', from: from.target,
            to: { kind: 'cell', objectId: growM.objectId, index: growM.index },
            text: growM.text,
          })
        }
      }
    }

    if (e.stdout) motions.push({ v: 'stdout', text: e.stdout })
    if (motions.length === 0) continue
    // 카드가 드는 값은 마지막에 정산한다 — 이 이벤트의 호출·반환·대입이 모두 반영된 뒤여야
    // 겹침 판정이 맞다. 샷이 되는 이벤트에서만 방출하므로 접힘 표시만 있는 빈 샷은 생기지 않는다
    emitFolds(motions)

    const focusObj = motions.find(m => m.v === 'grow' || m.v === 'bind' || m.v === 'enterObj') as
      | { objectId: number }
      | undefined
    // 판단과 반환은 읽을 시간을 받는다 — 칩에 적힌 값이 읽히기 전에 사라지면 없는 것과 같다
    const hasCmp = motions.some(m => m.v === 'compare' || m.v === 'returnValue')
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
