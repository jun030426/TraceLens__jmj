import { describe, it, expect } from 'vitest'
import { hintFor } from './syntaxHints'

/* 번역은 충실하게 — 파서가 말한 것만 옮기고, 추측성 진단은 넣지 않는다.
   표에 없는 메시지는 null → 화면은 원문만 보여준다 (지어내지 않는다) */
describe('syntaxHints: 파서 메시지의 학습자 번역', () => {
  it('흔한 메시지를 학습자 말로 옮긴다', () => {
    expect(hintFor("expected ':'")).toBe('여기에 콜론(:)이 와야 합니다')
    expect(hintFor('invalid syntax')).toBe('파이썬이 알아볼 수 없는 문장입니다')
    expect(hintFor('unexpected indent')).toBe('들여쓰기가 예상보다 깊습니다')
    expect(hintFor('unindent does not match any outer indentation level')).toBe('들여쓰기 깊이가 위쪽과 맞지 않습니다')
    expect(hintFor("expected an indented block after 'if' statement on line 1")).toBe('이 줄 아래에 들여쓴 블록이 필요합니다')
  })

  it('닫히지 않은 괄호·따옴표 — 무엇이 열려 있는지 그대로 전한다', () => {
    expect(hintFor("'(' was never closed")).toBe("'(' 가 닫히지 않았습니다")
    expect(hintFor("'[' was never closed")).toBe("'[' 가 닫히지 않았습니다")
    expect(hintFor('unterminated string literal (detected at line 3)')).toBe('따옴표가 닫히지 않았습니다')
  })

  it('전각 문자 — AI 채팅 복붙의 단골이라 글자를 그대로 보여준다', () => {
    expect(hintFor("invalid character '：' (U+FF1A)")).toBe(
      "쓸 수 없는 글자입니다: '：' — 채팅·문서에서 복사하면 전각 문자가 섞이기도 합니다",
    )
  })

  it('표에 없는 메시지는 번역하지 않는다 — 원문이 정직하다', () => {
    expect(hintFor('cannot assign to literal here')).toBeNull()
    expect(hintFor('')).toBeNull()
  })
})
