import { api, post } from '../api.ts'
import { getTestRole } from '../testAccess.ts'
import type { SourceLang } from './film/sourceRules.ts'
import { preflight } from './trace/preflight.ts'
import { runTrace, type StopLines, type TraceStage } from './trace/tracerClient.ts'
import type { TraceEvent, TraceResult } from './trace/types.ts'

export type TraceOutcome = TraceResult & { blocked?: string }

/** 서버 TraceEnvelope (snake_case, docs/06 실행 기록 계약) */
type Envelope = {
  language: string
  status: string
  events: Array<Record<string, unknown>>
  clipped: boolean
  error: string | null
  compile_error: { line: number | null; column: number | null; message: string; text: string | null; name?: string } | null
}

const toEvent = (e: Record<string, unknown>): TraceEvent => ({
  seq: e.seq as number,
  kind: e.kind as TraceEvent['kind'],
  frameId: e.frame_id as number,
  parentFrameId: e.parent_frame_id as number | null,
  func: e.func as string,
  causedByLine: e.caused_by_line as number | null,
  observedAtLine: e.observed_at_line as number,
  localsDelta: e.locals_delta as TraceEvent['localsDelta'],
  objectsDelta: e.objects_delta as TraceEvent['objectsDelta'],
  stdout: (e.stdout as string) ?? '',
  ...(e.error ? { error: e.error as string } : {}),
  ...(e.returned ? { returned: e.returned as TraceEvent['returned'] } : {}),
})

/**
 * 수업 언어 하나로 기록 경로를 고른다. 학생이 언어를 고르지 않는다.
 * - Python: 학생 브라우저의 Pyodide (서버에서 실행하지 않는다)
 * - Java·C: 서버가 격리 컨테이너에서 JDI·gdb로 기록한다. 격리 환경이 꺼져 있으면 서버가 503으로 거절한다.
 * 어느 쪽도 제출·채점이 아니다.
 */
export async function traceCode(
  lang: SourceLang,
  code: string,
  sectionId: string,
  onStage: (s: TraceStage) => void,
  stopLines: StopLines = {},
): Promise<TraceOutcome> {
  if (lang === 'python') {
    const blocking = preflight(code).find(i => i.level === 'block')
    if (blocking) return { events: [], clipped: false, blocked: blocking.message }
    return runTrace(code, onStage, {}, stopLines)
  }
  // 빈칸 앞에서 멈추기는 아직 Python(브라우저 기록기)만 된다 — Java·C 서버 기록기는 멈춤 줄을 모른다
  if (Object.keys(stopLines).length > 0)
    return { events: [], clipped: false, blocked: 'Java·C 실습은 빈칸을 모두 채우면 실행할 수 있어요. (빈칸 앞까지 미리 보기는 Python에서 먼저 지원해요)' }
  // 테스트 화면은 서버에 아무것도 보내지 않는다 (api.ts의 테스트 모드 규칙)
  if (getTestRole())
    return { events: [], clipped: false, blocked: '테스트 화면에서는 Java·C 코드를 실행하지 않아요. 실제 강의실에서 격리 실행 환경이 준비되면 실행할 수 있어요.' }
  onStage('executing')
  const env = await api<Envelope>(`/sections/${sectionId}/practice/trace`, post({ source: code }))
  onStage('building')
  const lines = code.split('\n')
  const ce = env.compile_error
  return {
    events: env.events.map(toEvent),
    clipped: env.clipped,
    error: env.error ?? undefined,
    syntaxError: ce
      ? {
          name: ce.name ?? '컴파일 오류',
          line: ce.line,
          offset: ce.column,
          text: ce.text ?? (ce.line ? (lines[ce.line - 1] ?? null) : null),
          msg: ce.message,
        }
      : undefined,
  }
}
