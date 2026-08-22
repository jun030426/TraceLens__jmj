import type { SyntaxErrorInfo } from '../trace/types'
import { hintFor } from './syntaxHints'

/* 구문 오류의 장면 — 실행이 0줄이므로 실행 재연은 없다. 파서가 준 사실(줄·글자 위치·
   문제 줄·메시지)만 무대에 세운다. 표시(▲)는 모노스페이스 전제의 공백 정렬 —
   파이썬 콘솔의 캐럿과 같은 방식이다. 탭은 폭이 글자 수와 어긋나므로 공백 하나로
   바꾼다 (offset은 글자 수 기준이라 정렬이 유지된다). */
export function SyntaxScene({ info }: { info: SyntaxErrorInfo }) {
  const text = info.text ? info.text.replace(/\t/g, ' ') : null
  const caretCol = info.offset === null ? null : Math.max(0, info.offset - 1)
  const hint = hintFor(info.msg)
  return (
    <div className="syntax-scene" role="alert">
      <p className="syntax-scene__head">
        파이썬이 이 코드를 <strong>읽다가 멈췄습니다</strong> — 아무것도 실행되지 않았어요
      </p>
      {text !== null && (
        <pre className="syntax-scene__code">
          <span className="syntax-scene__gutter">{info.line ?? '?'} │ </span>
          {text}
          {caretCol !== null && (
            <>
              {'\n'}
              <span className="syntax-scene__gutter" aria-hidden="true">
                {' '.repeat(String(info.line ?? '?').length)} │ </span>
              <span className="syntax-scene__caret" aria-hidden="true">
                {' '.repeat(Math.min(caretCol, 200))}▲</span>
            </>
          )}
        </pre>
      )}
      {hint && <p className="syntax-scene__hint">{hint}</p>}
      <code className="syntax-scene__raw tl-mono">
        {info.name}: {info.msg}
      </code>
    </div>
  )
}
