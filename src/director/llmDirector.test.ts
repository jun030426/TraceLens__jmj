import { describe, it, expect, vi } from 'vitest'
import type { Digest } from '../digest/buildDigest'
import { generateScreenplay } from './llmDirector'

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

describe('generateScreenplay', () => {
  it('정상 응답을 Screenplay로 변환한다', async () => {
    const call = vi.fn().mockResolvedValue(goodJson)
    const sp = await generateScreenplay('a = 1', digest, call)
    expect(sp.chapters[0].scenes.length).toBe(2)
    expect(call).toHaveBeenCalledTimes(1)
  })
  it('마크다운 펜스로 감싼 응답도 파싱한다', async () => {
    const call = vi.fn().mockResolvedValue('```json\n' + goodJson + '\n```')
    const sp = await generateScreenplay('a = 1', digest, call)
    expect(sp.chapters.length).toBe(1)
  })
  it('1차 실패 시 오류 피드백을 담아 1회 재시도한다', async () => {
    const call = vi.fn()
      .mockResolvedValueOnce(JSON.stringify({ chapters: [{ title: 'x', scenes: [{ spanRef: 'ghost', primitive: 'variables', narration: { template: 't' } }] }] }))
      .mockResolvedValueOnce(goodJson)
    const sp = await generateScreenplay('a = 1', digest, call)
    expect(call).toHaveBeenCalledTimes(2)
    expect(String(call.mock.calls[1][0])).toContain('spanRef')
    expect(sp.chapters.length).toBe(1)
  })
  it('재시도까지 실패하면 throw (호출자가 규칙 기반으로 폴백)', async () => {
    const call = vi.fn().mockResolvedValue('이건 JSON이 아님')
    await expect(generateScreenplay('a = 1', digest, call)).rejects.toThrow()
    expect(call).toHaveBeenCalledTimes(2)
  })
})

/* 캐싱 — 같은 코드면 같은 영화. localStorage가 필요하므로 jsdom 환경의 별도 파일에서 다룬다 */
