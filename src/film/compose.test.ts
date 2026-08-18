import { describe, it, expect } from 'vitest'
import { compose, LINGER } from './compose'
import type { Shot, StagePlan } from './types'
import type { StageLayout } from './layout'

const plan: StagePlan = {
  objects: [
    { objectId: 1, type: 'list', life: { from: 0, to: 99 }, maxItems: 4, changeCount: 3, referencedBy: ['0:a'], slot: 0 },
    { objectId: 2, type: 'list', life: { from: 0, to: 99 }, maxItems: 4, changeCount: 3, referencedBy: ['0:b'], slot: 1 },
  ],
  variables: [
    { varKey: '0:a', frameId: 0, name: 'a', life: { from: 0, to: 99 }, holdsRef: true },
    { varKey: '0:b', frameId: 0, name: 'b', life: { from: 0, to: 99 }, holdsRef: true },
    { varKey: '0:i', frameId: 0, name: 'i', life: { from: 0, to: 99 }, holdsRef: false },
  ],
  frames: [{ frameId: 0, func: '<module>', parentFrameId: null, life: { from: 0, to: 99 }, depth: 0, recursionIndex: 0 }],
  slotCount: 2, maxStackDepth: 1, maxListLength: 4, leadObjectId: 1,
}
const layout: StageLayout = {
  width: 1200, height: 640, cellW: 40,
  objPos: new Map([
    [1, { x: 560, y: 70, w: 300, h: 64 }],
    [2, { x: 560, y: 182, w: 300, h: 64 }],
  ]),
  varPos: new Map(),
  framePos: new Map(),
}
const shot = (seq: number, motions: Shot['motions']): Shot => ({ seq, motions, durationMs: 520, focus: null })

describe('compose', () => {
  it('이번 샷에 닿은 배우는 포커스(중앙·배율 1), 안 닿은 최근 배우는 대기(축소)', () => {
    const shots = [
      shot(0, [{ v: 'grow', objectId: 1, index: 0, text: '1' }]),
      shot(1, [{ v: 'grow', objectId: 2, index: 0, text: '2' }]),
    ]
    const comps = compose(shots, plan, layout)
    const c1 = comps[1]
    expect(c1.get('o2')!.focus).toBe(true)
    expect(c1.get('o2')!.s).toBe(1)
    expect(c1.get('o1')!.focus).toBe(false)
    expect(c1.get('o1')!.s).toBeLessThan(1)
    expect(c1.get('o1')!.x).toBeGreaterThan(c1.get('o2')!.x) // 대기열은 오른쪽
  })

  it('LINGER를 넘긴 배우는 무대에서 빠진다', () => {
    const shots = [
      shot(0, [{ v: 'grow', objectId: 1, index: 0, text: '1' }]),
      ...Array.from({ length: LINGER + 1 }, (_, k) => shot(k + 1, [{ v: 'setVar', varKey: '0:i', text: String(k) }])),
    ]
    const comps = compose(shots, plan, layout)
    expect(comps[comps.length - 1].has('o1')).toBe(false)
    expect(comps[LINGER].has('o1')).toBe(true) // 마지막 유예 샷까지는 남는다
  })

  it('변수는 좌측 스트립 — 닿은 것이 포커스', () => {
    const shots = [shot(0, [{ v: 'setVar', varKey: '0:i', text: '3' }])]
    const comps = compose(shots, plan, layout)
    const v = comps[0].get('v0:i')!
    expect(v.focus).toBe(true)
    expect(v.x).toBeLessThan(560)
  })

  it('같은 열 안에서 세로로 겹치지 않는다', () => {
    const shots = [
      shot(0, [
        { v: 'grow', objectId: 1, index: 0, text: '1' },
        { v: 'grow', objectId: 2, index: 0, text: '2' },
      ]),
    ]
    const comps = compose(shots, plan, layout)
    const a = comps[0].get('o1')!
    const b = comps[0].get('o2')!
    const h1 = 64 * a.s
    expect(Math.abs(b.y - a.y)).toBeGreaterThanOrEqual(h1) // 아래 배우가 위 배우 높이 밖
  })

  it('sticky — 계속 무대에 있는 배우는 세로 순서를 유지한다', () => {
    const shots = [
      shot(0, [
        { v: 'grow', objectId: 1, index: 0, text: '1' },
        { v: 'grow', objectId: 2, index: 0, text: '2' },
      ]),
      shot(1, [
        { v: 'setCell', objectId: 2, index: 0, text: '9' },
        { v: 'setCell', objectId: 1, index: 0, text: '8' },
      ]),
    ]
    const comps = compose(shots, plan, layout)
    const before = comps[0].get('o1')!.y < comps[0].get('o2')!.y
    const after = comps[1].get('o1')!.y < comps[1].get('o2')!.y
    expect(after).toBe(before)
  })
})
