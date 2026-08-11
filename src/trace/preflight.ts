export type PreflightIssue = { level: 'block' | 'warn'; code: string; message: string }

const BLOCKED_MODULES = /^\s*(?:import|from)\s+(requests|urllib|socket|http|django|flask|numpy|pandas|sqlite3|psycopg2)\b/m

export function preflight(source: string): PreflightIssue[] {
  const issues: PreflightIssue[] = []
  const add = (level: 'block' | 'warn', code: string, message: string) =>
    issues.push({ level, code, message })

  if (/\binput\s*\(/.test(source))
    add('block', 'input', '입력 대기 코드(input)는 아직 지원하지 않아요.')
  if (/\basync\s+def\b|\bawait\b|^\s*(?:import|from)\s+threading\b|\byield\b/m.test(source))
    add('block', 'unsupported-model', '이 실행 모델(async/generator/thread)은 아직 지원하지 않아요.')
  if (BLOCKED_MODULES.test(source) || /\bopen\s*\(/.test(source))
    add('block', 'external-dep', '브라우저 실행 환경에서는 네트워크·파일·외부 라이브러리를 사용할 수 없어요. 표준 문법 중심 코드를 넣어주세요.')
  if (/\bself\b/.test(source) && !/^\s*class\s/m.test(source))
    add('warn', 'fragment', '클래스 없이 self를 쓰는 조각 코드 같아요. 독립 실행 가능한 형태로 잘라서 넣어주세요.')

  const topLines = source.split(/\r?\n/).filter(l => l.trim() && !/^\s/.test(l))
  const onlyDefs = topLines.length > 0 &&
    topLines.every(l => /^(def |class |import |from |#|@)/.test(l))
  if (onlyDefs)
    add('warn', 'no-invocation', '실행되는 부분이 없어요 — 호출 예시를 한 줄 추가해 주세요. (예: print(f(...)))')

  return issues
}
