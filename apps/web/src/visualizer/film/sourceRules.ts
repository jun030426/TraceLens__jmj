// 소스 어휘 규칙 — 안무가 소스 줄에서 읽는 것(비교식·대입·반복문)의 언어별 모양.
// 값은 여전히 트레이스에서만 온다. 여기서는 "이 줄이 무엇을 판단·대입하는 줄인가"만 읽는다.
export type SourceLang = 'python' | 'java' | 'c'

const cLike = (lang: SourceLang) => lang === 'java' || lang === 'c'

/** 주석·문자열 리터럴을 걷어낸 줄 — 파이썬의 `//`는 나눗셈이라 Java·C에서만 주석으로 본다 */
export function stripNoise(line: string, lang: SourceLang = 'python'): string {
  if (!cLike(lang)) return line.split('#')[0].replace(/'[^']*'|"[^"]*"/g, '""')
  if (/^\s*#/.test(line)) return '' // 전처리 지시문 (#include …)
  return line
    .replace(/"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'/g, '""')
    .replace(/\/\*.*?\*\//g, '')
    .split('//')[0]
}

/** 그 줄이 실제로 판단하는 식 — 조건문이면 조건, 대입이면 우변 */
export function judgedExpr(line: string, lang: SourceLang = 'python'): string {
  const t = stripNoise(line, lang).trim()
  if (!cLike(lang)) {
    const c = /^(?:el)?if\s+(.*):$/.exec(t) ?? /^while\s+(.*):$/.exec(t)
    if (c) return c[1].trim()
    const a = /^[A-Za-z_]\w*(?:\[[^\]]+\])?\s*=\s*(.*)$/.exec(t)
    if (a) return a[1].trim()
    return t
  }
  const c = /^(?:\}\s*)?(?:else\s+)?(?:if|while)\s*\((.*)\)\s*\{?\s*\}?$/.exec(t)
  if (c) return c[1].trim()
  const s = normalizeStmt(t, lang)
  const a = /^[A-Za-z_]\w*(?:\[[^\]]+\])?\s*=\s*(.*)$/.exec(s)
  if (a) return a[1].trim()
  return s
}

const DECL = new RegExp(
  '^(?:(?:final|const|static|unsigned|signed|register)\\s+)*' +
    '(?:int|long|short|char|double|float|boolean|bool|byte|String|var|size_t)' +
    '(?:\\s*\\[\\s*\\])?\\s+(?=[A-Za-z_])',
)

/** Java·C 문장을 파이썬식 단문으로 — `int t = arr[j];` → `t = arr[j]`. 파이썬은 그대로 */
export function normalizeStmt(stmt: string, lang: SourceLang = 'python'): string {
  if (!cLike(lang)) return stmt
  return stmt.trim().replace(/;\s*$/, '').replace(DECL, '').trim()
}

export type SrcLoop = { header: number; end: number; name?: string }

/** 사용자 소스의 반복문 — 헤더 줄과 몸통 끝 줄(1-기준). 몸통을 못 찾으면 침묵한다 */
export function parseLoops(lines: string[], lang: SourceLang = 'python'): SrcLoop[] {
  return cLike(lang) ? parseBraceLoops(lines, lang) : parseIndentLoops(lines)
}

function parseIndentLoops(lines: string[]): SrcLoop[] {
  const out: SrcLoop[] = []
  const indentOf = (t: string) => t.length - t.trimStart().length
  const skip = (t: string) => t.trim() === '' || t.trim().startsWith('#')
  lines.forEach((line, i) => {
    const m = /^(\s*)(for|while)\b(.*):\s*(#.*)?$/.exec(line)
    if (!m) return
    const ind = m[1].length
    let end = 0
    for (let k = i + 1; k < lines.length; k++) {
      if (skip(lines[k])) continue
      if (indentOf(lines[k]) <= ind) break
      end = k + 1
    }
    if (!end) return // 몸통을 못 찾았다 (한 줄 루프 등) — 지어내지 않고 침묵
    // 튜플 언패킹(`for dr, dc in ...`)까지 읽는다 — BFS처럼 바깥이 `while`(이름 없음)이면
    // 둘 다 숫자만 남아 4 → 1 → 2가 근거 없이 널뛰는 것으로 보인다 (실측)
    const t = m[2] === 'for' ? /^\s*([A-Za-z_]\w*(?:\s*,\s*[A-Za-z_]\w*)*)\s+in\s/.exec(m[3]) : null
    out.push({ header: i + 1, end, ...(t ? { name: t[1].replace(/\s*,\s*/g, ', ') } : {}) })
  })
  return out
}

// 중괄호 언어 — 헤더 뒤 첫 `{`부터 짝이 맞는 `}`까지가 몸통. 중괄호가 없으면 다음 한 문장.
function parseBraceLoops(lines: string[], lang: SourceLang): SrcLoop[] {
  const out: SrcLoop[] = []
  const clean = lines.map(l => stripNoise(l, lang))
  clean.forEach((line, i) => {
    const m = /^\s*(?:\}\s*)?(for|while)\s*\((.*)$/.exec(line)
    if (!m) return
    if (/\)\s*;\s*$/.test(line) && m[1] === 'while' && /^\s*\}/.test(line)) return // do { } while (...);
    const t =
      m[1] === 'for' ? /^\s*(?:[A-Za-z_][\w<>[\]]*\s+)?([A-Za-z_]\w*)\s*(?:=|:)/.exec(m[2]) : null
    const name = t ? { name: t[1] } : {}
    // 헤더 줄의 괄호가 닫힌 뒤에서 몸통을 찾는다
    let depth = 0
    let k = i
    let col = line.indexOf('(')
    let opened = false
    let end = 0
    for (; k < clean.length && !end; k++, col = 0) {
      const text = clean[k]
      for (let c = col; c < text.length; c++) {
        const ch = text[c]
        if (!opened) {
          if (ch === '(') depth++
          else if (ch === ')') {
            depth--
            if (depth === 0) {
              opened = true
              const rest = text.slice(c + 1)
              if (/^\s*;/.test(rest)) return // 빈 몸통 (while (x);)
              if (/^\s*\{/.test(rest)) {
                depth = 0
                continue
              }
              if (rest.trim()) {
                end = k + 1 // 같은 줄 한 문장 몸통
                break
              }
              // 다음 줄이 `{`인지 한 문장인지
              let n = k + 1
              while (n < clean.length && clean[n].trim() === '') n++
              if (n >= clean.length) return
              if (!clean[n].trim().startsWith('{')) {
                end = n + 1
                break
              }
            }
          }
          continue
        }
        if (ch === '{') depth++
        else if (ch === '}') {
          depth--
          if (depth === 0) {
            end = k + 1
            break
          }
        }
      }
    }
    if (end <= i + 1) return // 한 줄 루프 — 회차를 셀 몸통 줄이 없다 (파이썬과 같은 침묵)
    out.push({ header: i + 1, end, ...name })
  })
  return out
}
