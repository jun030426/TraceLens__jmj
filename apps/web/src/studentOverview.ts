import type { Classroom } from "./api";

export type LearningRecord = {
  id: string;
  section_id: string;
  day: string;
  total: number;
  submitted: number;
  pending: number;
};

export const isSubmitted = (record?: LearningRecord) =>
  !!record && record.total > 0 && record.submitted >= record.total;

export function nextClassroom(
  rooms: Classroom[],
  records: LearningRecord[],
  day: string,
  completed: boolean,
) {
  const today = records.filter((record) => record.day === day);
  const inProgress = rooms.find((room) =>
    today.some(
      (record) =>
        record.section_id === room.section.id &&
        record.submitted > 0 &&
        !isSubmitted(record),
    ),
  );
  const finished = rooms.find((room) =>
    today.some(
      (record) => record.section_id === room.section.id && isSubmitted(record),
    ),
  );
  const assigned = rooms.find((room) =>
    today.some(
      (record) =>
        record.section_id === room.section.id &&
        record.total > 0 &&
        !isSubmitted(record),
    ),
  );
  return (completed ? finished : inProgress || assigned) || rooms[0];
}

export function weekLabel(week: number | null) {
  return week == null
    ? "교수 지정 진도"
    : week > 0
      ? `${week}주차 학습 중`
      : "학기 시작 전";
}

export function materialWeeks(weeks: number[], currentWeek: number | null) {
  return [
    ...new Set([
      ...weeks,
      ...(currentWeek != null && currentWeek > 0 ? [currentWeek] : []),
    ]),
  ].sort((a, b) => a - b);
}
