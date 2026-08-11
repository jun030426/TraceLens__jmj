import type { TraceEvent, TraceResult } from './types'
import { MAX_EVENTS, EXEC_TIMEOUT_MS } from './types'

export type TraceStage = 'python-loading' | 'executing' | 'building'

let worker: Worker | null = null
const makeWorker = () => new Worker(new URL('./tracerWorker.ts', import.meta.url), { type: 'module' })

export function warmUp() {
  if (!worker) worker = makeWorker()
}

export function runTrace(code: string, onStage: (s: TraceStage) => void): Promise<TraceResult> {
  if (!worker) worker = makeWorker()
  const w = worker
  const events: TraceEvent[] = []
  return new Promise((resolve) => {
    const timeout = setTimeout(() => {
      w.terminate()
      worker = null
      finish({ events, clipped: true, error: '실행 시간이 너무 깁니다 (10초 제한)' })
    }, EXEC_TIMEOUT_MS)
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
    w.postMessage({ code, maxEvents: MAX_EVENTS })
  })
}
