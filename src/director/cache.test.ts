// @vitest-environment jsdom
import { describe, it, expect, beforeEach } from 'vitest'
import {
  cacheKeyOf,
  clearScreenplayCache,
  readScreenplayCache,
  screenplayCacheSize,
  writeScreenplayCache,
} from './cache'
import type { DirectedResult } from './llmDirector'

const result = (title: string): DirectedResult => ({
  mode: 'ai',
  screenplay: {
    chapters: [
      {
        title,
        scenes: [
          {
            seqStart: 0, seqEnd: 1, primitive: 'variables', focus: [], pacing: 'normal',
            direction: [], narration: { template: '시작', bindings: {} },
          },
        ],
      },
    ],
  },
})

beforeEach(() => {
  localStorage.clear()
})

describe('연출 캐시: 키', () => {
  it('같은 모델·프롬프트는 같은 키, 하나라도 다르면 다른 키', () => {
    const a = cacheKeyOf('m1', 'prompt')
    expect(cacheKeyOf('m1', 'prompt')).toBe(a)
    expect(cacheKeyOf('m2', 'prompt')).not.toBe(a)
    expect(cacheKeyOf('m1', 'prompt ')).not.toBe(a)
  })

  it('프롬프트가 코드·다이제스트·지시문을 담으므로, 그중 무엇이 바뀌어도 키가 바뀐다', () => {
    const base = '지시문\n## 코드\nx = 1\n## 다이제스트\n[]'
    const keys = new Set([
      cacheKeyOf('m', base),
      cacheKeyOf('m', base.replace('x = 1', 'x = 2')), // 코드
      cacheKeyOf('m', base.replace('[]', '[1]')), // 다이제스트
      cacheKeyOf('m', base.replace('지시문', '지시문 v2')), // 프롬프트 버전
    ])
    expect(keys.size).toBe(4)
  })
})

describe('연출 캐시: 저장소', () => {
  it('쓴 것을 그대로 읽는다', () => {
    writeScreenplayCache('k1', result('첫 챕터'))
    const hit = readScreenplayCache('k1')
    expect(hit?.screenplay.chapters[0].title).toBe('첫 챕터')
    expect(hit?.mode).toBe('ai')
  })

  it('없는 키는 null — 적중 실패가 예외가 되지 않는다', () => {
    expect(readScreenplayCache('없음')).toBeNull()
  })

  it('상한(30)을 넘으면 가장 오래 안 쓴 것부터 버린다', () => {
    for (let i = 0; i < 33; i++) writeScreenplayCache(`k${i}`, result(`t${i}`))
    expect(screenplayCacheSize()).toBe(30)
    expect(readScreenplayCache('k0')).toBeNull() // 밀려났다
    expect(readScreenplayCache('k32')).not.toBeNull()
  })

  it('읽으면 최근 사용으로 올라간다 (LRU — 계속 쓰는 연출은 안 밀린다)', () => {
    for (let i = 0; i < 30; i++) writeScreenplayCache(`k${i}`, result(`t${i}`))
    readScreenplayCache('k0') // 되살린다
    writeScreenplayCache('new', result('새것'))
    expect(readScreenplayCache('k0')).not.toBeNull()
    expect(readScreenplayCache('k1')).toBeNull() // 대신 그다음이 밀렸다
  })

  it('비우기는 전부 지우고 개수를 돌려준다 — 나쁜 연출에 갇히지 않는 탈출구', () => {
    writeScreenplayCache('a', result('a'))
    writeScreenplayCache('b', result('b'))
    expect(clearScreenplayCache()).toBe(2)
    expect(screenplayCacheSize()).toBe(0)
    expect(readScreenplayCache('a')).toBeNull()
  })

  it('깨진 값은 조용히 무시한다 — 캐시 실패가 재생을 막아서는 안 된다', () => {
    localStorage.setItem('tracelens.director.v1:bad', '{깨진 JSON')
    expect(readScreenplayCache('bad')).toBeNull()
  })
})
