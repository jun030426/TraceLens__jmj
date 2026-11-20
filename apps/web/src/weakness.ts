import type { LearningConcept } from "./conceptProgress";
export type Band = "weak" | "insufficient" | "learning" | "strong" | "none";
export const BAND_LABEL: Record<Band, string> = {
  weak: "복습 필요",
  insufficient: "표본 부족",
  learning: "추가 확인",
  strong: "기준 충족",
  none: "이론 기록 없음",
};
export function weaknessSummary(items: LearningConcept[]) {
  const counts: Record<Band, number> = {
    weak: 0,
    insufficient: 0,
    learning: 0,
    strong: 0,
    none: 0,
  };
  const order: Record<Band, number> = {
    weak: 0,
    insufficient: 1,
    learning: 2,
    strong: 3,
    none: 4,
  };
  const rings = items
    .map((c) => {
      const state = c.learning?.state;
      // An older response without the shared evidence must never invent mastery or a score.
      const band: Band =
        state === "review"
          ? "weak"
          : state === "mastered"
            ? "strong"
            : state === "learning"
              ? "learning"
              : state === "insufficient" || c.valid_recent > 0
                ? "insufficient"
                : "none";
      counts[band]++;
      return {
        id: c.id,
        concept: c.concept,
        band,
        pct: c.learning && c.learning.sample >= 5 ? c.learning.weakness : null,
        solved: c.learning?.sample ?? c.valid_recent,
        correct: c.learning?.correct ?? c.correct_recent,
      };
    })
    .sort(
      (a, b) =>
        order[a.band] - order[b.band] ||
        (b.pct ?? -1) - (a.pct ?? -1) ||
        a.concept.localeCompare(b.concept, "ko"),
    );
  return { counts, rings };
}
export function weaknessHeadline(s: ReturnType<typeof weaknessSummary>) {
  if (s.counts.weak) return `복습이 필요한 개념이 ${s.counts.weak}개 있어요`;
  if (s.counts.insufficient) return "풀이 기록을 조금 더 쌓아 주세요";
  if (s.counts.learning) return "다른 날에도 이해도를 확인해 보세요";
  if (s.counts.none || !s.rings.length)
    return "아직 확인하지 않은 개념이 있어요";
  return "확인한 개념이 기준을 충족했어요";
}
