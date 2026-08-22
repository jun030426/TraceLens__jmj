// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach } from 'vitest'
import type { Digest } from '../digest/buildDigest'
import type { Screenplay } from '../screenplay/types'
import { generateScreenplayWithSalvage } from './llmDirector'
import { clearScreenplayCache } from './cache'

const digest: Digest = {
  spans: [
    { spanId: 's0', sourceSeqRange: [0, 0], lines: [1, 1], eventKinds: ['call'], funcs: ['<module>'], changedVars: [] },
    { spanId: 's1', sourceSeqRange: [1, 1], lines: [1, 2], eventKinds: ['line'], funcs: ['<module>'], changedVars: ['a'] },
  ],
}
const goodJson = JSON.stringify({
  chapters: [{ title: '실행', scenes: [
    { spanRef: 's0', primitive: 'variables', narration: { template: '시작합니다' } },
    { spanRef: 's1', primitive: 'variables', narration: { template: 'a가 설정됩니다' } },
  ] }],
})
const rule: Screenplay = { chapters: [{ title: '규칙', scenes: [] }] }

beforeEach(() => {
  localStorage.clear()
  clearScreenplayCache()
})

describe('Director 캐싱 — 같은 코드면 같은 영화', () => {
  it('두 번째 실행은 모델을 아예 부르지 않고 저장된 대본을 그대로 쓴다', async () => {
    const call = vi.fn().mockResolvedValue(goodJson)
    const first = await generateScreenplayWithSalvage('a = 1', digest, call, rule, 'm1')
    expect(call).toHaveBeenCalledTimes(1)
    expect(first.cached).toBeFalsy()

    const second = await generateScreenplayWithSalvage('a = 1', digest, call, rule, 'm1')
    expect(call).toHaveBeenCalledTimes(1) // 늘지 않았다 — 429가 날 일이 없다
    expect(second.cached).toBe(true)
    expect(second.screenplay).toEqual(first.screenplay)
  })

  it('코드가 다르면 다시 부른다 — 캐시가 다른 코드의 연출을 재활용하지 않는다', async () => {
    const call = vi.fn().mockResolvedValue(goodJson)
    await generateScreenplayWithSalvage('a = 1', digest, call, rule, 'm1')
    await generateScreenplayWithSalvage('a = 2', digest, call, rule, 'm1')
    expect(call).toHaveBeenCalledTimes(2)
  })

  it('모델이 바뀌면 다시 부른다', async () => {
    const call = vi.fn().mockResolvedValue(goodJson)
    await generateScreenplayWithSalvage('a = 1', digest, call, rule, 'm1')
    await generateScreenplayWithSalvage('a = 1', digest, call, rule, 'm2')
    expect(call).toHaveBeenCalledTimes(2)
  })

  it('모델명을 안 주면 캐시를 쓰지 않는다 (옵트인)', async () => {
    const call = vi.fn().mockResolvedValue(goodJson)
    await generateScreenplayWithSalvage('a = 1', digest, call, rule)
    await generateScreenplayWithSalvage('a = 1', digest, call, rule)
    expect(call).toHaveBeenCalledTimes(2)
  })

  it('실패한 생성은 캐시하지 않는다 — 실패를 굳혀두면 영원히 폴백이다', async () => {
    const bad = vi.fn().mockResolvedValue('{"chapters": "말이 안 되는 값"}')
    await expect(generateScreenplayWithSalvage('a = 1', digest, bad, rule, 'm1')).rejects.toThrow()
    const good = vi.fn().mockResolvedValue(goodJson)
    const retry = await generateScreenplayWithSalvage('a = 1', digest, good, rule, 'm1')
    expect(good).toHaveBeenCalled()
    expect(retry.cached).toBeFalsy()
  })
})
