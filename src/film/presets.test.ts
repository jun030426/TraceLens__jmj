import { describe, it, expect } from 'vitest'
import { GRAMMAR, applyGrammarPacing } from './presets'
import type { Shot } from './types'

const shot = (motions: Shot['motions'], durationMs = 1000): Shot => ({ seq: 0, motions, durationMs, focus: null })

describe('연출 문법 완급', () => {
  it('완급 배수는 교환·비교 샷에만 붙는다', () => {
    const shots = [
      shot([{ v: 'swap', objectId: 1, i: 0, k: 1, iText: '1', kText: '2' }]),
      shot([{ v: 'compare', text: '1 < 2 → 참', targets: [] }]),
      shot([{ v: 'setVar', varKey: '0:x', text: '1' }]),
    ]
    const styled = applyGrammarPacing(shots)
    expect(styled[0].durationMs).toBe(Math.round(1000 * GRAMMAR.paceSwap))
    expect(styled[1].durationMs).toBe(Math.round(1000 * GRAMMAR.paceCompare))
    expect(styled[2].durationMs).toBe(1000)
  })

  it('교환+비교 echo 샷은 교환 배수를 받는다 (이중 적용 금지)', () => {
    const styled = applyGrammarPacing([
      shot([
        { v: 'swap', objectId: 1, i: 0, k: 1, iText: '1', kText: '2' },
        { v: 'compare', text: '2 > 1 → 참', targets: [] },
      ]),
    ])
    expect(styled[0].durationMs).toBe(Math.round(1000 * GRAMMAR.paceSwap))
  })
})
