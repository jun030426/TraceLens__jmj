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

const kstDay = () =>
  new Intl.DateTimeFormat("sv-SE", { timeZone: "Asia/Seoul" }).format(
    new Date(),
  );

export function StudentToday() {
  const { user } = useContext(Auth);
  const rooms = useLoad<{ items: Classroom[] }>("/classrooms");
  const history = useLoad<{ items: LearningRecord[] }>("/my/learning-sessions");
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
    <div className="student-home student-today">
      <div className="today-greeting">
        <div>
          <span className="student-date">{date}</span>
          <h1>{user?.display_name}님, 안녕하세요.</h1>
        </div>
        {streak.data && (
          <Link className="today-streak" to="/attendance">
            <span aria-hidden="true">✦</span> 연속 학습{" "}
            <strong>{streak.data.current_streak}일</strong>
            <span aria-hidden="true">↗</span>
          </Link>
        )}
      </div>
      <ErrorNotice text={rooms.error || history.error || streak.error} />
      {room && ready ? (
        <section className="today-next" aria-labelledby="today-next-title">
          <div className="today-next-copy">
            <span className={`today-status ${completed ? "is-complete" : ""}`}>
              {completed
                ? "✓ 오늘의 학습 완료"
                : record
                  ? "이어서 학습하기"
                  : "오늘의 학습"}
            </span>
            <h2 id="today-next-title">
              {completed
                ? "배운 내용을 다시 살펴볼까요?"
                : remaining
                  ? `미제출 ${remaining}문항을 마무리해 보세요.`
                  : "오늘 배운 개념을 확인해 보세요."}
            </h2>
            <p>
              {room.course.title} <span>· {room.section.title}</span>
            </p>
            {record && (
              <div className="today-progress">
                <progress
                  value={record.submitted}
                  max={Math.max(record.total, 1)}
                  aria-label="오늘의 이론 제출 현황"
                />
                <span>
                  이론 {record.submitted}/{record.total}문항 제출
                  {record.pending > 0 &&
                    ` · 채점·검토 대기 ${record.pending}문항`}
                </span>
              </div>
            )}
          </div>
          <div className="today-next-actions">
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
                  ? "이론 이어서 풀기"
                  : "학습 시작하기"}{" "}
              <span aria-hidden="true">→</span>
            </Link>
            <Link
              className="today-text-link"
              to={`/classrooms/${room.section.id}`}
            >
              강의실로 가기 ↗
            </Link>
          </div>
        </section>
      ) : room && !ready ? (
        <p className="student-empty" role="status">
          {history.error || streak.error
            ? "학습 상태를 확인하지 못했어요. 아래 강의실에서 계속할 수 있어요."
            : "오늘의 학습 상태를 확인하고 있어요…"}
        </p>
      ) : null}
      <section className="today-courses" aria-labelledby="today-courses-title">
        <div className="today-section-heading">
          <h2 id="today-courses-title">
            내 강의 {rooms.data && <span>{active.length}</span>}
          </h2>
          <Link to="/courses">전체 강의·수강 신청 ↗</Link>
        </div>
        {!rooms.data ? (
          <p role="status">
            {rooms.error
              ? "강의 목록을 불러오지 못했어요."
              : "내 강의를 불러오는 중이에요…"}
          </p>
        ) : active.length ? (
          <div className="today-course-grid">
            {active.slice(0, 4).map((item) => {
              const learning = history.data?.items.find(
                (entry) =>
                  entry.section_id === item.section.id && entry.day === today,
              );
              return (
                <Link
                  className="today-course"
                  key={item.section.id}
                  to={`/classrooms/${item.section.id}`}
                >
                  <div className="today-course-heading">
                    <span className="today-week">
                      {weekLabel(item.current_week)}
                    </span>
                    <span aria-hidden="true">↗</span>
                  </div>
                  <h3>{item.course.title}</h3>
                  <p>
                    {item.teacher_name} · {item.section.title}
                  </p>
                  <div className="today-course-footer">
                    <span>
                      {!history.data
                        ? "학습 상태 확인 중"
                        : isSubmitted(learning)
                          ? "✓ 오늘의 이론 제출 완료"
                          : learning
                            ? `오늘의 이론 ${learning.submitted}/${learning.total}문항 제출`
                            : "오늘의 이론 시작 전"}
                    </span>
                    <strong>
                      강의실 입장 <span aria-hidden="true">→</span>
                    </strong>
                  </div>
                </Link>
              );
            })}
          </div>
        ) : (
          <div className="student-empty">
            <strong>
              {rooms.data.items.some((item) => item.status === "pending")
                ? "수강 승인을 기다리고 있어요."
                : "아직 수강 중인 강의가 없어요."}
            </strong>
            <p>수강 코드로 강의에 참여하고, 승인 상태를 확인하세요.</p>
            <Link to="/courses">강의·수강 신청 보기 ↗</Link>
          </div>
        )}
      </section>
      {room && <RecentLearning key={room.section.id} room={room} day={today} />}
    </div>
  );
}

function RecentLearning({ room, day }: { room: Classroom; day: string }) {
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
  const chat = useLoad<{ items: { question: string }[] }>(
    `/sections/${room.section.id}/chat/history`,
  );
  const reviews =
    learning.data?.items.filter(
      (item) =>
        item.valid_recent > 0 &&
        (!item.mastered || (item.review_due && item.review_due <= day)),
    ) || [];
  const questions =
    chat.data?.items
      .slice()
      .reverse()
      .filter(
        (item, index, items) =>
          items.findIndex((other) => other.question === item.question) ===
          index,
      )
      .slice(0, 2) || [];
  return (
    <>
      <ErrorNotice text={learning.error || chat.error} />
      {(reviews.length > 0 || questions.length > 0) && (
        <section
          className="today-recent"
          aria-label={`${room.course.title} 최근 학습`}
        >
          <div className="today-section-heading">
            <h2>지난 학습 이어보기</h2>
            <span>{room.course.title}</span>
          </div>
          <div className="today-recent-grid">
            {reviews.length > 0 && (
              <div className="today-recent-card">
                <div className="today-card-heading">
                  <h3>다시 살펴볼 개념</h3>
                  <Link to={`/attendance?section=${room.section.id}`}>
                    전체 보기 ↗
                  </Link>
                </div>
                {reviews.slice(0, 3).map((item) => (
                  <Link
                    className="today-recent-row"
                    key={item.concept}
                    to={
                      item.review_session_id
                        ? `/quiz/results/${item.review_session_id}#question-${item.review_question_id}`
                        : `/attendance?section=${room.section.id}`
                    }
                  >
                    <span>
                      <strong>{item.concept}</strong>
                      <small>
                        {item.review_due && item.review_due <= day
                          ? "복습 권장일이 되었어요"
                          : "내 답안과 해설 살펴보기"}
                      </small>
                    </span>
                    <span aria-hidden="true">→</span>
                  </Link>
                ))}
              </div>
            )}
            {questions.length > 0 && (
              <div className="today-recent-card">
                <div className="today-card-heading">
                  <h3>최근 AI 질문</h3>
                  <Link to={`/ai?section=${room.section.id}`}>대화 열기 ↗</Link>
                </div>
                {questions.map((item, i) => (
                  <Link
                    className="today-recent-row"
                    key={i}
                    to={`/ai?section=${room.section.id}`}
                  >
                    <span>
                      <strong className="today-question-text">
                        {item.question}
                      </strong>
                      <small>이전 대화에서 이어가기</small>
                    </span>
                    <span aria-hidden="true">→</span>
                  </Link>
                ))}
              </div>
            )}
          </div>
        </section>
      )}
    </>
  );
}
