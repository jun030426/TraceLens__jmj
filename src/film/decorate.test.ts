import { describe, it, expect } from 'vitest'
import { decorateShots } from './decorate'
import type { Shot, StagePlan } from './types'
import type { StageLayout } from './layout'
import type { DirectingVerb, Pacing, Screenplay } from '../screenplay/types'

const plan: StagePlan = {
  objects: [],
  frames: [],
  slotCount: 0,
  maxStackDepth: 0,
  maxListLength: 0,
  leadObjectId: null,
  variables: [{ varKey: '0:a', frameId: 0, name: 'a', life: { from: 0, to: 9 }, holdsRef: false }],
}
const layout: StageLayout = {
  width: 1200,
  height: 640,
  cellW: 40,
  objPos: new Map([[1, { x: 560, y: 70, w: 300, h: 64 }]]),
  varPos: new Map([['0:a', { x: 340, y: 70, w: 190, h: 36 }]]),
  framePos: new Map([[0, { x: 24, y: 500, w: 260, h: 58 }]]),
}
const shot = (seq: number, over: Partial<Shot> = {}): Shot => ({
  seq,
  motions: [{ v: 'enterVar', varKey: '0:a' }],
  durationMs: 520,
  focus: null,
  ...over,
})
const play = (pacing: Pacing, focus: string[] = []): Screenplay => ({
  chapters: [
    {
      title: 'c',
      scenes: [
        { seqStart: 0, seqEnd: 5, primitive: 'variables', focus, pacing, direction: [], narration: { template: '', bindings: {} } },
      ],
    },
  ],
})
const playD = (direction: DirectingVerb[], seqStart = 0, seqEnd = 5): Screenplay => ({
  chapters: [
    {
      title: 'c',
      scenes: [
        { seqStart, seqEnd, primitive: 'variables', focus: [], pacing: 'normal', direction, narration: { template: '', bindings: {} } },
      ],
    },
  ],
})

describe('decorateShots', () => {
  it('slow 장면은 느려지고 spotlight가 붙는다', () => {
    const out = decorateShots([shot(1)], play('slow', ['a']), plan, layout)
    expect(out[0].durationMs).toBe(780)
    expect(out[0].motions.at(-1)).toEqual({ v: 'spotlight', varKeys: ['0:a'] })
  })

  it('fast 장면은 빨라진다 (클램프 하한 220)', () => {
    expect(decorateShots([shot(1)], play('fast'), plan, layout)[0].durationMs).toBe(312)
    const tiny = decorateShots([shot(1, { durationMs: 300 })], play('fast'), plan, layout)
    expect(tiny[0].durationMs).toBe(220)
  })

  it('장면 밖 샷·timelapse 샷은 건드리지 않는다', () => {
    expect(decorateShots([shot(9)], play('slow'), plan, layout)[0].durationMs).toBe(520)
    const lapse = decorateShots([shot(1, { timelapse: 5 })], play('slow'), plan, layout)
    expect(lapse[0].durationMs).toBe(520)
  })

  it('샷 수를 보존한다', () => {
    expect(decorateShots([shot(1), shot(2)], play('slow'), plan, layout).length).toBe(2)
  })
})

describe('decorateShots: 연출 동사', () => {
  it('zoom: 대상 있는 첫 샷에 camera(k>1), 장면 마지막 샷에 복귀(k=1)', () => {
    const shots = [shot(1, { focus: { kind: 'object', objectId: 1 } }), shot(2)]
    const out = decorateShots(shots, playD(['zoom']), plan, layout)
    const cam0 = out[0].motions.find(m => m.v === 'camera') as { k: number }
    expect(cam0).toBeDefined()
    expect(cam0.k).toBeGreaterThan(1)
    const cam1 = out[1].motions.find(m => m.v === 'camera') as { k: number }
    expect(cam1).toEqual({ v: 'camera', k: 1, x: 0, y: 0 })
  })

  it('zoom: compare의 cell 타깃이 focus보다 우선한다', () => {
    const shots = [
      shot(1, {
        focus: { kind: 'frame', frameId: 0 },
        motions: [{ v: 'compare', text: '5 > 4', targets: [{ kind: 'cell', objectId: 1, index: 0 }] }],
      }),
    ]
    const out = decorateShots(shots, playD(['zoom']), plan, layout)
    const cam = out[0].motions.find(m => m.v === 'camera') as { k: number; x: number }
    // objPos(1) 기준 계산 — frame(24,500)이 아니라 object(560,70)를 향한다
    expect(cam.x).toBeLessThan(0)
    expect(cam.k).toBeGreaterThan(1)
  })

  it('zoom: 대상 rect가 전혀 없으면 무시된다', () => {
    const out = decorateShots([shot(1)], playD(['zoom']), plan, layout)
    expect(out[0].motions.some(m => m.v === 'camera')).toBe(false)
  })

  it('hold: 장면 마지막 샷이 길어진다 (×1.9)', () => {
    const out = decorateShots([shot(1), shot(2)], playD(['hold']), plan, layout)
    expect(out[0].durationMs).toBe(520)
    expect(out[1].durationMs).toBe(988)
  })

  it('skip: 전 샷 ×0.3(≥150), 같은 장면의 zoom·hold는 무시', () => {
    const out = decorateShots(
      [shot(1, { focus: { kind: 'object', objectId: 1 } })],
      playD(['skip', 'zoom', 'hold']),
      plan,
      layout,
    )
    expect(out[0].durationMs).toBe(156)
    expect(out[0].motions.some(m => m.v === 'camera')).toBe(false)
  })

  it('전역 캡: zoom 4장면이면 앞의 3장면만 카메라를 받는다', () => {
    const sc = (s: number): Screenplay['chapters'][0]['scenes'][0] => ({
      seqStart: s, seqEnd: s, primitive: 'variables', focus: [], pacing: 'normal',
      direction: ['zoom'], narration: { template: '', bindings: {} },
    })
    const sp: Screenplay = { chapters: [{ title: 'c', scenes: [sc(1), sc(2), sc(3), sc(4)] }] }
    const shots = [1, 2, 3, 4].map(s => shot(s, { focus: { kind: 'object', objectId: 1 } }))
    const out = decorateShots(shots, sp, plan, layout)
    const camScenes = out.filter(o => o.motions.some(m => m.v === 'camera' && (m as { k: number }).k > 1))
    expect(camScenes.length).toBe(3)
  })
})
