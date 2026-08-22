/* 파서 메시지의 학습자 번역 — 흔한 것만, 충실하게.
   추측성 진단("~하려던 것 아닌가요")은 넣지 않고, 표에 없으면 null — 화면은 원문만 보여준다.
   원문은 항상 병기되므로 번역이 틀릴 수 있는 자리가 아니라 덧붙이는 자리다. */

const TABLE: [RegExp, (m: RegExpMatchArray) => string][] = [
  [/^expected ':'/, () => '여기에 콜론(:)이 와야 합니다'],
  [/^invalid syntax/, () => '파이썬이 알아볼 수 없는 문장입니다'],
  [/^unexpected indent/, () => '들여쓰기가 예상보다 깊습니다'],
  [/^unindent does not match/, () => '들여쓰기 깊이가 위쪽과 맞지 않습니다'],
  [/^expected an indented block/, () => '이 줄 아래에 들여쓴 블록이 필요합니다'],
  [/^'(.+)' was never closed/, m => `'${m[1]}' 가 닫히지 않았습니다`],
  [/^unterminated (?:triple-quoted )?string/, () => '따옴표가 닫히지 않았습니다'],
  // AI 채팅·문서 복붙의 단골 — 전각 콜론(：)·따옴표(")·마이너스(−) 같은 것들
  [/^invalid character '(.+?)'/, m => `쓸 수 없는 글자입니다: '${m[1]}' — 채팅·문서에서 복사하면 전각 문자가 섞이기도 합니다`],
]

export function hintFor(msg: string): string | null {
  for (const [re, render] of TABLE) {
    const m = msg.match(re)
    if (m) return render(m)
  }
  return null
}
