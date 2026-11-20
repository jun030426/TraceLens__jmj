// 회색 답안 따라쓰기 표시와 문법 오류 표시용 타입. 정답 공개는 서버가 결정한다.

const BLANK = "[[빈칸]]";
/** 빈칸 틀의 [[빈칸]]을 답으로 채운 전체 코드 (서버 practice.target_code와 같아요) */
export function fillTemplate(template: string, answers: readonly string[]) {
  const parts = template.split(BLANK);
  return parts.slice(1).reduce((code, rest, i) => code + (answers[i] ?? "") + rest, parts[0]);
}

/**
 * 회색 글씨 따라쓰기 — 학생이 친 글자만큼 앞에서부터 회색 글씨가 지워져요.
 * typed: 학생이 친 부분(화면에서는 투명하게 자리만 차지) · rest: 아직 남은 회색 글씨
 * matched=false면 학생이 친 글자가 답지와 달라요 (남은 글씨를 다른 색으로 보여 줘요).
 */
export function ghostRest(target: string, typed: string): { typed: string; rest: string; matched: boolean } {
  const matched = target.startsWith(typed);
  return { typed, rest: typed.length >= target.length ? "" : target.slice(typed.length), matched };
}

/** 여러 줄 코드의 따라쓰기 — 줄마다 ghostRest */
export function ghostLines(target: string, typed: string) {
  const want = target.split("\n"), have = typed.split("\n");
  return want.map((line, i) => ghostRest(line, have[i] ?? ""));
}

/** 문법 검사 결과 한 줄 — 빨간 밑줄과 안내 문장에 써요 */
export type SyntaxIssue = { line: number | null; column?: number | null; message: string; name?: string };
