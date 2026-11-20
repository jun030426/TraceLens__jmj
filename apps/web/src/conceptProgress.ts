export type LearningConcept = {
  id: string;
  concept: string;
  weeks: number[];
  in_scope: boolean;
  valid_recent: number;
  correct_recent: number;
  mastered: boolean;
  learning?: {
    state: "no_data" | "insufficient" | "review" | "learning" | "mastered";
    sample: number; correct: number; success_days: number;
    weakness: number | null; trend_points: number | null;
  };
  review_due: string | null;
  review_session_id: string | null;
  review_question_id: string | null;
};

export function reviewReason(concept: LearningConcept, today: string) {
  if (!concept.in_scope || concept.valid_recent === 0) return "";
  if (concept.review_due && concept.review_due <= today)
    return "복습 권장일이 되었어요. 지난 답안과 해설을 다시 확인해 보세요.";
  if (!concept.mastered && concept.correct_recent < concept.valid_recent)
    return "최근 독립 풀이에 오답이 있어요. 답안과 해설을 비교해 보세요.";
  return "";
}

export function conceptStatus(concept: LearningConcept, _today?: string) {
  // Review reminders are advice, separate from the shared evidence classification.
  if (concept.learning) return concept.learning.state;
  if (!concept.valid_recent) return "no_data";
  if (concept.valid_recent < 5) return "insufficient";
  if (concept.mastered) return "mastered";
  return concept.correct_recent < 4 ? "review" : "learning";
}

export function suggestedConcepts(
  items: LearningConcept[],
  today: string,
  currentWeek: number | null,
) {
  const reviews = items.filter((item) => reviewReason(item, today));
  if (reviews.length)
    return {
      review: true,
      items: reviews
        .slice()
        .sort((a, b) =>
          (a.review_due || "9999").localeCompare(b.review_due || "9999"),
        )
        .slice(0, 3),
      total: reviews.length,
    };
  const current = items.filter(
    (item) =>
      item.in_scope && currentWeek != null && item.weeks.includes(currentWeek),
  );
  const candidates = current.length
    ? current
    : items.filter((item) => item.in_scope);
  return {
    review: false,
    items: candidates
      .slice()
      .sort((a, b) => a.valid_recent - b.valid_recent)
      .slice(0, 3),
    total: candidates.length,
  };
}
