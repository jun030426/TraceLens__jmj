// 3D 무대의 "무엇을 그릴까" — 샷마다 실제 실행 기록(스냅숏)에서 장면을 다시 읽는다.
// 여기는 three.js를 모른다: 값·구조·이번 샷의 사건만 정하고, 그리기는 Stage3D가 한다.
// 배역은 템플릿이 정한다 (펭귄 템플릿 / 호떡 템플릿) — 여기서는 변수·배열 칸·객체만 가른다.
import type { Film } from '../buildFilm.ts'
import type { Motion, Shot } from '../film/types.ts'
import { buildSnapshots, type Snapshot } from '../trace/snapshots.ts'
import type { ObjectSnap, Value } from '../trace/types.ts'

export type Cell = { text: string; num: number | null }
export type Row = { objectId: number; names: string[]; cells: Cell[]; hidden: number }
/** 변수 하나 — pointer는 그 변수가 인덱스로 가리키는 배열 (있으면 배열 위 깃발로 선다) */
export type Variable = { key: string; name: string; text: string; pointer: number | null }
export type Sign = { objectId: number; names: string[]; text: string }

export type Scene = {
  frameId: number | null
  stack: string[]
  vars: Variable[]
  rows: Row[]
  signs: Sign[]
}

export type Beat = {
  shot: Shot
  start: number // 초
  duration: number
  before: Scene
  after: Scene
}

export type World = {
  beats: Beat[]
  total: number
  /** 리스트별 |값| 최댓값 — 호떡 크기가 실행 내내 같은 잣대로 정해진다 */
  maxAbs: Map<number, number>
  /** 리스트별 가장 긴 길이 — 칸 간격이 실행 도중 출렁이지 않게 */
  maxLen: Map<number, number>
  /** 숫자 변수 전체의 |값| 최댓값 — 변수 펭귄들이 같은 잣대로 키를 잰다 */
  maxVarAbs: number
}

const EMPTY: Scene = { frameId: null, stack: [], vars: [], rows: [], signs: [] }
const LIST_TYPES = new Set(['list', 'tuple', 'array', 'deque'])

export const numOf = (text: string): number | null => {
  if (!/^-?\d+(\.\d+)?(e-?\d+)?$/i.test(text)) return null
  const n = Number(text)
  return Number.isFinite(n) ? n : null
}

const short = (s: string, n = 14) => (s.length > n ? s.slice(0, n - 1) + '…' : s)

function valueText(v: Value, objects: Map<number, ObjectSnap>): string {
  if (v.k === 'prim') return v.v
  const o = objects.get(v.id)
  if (!o) return '→'
  if (LIST_TYPES.has(o.type)) return `[${o.n ?? o.items?.length ?? 0}칸]`
  return `→ ${o.type}`
}

function objectSummary(o: ObjectSnap, objects: Map<number, ObjectSnap>): string {
  if (o.entries) return `${o.type} { ${o.entries.slice(0, 4).map(([k, v]) => `${k}: ${short(valueText(v, objects), 8)}`).join(', ')}${o.entries.length > 4 ? ', …' : ''} }`
  if (o.items) return `${o.type} (${o.items.length})`
  return o.type
}

export function sceneOf(snap: Snapshot | undefined, pointers: Map<string, number>): Scene {
  if (!snap || snap.stack.length === 0) return EMPTY
  const top = snap.stack[snap.stack.length - 1]
  const vars: Variable[] = []
  const rowNames = new Map<number, string[]>()
  const signNames = new Map<number, string[]>()
  for (const [name, v] of top.locals) {
    const key = `${top.frameId}:${name}`
    if (v.k === 'ref') {
      const o = snap.objects.get(v.id)
      if (o && LIST_TYPES.has(o.type) && o.items) {
        rowNames.set(v.id, [...(rowNames.get(v.id) ?? []), name])
        continue
      }
      if (o) signNames.set(v.id, [...(signNames.get(v.id) ?? []), name])
    }
    const ptr = pointers.get(key)
    vars.push({ key, name, text: valueText(v, snap.objects), pointer: ptr ?? null })
  }
  const rows: Row[] = [...rowNames].map(([objectId, names]) => {
    const o = snap.objects.get(objectId)!
    const cells = (o.items ?? []).map(it => {
      const text = it.k === 'prim' ? it.v : valueText(it, snap.objects)
      return { text, num: it.k === 'prim' ? numOf(it.v) : null }
    })
    return { objectId, names, cells, hidden: Math.max(0, (o.n ?? cells.length) - cells.length) }
  })
  const signs: Sign[] = [...signNames].map(([objectId, names]) => ({
    objectId,
    names,
    text: objectSummary(snap.objects.get(objectId)!, snap.objects),
  }))
  // 인덱스 변수는 자기 배열이 화면에 있을 때만 그 배열 위 깃발이 된다 — 아니면 보통 변수
  const shown = new Set(rows.map(r => r.objectId))
  for (const p of vars) if (p.pointer !== null && !shown.has(p.pointer)) p.pointer = null
  return { frameId: top.frameId, stack: snap.stack.map(f => f.func), vars, rows, signs }
}

export function buildWorld(film: Pick<Film, 'shots' | 'events'>): World {
  const snaps = buildSnapshots(film.events)
  const bySeq = (seq: number) => {
    let found: Snapshot | undefined
    for (const s of snaps) {
      if (s.seq > seq) break
      found = s
    }
    return found
  }
  const pointers = new Map<string, number>()
  for (const sh of film.shots) for (const m of sh.motions) if (m.v === 'pointer') pointers.set(m.varKey, m.objectId)

  const maxAbs = new Map<number, number>()
  const maxLen = new Map<number, number>()
  for (const s of snaps)
    for (const o of s.objects.values()) {
      if (!LIST_TYPES.has(o.type) || !o.items) continue
      maxLen.set(o.id, Math.max(maxLen.get(o.id) ?? 0, o.items.length))
      for (const it of o.items) {
        const n = it.k === 'prim' ? numOf(it.v) : null
        if (n !== null) maxAbs.set(o.id, Math.max(maxAbs.get(o.id) ?? 0, Math.abs(n)))
      }
    }

  let maxVarAbs = 0
  for (const s of snaps)
    for (const f of s.stack)
      for (const v of f.locals.values()) {
        const n = v.k === 'prim' ? numOf(v.v) : null
        if (n !== null) maxVarAbs = Math.max(maxVarAbs, Math.abs(n))
      }

  const beats: Beat[] = []
  let start = 0
  let prev = EMPTY
  for (const shot of film.shots) {
    const after = sceneOf(bySeq(shot.seq), pointers)
    const duration = shot.durationMs / 1000
    beats.push({ shot, start, duration, before: prev, after })
    start += duration
    prev = after
  }
  return { beats, total: start, maxAbs, maxLen, maxVarAbs }
}

/** 시각 t(초)의 샷과 그 샷 안의 진행도(0..1) */
export function beatAt(world: World, t: number): { beat: Beat; index: number; p: number } | null {
  const { beats } = world
  if (beats.length === 0) return null
  let lo = 0
  let hi = beats.length - 1
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1
    if (beats[mid].start <= t) lo = mid
    else hi = mid - 1
  }
  const beat = beats[lo]
  const p = beat.duration > 0 ? Math.min(1, Math.max(0, (t - beat.start) / beat.duration)) : 1
  return { beat, index: lo, p }
}

export const motionsOf = <V extends Motion['v']>(beat: Beat, v: V) =>
  beat.shot.motions.filter((m): m is Extract<Motion, { v: V }> => m.v === v)
