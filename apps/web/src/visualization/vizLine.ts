// 시각화가 지금 보여 주는 코드 줄 — 재생 화면 밖(예: 실습 페이지의 빈칸 편집기)에서도 같은 줄을 표시하려고 알린다.
import { createContext } from "react";
import type { Recording } from "./contracts";

export type VizLineKind = "next" | "ran" | "error" | "blank";
export type VizLine = { line: number; kind: VizLineKind; step: number; total: number };

/** 받는 쪽이 없으면 null — 그때는 아무것도 알리지 않는다 */
export const VizLineContext = createContext<((v: VizLine | null) => void) | null>(null);

type Step = Recording["steps"][number];

/** 이 단계에서 시각화가 가리키는 줄 — 오류 줄 > 빈칸 멈춤 줄 > 방금 실행한 줄 > 다음에 실행할 줄 */
export function vizLineOf(recording: Recording, current: Step | null): VizLine | null {
  if (!current) return null;
  const step = current.index + 1;
  const total = recording.steps.length;
  if (current.event === "exception") {
    const line = current.causedByLine ?? current.nextLine;
    return line ? { line, kind: "error", step, total } : null;
  }
  if (recording.blankStop && current.index === total - 1) return { line: recording.blankStop.line, kind: "blank", step, total };
  if (current.causedByLine) return { line: current.causedByLine, kind: "ran", step, total };
  if (current.nextLine) return { line: current.nextLine, kind: "next", step, total };
  return null;
}

export const VIZ_LINE_WORD: Record<VizLineKind, string> = {
  next: "실행할 줄",
  ran: "시각화 중",
  error: "오류",
  blank: "빈칸 앞 멈춤",
};
