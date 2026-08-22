import { describe, it, expect } from 'vitest'
import demo from '../fixtures/film-demo.trace.json'
import type { TraceEvent } from '../trace/types'
import { buildStage } from './buildStage'
import { STACK_SLOTS, layoutStage } from './layout'

const events = (demo as { events: TraceEvent[] }).events
const plan = buildStage(events)
const L = layoutStage(plan)

describe('layoutStage', () => {
  it('모든 등장인물에 자리가 있다', () => {
    for (const o of plan.objects) expect(L.objPos.has(o.objectId)).toBe(true)
    for (const v of plan.variables) expect(L.varPos.has(v.varKey)).toBe(true)
    // 프레임 카드는 이제 id가 아니라 슬롯(0..STACK_SLOTS-1) 자리를 갖는다 —
    // 어느 프레임이 어느 슬롯에 앉을지는 compose가 샷마다 정한다 (호출 스택 창)
    for (let slot = 0; slot < STACK_SLOTS; slot++) expect(L.framePos.has(slot)).toBe(true)
    expect(L.framePos.size).toBe(STACK_SLOTS)
  })

  it('스택 높이는 재귀 깊이에 흔들리지 않는다 — 창이 고정이므로', () => {
    const deep: typeof plan = {
      ...plan,
      frames: Array.from({ length: 20 }, (_, i) => ({
        frameId: i, func: i === 0 ? '<module>' : 'f', parentFrameId: i === 0 ? null : i - 1,
        life: { from: 0, to: 99 }, depth: i, recursionIndex: i,
      })),
    }
    expect(layoutStage(deep).height).toBe(L.height)
    for (const r of layoutStage(deep).framePos.values()) expect(r.w).toBeGreaterThan(0)
  })
  it('객체 폭이 최대 크기만큼 예약된다', () => {
    const big = plan.objects.find(o => o.maxItems >= 12)!
    expect(big).toBeDefined()
    expect(L.objPos.get(big.objectId)!.w).toBeGreaterThanOrEqual(big.maxItems * L.cellW)
  })
  it('모든 자리가 화면 안에 있다', () => {
    for (const r of L.objPos.values()) {
      expect(r.x).toBeGreaterThanOrEqual(0)
      expect(r.y + r.h).toBeLessThanOrEqual(L.height)
    }
  })
  it('셀 폭에 하한이 있다', () => {
    expect(L.cellW).toBeGreaterThanOrEqual(26)
  })

  /* 겹침 금지 — "덮어져 있는 느낌"의 원인들을 좌표 수준에서 차단한다 */

  it('출력 바 띠(height-52 아래)를 아무도 침범하지 않는다', () => {
    const stdoutTop = L.height - 52
    for (const r of L.objPos.values()) expect(r.y + r.h + 14).toBeLessThanOrEqual(stdoutTop) // +14 = 칸 번호
    for (const r of L.varPos.values()) expect(r.y + r.h).toBeLessThanOrEqual(stdoutTop)
    for (const r of L.framePos.values()) expect(r.y + r.h).toBeLessThanOrEqual(stdoutTop)
  })

  it('프레임 카드끼리 세로로 겹치지 않는다', () => {
    const rects = [...L.framePos.values()].sort((a, b) => a.y - b.y)
    for (let i = 1; i < rects.length; i++) {
      if (rects[i].y === rects[i - 1].y) continue // 같은 깊이는 시간상 교대 사용
      expect(rects[i].y).toBeGreaterThanOrEqual(rects[i - 1].y + rects[i - 1].h)
    }
  })

  it('변수 알약이 객체 상자 열(x=560)에 닿지 않는다', () => {
    for (const r of L.varPos.values()) expect(r.x + r.w).toBeLessThanOrEqual(560)
  })
})

describe('layoutStage: 격자', () => {
  const gridPlan = (): Parameters<typeof layoutStage>[0] => ({
    objects: [
      {
        objectId: 1, type: 'list', life: { from: 0, to: 9 }, maxItems: 4,
        changeCount: 1, referencedBy: ['0:maze'], slot: -1,
        grid: { rows: 4, cols: 4, binary: true },
      },
      { objectId: 2, type: 'list', life: { from: 1, to: 9 }, maxItems: 3, changeCount: 2, referencedBy: ['0:path'], slot: 0 },
    ],
    variables: [
      { varKey: '0:maze', frameId: 0, name: 'maze', life: { from: 0, to: 9 }, holdsRef: true },
      { varKey: '0:path', frameId: 0, name: 'path', life: { from: 1, to: 9 }, holdsRef: true },
    ],
    frames: [{ frameId: 0, func: '<module>', parentFrameId: null, life: { from: 0, to: 9 }, depth: 0, recursionIndex: 0 }],
    slotCount: 1, maxStackDepth: 1, maxListLength: 4, leadObjectId: 1,
  })

  it('격자는 rows·cols에 비례하는 2D 발자국을 받는다', () => {
    const L = layoutStage(gridPlan())
    const g = L.objPos.get(1)!
    expect(g.w).toBe(4 * 34 + 16)
    expect(g.h).toBe(4 * 34 + 16)
  })

  it('일반 상자는 격자 아래에서 시작한다', () => {
    const L = layoutStage(gridPlan())
    const g = L.objPos.get(1)!
    const box = L.objPos.get(2)!
    expect(box.y).toBeGreaterThanOrEqual(g.y + g.h)
  })
})

describe('layoutStage: 텍스트 띠 분리', () => {
  it('인접 슬롯 사이에 칸 번호 띠(+14)와 이름표 띠(-20)가 둘 다 들어간다', () => {
    const box = (id: number, slot: number) => ({
      objectId: id, type: 'list', life: { from: 0, to: 9 }, maxItems: 3,
      changeCount: 1, referencedBy: [`0:v${id}`], slot,
    })
    const L = layoutStage({
      objects: [box(1, 0), box(2, 1)],
      variables: [],
      frames: [{ frameId: 0, func: '<module>', parentFrameId: null, life: { from: 0, to: 9 }, depth: 0, recursionIndex: 0 }],
      slotCount: 2, maxStackDepth: 1, maxListLength: 3, leadObjectId: 1,
    })
    const a = L.objPos.get(1)!
    const b = L.objPos.get(2)!
    // 위 상자의 번호(y+h+14)와 아래 상자의 이름표(y-20)가 만나지 않아야 한다 (여유 12px)
    expect(b.y - 20).toBeGreaterThanOrEqual(a.y + a.h + 14 + 12)
  })

  it('격자 아래 첫 상자의 이름표가 격자 열 번호와 만나지 않는다', () => {
    const L = layoutStage({
      objects: [
        { objectId: 1, type: 'list', life: { from: 0, to: 9 }, maxItems: 4, changeCount: 1, referencedBy: ['0:g'], slot: -1, grid: { rows: 2, cols: 2, binary: true } },
        { objectId: 2, type: 'list', life: { from: 0, to: 9 }, maxItems: 3, changeCount: 1, referencedBy: ['0:a'], slot: 0 },
      ],
      variables: [],
      frames: [{ frameId: 0, func: '<module>', parentFrameId: null, life: { from: 0, to: 9 }, depth: 0, recursionIndex: 0 }],
      slotCount: 1, maxStackDepth: 1, maxListLength: 4, leadObjectId: 1,
    })
    const g = L.objPos.get(1)!
    const b = L.objPos.get(2)!
    expect(b.y - 20).toBeGreaterThanOrEqual(g.y + g.h + 14 + 12)
  })
})
