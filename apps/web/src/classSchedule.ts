/* 수업 등록 — 요일과 수업 시간을 여러 개 골라 하나의 수업 일정 이름으로 만들어요.
   서버에는 지금의 학기(terms) 자리에 이 이름과 시작·종료일이 저장돼요. */
export const WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"] as const;
export type Slot = { start: string; end: string };

const MAX_NAME = 100;

/** Native time/autofill edits may be submitted before a controlled state update. */
export function submittedSlots(form: FormData, count: number): Slot[] {
  return Array.from({ length: count }, (_, i) => ({
    start: String(form.get(`slot-start-${i}`) ?? ""),
    end: String(form.get(`slot-end-${i}`) ?? ""),
  }));
}

/** 고른 요일·시간을 확인하고 일정 이름을 돌려줘요. 문제가 있으면 바로 고칠 수 있게 문장으로 알려요. */
export function scheduleName(days: string[], slots: Slot[]): string {
  const picked = WEEKDAYS.filter(d => days.includes(d));
  if (picked.length === 0) throw new Error("수업 요일을 하나 이상 골라 주세요.");
  const filled = slots.filter(s => s.start || s.end);
  if (filled.length === 0) throw new Error("수업 시간을 하나 이상 입력해 주세요.");
  for (const s of filled) {
    if (!s.start || !s.end) throw new Error("수업 시간의 시작과 끝을 모두 입력해 주세요.");
    if (s.start >= s.end) throw new Error(`${s.start}–${s.end}: 끝나는 시간이 시작 시간보다 늦어야 해요.`);
  }
  const unique = [...new Map(filled.map(s => [`${s.start}-${s.end}`, s])).values()].sort((a, b) => a.start.localeCompare(b.start));
  const name = `${picked.join("·")} ${unique.map(s => `${s.start}–${s.end}`).join(", ")}`;
  if (name.length > MAX_NAME) throw new Error("수업 시간이 너무 많아요. 시간을 줄여 주세요.");
  return name;
}
