// Synthetic fixtures for the opt-in local student demo. No server requests or persistent records.
import { BLANK_QUIZZES, type QuizLanguage } from "./blankQuizzes";

const attempts = new Map<string, {
  id: string;
  practice_session_id: string;
  exercise_id: string;
  status: string;
  correct: null;
  independent: boolean;
  source: string;
  created_at: string;
  feedback: { message: string };
  exercise: { title: string; kind: "blank" | "full" };
}>();
const hintsUsed = new Map<string, number>();
const all = Object.values(BLANK_QUIZZES).flat();
const hintsByExercise: Record<string, string[]> = {
  "py-bubble": [
    "한 바퀴가 끝날 때마다 가장 큰 수가 뒤쪽에 자리 잡아요.",
    "이미 정렬된 뒤쪽 칸은 다음 반복에서 비교 범위에서 빼 보세요.",
    "두 값의 순서가 반대라면 서로의 위치를 바꿔 보세요.",
  ],
  "py-average": [
    "아직 점수를 더하지 않았을 때의 합계를 생각해 보세요.",
    "반복할 때마다 현재 점수를 합계에 더해 보세요.",
  ],
};

export function previewPractice(path: string, options: RequestInit) {
  const url = new URL(path, "http://preview.local");
  const route = url.pathname.match(/^\/sections\/([^/]+)\/practice\/(daily|attempts|help|submit)$/);
  if (!route) return undefined;
  const [, section, action] = route;
  const plan = `preview-practice-${section}`;
  if (action === "daily") {
    const language: QuizLanguage = section === "s3" ? "Java" : "Python";
    const quizzes = BLANK_QUIZZES[language];
    const items = quizzes.filter(q => q.kind !== "full").slice(0, 2).map(q => {
      const { answers, hints, ...item } = q;
      return {
        ...item,
        variants: {
          blank: { exercise_id: q.id, template: q.template, hint_steps: hintsByExercise[q.id]?.length ?? 1 },
          full: { exercise_id: `${q.id}-full`, template: q.template.split("\n")[0], hint_steps: hintsByExercise[q.id]?.length ?? 1 },
        },
      };
    });
    return { id: plan, status: "ready", items };
  }
  if (action === "attempts") return { items: [...attempts.values()].filter(a => a.practice_session_id === plan) };

  const body = JSON.parse(String(options.body ?? "{}"));
  const exercise = all.find(q => q.id === String(body.exercise_id).replace(/-full$/, ""));
  if (!exercise) throw new Error("테스트 실습 문제를 찾지 못했어요.");
  const key = `${plan}:${exercise.id}`;
  if (action === "help") {
    if (body.kind === "answer") {
      if (!attempts.has(key)) throw new Error("최종 제출 후 답지를 확인할 수 있어요.");
      return { answers: exercise.answers ?? [] };
    }
    const hints = exercise.hints ?? hintsByExercise[exercise.id] ?? ["예시 출력과 코드가 처리해야 할 값을 비교해 보세요."];
    const used = hintsUsed.get(key) ?? 0;
    const next = body.kind === "hint" ? Math.min(used + 1, hints.length) : used;
    hintsUsed.set(key, next);
    return { hints_used: next, hints: hints.slice(0, next), max_hint_steps: hints.length, can_view_answer: attempts.has(key) };
  }
  if (attempts.has(key)) throw new Error("이미 제출한 문제예요.");
  const attempt = {
    id: key,
    practice_session_id: plan,
    exercise_id: String(body.exercise_id),
    status: "submitted",
    correct: null,
    independent: !hintsUsed.get(key),
    source: String(body.source ?? ""),
    created_at: new Date().toISOString(),
    feedback: { message: "미리보기에서 제출을 확인했어요." },
    exercise: { title: exercise.title, kind: String(body.exercise_id).endsWith("-full") ? "full" as const : "blank" as const },
  };
  attempts.set(key, attempt);
  return attempt;
}
