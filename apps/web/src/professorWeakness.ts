// Professor review decisions use only the existing recent-five theory evidence.
export type Signal = {
  id: string;
  name: string;
  state: string;
  sample: number;
  correct: number;
  success_days: number;
  weakness: number | null;
  trend_points: number | null;
};
export type ReviewStudent = {
  id: string;
  name: string;
  active: boolean;
  concept_signals: Signal[];
  theory: { accuracy: number | null };
  last_activity_at: string | null;
};
export const REVIEW_STATES = [
  "review",
  "insufficient",
  "learning",
  "mastered",
  "no_data",
] as const;
export type ReviewState = (typeof REVIEW_STATES)[number];
export const REVIEW_LABEL: Record<ReviewState, string> = {
  review: "복습 필요",
  insufficient: "표본 부족",
  learning: "추가 확인",
  mastered: "확인한 개념 충족",
  no_data: "이론 기록 없음",
};
export function signalsFor(student: ReviewStudent, concept = "") {
  return (student.concept_signals || []).filter(
    (c) => !concept || c.id === concept,
  );
}
export function reviewState(signals: Signal[]): ReviewState {
  return (
    REVIEW_STATES.find((state) => signals.some((c) => c.state === state)) ||
    "no_data"
  );
}
export function prioritySignals(signals: Signal[]) {
  const rank = (state: string) => {
    const i = REVIEW_STATES.indexOf(state as ReviewState);
    return i < 0 ? 5 : i;
  };
  return [...signals].sort(
    (a, b) =>
      rank(a.state) - rank(b.state) ||
      (b.weakness ?? -1) - (a.weakness ?? -1) ||
      a.name.localeCompare(b.name, "ko") ||
      a.id.localeCompare(b.id),
  );
}
export function reviewCounts(students: ReviewStudent[], concept = "") {
  const counts: Record<string, number> = {
    all: students.length,
    ...Object.fromEntries(REVIEW_STATES.map((s) => [s, 0])),
  };
  for (const student of students)
    counts[reviewState(signalsFor(student, concept))]++;
  return counts;
}
export function reviewStudents<T extends ReviewStudent>(
  students: T[],
  options: { search: string; concept: string; scope: string; sort: string },
) {
  const needle = options.search.trim().toLocaleLowerCase();
  const filtered = students
    .filter(
      (s) =>
        !needle ||
        [s.name, ...signalsFor(s, options.concept).map((c) => c.name)].some(
          (v) => v.toLocaleLowerCase().includes(needle),
        ),
    )
    .filter(
      (s) =>
        options.scope === "all" ||
        reviewState(signalsFor(s, options.concept)) === options.scope,
    );
  const worst = (s: T) =>
    Math.max(
      -1,
      ...signalsFor(s, options.concept)
        .filter((c) => c.state === "review")
        .map((c) => c.weakness ?? -1),
    );
  return filtered.sort((a, b) => {
    if (options.sort === "name")
      return a.name.localeCompare(b.name, "ko") || a.id.localeCompare(b.id);
    if (options.sort === "recent")
      return (
        (b.last_activity_at || "").localeCompare(a.last_activity_at || "") ||
        a.name.localeCompare(b.name, "ko")
      );
    if (options.sort === "accuracy")
      return (
        (a.theory.accuracy ?? 101) - (b.theory.accuracy ?? 101) ||
        a.name.localeCompare(b.name, "ko")
      );
    return (
      REVIEW_STATES.indexOf(reviewState(signalsFor(a, options.concept))) -
        REVIEW_STATES.indexOf(reviewState(signalsFor(b, options.concept))) ||
      worst(b) - worst(a) ||
      signalsFor(b, options.concept).filter((c) => c.state === "review")
        .length -
        signalsFor(a, options.concept).filter((c) => c.state === "review")
          .length ||
      a.name.localeCompare(b.name, "ko") ||
      a.id.localeCompare(b.id)
    );
  });
}
export function signalNote(signal: Signal) {
  if (signal.state === "no_data") return "채점된 독립 풀이가 없어요.";
  if (signal.sample < 5)
    return `독립 풀이 ${signal.sample}/5건 · 아직 취약도를 판단하지 않아요.`;
  if (signal.state === "learning")
    return `최근 5건 중 ${signal.correct}건 정답 · 다른 날짜의 풀이를 더 확인해요.`;
  return `최근 5건 중 ${5 - signal.correct}건 오답 · ${signal.correct}건 정답`;
}
