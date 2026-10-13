import { useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import {
  Link,
  Navigate,
  useNavigate,
  useLocation,
  useParams,
  useSearchParams,
} from "react-router-dom";
import { Auth } from "./Auth";
import { api, post, type Classroom, type Course, type Section, type Enrollment, type Term } from "./api";
import { AIAvailability, ErrorNotice, Notice, useLoad } from "./components";
import { Chat, Materials } from "./Learning";
import { type Daily } from "./Theory";
import { LearningHistory, LearningProgress } from "./LearningProgress";

import { PagedList } from "./StudentLists";
import { matchesSearch } from "./listNavigation";
import { QuestionArchive } from "./QuestionArchive";

type Record = {
  id: string;
  section_id: string;
  day: string;
  total: number;
  submitted: number;
  pending: number;
  valid: number;
  correct: number;
};
const kstDay = () =>
  new Intl.DateTimeFormat("sv-SE", { timeZone: "Asia/Seoul" }).format(
    new Date(),
  );
export function RoleHome() {
  const { user } = useContext(Auth);
  return (
    <Navigate
      to={
        user?.role === "student"
          ? "/student"
          : user?.role === "teacher"
            ? "/professor"
            : "/classrooms"
      }
      replace
    />
  );
}
export function StudentOnly({ children }: { children: ReactNode }) {
  const { user } = useContext(Auth);
  return user?.role === "student" ? (
    children
  ) : (
    <Notice>
      학생 계정에서 사용할 수 있어요. <Link to="/home">내 홈으로</Link>
    </Notice>
  );
}
export function QuizCatalog() {
  const [criteriaOpen, setCriteriaOpen] = useState(false);
  const streak = useLoad<{ today_completed: boolean; current_streak: number; total_days: number }>("/my/learning-streak");
  const rooms = useLoad<{ items: Classroom[] }>("/classrooms");
  const [historyOpen, setHistoryOpen] = useState(false);
  const [search, setSearch] = useState("");
  const today = kstDay();
  const history = useLoad<{ items: Record[] }>(`/my/learning-sessions?date_from=${today}&date_to=${today}`);
  const [params, setParams] = useSearchParams();
  const selected = params.get("section") || "";
  const active = rooms.data?.items.filter((r) => r.status === "active") || [];
  const filtered = active.filter(r => (!selected || r.section.id === selected) && matchesSearch(search, r.course.title, r.section.title, r.teacher_name));
  const records = (history.data?.items || []).filter(
    (s) => !selected || s.section_id === selected,
  );
  return (
    <section className="student-home quiz-catalog">
      <span className="student-eyebrow">MY QUIZ</span>
      <h1>퀴즈</h1>
      <p className="quiz-description">강의별 이론과 실습을 이어가세요.</p>
      <div className="quiz-streak-summary">
        <div><strong>{streak.data ? `${streak.data.current_streak}일 연속 학습` : "연속 학습"}</strong></div>
        <p>{streak.error ? "연속 학습 기록을 불러오지 못했어요." : !streak.data ? "학습 기록을 확인하고 있어요…" : streak.data.today_completed ? "오늘의 학습 완료 · 내일도 이어가 보세요." : "이론 또는 실습을 완료하면 오늘의 학습으로 인정돼요."}</p>
        <button type="button" className="quiz-criteria-toggle" aria-expanded={criteriaOpen} aria-controls="quiz-criteria" onClick={() => setCriteriaOpen(!criteriaOpen)}>인정 기준 <svg aria-hidden="true" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><path d="m6 9 6 6 6-6" /></svg></button>
        <div id="quiz-criteria" className="quiz-criteria-body" hidden={!criteriaOpen}>
          <p>이론 또는 실습의 하루 묶음을 최종 제출하면 정답 여부와 관계없이 인정돼요.</p>
          <p>한국 시간 기준 하루 1회 · 풀이 시작, 부분 제출, 코드 실행만으로는 인정되지 않아요.</p>
        </div>
      </div>
      <ErrorNotice text={rooms.error || history.error} />
      <div className="student-list-tools">
        <label>강의 선택<select value={selected} onChange={e => setParams(e.target.value ? {section:e.target.value} : {})}><option value="">전체 강의</option>{active.map(r => <option key={r.section.id} value={r.section.id}>{r.course.title} · {r.section.title}</option>)}</select></label>
        {active.length > 3 && <label>강의 검색<input type="search" value={search} onChange={e => setSearch(e.target.value)} placeholder="강의·분반·교수 이름" /></label>}
      </div>
      <div className="quiz-section-heading"><h2>오늘의 학습</h2></div>
      {!active.length && rooms.data && (
        <Notice>
          먼저 강의에 참여해 주세요. <Link to="/courses">내 강의로</Link>
        </Notice>
      )}
      {active.length > 0 && !filtered.length && <p className="student-list-empty">조건에 맞는 강의가 없어요.</p>}
      <PagedList items={filtered} label="오늘의 강의" size={3} resetKey={`${selected}:${search}`}>{visible => <div className="quiz-course-groups">
        {visible.map((r) => {
          const record = records.find(
            (s) => s.section_id === r.section.id && s.day === kstDay(),
          );
          const done = record && record.total > 0 && record.submitted >= record.total;
          return (
            <section className="quiz-course-group" key={r.section.id}>
              <header className="quiz-course-heading">
                <h3>{r.course.title.split(/\s+[—–]\s+/)[0]}</h3>
                <span>{r.section.title}</span>
                {r.course.title.split(/\s+[—–]\s+/).length > 1 && <p>{r.course.title.split(/\s+[—–]\s+/).slice(1).join(" — ")}</p>}
              </header>
              <div className="quiz-mode-grid">
                <article className="quiz-mode-card">
                  <div className="quiz-mode-top"><span className="student-eyebrow">01 / THEORY</span><span className="quiz-mode-tag">이론</span></div>
                  <h4>배운 개념을 확인해요.</h4>
                  <p className="quiz-mode-description">객관식 2문항 · 서술형 1문항</p>
                  <div className="quiz-mode-footer">
                    <p className="quiz-progress-status">{record
                      ? `${record.submitted}/${record.total}문항 제출${record.pending ? ` · 채점·검토 대기 ${record.pending}건` : ""}`
                      : "아직 시작하지 않았어요."}</p>
                    <Link className="ln-cta" to={done ? `/quiz/results/${record.id}` : `/quiz/${r.section.id}`}>
                      {done ? "이론 결과·해설 보기" : record ? "이론 이어서 풀기" : "이론 풀기"} ↗
                    </Link>
                  </div>
                </article>
                <article className="quiz-mode-card quiz-practice-card">
                  <div className="quiz-mode-top"><span className="student-eyebrow">02 / PRACTICE</span><span className="quiz-mode-tag">실습 · {({ python: "Python", java: "Java", c: "C" } as { [key: string]: string })[r.course.teaching_language.toLowerCase()] || r.course.teaching_language}</span></div>
                  <h4>직접 풀며 연결해요.</h4>
                  <p className="quiz-mode-description">직접 구현 2문제 · 핵심 로직을 작성해요.</p>
                  <div className="quiz-mode-footer">
                    <Link className="ln-cta" to={`/classrooms/${r.section.id}/practice`}>실습 풀기 ↗</Link>
                  </div>
                </article>
              </div>
            </section>
          );
        })}
      </div>}</PagedList>
      <details className="student-record-archive" onToggle={e => setHistoryOpen(e.currentTarget.open)}>
        <summary>지난 이론 학습·복습 기록 <small>날짜별로 찾고 답안·해설을 다시 확인해요.</small></summary>
        {historyOpen && <div className="learning-progress"><LearningHistory key={selected} sectionId={selected || undefined} classrooms={active} /></div>}
      </details>
    </section>
  );
}

function draftKey(userId: string, sessionId: string) {
  return `lerny-quiz:${userId}:${sessionId}`;
}
export function QuizTakeFlow() {
  const { sectionId = "" } = useParams();
  const { user } = useContext(Auth);
  const navigate = useNavigate();
  const [daily, setDaily] = useState<Daily>();
  const [error, setError] = useState("");
  const [index, setIndex] = useState(0);
  const [answers, setAnswers] = useState<{ [key: string]: string }>({});
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let active = true;
    setDaily(undefined);
    setError("");
    setIndex(0);
    setAnswers({});
    api<Daily>(`/sections/${sectionId}/daily`, post({}))
      .then((d) => {
        if (!active) return;
        setDaily(d);
        try {
          const position = Number(
            sessionStorage.getItem(draftKey(user!.id, d.id) + ":position") ||
              "0",
          );
          if (
            Number.isInteger(position) &&
            position >= 0 &&
            position < d.items.length
          )
            setIndex(position);
          const saved = JSON.parse(
            sessionStorage.getItem(draftKey(user!.id, d.id)) || "{}",
          );
          if (saved && typeof saved === "object" && !Array.isArray(saved))
            setAnswers(
              Object.fromEntries(
                Object.entries(saved).filter(
                  ([key, value]) =>
                    d.items.some((q) => q.id === key) &&
                    typeof value === "string" &&
                    value.length <= 4000,
                ),
              ) as { [key: string]: string },
            );
        } catch {
          /* Empty draft on unavailable storage. */
        }
      })
      .catch((e) => {
        if (active) setError(e.message);
      });
    return () => {
      active = false;
    };
  }, [sectionId, user?.id]);
  const choose = (value: string) => {
    if (!daily) return;
    const next = { ...answers, [daily.items[index].id]: value };
    setAnswers(next);
    try {
      sessionStorage.setItem(
        draftKey(user!.id, daily.id),
        JSON.stringify(next),
      );
    } catch {
      /* Form still works without browser storage. */
    }
  };
  const move = (next: number) => {
    setIndex(next);
    if (daily)
      try {
        sessionStorage.setItem(
          draftKey(user!.id, daily.id) + ":position",
          String(next),
        );
      } catch {
        /* Optional storage. */
      }
  };
  const submit = async () => {
    if (!daily) return;
    setError("");
    setBusy(true);
    try {
      const fresh = await api<Daily>(`/learning-sessions/${daily.id}`);
      setDaily(fresh);
      const remaining = fresh.items.filter(
        (q) => !q.attempt && q.status !== "unavailable",
      );
      if (remaining.some((q) => !answers[q.id]?.trim()))
        throw new Error(
          "아직 답하지 않은 문항이 있어요. 문항 번호를 눌러 확인해 주세요.",
        );
      for (const q of remaining)
        await api(`/learning-sessions/${daily.id}/questions/${q.id}/submit`, {
          ...post({ answer: answers[q.id] }),
          headers: { "Idempotency-Key": `${daily.id}:${q.id}` },
        });
      try {
        sessionStorage.removeItem(draftKey(user!.id, daily.id));
        sessionStorage.removeItem(draftKey(user!.id, daily.id) + ":position");
      } catch {
        /* Submission already persisted. */
      }
      navigate(`/quiz/results/${daily.id}`);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  if (!daily)
    return (
      <section className="student-home quiz-flow theory-workspace">
        <Link to={`/quiz?section=${sectionId}`}>← 퀴즈 목록</Link>
        <h1>오늘의 퀴즈</h1>
        {error ? (
          <ErrorNotice text={error} />
        ) : (
          <Notice>문항을 준비하고 있어요…</Notice>
        )}
      </section>
    );
  const q = daily.items[index];
  const complete = daily.items.every(
    (q) => q.attempt || q.status === "unavailable",
  );
  return (
    <section className="student-home quiz-flow theory-workspace">
      <Link to={`/quiz?section=${sectionId}`}>← 퀴즈 목록</Link>
      <span className="student-eyebrow theory-eyebrow">CONNECT THROUGH PRACTICE</span>
      <div className="theory-title-row"><h1>오늘의 이론</h1><span>{daily.items.filter(item => item.attempt || answers[item.id]?.trim()).length} / {daily.items.length}문항 작성</span></div>
      <p>
        한 문항씩 풀고 마지막에 제출하세요. 해설은 결과 화면에서 확인할 수
        있어요.
      </p>
      {daily.shortage > 0 && (
        <Notice>현재 준비된 {daily.items.length}문항으로 진행해요.</Notice>
      )}
      <nav className="question-steps" aria-label="문항 이동">
        {daily.items.map((item, i) => (
          <button
            key={item.id}
            disabled={busy}
            aria-current={index === i ? "step" : undefined}
            className={index === i ? "selected" : ""}
            onClick={() => move(i)}
          >
            {i + 1}번{" "}
            {item.attempt ? "제출됨" : answers[item.id] ? "작성됨" : ""}
          </button>
        ))}
      </nav>
      {q && (
        <article className="panel theory-question">
          <small>
            {index + 1} / {daily.items.length} ·{" "}
            {q.kind === "essay" ? "서술형" : "객관식"}
          </small>
          <h2>{q.prompt}</h2>
          {q.attempt ? (
            <Notice>
              이미 제출한 답안이에요. 결과 화면에서 채점을 확인하세요.
            </Notice>
          ) : q.status === "unavailable" ? (
            <Notice>이 문항은 변경되어 제출할 수 없어요.</Notice>
          ) : (
            <fieldset disabled={busy}>
              <legend className="theory-answer-legend">{q.kind === "mcq" ? "정답이라고 생각하는 보기 하나를 선택해 주세요." : "배운 내용을 자신의 말로 설명해 주세요."}</legend>
              {q.kind === "mcq" ? (
                q.options.map((option, i) => (
                  <label className={`answer-option ${answers[q.id] === String(i) ? "is-chosen" : ""}`} key={i}>
                    <input
                      type="radio"
                      name={q.id}
                      checked={answers[q.id] === String(i)}
                      onChange={() => choose(String(i))}
                    />
                    <span className="theory-option-number" aria-hidden="true">{i + 1}</span><span>{option}</span>
                  </label>
                ))
              ) : (
                <label>
                  내 설명
                  <textarea
                    value={answers[q.id] || ""}
                    onChange={(e) => choose(e.target.value)}
                    rows={7}
                    maxLength={4000}
                    placeholder="핵심 개념과 그 이유를 차근차근 적어 주세요."
                  />
                </label>
              )}
            </fieldset>
          )}
          <ErrorNotice text={error} />
          <div className="flow-actions">
            <button
              disabled={index === 0 || busy}
              onClick={() => move(index - 1)}
            >
              이전 문항
            </button>
            {index < daily.items.length - 1 ? (
              <button
                className="primary"
                disabled={busy}
                onClick={() => move(index + 1)}
              >
                다음 문항 →
              </button>
            ) : complete ? (
              <Link
                className="primary link-button"
                to={`/quiz/results/${daily.id}`}
              >
                결과·해설 보기 →
              </Link>
            ) : (
              <button
                className="primary"
                disabled={busy}
                onClick={() => void submit()}
              >
                {busy ? "제출 중…" : "답안 제출"}
              </button>
            )}
          </div>
        </article>
      )}
    </section>
  );
}

export function QuizResults() {
  const [actionError, setActionError] = useState("");
  const { learningId = "" } = useParams();
  const r = useLoad<Daily>(`/learning-sessions/${learningId}`);
  const { hash } = useLocation();
  const hasResult = !!r.data;
  useEffect(() => {
    if (!hasResult || !hash.startsWith("#question-")) return;
    document.getElementById(hash.slice(1))?.scrollIntoView({ block: "start" });
  }, [hash, hasResult]);
  useEffect(() => {
    if (!r.data?.items.some((q) => q.attempt?.status === "pending")) return;
    const timer = setTimeout(r.reload, 3000);
    return () => clearTimeout(timer);
  }, [r.data]);
  const submitted = r.data?.items.filter((q) => q.attempt) || [];
  const graded = submitted.filter((q) => q.attempt?.status === "graded");
  return (
    <section className="student-home quiz-results">
      <Link to={r.data ? `/quiz?section=${r.data.section_id}` : "/quiz"}>
        ← 퀴즈 목록
      </Link>
      <span className="student-eyebrow result-eyebrow">TURN ANSWERS INTO UNDERSTANDING</span>
      <h1>결과와 복습</h1>
      {submitted.some(q => q.attempt?.status === "pending") && <AIAvailability />}
      <p className="result-intro">맞힌 이유도, 헷갈린 부분도. 해설과 함께 이해를 한 걸음 넓혀 보세요.</p>
      <ErrorNotice text={r.error} />
      {!r.data && !r.error && <Notice>결과를 불러오는 중…</Notice>}
      {r.data && (
        <>
          <div className="result-overview">
            <div className="result-overview-title"><div><span className="student-eyebrow">YOUR PRACTICE</span><h2>{submitted.length}/{r.data.items.length}문항 제출</h2></div><button onClick={r.reload}>채점 상태 새로고침 ↻</button></div>
            <div className="result-stats">
              <div><span>채점 완료</span><strong>{graded.length}<small>문항</small></strong></div>
              <div><span>정답</span><strong>{graded.filter(q => q.attempt?.correct).length}<small>문항</small></strong></div>
              <div><span>대기·보류</span><strong>{submitted.length - graded.length}<small>문항</small></strong></div>
            </div>
            <p>성적에 반영되지 않는 학습 기록이에요. 대기·보류 문항은 오답으로 세지 않아요.</p>
          </div>
          <h2 className="result-section-title">문항별 답안과 해설</h2>
          {r.data.items.map((q, i) => (
            <article id={`question-${q.id}`} className={`panel result-question ${q.attempt?.status === "graded" ? (q.attempt.correct ? "result-correct" : "result-review") : "result-pending"}`} key={q.id}>
              <div className="result-question-meta"><small>
                {i + 1}번 · {q.kind === "essay" ? "서술형" : "객관식"}
              </small><span className={`result-status ${q.attempt?.status === "graded" ? (q.attempt.correct ? "is-correct" : "is-review") : "is-pending"}`}>{q.attempt?.status === "graded" ? (q.attempt.correct ? "정답" : "복습해 보세요") : q.attempt?.status === "pending" ? "채점 중" : q.attempt ? "검토 보류" : "미제출"}</span></div>
              <h2>{q.prompt}</h2>
              <div className="result-answer-comparison">
              {q.submitted_answer && (
                <p className="result-answer">
                  <strong>{q.kind === "mcq" && q.attempt?.status === "graded" && q.attempt.correct && q.submitted_answer === q.correct_option ? "내 답안 · 정답" : "내 답안"}</strong><span>{q.submitted_answer}</span>
                </p>
              )}
              {q.correct_option && !(q.kind === "mcq" && q.attempt?.status === "graded" && q.attempt.correct && q.submitted_answer === q.correct_option) && (
                <p className="result-answer result-correct-answer">
                  <strong>정답</strong><span>{q.correct_option}</span>
                </p>
              )}
              </div>
              {q.attempt?.status === "graded" ? (q.attempt.feedback?.message && q.attempt.feedback.message !== "정답이에요." && <p className="result-feedback">{q.attempt.feedback.message}</p>) : <Notice>
                {q.attempt?.status === "pending"
                  ? "채점 중이에요."
                  : q.attempt?.feedback?.message ||
                    (q.attempt
                      ? "검토 보류 중이에요."
                      : "제출하지 않은 문항이에요.")}
              </Notice>}
              {q.attempt?.feedback?.criteria?.map((c, j) => (
                <p key={j}>
                  {c.criterion} · {c.score}점
                </p>
              ))}
              {q.explanation && (
                <details open>
                  <summary>해설</summary>
                  <p>{q.explanation}</p>
                </details>
              )}
              {q.kind === "essay" &&
                q.attempt &&
                !q.attempt.appealed &&
                q.attempt.status !== "pending" && (
                  <button
                    onClick={async () => {
                      try {
                        await api(
                          `/attempts/${q.attempt!.id}/appeal`,
                          post({}),
                        );
                        r.reload();
                      } catch (e) {
                        setActionError((e as Error).message);
                      }
                    }}
                  >
                    채점 재검토 요청
                  </button>
                )}
            </article>
          ))}
          <div className="flow-actions">
            <Link to="/quiz">다른 강의 퀴즈 보기</Link>
            <Link
              className="primary link-button"
              to={`/attendance?section=${r.data.section_id}`}
            >
              내 복습 현황 →
            </Link>
            <Link to={`/ai?section=${r.data.section_id}`}>
              이 강의에 질문하기
            </Link>
            {submitted.length < r.data.items.length && (
              <Link to={`/quiz/${r.data.section_id}`}>
                남은 문항 이어서 풀기 →
              </Link>
            )}
            <Link to="/student">홈으로</Link>
          </div>
        </>
      )}
      <ErrorNotice text={actionError} />
    </section>
  );
}

export function CourseWorkspace({ mode }: { mode: "chat" | "progress" }) {
  const rooms = useLoad<{ items: Classroom[] }>("/classrooms");
  const [params, setParams] = useSearchParams();
  const domain = params.get("domain") === "practice" ? "practice" : "theory";
  const active = rooms.data?.items.filter((r) => r.status === "active") || [];
  const room = active.find((r) => r.section.id === params.get("section"));
  const [archiveOpen, setArchiveOpen] = useState(false);
  const [archiveRevision, setArchiveRevision] = useState(0);
  const updateArchive = useCallback(() => setArchiveRevision(value => value + 1), []);
  const courseRail = <>
          <h2>내 강의</h2>
          {active.length > 5 ? <div className="student-course-choice"><label>학습할 강의<select value={room?.section.id || ""} onChange={e => setParams(mode === "progress" ? {section:e.target.value,domain} : {section:e.target.value})}><option value="" disabled>강의를 선택하세요</option>{active.map(r => <option key={r.section.id} value={r.section.id}>{r.course.title} · {r.section.title}</option>)}</select></label>{room && <p>{room.course.title}<br />{room.section.title}</p>}</div> : <>
          {active.map((r) => {
            const [subject, ...details] = r.course.title.split(/\s+[—–]\s+/);
            return (
              <button
                aria-pressed={room?.section.id === r.section.id}
                className={room?.section.id === r.section.id ? "selected" : ""}
                key={r.section.id}
                onClick={() => setParams(mode === "progress" ? { section: r.section.id, domain,  } : { section: r.section.id })}
              >
                <span className="course-rail-subject">{subject}</span>
                {details.length > 0 && (
                  <span className="course-rail-detail">{details.join(" — ")}</span>
                )}
                <small>{r.section.title}</small>
              </button>
            );
          })}
          </>}
          <Link to="/courses">강의·수강 관리 →</Link>
  </>;
  return (
    <section className={mode === "chat" ? "student-home ai-page chat-page" : "student-home progress-page ai-page"}>
      <span className={"student-eyebrow"}>
        {mode === "chat" ? "CONNECT THROUGH QUESTIONS" : "MY LEARNING"}
      </span>
      <h1>{mode === "chat" ? "AI 질문" : "학습 기록과 복습"}</h1>
      {mode === "chat" && (
        <p className="ai-page-description">
          수업 자료에서 답변의 근거를 함께 확인하세요.
        </p>
      )}
      <ErrorNotice text={rooms.error} />
      {mode === "progress" && (
        <p>
          배운 만큼 쌓이는 나의 이해. 개념별 학습과 복습할 내용을 확인해 보세요.
        </p>
      )}
      <div className={"workspace ai-workspace"}>
        {mode === "chat" && <div className="chat-mobile-course"><label>질문할 강의<select value={room?.section.id || ""} onChange={e => setParams({ section: e.target.value })}><option value="" disabled>강의를 선택하세요</option>{active.map(r => <option key={r.section.id} value={r.section.id}>{r.course.title} · {r.section.title}</option>)}</select></label></div>}
        <aside className={mode === "chat" ? "course-rail chat-sidebar" : "course-rail"}>
          {mode === "chat" ? <div className="chat-course-list">{courseRail}</div> : courseRail}
          {mode === "chat" && room && <QuestionArchive key={room.section.id} sectionId={room.section.id} revision={archiveRevision} open={archiveOpen} onOpenChange={setArchiveOpen} />}
        </aside>
        <div className={mode === "chat" ? "chat-column" : undefined}>
          {room ? (
            mode === "chat" ? (
              <Chat key={room.section.id} sectionId={room.section.id} courseTitle={`${room.course.title} · ${room.section.title}`} archiveInSidebar onHistoryChange={updateArchive} />
            ) : (
              <section className="panel progress-panel">
                <span className="student-eyebrow">MY UNDERSTANDING</span>
                <h2>{room.course.title.split(/\s+[—–]\s+/)[0]}</h2>
                <p className="progress-caption">{room.section.title} · {domain === "theory" ? "이론" : "실습"} 학습 기록</p>
                <div className="progress-domain-tabs" aria-label="학습 유형">{(["theory", "practice"] as const).map(d => <button key={d} aria-pressed={domain === d} onClick={() => setParams({ section: room.section.id, domain: d })}>{d === "theory" ? "이론" : "실습"}</button>)}</div>
                {domain === "theory" ? <LearningProgress key={room.section.id} room={room} /> : <>
                  <div className="progress-practice-heading"><div><h3>개념별 실습과 복습</h3><p>수업에서 배운 개념을 적용한 기록과 다시 살펴볼 내용을 확인해요.</p></div><span className="progress-course-language">수업 언어 · {({ python: "Python", java: "Java", c: "C" } as { [key: string]: string })[room.course.teaching_language.toLowerCase()] || room.course.teaching_language}</span></div>
                  <div className="progress-practice-metrics"><div><span>제출한 문제</span><strong>—</strong></div><div><span>검증 완료</span><strong>—</strong></div><div><span>복습할 개념</span><strong>—</strong></div></div>
                  <div className="progress-practice-empty"><span aria-hidden="true">&lt;/&gt;</span><h3>실습 기록이 쌓일 공간이에요.</h3><p>문제 유형별 제출 결과와 오류 유형, 개념별 복습 상태를 확인할 수 있어요.</p><Link className="ln-cta" to={`/classrooms/${room.section.id}/practice`}>실습 시작하기 ↗</Link><small>실습 기록 API 연결 전 · 현재 표시할 기록 없음</small></div>
                  <div className="progress-practice-bottom"><h3>최근 실습 제출</h3><p>실습을 제출하면 개념과 문제 유형별로 기록을 확인할 수 있어요.</p></div>
                </>}
                <div className="progress-actions"><p>학습 기록은 학교의 공식 출결과 별개예요.</p><Link className="ln-cta" to={domain === "practice" ? `/classrooms/${room.section.id}/practice` : `/quiz?section=${room.section.id}`}>{domain === "practice" ? "실습 이어가기" : "퀴즈로 학습 이어가기"} ↗</Link></div>
              </section>
            )
          ) : (
            <Notice>
              {rooms.data
                ? active.length
                  ? "학습할 강의를 선택해 주세요."
                  : "수강 중인 강의를 등록하면 사용할 수 있어요."
                : "강의를 불러오는 중…"}
            </Notice>
          )}
        </div>
      </div>
    </section>
  );
}

export function Profile() {
  const { user, refresh } = useContext(Auth);
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [feedback, setFeedback] = useState("");
  const [error, setError] = useState("");
  const saveProfile = async (payload: { major?: string; student_number?: string; email?: string; avatar?: string | null }) => {
    setBusy(true); setError(""); setFeedback("");
    try {
      await api("/me/profile", { method: "PATCH", body: JSON.stringify(payload) });
      await refresh(); setEditing(false); setFeedback("프로필을 저장했어요.");
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  };
  const role = user?.role === "student" ? "학생" : user?.role === "teacher" ? "교수" : "운영 담당자";
  return (
    <section className="student-home profile-page">
      <span className="student-eyebrow">YOUR LERNY ACCOUNT</span>
      <h1>내 정보</h1>
      <p className="profile-intro">나의 계정 정보를 확인하고 안전하게 관리하세요.</p>
      <ErrorNotice text={error} />
      {feedback && <p role="status" className="profile-feedback">{feedback}</p>}
      <div className="profile-grid">
        <section className="profile-identity">
          <div className="profile-avatar" aria-hidden="true">{user?.avatar ? <img src={user.avatar} alt="" /> : user?.display_name?.trim().slice(0, 1) || "L"}</div>
          <label className="profile-photo-control">{busy ? "저장 중…" : "사진 변경"}<input type="file" accept="image/jpeg,image/png,image/webp" disabled={busy} onChange={async e => {
            const file = e.target.files?.[0]; e.target.value = "";
            if (!file) return;
            if (file.size > 2 * 1024 * 1024) { setError("2MB 이하의 사진을 선택해 주세요."); return; }
            const reader = new FileReader();
            reader.onload = () => { void saveProfile({ avatar: String(reader.result) }); };
            reader.onerror = () => setError("사진을 읽지 못했어요. 다시 선택해 주세요.");
            reader.readAsDataURL(file);
          }} /></label>
          {user?.avatar && <button className="profile-photo-remove" disabled={busy} onClick={() => void saveProfile({ avatar: null })}>사진 삭제</button>}
          <p className="profile-photo-hint">JPG · PNG · WebP / 최대 2MB</p>
          <span className="profile-role">{role}</span>
          <h2>{user?.display_name}</h2>
          <p>Lerny에서 쌓아가는<br />나만의 배움과 이해.</p>
          <Link to="/home">내 홈으로 ↗</Link>
        </section>
        <div className="profile-details">
          <section className="profile-card">
            <span className="student-eyebrow">ACCOUNT DETAILS</span>
            <div className="profile-card-heading"><h2>계정 정보</h2><button className={editing ? "action-secondary" : "primary"} disabled={busy} onClick={() => setEditing(!editing)}>{editing ? "취소" : "정보 수정"}</button></div>
            <dl><div><dt>이름</dt><dd>{user?.display_name}</dd></div><div><dt>아이디</dt><dd>{user?.login_id}</dd></div><div><dt>이메일</dt><dd>{user?.email || "미등록"}</dd></div><div><dt>계정 유형</dt><dd>{role}</dd></div><div><dt>전공</dt><dd>{user?.major || "미등록"}</dd></div><div><dt>학번</dt><dd>{user?.student_number || "미등록"}</dd></div></dl>
            {editing && <form className="profile-edit-form" onSubmit={e => { e.preventDefault(); const f = new FormData(e.currentTarget); void saveProfile({ email: String(f.get("email") || ""), major: String(f.get("major") || ""), student_number: String(f.get("student_number") || "") }); }}>
              <label>전공<input name="major" defaultValue={user?.major || ""} maxLength={100} placeholder="예: 컴퓨터공학과" disabled={busy} /></label>
              <label>이메일<input name="email" type="email" defaultValue={user?.email || ""} maxLength={254} autoComplete="email" required disabled={busy} /></label>
              <label>학번<input name="student_number" defaultValue={user?.student_number || ""} maxLength={40} placeholder="학번을 입력해 주세요" disabled={busy} /></label>
              <button className="ln-cta" disabled={busy}>{busy ? "저장 중…" : "변경 사항 저장"}</button>
            </form>}
          </section>
          <section className="profile-card profile-security">
            <div><span className="student-eyebrow">SECURITY</span><h2>비밀번호 관리</h2><p>계정을 보호할 새로운 비밀번호로 변경할 수 있어요.</p></div>
            <Link className="ln-cta" to="/change-password">비밀번호 변경 ↗</Link>
          </section>
        </div>
      </div>
    </section>
  );
}

export function ProfessorWorkspace({
  mode,
}: {
  mode: "materials" | "students";
}) {
  const courses = useLoad<{ items: Course[] }>("/courses");
  const terms = useLoad<{ items: Term[] }>("/terms");
  const [params, setParams] = useSearchParams();
  const selected =
    courses.data?.items.find((c) => c.id === params.get("course")) ||
    courses.data?.items[0];
  if (mode === "materials") return <section className="professor-material-hub">
    <Link to="/professor" className="teacher-course-back">← 담당 강의</Link>
    <header className="material-hub-heading"><span className="student-eyebrow">YOUR CLASS MATERIALS</span><h1>강의 자료 관리</h1><p>담당 강의의 자료를 확인하고, 새로운 수업 자료를 올리세요.</p></header>
    <ErrorNotice text={courses.error || terms.error} />
    {!courses.data && !courses.error && <Notice>담당 강의를 불러오고 있어요…</Notice>}
    {courses.data?.items.length === 0 && <div className="material-hub-empty"><h2>먼저 강의를 만들어 주세요.</h2><p>강의를 등록하면 이곳에서 수업 자료를 관리할 수 있어요.</p><Link to="/professor#create-course">강의 만들기 →</Link></div>}
    {selected && <>
      <div className="material-hub-course"><label>자료를 관리할 수업<select aria-label="자료를 관리할 수업" value={selected.id} onChange={e => setParams({ course: e.target.value })}>{courses.data?.items.map(c => <option key={c.id} value={c.id}>{c.title} · {terms.data?.items.find(t => t.id === c.term_id)?.name || (terms.error ? "학기 확인 불가" : terms.data ? "학기 미등록" : "학기 확인 중…")}</option>)}</select></label><Link to={`/professor/courses/${selected.id}?tab=materials`}>이 강의실로 이동 ↗</Link></div>
      <Materials key={selected.id} courseId={selected.id} teacher />
    </>}
  </section>;
  return <section className="professor-material-hub professor-student-hub">
    <Link to="/professor" className="teacher-course-back">← 담당 강의</Link>
    <header className="material-hub-heading"><span className="student-eyebrow">YOUR STUDENTS</span><h1>수강생 관리</h1><p>수업을 선택하면 아래에 해당 수업의 분반별 수강생이 표시됩니다.</p></header>
    <ErrorNotice text={courses.error || terms.error} />
    {!courses.data && !courses.error && <Notice>담당 강의를 불러오고 있어요…</Notice>}
    {courses.data?.items.length === 0 && <div className="material-hub-empty"><h2>아직 담당 강의가 없어요.</h2><p>강의를 만들고 분반을 등록하면 수강생을 확인할 수 있어요.</p><Link to="/professor#create-course">강의 만들기 →</Link></div>}
    {selected && <><div className="material-hub-course"><label>수강생을 확인할 수업<select aria-label="수강생을 확인할 수업" value={selected.id} onChange={e => setParams({course:e.target.value})}>{courses.data?.items.map(c => <option key={c.id} value={c.id}>{c.title} · {terms.data?.items.find(t => t.id === c.term_id)?.name || (terms.error ? "학기 확인 불가" : terms.data ? "학기 미등록" : "학기 확인 중…")}</option>)}</select></label><Link to={`/professor/courses/${selected.id}?tab=overview`}>이 강의실로 이동 ↗</Link></div><CourseStudentOverview key={selected.id} courseId={selected.id} /></>}
  </section>;
}
function CourseStudentOverview({courseId}:{courseId:string}) {
  const sections=useLoad<{items:Section[]}>(`/courses/${courseId}/sections`);
  return <div className="student-hub-sections"><div className="teacher-tab-heading"><div><h2>분반별 수강생</h2><p>승인과 분반 이동은 분반 관리에서 진행할 수 있어요.</p></div><Link to={`/professor/courses/${courseId}?tab=sections`}>분반 관리 →</Link></div><ErrorNotice text={sections.error}/>{!sections.data&&!sections.error&&<Notice>분반을 불러오는 중이에요…</Notice>}{sections.data?.items.length===0&&<div className="material-hub-empty"><h2>첫 분반을 만들어 주세요.</h2><p>분반을 등록하고 수강 코드를 안내하면 학생들이 참여할 수 있어요.</p><Link to={`/professor/courses/${courseId}?tab=sections`}>분반 등록하기 →</Link></div>}{sections.data?.items.map(section=><StudentRosterPreview key={section.id} section={section} courseId={courseId}/>)}</div>;
}
function StudentRosterPreview({section,courseId}:{section:Section;courseId:string}) {
  const roster=useLoad<{items:Enrollment[]}>(`/sections/${section.id}/enrollments`);
  const [search,setSearch]=useState("");
  const [status,setStatus]=useState("all");
  const items=roster.data?.items || [];
  const filtered=items.filter(e=>e.display_name.toLowerCase().includes(search.toLowerCase())&&(status==="all"||e.status===status));
  const statusName=(value:string)=>({active:"수강 중",pending:"승인 대기",transferred:"분반 이동",cancelled:"수강 취소"}[value]||value);
  return <section className="student-hub-roster"><div className="student-hub-roster-heading"><div><h3>{section.title}</h3><p>수강 중 <strong>{roster.data?items.filter(e=>e.status==="active").length:"—"}</strong>명<span>승인 대기 <strong>{roster.data?items.filter(e=>e.status==="pending").length:"—"}</strong>명</span></p></div><button onClick={roster.reload}>새로고침</button></div><ErrorNotice text={roster.error}/>{!roster.data&&!roster.error&&<Notice>수강생을 불러오는 중이에요…</Notice>}{roster.data&&<><div className="student-hub-roster-tools"><label>이름 검색<input type="search" placeholder="학생 이름으로 검색" value={search} onChange={e=>setSearch(e.target.value)}/></label><label>수강 상태<select value={status} onChange={e=>setStatus(e.target.value)}><option value="all">전체</option><option value="active">수강 중</option><option value="pending">승인 대기</option><option value="transferred">분반 이동</option><option value="cancelled">수강 취소</option></select></label></div>{!items.length?<p className="student-hub-roster-empty">아직 참여한 학생이 없어요. 분반 관리에서 수강 코드를 발급해 안내하세요.</p>:!filtered.length?<p className="student-hub-roster-empty">조건에 맞는 학생이 없어요.</p>:<ul className="student-hub-roster-list">{filtered.map(e=><li key={e.id}><strong>{e.display_name}</strong><span className={e.status==="pending"?"is-pending":""}>{statusName(e.status)}</span></li>)}</ul>}<div className="student-hub-roster-footer"><span>{filtered.length}명 표시</span><Link to={`/professor/courses/${courseId}?tab=sections`}>수강 승인·분반 이동 →</Link></div></>}</section>;
}
