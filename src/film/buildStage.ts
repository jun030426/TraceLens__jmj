import type { TraceEvent } from '../trace/types'
import { buildSnapshots } from '../trace/snapshots'
import type { CastFrame, CastObject, CastVariable, StagePlan } from './types'

const varKeyOf = (frameId: number, name: string) => `${frameId}:${name}`

// 1패스 — 트레이스 전체를 미리 읽어 "이 영화에 나오는 모든 것"과 각자의 자리를 정한다.
// 디버거는 미래를 모르지만 우리는 실행을 끝내놓고 시작하므로 무대를 미리 짤 수 있다.
export function buildStage(events: TraceEvent[]): StagePlan {
  if (events.length === 0) {
    return { objects: [], variables: [], frames: [], slotCount: 0, maxStackDepth: 0, maxListLength: 0, leadObjectId: null }
  }
  const lastSeq = events[events.length - 1].seq

  // ── 객체 수집 ──
  const objAcc = new Map<number, { type: string; from: number; to: number; maxItems: number; changes: number; refs: Set<string> }>()
  for (const e of events) {
    for (const d of e.objectsDelta) {
      if (d.op !== 'set' || !d.obj) continue
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
  }

  // ── 변수 수집 + 참조 관계 ──
  const varAcc = new Map<string, { frameId: number; name: string; from: number; to: number; holdsRef: boolean }>()
  for (const e of events) {
    for (const d of e.localsDelta) {
      const key = varKeyOf(e.frameId, d.name)
      const cur = varAcc.get(key)
      if (cur) cur.to = e.seq
      else varAcc.set(key, { frameId: e.frameId, name: d.name, from: e.seq, to: e.seq, holdsRef: false })
      if (d.op === 'set' && d.value?.k === 'ref') {
        varAcc.get(key)!.holdsRef = true
        const o = objAcc.get(d.value.id)
        if (o) {
          o.refs.add(key)
          o.to = Math.max(o.to, e.seq)
        }
      }
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

  // ── 슬롯 배정 (선형 스캔 = 레지스터 할당과 동형) ──
  // 생존 구간이 겹치지 않는 객체끼리는 무대 자리를 나눠 쓴다.
  const objects: CastObject[] = [...objAcc.entries()]
    .map(([objectId, o]) => ({
      objectId, type: o.type, life: { from: o.from, to: o.to },
      maxItems: o.maxItems, changeCount: o.changes, referencedBy: [...o.refs], slot: -1,
    }))
    .sort((a, b) => a.life.from - b.life.from)

  const freed: { slot: number; until: number }[] = []
  let slotCount = 0
  for (const o of objects) {
    const reusable = freed
      .filter(f => f.until < o.life.from)
      .sort((a, b) => a.slot - b.slot)[0]
    if (reusable) {
      o.slot = reusable.slot
      freed.splice(freed.indexOf(reusable), 1)
    } else {
      o.slot = slotCount++
    }
    freed.push({ slot: o.slot, until: o.life.to })
  }

  // ── 전체 지표 ──
  const snaps = buildSnapshots(events)
  const maxStackDepth = Math.max(...snaps.map(s => s.stack.length), 0)
  const maxListLength = Math.max(...objects.map(o => o.maxItems), 0)
  const lead = [...objects].sort(
    (a, b) => b.changeCount - a.changeCount || (b.life.to - b.life.from) - (a.life.to - a.life.from),
  )[0]

  const variables: CastVariable[] = [...varAcc.entries()].map(([varKey, v]) => ({
    varKey, frameId: v.frameId, name: v.name,
    life: { from: v.from, to: Math.min(v.to, lastSeq) }, holdsRef: v.holdsRef,
  }))

  return { objects, variables, frames, slotCount, maxStackDepth, maxListLength, leadObjectId: lead?.objectId ?? null }
}
