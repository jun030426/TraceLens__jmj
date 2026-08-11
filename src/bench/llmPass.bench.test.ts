import { describe, it, expect, afterAll } from 'vitest'
import type { TraceEvent } from '../trace/types'
import { buildDigest } from '../digest/buildDigest'
import { buildSnapshots } from '../trace/snapshots'
import { expandScreenplay } from '../player/expand'
import { generateScreenplay } from '../director/llmDirector'
import { makeGeminiCall } from '../director/gemini'

// LLM 대본 검증 통과율 실측 — 실제 API 호출이 필요하므로 RUN_LLM_BENCH=1 일 때만 실행.
// 실행: RUN_LLM_BENCH=1 npx vitest run src/bench/llmPass.bench.test.ts

const enabled = !!process.env.RUN_LLM_BENCH

async function readApiKey(): Promise<string | undefined> {
  const { readFileSync } = await import('node:fs')
  try {
    const env = readFileSync(new URL('../../.env.local', import.meta.url), 'utf-8')
    return env.match(/^VITE_GEMINI_API_KEY=(.+)$/m)?.[1]?.trim()
  } catch {
    return undefined
  }
}

const SAMPLE_IDS = ['aliasing-basic', 'recursion-fact', 'control-while', 'mutation-dict', 'exception-index', 'class-method']
const modules = import.meta.glob('./fixtures/*.bench.json', { eager: true }) as Record<
  string,
  { default: { id: string; code: string; events: TraceEvent[] } }
>
const fixtures = Object.values(modules).map(m => m.default).filter(f => SAMPLE_IDS.includes(f.id))

const outcomes: { id: string; ok: boolean; error?: string }[] = []
const sleep = (ms: number) => new Promise(r => setTimeout(r, ms))

describe.skipIf(!enabled)('LLM 대본 검증 통과율 (Gemini 실측)', () => {
  for (const f of fixtures) {
    it(`${f.id} — 검증 통과 대본 생성`, { timeout: 90_000 }, async () => {
      const key = await readApiKey()
      expect(key, '.env.local의 VITE_GEMINI_API_KEY 필요').toBeTruthy()
      await sleep(4000)   // 무료 티어 RPM 보호
      try {
        const sp = await generateScreenplay(f.code, buildDigest(f.events), makeGeminiCall(key!))
        const steps = expandScreenplay(sp, buildSnapshots(f.events))
        expect(steps.length).toBeGreaterThan(0)
        for (const s of steps) expect(s.narration).not.toMatch(/\{\w+\}/)
        outcomes.push({ id: f.id, ok: true })
      } catch (err) {
        outcomes.push({ id: f.id, ok: false, error: String(err).slice(0, 120) })
        throw err
      }
    })
  }

  afterAll(async () => {
    if (!outcomes.length) return
    const { writeFileSync } = await import('node:fs')
    const pass = outcomes.filter(o => o.ok).length
    writeFileSync(
      new URL('./llm-summary.json', import.meta.url),
      JSON.stringify({ passRate: pass / outcomes.length, outcomes }, null, 2),
    )
  })
})
