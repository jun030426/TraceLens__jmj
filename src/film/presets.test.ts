import { describe, it, expect } from 'vitest'
import { PRESETS, applyPresetPacing } from './presets'
import type { Shot } from './types'

const shot = (motions: Shot['motions'], durationMs = 1000): Shot => ({ seq: 0, motions, durationMs, focus: null })

describe('연출 프리셋', () => {
  it('완급 배수는 교환·비교 샷에만 붙는다', () => {
    const focus = PRESETS.find(p => p.key === 'focus')!
    const shots = [
      shot([{ v: 'swap', objectId: 1, i: 0, k: 1, iText: '1', kText: '2' }]),
      shot([{ v: 'compare', text: '1 < 2 → 참', targets: [] }]),
      shot([{ v: 'setVar', varKey: '0:x', text: '1' }]),
    ]
    const styled = applyPresetPacing(shots, focus)
    expect(styled[0].durationMs).toBe(Math.round(1000 * focus.paceSwap))
    expect(styled[1].durationMs).toBe(Math.round(1000 * focus.paceCompare))
    expect(styled[2].durationMs).toBe(1000)
  })

  it('교환+비교 echo 샷은 교환 배수를 받는다 (이중 적용 금지)', () => {
    const mass = PRESETS.find(p => p.key === 'mass')!
    const styled = applyPresetPacing(
      [shot([
        { v: 'swap', objectId: 1, i: 0, k: 1, iText: '1', kText: '2' },
        { v: 'compare', text: '2 > 1 → 참', targets: [] },
      ])],
      mass,
    )
    expect(styled[0].durationMs).toBe(Math.round(1000 * mass.paceSwap))
  })

  it('프리셋 3종의 파라미터는 서로 다르게 조율되어 있다', () => {
    const [a, b, c] = PRESETS
    expect(a.dimIdle).toBeLessThan(b.dimIdle) // 집중이 가장 어둡게
    expect(b.anticipation).toBeGreaterThan(c.anticipation) // 물성이 가장 길게 예고
    expect(c.flashStrength).toBeGreaterThan(a.flashStrength) // 쫀득이 가장 강한 플래시
  })
})
