/* 이론 문항 유형 이름표. 오늘의 이론 퀴즈는 객관식 5문항이에요 (빈칸·OX는 예전 문항 표시용). */
const KIND_LABELS: Record<string, string> = { mcq: "객관식", essay: "서술형", blank: "빈칸 채우기", ox: "OX" };

export const kindLabel = (kind: string) => KIND_LABELS[kind] || "문항";
export const isChoice = (kind: string) => kind === "mcq" || kind === "ox";

export function answerGuide(kind: string) {
  if (kind === "mcq") return "정답이라고 생각하는 보기 하나를 선택해 주세요.";
  if (kind === "ox") return "맞으면 O, 틀리면 X를 골라 주세요.";
  if (kind === "blank") return "____ 자리에 들어갈 말을 적어 주세요.";
  return "배운 내용을 자신의 말로 설명해 주세요.";
}
