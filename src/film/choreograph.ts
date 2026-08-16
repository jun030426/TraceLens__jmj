import type { TraceEvent, Value, ObjectSnap } from '../trace/types'
import { buildDigest } from '../digest/buildDigest'
import type { Motion, Shot, StagePlan } from './types'

const BASE_MS = 520
const SLOW_MS = 1100
const LAPSE_MS = 900
const FULL_ITERATIONS = 10 // 반복은 10회까지 온전히 보여주고, 그 이후는 압축한다

const shortText = (v: Value, objects: Map<number, ObjectSnap>): string => {
  if (v.k === 'prim') return v.v.length > 10 ? v.v.slice(0, 10) + '…' : v.v
  const o = objects.get(v.id)
  return o ? `${o.type}` : '객체'
}

// 2패스 — 실행 사건을 "무엇이 어떻게 움직이는가"로 번역한다.
export function choreograph(events: TraceEvent[], _plan: StagePlan): Shot[] {
  const digest = buildDigest(events)
  const varsSeen = new Set<string>()
  const objsSeen = new Set<number>()
  const refCount = new Map<number, Set<string>>()
  const objects = new Map<number, ObjectSnap>()
  const prevSize = new Map<number, number>()

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

  const shots: Shot[] = []
  const consumed = new Set<number>()

  for (const e of events) {
    for (const d of e.objectsDelta) {
      if (d.op === 'set' && d.obj) objects.set(d.obj.id, d.obj)
      else if (d.id !== undefined) objects.delete(d.id)
    }

    const inLapse = lapseAt(e.seq)
    if (inLapse) {
      if (consumed.has(inLapse.from)) continue
      consumed.add(inLapse.from)
      const target = [...objects.entries()].sort((a, b) => (b[1].items?.length ?? 0) - (a[1].items?.length ?? 0))[0]
      shots.push({
        seq: e.seq,
        motions: target
          ? [{ v: 'setCell', objectId: target[0], index: Math.max(0, (target[1].items?.length ?? 1) - 1), text: '…' }]
          : [{ v: 'stdout', text: '' }],
        durationMs: LAPSE_MS,
        focus: target ? { kind: 'object', objectId: target[0] } : null,
        timelapse: inLapse.count,
      })
      continue
    }

    const motions: Motion[] = []
    let slow = false

    if (e.kind === 'call') motions.push({ v: 'pushFrame', frameId: e.frameId })
    if (e.kind === 'return') motions.push({ v: 'popFrame', frameId: e.frameId })
    if (e.kind === 'exception') {
      // 예외는 실패가 아니라 콘텐츠 — 흔들고, 무엇이 터졌는지 무대에 적는다
      motions.push({ v: 'shake', frameId: e.frameId })
      motions.push({ v: 'raise', frameId: e.frameId, text: e.error ?? '예외 발생' })
      slow = true
    }

    for (const d of e.objectsDelta) {
      if (d.op !== 'set' || !d.obj) continue
      const size = (d.obj.items?.length ?? 0) + (d.obj.entries?.length ?? 0)
      const cellTextAt = (idx: number): string | null => {
        const item = d.obj?.items?.[idx]
        if (item) return shortText(item, objects)
        const entry = d.obj?.entries?.[idx]
        if (entry) return `${entry[0]}: ${shortText(entry[1], objects)}`
        return null
      }
      if (!objsSeen.has(d.obj.id)) {
        objsSeen.add(d.obj.id)
        motions.push({ v: 'enterObj', objectId: d.obj.id })
        // 리터럴로 이미 원소를 가진 채 태어난 객체 — 그 칸들도 채워야 한다.
        // 안 그러면 상자만 나타나고 안이 영원히 빈 채로 남는다.
        for (let i = 0; i < size; i++) {
          motions.push({ v: 'grow', objectId: d.obj.id, index: i, text: cellTextAt(i) ?? '' })
        }
      } else {
        const before = prevSize.get(d.obj.id) ?? 0
        // dict·set도 칸이 차오르는 순서를 보여준다 — 리스트는 값만, dict는 키: 값
        if (size > before) {
          for (let i = before; i < size; i++) {
            motions.push({ v: 'grow', objectId: d.obj.id, index: i, text: cellTextAt(i) ?? '' })
          }
        } else if (size === before && size > 0) {
          const idx = Math.max(0, size - 1)
          const text = cellTextAt(idx)
          if (text !== null) motions.push({ v: 'setCell', objectId: d.obj.id, index: idx, text })
        }
      }
      prevSize.set(d.obj.id, size)
    }

    for (const d of e.localsDelta) {
      const varKey = `${e.frameId}:${d.name}`
      if (d.op === 'delete') {
        motions.push({ v: 'exitVar', varKey })
        varsSeen.delete(varKey)
        continue
      }
      if (!varsSeen.has(varKey)) {
        varsSeen.add(varKey)
        motions.push({ v: 'enterVar', varKey })
      }
      if (d.value?.k === 'ref') {
        const holders = refCount.get(d.value.id) ?? new Set<string>()
        holders.add(varKey)
        refCount.set(d.value.id, holders)
        const alias = holders.size > 1
        if (alias) slow = true
        motions.push({ v: 'bind', varKey, objectId: d.value.id, alias })
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

  return shots
}
