/* [XP · 등급] 경험치 규칙과 등급 기준 — 숫자를 바꾸고 싶으면 이 파일만 고치면 돼요.
   성적이 아니라 "얼마나 꾸준히 참여했는지"를 보여 주는 재미용 등급이에요.
   그래서 정답·오답에 따라 XP를 다르게 주지 않고, 제출과 연속 학습에만 XP를 줘요.
   - XP_RULES: 무엇을 하면 몇 XP를 주는지
   - GRADES: 몇 XP부터 어떤 등급(마스코트)인지 — 낮은 등급부터 순서대로 적어요
   - computeXp(): 서버의 이론·실습 제출과 연속 학습 기록으로 XP를 계산해요. */

export const XP_RULES = {
  /** 오늘의 이론 퀴즈를 모두 제출했을 때 (맞았는지와 상관없이 같아요 · 하루 한 번) */
  theoryDaily: 50,
  /** 실습 문제를 최종 제출했을 때 (맞았는지와 상관없이 같아요 · 문제마다 하루 한 번) */
  practiceSubmit: 30,
  /** 학습을 완료한 날 하루마다 */
  studyDay: 10,
  /** 연속 학습 기록이 이 날수에 처음 닿으면 한 번 주는 보너스 (가장 길었던 연속 기록 기준이라 끊겨도 줄지 않아요) */
  streakMilestones: [
    { days: 3, xp: 30 },
    { days: 7, xp: 70 },
    { days: 14, xp: 150 },
    { days: 30, xp: 300 },
  ],
} as const;

export type Grade = {
  /** 화면에 보이는 등급 글자 */
  label: string;
  /** 이 XP 이상이면 이 등급 */
  min: number;
  /** 마스코트 그림 (public/xp-grades/) */
  image: string;
  /** 등급 한 줄 설명 */
  title: string;
};

export const GRADES: Grade[] = [
  { label: "F", min: 0, image: "/xp-grades/f.webp", title: "이제 막 출발했어요" },
  { label: "D", min: 100, image: "/xp-grades/d.webp", title: "시동 거는 중이에요" },
  { label: "C0", min: 250, image: "/xp-grades/c-zero.webp", title: "조금씩 감을 잡고 있어요" },
  { label: "C+", min: 450, image: "/xp-grades/c-plus.webp", title: "궁금한 게 많아지는 중이에요" },
  { label: "B0", min: 700, image: "/xp-grades/b-zero.webp", title: "차분히 쌓아 가고 있어요" },
  { label: "B+", min: 900, image: "/xp-grades/b-plus.webp", title: "신나게 성장하고 있어요" },
  { label: "A0", min: 1200, image: "/xp-grades/a-zero.webp", title: "자신감이 꽉 찼어요" },
  { label: "A+", min: 1600, image: "/xp-grades/a-plus.webp", title: "최고 등급이에요!" },
];

/** /my/learning-sessions 한 줄 (서버가 주는 값) */
export type TheoryRecord = { total: number; submitted: number };
/** /my/learning-streak (서버가 주는 값) */
export type StreakInfo = { current_streak: number; total_days: number; days?: string[] };

export type XpPart = { key: string; label: string; xp: number; detail: string };
export type XpSummary = {
  total: number;
  parts: XpPart[];
  grade: Grade;
  next: Grade | null;
  /** 다음 등급까지 채운 비율 0~1 */
  progress: number;
  longestStreak: number;
};

/** 날짜 목록에서 가장 길었던 연속 학습 일수 */
export function longestStreak(days: string[] = []) {
  const sorted = [...new Set(days)].sort();
  let best = 0;
  let run = 0;
  let prev = NaN;
  for (const day of sorted) {
    const t = Date.parse(`${day}T00:00:00Z`);
    run = t - prev === 86400000 ? run + 1 : 1;
    prev = t;
    best = Math.max(best, run);
  }
  return best;
}

export function gradeFor(total: number) {
  let index = 0;
  GRADES.forEach((g, i) => {
    if (total >= g.min) index = i;
  });
  return { grade: GRADES[index], next: GRADES[index + 1] || null, index };
}

export function computeXp(
  theory: TheoryRecord[],
  streak: StreakInfo | undefined,
  practice: { submitted: number },
): XpSummary {
  const sets = theory.filter((r) => r.total > 0 && r.submitted >= r.total).length;
  const studyDays = streak?.total_days || 0;
  const longest = Math.max(longestStreak(streak?.days), streak?.current_streak || 0);
  const milestones = XP_RULES.streakMilestones.filter((m) => longest >= m.days);

  const parts: XpPart[] = [
    {
      key: "theory",
      label: "이론 퀴즈",
      xp: sets * XP_RULES.theoryDaily,
      detail: `오늘의 퀴즈를 다 제출한 날 ${sets}번`,
    },
    {
      key: "practice",
      label: "실습 문제",
      xp: practice.submitted * XP_RULES.practiceSubmit,
      detail: `최종 제출 ${practice.submitted}번`,
    },
    {
      key: "streak",
      label: "꾸준한 학습",
      xp: studyDays * XP_RULES.studyDay + milestones.reduce((s, m) => s + m.xp, 0),
      detail: `학습한 날 ${studyDays}일 · 최장 연속 ${longest}일`,
    },
  ];
  const total = parts.reduce((s, p) => s + p.xp, 0);
  const { grade, next } = gradeFor(total);
  const progress = next ? Math.min(1, (total - grade.min) / (next.min - grade.min)) : 1;
  return { total, parts, grade, next, progress, longestStreak: longest };
}
