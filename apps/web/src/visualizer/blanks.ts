// 빈칸 채우기 실습 — 문제 틀(template)의 빈칸과 학생이 채운 내용을 실행할 코드로 바꾼다.
//
// 틀 문법: 코드 안의 `[[빈칸]]` 하나가 빈칸 하나다. 위에서 아래, 왼쪽에서 오른쪽 순서로 ①②③… 번호가 붙는다.
//   예) for j in range([[빈칸]]):
// 실행 규칙:
//   - 채운 빈칸은 학생이 쓴 글자로 바꾼다.
//   - 안 채운 빈칸은 실행되지 않는 자리표시 이름(`__blank1__`)으로 바꿔서 코드 전체가 문법상 읽히게 하고,
//     그 빈칸이 있는 줄을 "멈춤 줄"로 기록기에 넘긴다. 기록기는 그 줄을 실행하기 직전에 멈춘다.
//   - 그래서 빈칸 ①만 채우면 빈칸 ② 바로 앞까지 실행·시각화된다. 하나도 안 채워도 첫 빈칸 앞까지 보인다.
// 줄 번호는 바뀌지 않는다 (한 줄 안에서만 바꾼다) — 시각화의 코드 줄과 그대로 맞는다.

export const BLANK_TOKEN = /\[\[빈칸\]\]/g;

export type BlankPart = string | { blank: number };
export type BlankTemplate = {
  /** 줄마다 글자 조각과 빈칸을 순서대로 */
  lines: BlankPart[][];
  /** 빈칸 번호(1부터) → 줄 번호(1부터) */
  blanks: { n: number; line: number }[];
};

export function parseTemplate(template: string): BlankTemplate {
  const blanks: BlankTemplate["blanks"] = [];
  let n = 0;
  const lines = template.split("\n").map((text, i) => {
    const parts: BlankPart[] = [];
    let last = 0;
    for (const m of text.matchAll(BLANK_TOKEN)) {
      if (m.index! > last) parts.push(text.slice(last, m.index));
      n += 1;
      parts.push({ blank: n });
      blanks.push({ n, line: i + 1 });
      last = m.index! + m[0].length;
    }
    if (last < text.length || parts.length === 0) parts.push(text.slice(last));
    return parts;
  });
  return { lines, blanks };
}

/** 자리표시 이름 — 실행되지 않는 줄에만 남으므로 값이 필요 없다. 이름이 __로 시작해 기록기 변수 목록에도 안 잡힌다 */
export const placeholder = (n: number) => `__blank${n}__`;
export const PLACEHOLDER_RE = /__blank(\d+)__/g;

/** 학생 입력 한 칸을 한 줄로 정리 — 줄바꿈을 넣으면 줄 번호가 밀리므로 공백으로 바꾼다 */
export const cleanFill = (s: string | undefined) => (s ?? "").replace(/[\r\n]+/g, " ").trim();

export type RunnableBlanks = {
  /** 실행할 코드 (줄 수·줄 번호는 틀과 같다) */
  code: string;
  /** 멈춤 줄 → 그 줄의 첫 번째 안 채운 빈칸 번호 */
  stopLines: Record<number, number>;
  /** 아직 안 채운 빈칸 번호 */
  unfilled: number[];
};

export function buildRunnable(t: BlankTemplate, fills: Record<number, string>): RunnableBlanks {
  const stopLines: Record<number, number> = {};
  const unfilled: number[] = [];
  const code = t.lines
    .map((parts, i) =>
      parts
        .map(p => {
          if (typeof p === "string") return p;
          const text = cleanFill(fills[p.blank]);
          if (text) return text;
          unfilled.push(p.blank);
          if (stopLines[i + 1] === undefined) stopLines[i + 1] = p.blank;
          return placeholder(p.blank);
        })
        .join(""),
    )
    .join("\n");
  return { code, stopLines, unfilled };
}

/** 시각화·결과 화면에서 자리표시 이름을 학생이 아는 모양으로 되돌린다 */
export const showBlanks = (line: string) => line.replace(PLACEHOLDER_RE, (_, n) => `［빈칸 ${circled(Number(n))}］`);

export const circled = (n: number) => (n >= 1 && n <= 20 ? String.fromCodePoint(0x2460 + n - 1) : `(${n})`);
