import type { ExecutionTrace } from '../pythonTrace.ts'
import type { SourceLang } from './film/sourceRules.ts'
import type { StopLines, TraceStage } from './trace/tracerClient.ts'
import type { SyntaxErrorInfo } from './trace/types.ts'
import { toExecutionTrace } from './toExecutionTrace.ts'
import { traceCode } from './traceCode.ts'

export type PracticeLanguage = 'Python' | 'Java' | 'C'
const LANG: Record<PracticeLanguage, SourceLang> = { Python: 'python', Java: 'java', C: 'c' }

export const STAGE_LABEL: Record<TraceStage, string> = {
  'python-loading': '파이썬 실행 환경을 준비하고 있어요…',
  executing: '코드를 한 줄씩 실행하고 있어요…',
  building: '실행 기록을 장면으로 바꾸고 있어요…',
}

/** 한 번의 "코드 실행" 결과 — 실행 결과 탭과 시각화 탭이 같은 기록을 나눠 쓴다 */
export type PracticeRun =
  | { kind: 'ran'; code: string; stdout: string; error?: string; clipped: boolean; trace: ExecutionTrace | null; blankStop?: { blank: number; line: number } }
  | { kind: 'syntax'; code: string; info: SyntaxErrorInfo }
  | { kind: 'blocked'; code: string; text: string }

/**
 * 코드 실행 = 실행 기록 한 번. 출력·오류와 시각화용 공통 실행 기록(ExecutionTrace)을 같은 기록에서 만든다.
 * 제출·채점이 아니다 (docs/06). Python은 브라우저에서, Java·C는 격리 샌드박스에서만 돈다.
 */
export async function runPractice(
  language: PracticeLanguage,
  code: string,
  sectionId: string,
  onStage: (s: TraceStage) => void,
  stopLines: StopLines = {},
): Promise<PracticeRun> {
  const lang = LANG[language]
  try {
    let r = await traceCode(lang, code, sectionId, onStage, stopLines)
    if (lang === 'python' && r.syntaxError && Object.keys(stopLines).length) {
      const firstLine = Math.min(...Object.keys(stopLines).map(Number))
      if (r.syntaxError.line !== null && r.syntaxError.line >= firstLine) {
        const lines = code.split('\n')
        const indent = lines[firstLine - 1].match(/^[ \t]*/)?.[0] ?? ''
        // Keep the original source for the scene, but compile only the prefix and
        // a stop marker so a missing block header cannot block earlier steps.
        const prefix = [...lines.slice(0, firstLine - 1), indent + 'pass'].join('\n')
        const partial = await traceCode(lang, prefix, sectionId, onStage, { [firstLine]: stopLines[firstLine] })
        if (partial.stoppedAtBlank || (partial.error && partial.events.length)) r = partial
      }
    }
    if (r.blocked) return { kind: 'blocked', code, text: r.blocked }
    if (r.syntaxError) return { kind: 'syntax', code, info: r.syntaxError }
    onStage('building')
    return {
      kind: 'ran',
      code,
      stdout: r.events.map(e => e.stdout).join(''),
      error: r.error,
      clipped: r.clipped,
      ...(r.stoppedAtBlank ? { blankStop: r.stoppedAtBlank } : {}),
      trace: r.events.length > 0 ? toExecutionTrace(lang, r.events, { clipped: r.clipped, error: r.error, blankStop: r.stoppedAtBlank }) : null,
    }
  } catch (err) {
    return { kind: 'blocked', code, text: err instanceof Error ? err.message : String(err) }
  }
}
