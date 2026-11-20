/* [XP · 실습] 실습 최종 제출 기록 — 제출 결과 자체는 서버(practice.py)에 저장되지만, 학생의 전체 제출 목록을
   한 번에 읽는 API가 아직 없어서 XP 계산용으로 이 브라우저의 localStorage 에도 남겨요.
   (다른 기기·브라우저에서는 실습 XP가 따로 쌓여요) 서버에 "내 실습 제출 목록" API가 생기면 이 파일만 바꾸면 돼요. */

export const XP_CHANGED = "lerny-xp-changed";
type Entry = { at: string; correct?: boolean };
const keyOf = (userId: string) => `lerny-xp-practice:${userId}`;

function read(userId: string): Record<string, Entry> {
  try {
    const v = JSON.parse(localStorage.getItem(keyOf(userId)) || "{}");
    return v && typeof v === "object" && !Array.isArray(v) ? v : {};
  } catch {
    return {};
  }
}

const today = () => new Intl.DateTimeFormat("sv-SE", { timeZone: "Asia/Seoul" }).format(new Date());

/** 실습 문제를 최종 제출했을 때 불러요. 맞았는지는 기록만 하고 XP에는 쓰지 않아요. 같은 문제는 하루에 한 번만 쌓여요. 새로 쌓였으면 true */
export function recordPracticeSubmit(userId: string, sectionId: string, quizId: string) {
  const log = read(userId);
  const id = `${today()}:${sectionId}:${quizId}`;
  if (log[id]) return false;
  log[id] = { at: new Date().toISOString() };
  try {
    localStorage.setItem(keyOf(userId), JSON.stringify(log));
  } catch {
    return false; // 저장이 막힌 브라우저
  }
  window.dispatchEvent(new CustomEvent(XP_CHANGED));
  return true;
}

export function practiceCounts(userId: string) {
  return { submitted: Object.keys(read(userId)).length };
}
