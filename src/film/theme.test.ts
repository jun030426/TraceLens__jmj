import { describe, it, expect } from 'vitest'
import { detectTheme } from './theme'
import type { Shot, StagePlan } from './types'

const plan = (over?: Partial<StagePlan>): StagePlan => ({
  objects: [
    { objectId: 1, type: 'list', life: { from: 0, to: 99 }, maxItems: 3, changeCount: 3, referencedBy: ['0:a'], slot: 0 },
  ],
  variables: [{ varKey: '0:a', frameId: 0, name: 'a', life: { from: 0, to: 99 }, holdsRef: true }],
  frames: [{ frameId: 0, func: '<module>', parentFrameId: null, life: { from: 0, to: 99 }, depth: 0, recursionIndex: 0 }],
  slotCount: 1, maxStackDepth: 1, maxListLength: 3, leadObjectId: 1,
  ...over,
})
const shot = (motions: Shot['motions']): Shot => ({ seq: 0, motions, durationMs: 520, focus: null })

describe('detectTheme', () => {
  it('음수 없는 숫자 리스트에 swap 2회 이상 → 정렬 테마 + 막대 대상', () => {
    const t = detectTheme(plan(), [
      shot([
        { v: 'grow', objectId: 1, index: 0, text: '5' },
        { v: 'grow', objectId: 1, index: 1, text: '2' },
        { v: 'grow', objectId: 1, index: 2, text: '9' },
      ]),
      shot([{ v: 'swap', objectId: 1, i: 0, k: 1, iText: '2', kText: '5' }]),
      shot([{ v: 'swap', objectId: 1, i: 1, k: 2, iText: '5', kText: '9' }]),
    ])
    expect(t.kind).toBe('sorting')
    expect(t.barObjects.has(1)).toBe(true)
    expect(t.maxAbs.get(1)).toBe(9)
  })

  it('문자 값이 섞이면 막대 대상이 아니고 정렬 테마도 아니다', () => {
    const t = detectTheme(plan(), [
      shot([
        { v: 'grow', objectId: 1, index: 0, text: 'kim' },
        { v: 'grow', objectId: 1, index: 1, text: '2' },
      ]),
      shot([{ v: 'swap', objectId: 1, i: 0, k: 1, iText: '2', kText: 'kim' }]),
      shot([{ v: 'swap', objectId: 1, i: 0, k: 1, iText: 'kim', kText: '2' }]),
    ])
    expect(t.barObjects.has(1)).toBe(false)
    expect(t.kind).toBe('generic')
  })

  it('음수가 보이면 막대를 포기한다 — |v| 인코딩은 순서를 거짓말한다', () => {
    const t = detectTheme(plan(), [
      shot([
        { v: 'grow', objectId: 1, index: 0, text: '-3' },
        { v: 'grow', objectId: 1, index: 1, text: '2' },
      ]),
    ])
    expect(t.barObjects.has(1)).toBe(false)
  })

  it('격자가 있으면 공간 탐색 테마', () => {
    const t = detectTheme(
      plan({
        objects: [
          { objectId: 7, type: 'list', life: { from: 0, to: 99 }, maxItems: 9, changeCount: 1, referencedBy: ['0:m'], slot: 0, grid: { rows: 3, cols: 3, binary: true } },
        ],
      }),
      [shot([{ v: 'gridVisit', objectId: 7, r: 0, c: 0 }])],
    )
    expect(t.kind).toBe('spatial')
  })

  it('아무 신호도 없으면 중립', () => {
    const t = detectTheme(plan(), [shot([{ v: 'setVar', varKey: '0:a', text: '1' }])])
    expect(t.kind).toBe('generic')
  })
})
