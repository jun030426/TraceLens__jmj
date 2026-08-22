import { describe, it, expect, afterAll } from 'vitest'
import type { TraceEvent } from '../trace/types'
import { buildSnapshots } from '../trace/snapshots'
import { buildScreenplay } from '../screenplay/ruleDirector'
import { buildDigest } from '../digest/buildDigest'
import { expandScreenplay } from '../player/expand'

// 기술 벤치마크 — 기획안 검증 과제. 유형별 층화 샘플 셋에 대한 파이프라인 완주·정확성 회귀 테스트.
type BenchFixture = {
  id: string
  category: string
  code: string
  expectedStdout: string
  expectedError: string | null
  events: TraceEvent[]
  clipped: boolean
  traceError?: string
}

const modules = import.meta.glob('./fixtures/*.bench.json', { eager: true }) as Record<string, { default: BenchFixture }>
const fixtures = Object.values(modules).map(m => m.default)

const results: { id: string; category: string; events: number; steps: number; ratio: number }[] = []

describe('기술 벤치마크 — 층화 샘플 셋', () => {
  it('샘플 셋이 로드된다 (9개 유형 × 2)', () => {
    expect(fixtures.length).toBe(18)
    expect(new Set(fixtures.map(f => f.category)).size).toBe(9)
  })

  for (const f of fixtures) {
    describe(`${f.category} · ${f.id}`, () => {
      const snaps = buildSnapshots(f.events)
      const screenplay = buildScreenplay(f.events)
      const steps = expandScreenplay(screenplay, snaps)
      const digest = buildDigest(f.events)
      const ratio = JSON.stringify(digest).length / JSON.stringify(f.events).length
      results.push({ id: f.id, category: f.category, events: f.events.length, steps: steps.length, ratio })

      it('파이프라인이 완주한다 (규칙 기반)', () => {
        expect(steps.length).toBeGreaterThan(0)
      })
      it('Tracer 정확성 — 기록된 stdout이 실제 실행 출력과 일치한다', () => {
        expect(snaps[snaps.length - 1].stdout).toBe(f.expectedStdout)
      })
      if (f.expectedError) {
        it(`예외가 트레이스에 기록된다 (${f.expectedError})`, () => {
          expect(f.traceError).toContain(f.expectedError)
          expect(f.events.some(e => e.kind === 'exception')).toBe(true)
        })
      }
      it('스텝 seq가 단조 증가하고 자막에 미치환 플레이스홀더가 없다', () => {
        for (let i = 1; i < steps.length; i++) expect(steps[i].seq).toBeGreaterThan(steps[i - 1].seq)
        for (const s of steps) expect(s.narration).not.toMatch(/\{\w+\}/)
      })
      it('Digest가 원본보다 작다', () => {
        expect(ratio).toBeLessThan(1)
      })
    })
  }

  afterAll(async () => {
    const avg = results.reduce((a, r) => a + r.ratio, 0) / results.length
    const summary = { count: results.length, avgDigestRatio: avg, results }
    const { writeFileSync } = await import('node:fs')
    writeFileSync(new URL('./summary.json', import.meta.url), JSON.stringify(summary, null, 2))
  })
})
