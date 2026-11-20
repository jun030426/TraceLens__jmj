// 브라우저 예시 출력 비교. 최종 채점은 서버의 여러 입력 검증으로 결정한다.
//
// 정답 비교는 "빈칸 글자"가 아니라 "실행 결과(출력)"로 한다. 그래야 `n - 1 - i`와 `n - i - 1`처럼
// 다르게 썼어도 같은 일을 하는 답을 정답으로 인정할 수 있다.
// 틀린 경우는 네 가지로 나눈다: 문법이 틀림(빈칸을 짚는다) · 실행 중 오류 · 끝나지 않음 · 결과가 다름.
import type { PracticeRun } from "./practiceRun.ts";
import { circled } from "./blanks.ts";

export type BlankVerdict =
  | { kind: "correct"; title: string; text: string }
  | { kind: "syntax" | "runtime" | "endless" | "wrong"; title: string; text: string; badBlanks: number[]; expected?: string; actual?: string };

/** 줄 끝 공백·마지막 빈 줄은 비교에서 뺀다 */
export const normalizeOutput = (s: string) => s.replace(/\r/g, "").split("\n").map(l => l.replace(/\s+$/, "")).join("\n").replace(/\n+$/, "");

const blanksOn = (blanks: readonly { n: number; line: number }[], line: number | null | undefined) =>
  line ? blanks.filter(b => b.line === line).map(b => b.n) : [];

const names = (ns: number[]) => ns.map(circled).join("·");

/**
 * run: 이번 실행 기록 / unfilled: 아직 안 채운 빈칸 / blanks: 빈칸 번호 → 줄 / expected: 문제의 정답 출력.
 * 빈칸이 남아 있으면(빈칸 앞에서 멈춘 실행) 아직 채점하지 않는다 — null.
 */
export function checkBlanks(run: PracticeRun | null, unfilled: readonly number[], blanks: readonly { n: number; line: number }[], expected: string | undefined): BlankVerdict | null {
  // An unfilled control-flow line can make the remaining starter code invalid.
  // This is an incomplete template, not a syntax mistake in a submitted answer.
  if (!run || run.kind === "blocked" || unfilled.length > 0) return null;
  if (run.kind === "syntax") {
    const bad = blanksOn(blanks, run.info.line);
    return {
      kind: "syntax",
      title: bad.length ? `틀렸어요 · 빈칸 ${names(bad)}의 코드가 문법에 맞지 않아요` : "틀렸어요 · 코드가 문법에 맞지 않아요",
      text: `${run.info.line ? `${run.info.line}번째 줄을 읽지 못했어요. ` : ""}괄호·따옴표·콜론(:)이 빠지지 않았는지, 변수 이름을 바르게 썼는지 확인해 보세요.`,
      badBlanks: bad,
    };
  }
  if (run.blankStop) return null;
  if (run.error) {
    const last = run.trace?.steps[run.trace.steps.length - 1];
    const line = last?.event === "exception" ? last.causedByLine ?? last.nextLine : null;
    const bad = blanksOn(blanks, line);
    return {
      kind: "runtime",
      title: bad.length ? `틀렸어요 · 빈칸 ${names(bad)}이 있는 줄에서 오류가 났어요` : "틀렸어요 · 실행 중에 오류가 났어요",
      text: `${line ? `${line}번째 줄에서 멈췄어요. ` : ""}시각화의 "⚠ 오류 장면"에서 어디서 왜 멈췄는지 확인해 보세요.`,
      badBlanks: bad,
    };
  }
  if (run.clipped) return { kind: "endless", title: "틀렸어요 · 실행이 끝나지 않아요", text: "반복이 멈추지 않는 것 같아요. 반복 범위나 조건을 쓴 빈칸을 다시 확인해 보세요.", badBlanks: [] };
  if (expected === undefined) return null;
  const actual = normalizeOutput(run.stdout);
  const want = normalizeOutput(expected);
  if (actual === want) return { kind: "correct", title: "예시 출력이 같아요", text: "예시 입력의 출력이 일치해요. 최종 제출하면 다른 입력으로도 채점해요." };
  return {
    kind: "wrong",
    title: "틀렸어요 · 실행은 됐지만 결과가 달라요",
    text: "시각화를 처음부터 재생하면서 값이 언제부터 기대와 달라지는지 찾아보세요.",
    badBlanks: [],
    expected: want,
    actual: actual || "(출력 없음)",
  };
}
