import type { ObjectSnap, TraceEvent } from '../trace/types'
import { buildSnapshots } from '../trace/snapshots'
import type { CastFrame, CastObject, CastVariable, StagePlan } from './types'

const varKeyOf = (frameId: number, name: string) => `${frameId}:${name}`

// 데이터가 아닌 것들 — 여기에만 묶인 변수는 알약을 받지 않고, 이 객체는 상자를 받지 않는다
const CALLABLE_TYPES = new Set(['function', 'builtin_function_or_method', 'method', 'type', 'module'])
// 이 크기 이하의 전원-프림 튜플은 상자 대신 알약 값 "(1, 1)"로 인라인 표시된다
const INLINE_TUPLE_MAX = 3

// 1패스 — 등장인물 명단과 수명. 원칙: **변수가 쥔 것만 상자를 받는다.**
// 컨테이너 안에만 사는 조연(큐 속 튜플, maze 행…)은 부모 칸의 요약 텍스트가 전부다.
// 상자의 수명은 "마지막으로 만져진 때"가 아니라 "변수가 쥐고 있는 동안"이다 —
// 놓인 상자는 무대에서 내려가므로 슬롯을 물려받은 후임과 겹치지 않는다.
export function buildStage(events: TraceEvent[]): StagePlan {
  if (events.length === 0) {
    return { objects: [], variables: [], frames: [], slotCount: 0, maxStackDepth: 0, maxListLength: 0, leadObjectId: null }
  }

  const objAcc = new Map<number, { type: string; from: number; to: number; maxItems: number; changes: number; refs: Set<string> }>()
  const varAcc = new Map<string, { frameId: number; name: string; from: number; to: number; holdsRef: boolean; dataish: boolean }>()
  const snapOf = new Map<number, ObjectSnap>() // 최신 스냅 — 인라인·callable 판정용

  const holdersOf = new Map<number, Set<string>>() // objectId → 지금 쥐고 있는 변수들
  const boundTo = new Map<string, number>() // varKey → objectId
  const frameKeys = new Map<number, Set<string>>()
  const everHeld = new Set<number>()

  const unbind = (key: string) => {
    const id = boundTo.get(key)
    if (id !== undefined) {
      holdersOf.get(id)?.delete(key)
      boundTo.delete(key)
    }
  }

  for (const e of events) {
    for (const d of e.objectsDelta) {
      if (d.op !== 'set' || !d.obj) continue
      snapOf.set(d.obj.id, d.obj)
      const size = (d.obj.items?.length ?? 0) + (d.obj.entries?.length ?? 0)
      const cur = objAcc.get(d.obj.id)
      if (cur) {
        cur.to = e.seq
        cur.maxItems = Math.max(cur.maxItems, size)
        cur.changes += 1
      } else {
        objAcc.set(d.obj.id, { type: d.obj.type, from: e.seq, to: e.seq, maxItems: size, changes: 1, refs: new Set() })
      }
    }

    for (const d of e.localsDelta) {
      const key = varKeyOf(e.frameId, d.name)
      const cur = varAcc.get(key)
      if (cur) cur.to = e.seq
      else varAcc.set(key, { frameId: e.frameId, name: d.name, from: e.seq, to: e.seq, holdsRef: false, dataish: false })
      const acc = varAcc.get(key)!

      if (d.op === 'delete') {
        unbind(key)
        continue
      }
      if (d.value?.k === 'ref') {
        acc.holdsRef = true
        const snap = snapOf.get(d.value.id)
        const callable = !!snap?.unsupported && CALLABLE_TYPES.has(snap.type)
        if (!callable) acc.dataish = true
        unbind(key)
        boundTo.set(key, d.value.id)
        const holders = holdersOf.get(d.value.id) ?? new Set<string>()
        holders.add(key)
        holdersOf.set(d.value.id, holders)
        everHeld.add(d.value.id)
        const keys = frameKeys.get(e.frameId) ?? new Set<string>()
        keys.add(key)
        frameKeys.set(e.frameId, keys)
        const o = objAcc.get(d.value.id)
        if (o) o.refs.add(key)
      } else if (d.value) {
        acc.dataish = true
        unbind(key)
      }
    }

    // 프레임이 반환되면 그 지역 변수들의 손이 풀린다 (모듈 프레임 제외 — 최종 상태 유지)
    if (e.kind === 'return' && e.parentFrameId !== null) {
      for (const key of frameKeys.get(e.frameId) ?? []) unbind(key)
      frameKeys.delete(e.frameId)
    }

    // 쥐어져 있는 동안 수명이 이어진다
    for (const [id, holders] of holdersOf) {
      if (holders.size === 0) continue
      const o = objAcc.get(id)
      if (o) o.to = e.seq
    }
  }

  // ── 프레임 수집 ──
  const frameAcc = new Map<number, { func: string; parent: number | null; from: number; to: number }>()
  for (const e of events) {
    const cur = frameAcc.get(e.frameId)
    if (cur) cur.to = e.seq
    else frameAcc.set(e.frameId, { func: e.func, parent: e.parentFrameId, from: e.seq, to: e.seq })
  }
  const frames: CastFrame[] = [...frameAcc.entries()].map(([frameId, f]) => {
    let depth = 0
    let recursionIndex = 0
    let p = f.parent
    const guard = new Set<number>()
    while (p !== null && p !== undefined && !guard.has(p)) {
      guard.add(p)
      depth += 1
      const parent = frameAcc.get(p)
      if (parent?.func === f.func) recursionIndex += 1
      p = parent?.parent ?? null
    }
    return { frameId, func: f.func, parentFrameId: f.parent, life: { from: f.from, to: f.to }, depth, recursionIndex }
  })

  // ── 캐스팅 — 상자를 받을 객체 ──
  const isCallable = (id: number) => {
    const s = snapOf.get(id)
    return !!s?.unsupported && CALLABLE_TYPES.has(s.type)
  }
  const isInlineTuple = (id: number) => {
    const s = snapOf.get(id)
    return s?.type === 'tuple' && (s.items?.length ?? 0) <= INLINE_TUPLE_MAX && (s.items ?? []).every(i => i.k === 'prim')
  }
  const boxed = (id: number) => everHeld.has(id) && !isCallable(id) && !isInlineTuple(id)

  // ── 슬롯 배정 (선형 스캔) — 상자 받는 객체만 ──
  const objects: CastObject[] = [...objAcc.entries()]
    .filter(([objectId]) => boxed(objectId))
    .map(([objectId, o]) => ({
      objectId, type: o.type, life: { from: o.from, to: o.to },
      maxItems: o.maxItems, changeCount: o.changes, referencedBy: [...o.refs], slot: -1,
    }))
    .sort((a, b) => a.life.from - b.life.from)

  const freed: { slot: number; until: number }[] = []
  let slotCount = 0
  for (const o of objects) {
    const reusable = freed.filter(f => f.until < o.life.from).sort((a, b) => a.slot - b.slot)[0]
    if (reusable) {
      o.slot = reusable.slot
      freed.splice(freed.indexOf(reusable), 1)
    } else {
      o.slot = slotCount++
    }
    freed.push({ slot: o.slot, until: o.life.to })
  }

  // ── 전체 지표 ──
  const lastSeq = events[events.length - 1].seq
  const snaps = buildSnapshots(events)
  const maxStackDepth = Math.max(...snaps.map(s => s.stack.length), 0)
  const maxListLength = Math.max(...objects.map(o => o.maxItems), 0)
  const lead = [...objects].sort(
    (a, b) => b.changeCount - a.changeCount || (b.life.to - b.life.from) - (a.life.to - a.life.from),
  )[0]

  const variables: CastVariable[] = [...varAcc.entries()]
    .filter(([, v]) => v.dataish) // 함수·클래스·모듈에만 묶였던 이름은 데이터가 아니다
    .map(([varKey, v]) => ({
      varKey, frameId: v.frameId, name: v.name,
      life: { from: v.from, to: Math.min(v.to, lastSeq) }, holdsRef: v.holdsRef,
    }))

  return { objects, variables, frames, slotCount, maxStackDepth, maxListLength, leadObjectId: lead?.objectId ?? null }
}
