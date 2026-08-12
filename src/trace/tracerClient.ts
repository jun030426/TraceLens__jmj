import type { TraceEvent, TraceResult } from './types'
import { MAX_EVENTS, EXEC_TIMEOUT_MS } from './types'

export type TraceStage = 'python-loading' | 'executing' | 'building'

let worker: Worker | null = null
const makeWorker = () => new Worker(new URL('./tracerWorker.ts', import.meta.url), { type: 'module' })

export function warmUp() {
  if (!worker) worker = makeWorker()
}

/** 사용자가 설정에서 올리고 내릴 수 있는 실행 상한. 넘기지 않으면 기본값을 쓴다. */
export type TraceLimits = { maxEvents?: number; timeoutMs?: number }

export function runTrace(
  code: string,
  onStage: (s: TraceStage) => void,
  limits: TraceLimits = {},
): Promise<TraceResult> {
  if (!worker) worker = makeWorker()
  const w = worker
  const maxEvents = limits.maxEvents ?? MAX_EVENTS
  const timeoutMs = limits.timeoutMs ?? EXEC_TIMEOUT_MS
  const events: TraceEvent[] = []
  return new Promise((resolve) => {
    const timeout = setTimeout(() => {
      w.terminate()
      worker = null
      finish({ events, clipped: true, error: `실행 시간이 너무 깁니다 (${Math.round(timeoutMs / 1000)}초 제한)` })
    }, timeoutMs)
    const finish = (r: TraceResult) => {
      clearTimeout(timeout)
      w.onmessage = null
      resolve(r)
    }
    w.onmessage = (e: MessageEvent) => {
      const m = e.data
      if (m.type === 'stage') onStage(m.stage)
      else if (m.type === 'chunk') {
        const parsed = JSON.parse(m.json)
        if (Array.isArray(parsed)) events.push(...parsed)
        else {
          onStage('building')
          finish({ events, clipped: parsed.clipped, error: parsed.error ?? undefined })
        }
      } else if (m.type === 'fatal') finish({ events, clipped: false, error: m.message })
    }
    w.postMessage({ code, maxEvents })
  })
}
