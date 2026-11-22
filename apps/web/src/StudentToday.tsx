import { useContext } from "react";
import { Link } from "react-router-dom";
import { Auth } from "./Auth";
import type { Classroom } from "./api";
import { ErrorNotice, useLoad } from "./components";
import {
  isSubmitted,
  nextClassroom,
  weekLabel,
  type LearningRecord,
} from "./studentOverview";
import "./student-home.css";
import "./student-home-clean.css";

const kstDay = () =>
  new Intl.DateTimeFormat("sv-SE", { timeZone: "Asia/Seoul" }).format(
    new Date(),
  );

export function StudentToday() {
  const { user } = useContext(Auth);
  const rooms = useLoad<{ items: Classroom[] }>("/classrooms");
  const history = useLoad<{ items: LearningRecord[] }>("/my/learning-sessions?today_only=true");
  const streak = useLoad<{ today_completed: boolean; current_streak: number }>(
    "/my/learning-streak",
  );
  const active =
    rooms.data?.items.filter((room) => room.status === "active") || [];
  const today = kstDay();
  const completed = streak.data?.today_completed === true;
  const ready = !!history.data && !!streak.data;
  const room = nextClassroom(
    active,
    history.data?.items || [],
    today,
    completed,
  );
  const record = history.data?.items.find(
    (item) => item.section_id === room?.section.id && item.day === today,
  );
  const done = isSubmitted(record);
  const remaining = record ? Math.max(0, record.total - record.submitted) : 0;
  const date = new Intl.DateTimeFormat("ko-KR", {
    timeZone: "Asia/Seoul",
    month: "long",
    day: "numeric",
    weekday: "long",
  }).format(new Date());
  return (
    <div className="student-home student-today sh-home">
      {/* 1. 인사 — 날짜와 이름만. 연속 학습은 학습 기록 화면에서 보여 줘요 */}
      <div className="sh-greeting">
        <p className="sh-meta">{date}</p>
        <h1>{user?.display_name}님, 안녕하세요.</h1>
      </div>
      <ErrorNotice text={rooms.error || history.error || streak.error} />

      {/* 2. 오늘 할 일 — 화면에서 가장 눈에 띄는 단 하나의 버튼 */}
      {room && ready ? (
        <section className="today-next sh-next" aria-labelledby="today-next-title">
          <div className="today-next-copy">
            <h2 id="today-next-title">
              {/* 박스 어디를 눌러도 이 강의실로 들어가요 (링크가 박스 전체를 덮어요) */}
              <Link className="sh-next-link" to={`/classrooms/${room.section.id}`}>{room.course.title}</Link>
              <small className="sh-section-name">{room.section.title}</small>
            </h2>
            <p className="sh-today">
              <span className="sh-label">
                {completed
                  ? "✓ 오늘의 학습 완료"
                  : record
                    ? "이어서 학습하기"
                    : "오늘의 학습"}
              </span>
              {completed
                ? "배운 내용을 다시 살펴볼까요?"
                : remaining
                  ? `미제출 ${remaining}문항을 마무리해 보세요.`
                  : "오늘 배운 개념을 확인해 보세요."}
              {record && ` (이론 ${record.submitted}/${record.total}문항 제출)`}
            </p>
            {record && (
              <progress
                className="sh-progress"
                value={record.submitted}
                max={Math.max(record.total, 1)}
                aria-label="오늘의 이론 제출 현황"
              />
            )}
          </div>
          <Link
            className="ln-cta"
            to={
              done && record
                ? `/quiz/results/${record.id}`
                : completed
                  ? `/attendance?section=${room.section.id}`
                  : record
                    ? `/quiz/${room.section.id}`
                    : `/quiz?section=${room.section.id}`
            }
          >
            {completed || done
              ? "결과·복습 보기"
              : record
                ? "이어서 풀기"
                : "학습 시작하기"}{" "}
            <span aria-hidden="true">→</span>
          </Link>
        </section>
      ) : room && !ready ? (
        <p className="student-empty" role="status">
          {history.error || streak.error
            ? "학습 상태를 확인하지 못했어요. 아래 강의실에서 계속할 수 있어요."
            : "오늘의 학습 상태를 확인하고 있어요…"}
        </p>
      ) : null}

      {/* 3. 내 강의 — 한 줄짜리 목록, 줄 전체가 강의실 링크 */}
      <section className="sh-section" aria-labelledby="today-courses-title">
        <div className="sh-heading">
          <h2 id="today-courses-title">내 강의</h2>
          <Link to="/courses">전체 보기</Link>
        </div>
        {!rooms.data ? (
          <p className="sh-note" role="status">
            {rooms.error
              ? "강의 목록을 불러오지 못했어요."
              : "내 강의를 불러오는 중이에요…"}
          </p>
        ) : active.length ? (
          <ul className="sh-list">
            {active.slice(0, 4).map((item) => {
              const learning = history.data?.items.find(
                (entry) =>
                  entry.section_id === item.section.id && entry.day === today,
              );
              const doneToday = isSubmitted(learning);
              return (
                <li key={item.section.id}>
                  <Link
                    className="sh-row"
                    to={`/classrooms/${item.section.id}`}
                  >
                    <span className="sh-row-main">
                      <strong>{item.course.title}</strong>
                      <small>
                        {weekLabel(item.current_week)} · {item.teacher_name} ·{" "}
                        {item.section.title}
                      </small>
                    </span>
                    {doneToday && (
                      <span className="sh-row-state is-done">✓ 오늘 완료</span>
                    )}
                    <span className="sh-arrow" aria-hidden="true">
                      →
                    </span>
                  </Link>
                </li>
              );
            })}
          </ul>
        ) : (
          <div className="sh-empty">
            <strong>
              {rooms.data.items.some((item) => item.status === "pending")
                ? "수강 승인을 기다리고 있어요."
                : "아직 수강 중인 강의가 없어요."}
            </strong>
            <p>수강 코드로 강의에 참여하고, 승인 상태를 확인하세요.</p>
            <Link to="/courses">수강 신청하기 →</Link>
          </div>
        )}
      </section>

      {/* 4. 복습할 개념 — 있을 때만 */}
      {room && <ReviewConcepts key={room.section.id} room={room} day={today} />}
    </div>
  );
}

