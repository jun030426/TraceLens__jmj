import { describe, it, expect } from 'vitest'
import { decorateShots } from './decorate'
import type { Shot, StagePlan } from './types'
import type { Screenplay } from '../screenplay/types'

const plan: StagePlan = {
  objects: [],
  frames: [],
  slotCount: 0,
  maxStackDepth: 0,
  maxListLength: 0,
  leadObjectId: null,
  variables: [{ varKey: '0:a', frameId: 0, name: 'a', life: { from: 0, to: 9 }, holdsRef: false }],
}
const shot = (seq: number, over: Partial<Shot> = {}): Shot => ({
  seq,
  motions: [{ v: 'enterVar', varKey: '0:a' }],
  durationMs: 520,
  focus: null,
  ...over,
})
const play = (pacing: 'slow' | 'fast' | 'normal', focus: string[] = []): Screenplay => ({
  chapters: [
    {
      title: 'c',
      scenes: [{ seqStart: 0, seqEnd: 5, primitive: 'variables', focus, pacing, narration: { template: '', bindings: {} } }],
    },
  ],
})

describe('decorateShots', () => {
  it('slow 장면은 느려지고 spotlight가 붙는다', () => {
    const out = decorateShots([shot(1)], play('slow', ['a']), plan)
    expect(out[0].durationMs).toBe(780)
    expect(out[0].motions.at(-1)).toEqual({ v: 'spotlight', varKeys: ['0:a'] })
  })

  it('fast 장면은 빨라진다 (클램프 하한 220)', () => {
    expect(decorateShots([shot(1)], play('fast'), plan)[0].durationMs).toBe(312)
    const tiny = decorateShots([shot(1, { durationMs: 300 })], play('fast'), plan)
    expect(tiny[0].durationMs).toBe(220)
  })

  it('장면 밖 샷·timelapse 샷은 건드리지 않는다', () => {
    expect(decorateShots([shot(9)], play('slow'), plan)[0].durationMs).toBe(520)
    const lapse = decorateShots([shot(1, { timelapse: 5 })], play('slow'), plan)
    expect(lapse[0].durationMs).toBe(520)
  })

  it('샷 수를 보존한다', () => {
    expect(decorateShots([shot(1), shot(2)], play('slow'), plan).length).toBe(2)
  })
})
