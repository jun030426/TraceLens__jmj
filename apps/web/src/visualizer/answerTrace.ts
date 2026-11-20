// 실습 답지 따라 쓰기 — 최종 제출 뒤 "답지 보기"를 누르면 답이 회색 글씨로 깔리고, 학생이 그대로 따라 써야 다음 문제로 넘어가요.
//
// 빈칸 문제: 빈칸마다 답 글자를 따라 써요. 띄어쓰기 개수와 앞뒤 공백은 따지지 않아요 ("n-1-i"와 "n - 1 - i"는 달라요).
// 직접 작성 문제: 시작 코드에 있던 머리 부분(함수 머리·class·main 줄)과 꼬리 부분(닫는 괄호·호출 줄)은 미리 놓아 주고,
//   그 사이 몸통 줄만 빈 줄로 비워 둬요. 줄 자리가 답지와 같아서 회색 글씨 바로 위에 따라 쓸 수 있어요.
//   줄 끝 공백과 끝의 빈 줄은 따지지 않고, 들여쓰기는 따져요 (Python은 들여쓰기가 코드의 일부예요).

const trimEndLines = (code: string) => {
  const lines = code.replace(/\r\n?/g, "\n").split("\n").map(l => l.replace(/\s+$/, ""));
  while (lines.length && lines[lines.length - 1] === "") lines.pop();
  return lines;
};

export type FullSkeleton = {
  /** 따라 쓰기를 시작할 때 편집기에 놓는 코드 — 머리·꼬리 줄은 채워져 있고 몸통 줄은 비어 있어요 */
  start: string;
  /** 줄마다 미리 놓아 준 줄인지 (true면 머리·꼬리, false면 학생이 따라 쓸 몸통) */
  given: boolean[];
};

/** 시작 코드와 모범 코드가 앞뒤로 같은 줄을 머리·꼬리로 보고, 나머지 몸통 줄을 비운 시작 코드를 만들어요 */
export function fullSkeleton(template: string, answer: string): FullSkeleton {
  const t = trimEndLines(template), a = trimEndLines(answer);
  let head = 0;
  while (head < t.length && head < a.length && t[head] === a[head]) head++;
  let tail = 0;
  while (tail < t.length - head && tail < a.length - head && t[t.length - 1 - tail] === a[a.length - 1 - tail]) tail++;
  const given = a.map((_, i) => i < head || i >= a.length - tail);
  return { start: a.map((line, i) => (given[i] ? line : "")).join("\n"), given };
}

/** 직접 작성 문제 따라 쓰기 진행 — 몸통 줄 중 몇 줄을 똑같이 썼는지, 전체가 답지와 같은지 */
export function fullTraceProgress(template: string, answer: string, typed: string) {
  const { given } = fullSkeleton(template, answer);
  const a = trimEndLines(answer), y = trimEndLines(typed);
  const body = a.map((_, i) => i).filter(i => !given[i]);
  const matched = body.filter(i => y[i] === a[i]).length;
  const done = y.length === a.length && y.every((line, i) => line === a[i]);
  return { matched, total: body.length, done };
}

const normBlank = (s: string | undefined) => (s ?? "").replace(/\s+/g, " ").trim();

/** 빈칸 하나를 답지와 똑같이 따라 썼는지 */
export const blankMatches = (typed: string | undefined, answer: string) => normBlank(typed) === normBlank(answer);

/** 빈칸 문제 따라 쓰기 진행 */
export function blankTraceProgress(answers: string[], typed: Record<number, string>) {
  const matched = answers.filter((a, i) => blankMatches(typed[i + 1], a)).length;
  return { matched, total: answers.length, done: answers.length > 0 && matched === answers.length };
}