/* AI 질문은 오른쪽 아래 챗봇 버튼에서 바로 이어 할 수 있어서 홈에서는 뺐어요. */
function ReviewConcepts({ room, day }: { room: Classroom; day: string }) {
  const learning = useLoad<{
    items: {
      concept: string;
      valid_recent: number;
      mastered: boolean;
      review_due: string | null;
      review_session_id: string | null;
      review_question_id: string | null;
    }[];
  }>(`/sections/${room.section.id}/my-learning`);
  const reviews =
    learning.data?.items.filter(
      (item) =>
        item.valid_recent > 0 &&
        (!item.mastered || (item.review_due && item.review_due <= day)),
    ) || [];
  if (learning.error) return <ErrorNotice text={learning.error} />;
  if (!reviews.length) return null;
  return (
    <section className="sh-section" aria-labelledby="today-review-title">
      <div className="sh-heading">
        <h2 id="today-review-title">다시 볼 개념</h2>
        <Link to={`/attendance?section=${room.section.id}`}>전체 보기</Link>
      </div>
      <ul className="sh-list">
        {reviews.slice(0, 3).map((item) => (
          <li key={item.concept}>
            <Link
              className="sh-row"
              to={
                item.review_session_id
                  ? `/quiz/results/${item.review_session_id}#question-${item.review_question_id}`
                  : `/attendance?section=${room.section.id}`
              }
            >
              <span className="sh-row-main">
                <strong>{item.concept}</strong>
                <small>
                  {item.review_due && item.review_due <= day
                    ? "복습할 때가 되었어요"
                    : "내 답안과 해설 보기"}
                </small>
              </span>
              <span className="sh-arrow" aria-hidden="true">
                →
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
