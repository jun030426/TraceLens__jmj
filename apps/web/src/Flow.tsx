import { archivePath } from "./QuizArchive";
import { CourseCombo } from "./CourseCombo";
import { DropSelect } from "./DropSelect";
import { LearningText } from "./LearningText";
import { initialPeriod } from "./learningPeriod";
import { PeriodFilter } from "./LearningPeriodFilter";
import { StudentPracticeHistory } from "./StudentPracticeHistory";
import "./student-learning.css";
import { useContext, useEffect, useState, type ReactNode } from "react";
import { answerGuide, isChoice, kindLabel } from "./questionKinds";
import {
  Link,
  Navigate,
  useLocation,
  useParams,
  useSearchParams,
} from "react-router-dom";
import { Auth } from "./Auth";
import { termWeeks } from "./classSchedule";
import { api, post, type Classroom, type Course, type Section, type Enrollment, type Term } from "./api";
import { ErrorNotice, Notice, useLoad } from "./components";
import { Chat, Materials } from "./Learning";
import { type Daily } from "./Theory";
import { TheoryHints } from "./TheoryHints";
import { XP_CHANGED } from "./xp/practiceXp";
import { ChatBubbleIcon } from "./ChatFab";
import type { QuizAsk } from "./Learning";
import { ArchivePeriodFilter, LearningHistory, LearningProgress } from "./LearningProgress";
import { WeaknessTab } from "./WeaknessRings";

import { PagedList } from "./StudentLists";
import { matchesSearch } from "./listNavigation";

type Record = {
  id: string;
  section_id: string;
  day: string;
  total: number;
  submitted: number;
  answered?: number;
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
            : "/admin"
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
  const [historyKind, setHistoryKind] = useState("theory");
  const [archiveSection, setArchiveSection] = useState("");
  const [range, setRange] = useState(initialPeriod);
  const practice = useLoad<{ items: { section_id: string; session_id: string; total: number; submitted: number }[] }>("/my/practice-progress");
  const [search, setSearch] = useState("");
  const today = kstDay();
  const history = useLoad<{ items: Record[] }>(`/my/learning-sessions?today_only=true`);
  const [params, setParams] = useSearchParams();
  const selected = params.get("section") || "";
  const active = rooms.data?.items.filter((r) => r.status === "active") || [];
  const filtered = active.filter(r => (!selected || r.section.id === selected) && matchesSearch(search, r.course.title, r.section.title, r.teacher_name));
  const metaRoom = active.find(r => r.section.id === selected) || (active.length === 1 ? active[0] : undefined);
  const practiceRoom = metaRoom || active.find(r => r.section.id === archiveSection) || active[0];
  const records = (history.data?.items || []).filter(
    (s) => !selected || s.section_id === selected,
  );
  return (
    <section className="student-home quiz-catalog">
      <Link className="cr-back" to="/courses"><span aria-hidden="true">←</span> 내 강의로</Link>
      <div className="quiz-titlebar">
        <h1><span className="quiz-title-mark"><time className="quiz-today-date" dateTime={today}>{`${Number(today.slice(0, 4))}년 ${Number(today.slice(5, 7))}월 ${Number(today.slice(8, 10))}일`}</time> 오늘의 학습</span><small className="quiz-title-desc">강의별 이론과 실습을 이어가세요.</small></h1>
        <div className="quiz-header-meta">
          <strong className="quiz-header-streak" role="status" title={streak.error ? "연속 학습 기록을 불러오지 못했어요." : undefined}>{streak.data ? `${streak.data.current_streak}일 연속 학습` : "연속 학습"}</strong>
          {metaRoom && <p className="quiz-course-meta">{metaRoom.course.title} · {metaRoom.term.name} · {metaRoom.teacher_name} · {metaRoom.section.title}</p>}
        </div>
      </div>
      <ErrorNotice text={rooms.error || history.error || practice.error} />
      {practice.error && <button type="button" onClick={practice.reload}>실습 진행 다시 불러오기</button>}
      <div className="student-list-tools">
        <label>강의 선택<select value={selected} onChange={e => setParams(e.target.value ? {section:e.target.value} : {})}><option value="">전체 강의</option>{active.map(r => <option key={r.section.id} value={r.section.id}>{r.course.title} · {r.section.title}</option>)}</select></label>
        {active.length > 3 && <label>강의 검색<input type="search" value={search} onChange={e => setSearch(e.target.value)} placeholder="강의·분반·교수 이름" /></label>}
      </div>
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
          const progress = practice.data?.items.find(item => item.section_id === r.section.id);
          const practiceDone = !!progress && progress.total > 0 && progress.submitted >= progress.total;
          const answered = record?.answered ?? record?.submitted ?? 0;
          const done = record && record.total > 0 && answered >= record.total;
          return (
            <section className="quiz-course-group" key={r.section.id}>
              <header className="quiz-course-heading">
                <h3>{r.course.title.split(/\s+[—–]\s+/)[0]}</h3>
                <span>{r.section.title}</span>
                {r.course.title.split(/\s+[—–]\s+/).length > 1 && <p>{r.course.title.split(/\s+[—–]\s+/).slice(1).join(" — ")}</p>}
              </header>
              <div className="quiz-mode-grid">
                <Link className="quiz-mode-card" to={done ? `/quiz/results/${record.id}` : `/quiz/${r.section.id}`}
                  aria-label={done ? "이론 결과·해설 보기" : record ? "이론 이어서 풀기" : "이론 풀기"}>
                  <div className="quiz-mode-top"><span className="quiz-mode-tag">이론</span><span className="quiz-mode-arrow go-arrow" aria-hidden="true">→</span></div>
                  <h4>배운 개념을 확인해요.</h4>
                  <p className="quiz-mode-description">하루 5문항 · 주차별 7일 · 4일차부터 나의 오답 복습</p>
                  <div className="quiz-mode-footer">
                    <p className="quiz-progress-status">{done
                      ? "오늘 제출 완료 · 눌러서 결과·해설 보기"
                      : record
                        ? `${answered}/${record.total}문항 풀이${record.pending ? ` · 채점·검토 대기 ${record.pending}건` : ""}`
                        : "아직 시작하지 않았어요."}</p>
                  </div>
                </Link>
                <Link className="quiz-mode-card quiz-practice-card" to={`/classrooms/${r.section.id}/practice${practiceDone ? "/results?plan="+encodeURIComponent(progress.session_id) : ""}`} aria-label={practiceDone ? "실습 결과 보기" : "실습 풀기"}>
                  <div className="quiz-mode-top"><span className="quiz-mode-tag">실습 · {({ python: "Python", java: "Java", c: "C" } as { [key: string]: string })[r.course.teaching_language.toLowerCase()] || r.course.teaching_language}</span><span className="quiz-mode-arrow go-arrow" aria-hidden="true">→</span></div>
                  <h4>직접 풀며 연결해요.</h4>
                  <p className="quiz-mode-description">이번 주 강의 코드로 빈칸과 풀코딩을 연습해요.</p>
                  <div className="quiz-mode-footer"><p className={`quiz-progress-status ${practiceDone ? "is-done" : progress?.submitted ? "is-progress" : ""}`}>
                    {practice.error ? "제출 기록을 확인할 수 없어요." : !practice.data ? "기록 확인 중…" :
                      practiceDone ? "오늘 제출 완료 · 결과 보기" : progress?.total ? `${progress.submitted}/${progress.total}문제 제출` : progress ? "오늘 배정된 실습이 없어요." : "아직 시작하지 않았어요."}
                  </p></div>
                </Link>
              </div>
              <Link className="qa-entry" to={archivePath(r.section.id)}><span>이전 퀴즈 보기</span><span aria-hidden="true">→</span></Link>
            </section>
          );
        })}
      </div>}</PagedList>
      <div className="quiz-streak-summary">
        <p>{streak.error ? "연속 학습 기록을 불러오지 못했어요." : !streak.data ? "학습 기록을 확인하고 있어요…" : streak.data.today_completed ? "오늘의 학습 완료 · 내일도 이어가 보세요." : "이론 또는 실습을 완료하면 오늘의 학습으로 인정돼요."}</p>
        <button type="button" className="quiz-criteria-toggle" aria-expanded={criteriaOpen} aria-controls="quiz-criteria" onClick={() => setCriteriaOpen(!criteriaOpen)}>인정 기준 <svg aria-hidden="true" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><path d="m6 9 6 6 6-6" /></svg></button>
        <div id="quiz-criteria" className="quiz-criteria-body" hidden={!criteriaOpen}>
          <p>이론 또는 실습의 하루 묶음을 최종 제출하면 정답 여부와 관계없이 인정돼요.</p>
          <p>한국 시간 기준 하루 1회 · 풀이 시작, 부분 제출, 코드 실행만으로는 인정되지 않아요.</p>
        </div>
      </div>
      <details className="student-record-archive" onToggle={e => setHistoryOpen(e.currentTarget.open)}>
        <summary><span className="record-archive-title">지난 학습·복습 기록</span> <small>날짜별 이론 답안과 실습 채점 결과</small></summary>
        {historyOpen && <div className="learning-progress archive-controls">
          <ArchivePeriodFilter value={range} onChange={setRange}>
            <div className="record-kind-tabs" role="group" aria-label="지난 기록 종류">
              {([["theory", "이론 기록"], ["practice", "실습 기록"]] as const).map(([key, label]) =>
                <button type="button" key={key} className={historyKind === key ? "is-active" : ""}
                  aria-pressed={historyKind === key} onClick={() => setHistoryKind(key)}>{label}</button>)}
            </div>
          </ArchivePeriodFilter>
          {historyKind === "theory" ? <LearningHistory key={`${selected}:${range.from}:${range.to}`} sectionId={selected || undefined} classrooms={active} period={range} /> :
            practiceRoom ? <>
              {!selected && active.length > 1 && <DropSelect label="실습 기록 강의" value={practiceRoom.section.id}
                options={active.map(r => ({ value: r.section.id, label: r.course.title+" · "+r.section.title }))} onChange={setArchiveSection} />}
              <StudentPracticeHistory key={`${practiceRoom.section.id}:${range.from}:${range.to}`} room={practiceRoom} period={range} />
            </> : <Notice>수강 중인 강의가 없어요.</Notice>}
        </div>}
      </details>
    </section>
  );
}

function draftKey(userId: string, sessionId: string) {
  return `lerny-quiz:${userId}:${sessionId}`;
}
export function QuizTakeFlow() {
  const { sectionId = "", week, dayIndex } = useParams();
  const [params] = useSearchParams();
  const archiveSession = params.get("session");
  const path = week ? `/sections/${sectionId}/quiz-archive/${week}/days/${dayIndex}${archiveSession ? "?session_id=" + encodeURIComponent(archiveSession) : ""}`
    : `/sections/${sectionId}/daily`;
  return <QuizQuestions key={path} sectionId={sectionId} path={path} week={week} dayIndex={dayIndex} />;
}

function QuizQuestions({ sectionId, path, week, dayIndex }: { sectionId: string; path: string; week?: string; dayIndex?: string }) {
  const back = week ? archivePath(sectionId, week) + "/theory" : `/quiz?section=${sectionId}`;
  const heading = week ? `${week}주차 · ${dayIndex}일차 개념 퀴즈` : "오늘의 이론";
  const { user } = useContext(Auth);
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
    api<Daily>(path, post({}))
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
  }, [path, user?.id]);
  useEffect(() => {
    if (week || !daily || daily.items.length || !["queued", "running", "waiting_ai"].includes(daily.status || "")) return;
    let active = true;
    const timer = setInterval(() => {
      void api<Daily>(`/sections/${sectionId}/daily`, post({}))
        .then(d => { if (active) { setDaily(d); setError(""); } })
        .catch(e => { if (active) setError(e.message); });
    }, 4000);
    return () => { active = false; clearInterval(timer); };
  }, [daily?.id, daily?.status, daily?.items.length, sectionId, week]);
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
    setError("");
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
  // 한 문항씩 정답 확인 (11-14): 이 문항만 제출하고, 바로 정답·해설을 받아와 같은 화면에 보여 줘요
  const checkOne = async () => {
    if (!daily) return;
    const item = daily.items[index];
    if (!item || item.attempt || item.status === "unavailable") return;
    if (!answers[item.id]?.trim()) { setError("답을 고르거나 적은 뒤 정답을 확인해 주세요."); return; }
    setError("");
    setBusy(true);
    try {
      await api(`/learning-sessions/${daily.id}/questions/${item.id}/submit`, {
        ...post({ answer: answers[item.id] }),
        headers: { "Idempotency-Key": `${daily.id}:${item.id}` },
      });
      window.dispatchEvent(new Event(XP_CHANGED));
      setDaily(await api<Daily>(`/learning-sessions/${daily.id}`));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const pendingId = daily?.items.some((it) => it.attempt?.status === "pending") ? daily.id : "";
  useEffect(() => {
    if (!pendingId) return;
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const fresh = await api<Daily>(`/learning-sessions/${pendingId}`);
        if (!active) return;
        setDaily(fresh); setError("");
        if (!fresh.items.some(q => q.attempt?.status === "pending")) return;
      } catch (e) { if (active) setError((e as Error).message); }
      if (active) timer = setTimeout(poll, 3000);
    };
    timer = setTimeout(poll, 3000);
    return () => { active = false; clearTimeout(timer); };
  }, [pendingId]);
  if (!daily || !daily.items.length)
    return (
      <section className="student-home quiz-flow theory-workspace">
        <Link to={back}>← {week ? "날짜 목록" : "퀴즈 목록"}</Link>
        <h1>{week ? heading : "오늘의 퀴즈"}</h1>
        {error ? (
          <ErrorNotice text={error} />
        ) : (
          <><Notice>{daily?.status === "failed" ? "오늘의 문항 준비를 완료하지 못했어요." : daily?.message || (week ? "저장된 문항을 불러오는 중이에요." : "문항을 준비하고 있어요…")}</Notice>
          {daily?.retry_at && <p>{new Date(daily.retry_at).toLocaleString("ko-KR", {timeZone:"Asia/Seoul"})} 이후 자동으로 다시 준비해요.</p>}</>
        )}
        {daily?.status === "failed" && daily.job_id && <button disabled={busy} onClick={async () => {
          setBusy(true); setError("");
          try { await api(`/jobs/${daily.job_id}/retry`, post({})); setDaily(await api<Daily>(`/sections/${sectionId}/daily`, post({}))); }
          catch (e) { setError((e as Error).message); } finally { setBusy(false); }
        }}>문항 준비 다시 시도</button>}
      </section>
    );
  const q = daily.items[index];
  const complete = daily.items.every(
    (q) => q.attempt || q.status === "unavailable",
  );
  return (
    <section className="student-home quiz-flow theory-workspace">
      <Link to={back}>← {week ? "날짜 목록" : "퀴즈 목록"}</Link>
      <div className="theory-title-row"><h1>{heading}</h1><span>{daily.items.filter(item => item.attempt).length} / {daily.items.length}문항 확인</span></div>
      <p>
        문항마다 한 번만 제출할 수 있어요. '정답 확인'을 누르면 내 답안이 저장돼요. 모두 풀면
        전체 문항의 답과 해설을 한 번에 볼 수 있어요.
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
            {item.attempt ? (item.attempt.status === "graded" ? (item.attempt.correct ? "정답" : "복습") : item.attempt.status === "pending" ? "채점 중" : "확인") : answers[item.id] ? "작성됨" : ""}
          </button>
        ))}
      </nav>
      {q && (
        <article className="panel theory-question">
          <small>
            {index + 1} / {daily.items.length} ·{" "}
            {kindLabel(q.kind)}{q.quiz_role && ` · ${q.quiz_role}`}
          </small>
          <h2>{q.prompt}</h2>
          {q.attempt ? (
            <TheoryCheckResult q={q} index={index} sectionId={daily.section_id} />
          ) : q.status === "unavailable" ? (
            <Notice>이 문항은 변경되어 제출할 수 없어요.</Notice>
          ) : (
            <fieldset disabled={busy}>
              <legend className="theory-answer-legend">{answerGuide(q.kind)}</legend>
              {isChoice(q.kind) ? (
                q.options.map((option, i) => (
                  <label className={`answer-option ${answers[q.id] === String(i) ? "is-chosen" : ""}`} key={i}>
                    <input
                      type="radio"
                      name={q.id}
                      checked={answers[q.id] === String(i)}
                      onChange={() => choose(String(i))}
                    />
                    <span className="theory-option-number" aria-hidden="true">{q.kind === "ox" ? option : i + 1}</span><span>{q.kind === "ox" ? (option === "O" ? "맞아요" : "틀려요") : option}</span>
                  </label>
                ))
              ) : q.kind === "blank" ? (
                <label className="theory-blank-answer">
                  빈칸에 들어갈 말
                  <input
                    type="text"
                    value={answers[q.id] || ""}
                    onChange={(e) => choose(e.target.value)}
                    maxLength={100}
                    autoComplete="off"
                    placeholder="정답을 적어 주세요."
                  />
                </label>
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
          {!q.attempt && q.status !== "unavailable" && (
            <TheoryHints key={q.id} storageKey={`lerny-quiz-hint:${user?.id}:${daily.id}:${q.id}`}
              loadQuote={async () => {
                setBusy(true);
                try {
                  const response = await api<{ hint: string }>(`/learning-sessions/${daily.id}/questions/${q.id}/help`, post({}));
                  return response.hint;
                } finally {
                  setBusy(false);
                }
              }}
            />
          )}
          <ErrorNotice text={error} />
          <div className="flow-actions">
            <button
              disabled={index === 0 || busy}
              onClick={() => move(index - 1)}
            >
              이전 문항
            </button>
            <div className="theory-check-actions">
              {/* 한 자리 버튼 (11-14): 답을 고르거나 쓰면 [정답 확인], 확인했거나 아직 안 풀었으면 [다음 문항],
                  마지막 문항에서 안 푼 문항이 남았으면 [남은 문항 풀기], 모두 풀면 [퀴즈 나가기]·[전체 답·해설 보기] */}
              {(() => {
                const open = !q.attempt && q.status !== "unavailable";
                const leftIndex = daily.items.findIndex((it, i) => i !== index && !it.attempt && it.status !== "unavailable");
                if (open && answers[q.id]?.trim())
                  return <button className="primary theory-check-button" disabled={busy} onClick={() => void checkOne()}>{busy ? "확인 중…" : "정답 확인"}</button>;
                if (complete)
                  return <>
                    <Link className="link-button" to={back}>퀴즈 나가기</Link>
                    <Link className="primary link-button" to={`/quiz/results/${daily.id}${week ? "?week="+week+"&day="+dayIndex : ""}`}>전체 답·해설 보기 <span className="go-arrow" aria-hidden="true">→</span></Link>
                  </>;
                if (index < daily.items.length - 1)
                  return <button className={open ? "" : "primary"} disabled={busy} onClick={() => move(index + 1)}>다음 문항 <span className="go-arrow" aria-hidden="true">→</span></button>;
                if (leftIndex >= 0)
                  return <button className="primary" disabled={busy} onClick={() => move(leftIndex)}>남은 문항 풀기 <span className="go-arrow" aria-hidden="true">→</span></button>;
                return <button className="primary theory-check-button" disabled>정답 확인</button>;
              })()}
            </div>
          </div>
          {complete && <p className="theory-all-done">모든 문항을 풀었어요. 답안은 문항마다 정답을 확인할 때 이미 제출됐어요. 퀴즈를 나가거나 전체 답과 해설을 한 번에 볼 수 있어요.</p>}
        </article>
      )}
    </section>
  );
}

/* 개념 퀴즈 해설 아래 "AI에게 물어보기" 바로가기.
   누르면 AI 질문 화면으로 가면서 이 문항(문제·내 답안·정답·해설)을 함께 넘기고, 질문 칸에 질문 예시를 적어 둬요.
   문제 상황을 질문 본문에 함께 보내고, 학생은 보내기 전에 뺄 수 있어요. */
type DailyItem = Daily["items"][number];
function quizAskOf(q: DailyItem, index: number): QuizAsk {
  const graded = q.attempt?.status === "graded";
  const lines = [
    `개념 퀴즈 문제: ${q.prompt}`,
    `유형: ${kindLabel(q.kind)}`,
    q.options?.length ? `보기: ${q.options.join(" / ")}` : "",
    q.submitted_answer ? `학생 답안: ${q.submitted_answer}` : "",
    q.correct_option ? `정답: ${q.correct_option}` : "",
    `채점: ${graded ? (q.attempt!.correct ? "정답" : "오답") : q.attempt?.status === "pending" ? "채점 중" : q.attempt ? "검토 보류" : "미제출"}`,
    q.explanation ? `해설: ${q.explanation}` : "",
  ].filter(Boolean);
  return {
    title: `${index + 1}번 · ${q.prompt.length > 40 ? q.prompt.slice(0, 40) + "…" : q.prompt}`,
    question: graded && !q.attempt!.correct
      ? "제 답안이 왜 틀렸는지, 해설을 더 쉽게 설명해 주세요."
      : "이 문제의 해설을 다른 예시로 한 번 더 설명해 주세요.",
    conceptId: q.concept_id,
    context: lines.join("\n").slice(0, 3000),
  };
}
/* 한 문항 정답 확인 결과 — 결과 화면과 같은 모양으로 이 문항의 정답·해설을 바로 보여 줘요 (11-14) */
function TheoryCheckResult({ q, index, sectionId }: { q: DailyItem; index: number; sectionId: string }) {
  const graded = q.attempt?.status === "graded";
  const right = graded && !!q.attempt?.correct;
  const sameAsMine = q.kind !== "essay" && right && (q.kind === "blank" || q.submitted_answer === q.correct_option);
  return (
    <div className={`result-question theory-check-result ${graded ? (right ? "result-correct" : "result-review") : "result-pending"}`} aria-live="polite">
      <div className="result-question-meta">
        <small>정답 확인</small>
        <span className={`result-status ${graded ? (right ? "is-correct" : "is-review") : "is-pending"}`}>{graded ? (right ? "정답" : "복습해 보세요") : q.attempt?.status === "pending" ? "채점 중" : "검토 보류"}</span>
      </div>
      <div className="result-answer-comparison">
        {q.submitted_answer && <p className={`result-answer ${right ? "result-correct-answer" : ""}`}><strong>{sameAsMine ? "내 답안 · 정답" : "내 답안"}</strong><span>{q.submitted_answer}</span></p>}
        {q.correct_option && !sameAsMine && <p className="result-answer result-correct-answer"><strong>정답</strong><span>{q.correct_option}</span></p>}
      </div>
      {graded ? (q.attempt?.feedback?.message && q.attempt.feedback.message !== "정답이에요." && <p className="result-feedback">{q.attempt.feedback.message}</p>)
        : <Notice>{q.attempt?.status === "pending" ? "채점 중이에요. 잠시 뒤 정답과 해설이 여기에 나와요." : q.attempt?.feedback?.message || "검토 보류 중이에요."}</Notice>}
      {q.explanation && <details open><summary>해설</summary><LearningText text={q.explanation} /></details>}
      {(graded || q.explanation) && <QuizAskLink sectionId={sectionId} q={q} index={index} />}
    </div>
  );
}
function QuizAskLink({ sectionId, q, index }: { sectionId: string; q: DailyItem; index: number }) {
  return (
    <Link className="quiz-ask-link" to={`/ai?section=${encodeURIComponent(sectionId)}`} state={{ quizAsk: quizAskOf(q, index) }}>
      <span className="quiz-ask-link__icon"><ChatBubbleIcon size={18} /></span>
      <span className="quiz-ask-link__text"><strong>해설이 아직 헷갈리나요? AI에게 물어보기 →</strong><small>이 문제와 내 답안을 함께 보내 바로 질문할 수 있어요.</small></span>
    </Link>
  );
}

export function QuizResults() {
  const [actionError, setActionError] = useState("");
  const { learningId = "" } = useParams();
  const r = useLoad<Daily>(`/learning-sessions/${learningId}`);
  const { hash } = useLocation();
  const [params] = useSearchParams();
  const week = params.get("week");
  const day = params.get("day");
  const archive = r.data && week && day ? archivePath(r.data.section_id, week) + "/theory" : "";
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
      <Link className="cr-back" to={archive || (r.data ? `/quiz?section=${r.data.section_id}` : "/quiz")}><span aria-hidden="true">←</span> {archive ? "날짜 목록" : "퀴즈 목록"}</Link>
      {/* 제목 옆에 안내 문구를 붙여요 (2026-11-18) */}
      <div className="result-titlebar"><h1>결과와 복습</h1><p className="result-intro">맞힌 이유도, 헷갈린 부분도. 해설과 함께 이해를 한 걸음 넓혀 보세요.</p></div>
      <ErrorNotice text={r.error} />
      {!r.data && !r.error && <Notice>결과를 불러오는 중…</Notice>}
      {r.data && (
        <>
          <div className="result-overview">
            <div className="result-overview-title"><div><h2>{submitted.length}/{r.data.items.length}문항 제출</h2></div><button onClick={r.reload}>채점 상태 새로고침 ↻</button></div>
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
                {i + 1}번 · {kindLabel(q.kind)}
              </small><span className={`result-status ${q.attempt?.status === "graded" ? (q.attempt.correct ? "is-correct" : "is-review") : "is-pending"}`}>{q.attempt?.status === "graded" ? (q.attempt.correct ? "정답" : "복습해 보세요") : q.attempt?.status === "pending" ? "채점 중" : q.attempt ? "검토 보류" : "미제출"}</span></div>
              <h2>{q.prompt}</h2>
              <div className="result-answer-comparison">
              {q.submitted_answer && (
                <p className="result-answer">
                  <strong>{q.kind !== "essay" && q.attempt?.status === "graded" && q.attempt.correct && (q.kind === "blank" || q.submitted_answer === q.correct_option) ? "내 답안 · 정답" : "내 답안"}</strong><span>{q.submitted_answer}</span>
                </p>
              )}
              {q.correct_option && !(q.kind !== "essay" && q.attempt?.status === "graded" && q.attempt.correct && (q.kind === "blank" || q.submitted_answer === q.correct_option)) && (
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
                  <LearningText text={q.explanation} />
                </details>
              )}
              {(q.attempt || q.explanation) && <QuizAskLink sectionId={r.data!.section_id} q={q} index={i} />}
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
            {submitted.length < r.data.items.length && (
              <Link to={archive ? `${archive}/${day}?session=${learningId}` : `/quiz/${r.data.section_id}`}>
                남은 문항 이어서 풀기 →
              </Link>
            )}
            <Link to="/student">홈으로</Link>
            <Link to={`/ai?section=${r.data.section_id}`}>
              이 강의에 질문하기
            </Link>
            <Link to="/quiz">다른 강의 퀴즈 보기</Link>
            <Link
              className="primary link-button"
              to={`/attendance?section=${r.data.section_id}`}
            >
              내 복습 현황 →
            </Link>
          </div>
        </>
      )}
      <ErrorNotice text={actionError} />
    </section>
  );
}

export function CourseWorkspace({ mode }: { mode: "chat" | "progress" }) {
  const [period, setPeriod] = useState(initialPeriod);
  const rooms = useLoad<{ items: Classroom[] }>("/classrooms");
  const [params, setParams] = useSearchParams();
  // 학습 기록 탭: 이론 · 실습 · 취약도 (취약도 탭은 2026-11-14 추가)
  const domain = params.get("domain") === "practice" ? "practice" : params.get("domain") === "weakness" ? "weakness" : "theory";
  const DOMAIN_LABEL = { theory: "이론", practice: "실습", weakness: "취약도" } as const;
  const active = rooms.data?.items.filter((r) => r.status === "active") || [];
  const room = active.find((r) => r.section.id === params.get("section"));
  return (
    <section className={mode === "chat" ? "student-home ai-page chat-page" : "student-home progress-page ai-page"}>
      {mode === "chat" && <span className="student-eyebrow">CONNECT THROUGH QUESTIONS</span>}
      {mode === "progress" && <header className="progress-title-row">
        <h1>학습 기록과 복습</h1>
        <p className="progress-caption">개념별 학습과 복습할 내용을 확인해 보세요.</p>
        {room && <span className="progress-domain-label">{DOMAIN_LABEL[domain]}</span>}
      </header>}
      <ErrorNotice text={rooms.error} />
      <div className={"workspace ai-workspace"}>
        {mode === "chat" && <div className="chat-mobile-course"><label>질문할 강의<select value={room?.section.id || ""} onChange={e => setParams({ section: e.target.value })}><option value="" disabled>강의를 선택하세요</option>{active.map(r => <option key={r.section.id} value={r.section.id}>{r.course.title} · {r.section.title}</option>)}</select></label><Link className="course-rail-manage" to="/courses">강의·수강 관리 <span className="go-arrow" aria-hidden="true">→</span></Link></div>}
        {(() => { const rail = (
        <aside className="course-rail">
          <div className="course-rail-head"><h2>내 강의</h2><Link className="course-rail-manage" to="/courses">강의·수강 관리 <span className="go-arrow" aria-hidden="true">→</span></Link></div>
          {active.length > 5 ? <div className="student-course-choice"><label>학습할 강의<select value={room?.section.id || ""} onChange={e => setParams(mode === "progress" ? {section:e.target.value,domain} : {section:e.target.value})}><option value="" disabled>강의를 선택하세요</option>{active.map(r => <option key={r.section.id} value={r.section.id}>{r.course.title} · {r.section.title}</option>)}</select></label>{room && <p>{room.course.title}<br />{room.section.title}</p>}</div> : <>
          {active.map((r) => {
            const [subject] = r.course.title.split(/\s+[—–]\s+/);
            return (
              <button
                aria-pressed={room?.section.id === r.section.id}
                className={room?.section.id === r.section.id ? "selected" : ""}
                key={r.section.id}
                onClick={() => setParams(mode === "progress" ? { section: r.section.id, domain,  } : { section: r.section.id })}
              >
                <span className="course-rail-subject course-rail-title">{subject}{r.teacher_name && <span className="course-rail-teacher">{r.teacher_name}</span>}</span>
                <small className="course-rail-term">{[r.term?.name, r.section.title].filter(Boolean).join(" · ")}</small>
              </button>
            );
          })}
          </>}
        </aside>
        ); return mode === "chat" ? <div className="ai-side">{rail}{/* 이전 질문 내역 — Chat 이 이 자리에 그려요 */}<div id="chat-archive-slot" className="chat-archive-slot" /></div> : rail; })()}
        <div>
          {room ? (
            mode === "chat" ? (
              <Chat key={room.section.id} sectionId={room.section.id} courseId={room.course.id} />
            ) : (
              <section className="panel progress-panel">
                <h2>{room.course.title.split(/\s+[—–]\s+/)[0]}</h2>
                <p className="progress-caption">{room.section.title} · {domain === "weakness" ? "개념별 취약도" : `${DOMAIN_LABEL[domain]} 학습 기록`}</p>
                <div className="progress-domain-tabs" aria-label="학습 유형">{(["theory", "practice", "weakness"] as const).map(d => <button key={d} aria-pressed={domain === d} onClick={() => setParams({ section: room.section.id, domain: d })}>{DOMAIN_LABEL[d]}</button>)}</div>
                <div className="student-period">
                  <p><strong>조회 기간</strong> · {period.from} ~ {period.to} (한국 시간)</p>
                  <details><summary>기간 변경</summary><PeriodFilter value={period} onChange={setPeriod} variant="calendar" /></details>
                  <small>이론·실습·취약도에 같은 기간을 적용해요. 교수자 화면과 동일한 기준이에요.</small>
                </div>
                {domain === "theory" ? <LearningProgress key={room.section.id} room={room} period={period} />
                  : domain === "weakness" ? <WeaknessTab key={room.section.id} room={room} period={period} />
                  : <StudentPracticeHistory key={`${room.section.id}:${period.from}:${period.to}`} room={room} period={period} />}
                <div className="progress-actions"><p>학습 기록은 학교의 공식 출결과 별개예요.</p><Link className="ln-cta" to={domain === "practice" ? `/classrooms/${room.section.id}/practice` : `/quiz?section=${room.section.id}`}>{domain === "practice" ? "실습 이어가기" : "퀴즈로 학습 이어가기"} <span className="go-arrow" aria-hidden="true">→</span></Link></div>
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
          <Link to="/home">내 홈으로 <span className="go-arrow" aria-hidden="true">→</span></Link>
        </section>
        <div className="profile-details">
          <section className="profile-card">
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
            <div><h2>비밀번호 관리</h2><p>계정을 보호할 새로운 비밀번호로 변경할 수 있어요.</p></div>
            <Link className="ln-cta" to="/change-password">비밀번호 변경 <span className="go-arrow" aria-hidden="true">→</span></Link>
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
  const pickedTerm = terms.data?.items.find(t => t.id === selected?.term_id);
  const today = kstDay();
  const week = pickedTerm && pickedTerm.starts_on <= today && today <= pickedTerm.ends_on
    ? 1 + Math.floor((Date.parse(today) - Date.parse(pickedTerm.starts_on)) / 604800000) : null;
  const picker = selected && <><CourseCombo label={mode === "materials" ? "자료를 관리할 수업" : "수강생을 확인할 수업"}
    value={selected.id} onChange={course => setParams({ course })}
    options={(courses.data?.items || []).map(c => ({ value: c.id, label: c.title+" · "+(terms.data?.items.find(t => t.id === c.term_id)?.name || "학기 확인 중") }))} />
    {week && <span className="teacher-now-week">학기 {week}주차</span>}</>;
  if (mode === "materials") return <section className="professor-material-hub">
    <Link to="/professor" className="teacher-course-back">← 담당 강의</Link>
    <header className="material-hub-heading"><h1>강의 자료 관리</h1><p>담당 강의의 자료를 확인하고, 새로운 수업 자료를 올리세요.</p></header>
    <ErrorNotice text={courses.error || terms.error} />
    {!courses.data && !courses.error && <Notice>담당 강의를 불러오고 있어요…</Notice>}
    {courses.data?.items.length === 0 && <div className="material-hub-empty"><h2>먼저 강의를 만들어 주세요.</h2><p>강의를 등록하면 이곳에서 수업 자료를 관리할 수 있어요.</p><Link to="/professor#create-course">강의 만들기 →</Link></div>}
    {selected && <>
      <div className="material-hub-course">{picker}<Link to={`/professor/courses/${selected.id}?tab=materials`}>이 강의실로 이동 ↗</Link></div>
      <Materials key={selected.id} courseId={selected.id} teacher totalWeeks={termWeeks(pickedTerm?.starts_on, pickedTerm?.ends_on)} />
    </>}
  </section>;
  return <section className="professor-material-hub professor-student-hub">
    <Link to="/professor" className="teacher-course-back">← 담당 강의</Link>
    <header className="material-hub-heading"><h1>수강생 관리</h1><p>수업을 선택하면 아래에 해당 수업의 분반별 수강생이 표시됩니다.</p></header>
    <ErrorNotice text={courses.error || terms.error} />
    {!courses.data && !courses.error && <Notice>담당 강의를 불러오고 있어요…</Notice>}
    {courses.data?.items.length === 0 && <div className="material-hub-empty"><h2>아직 담당 강의가 없어요.</h2><p>강의를 만들고 분반을 등록하면 수강생을 확인할 수 있어요.</p><Link to="/professor#create-course">강의 만들기 →</Link></div>}
    {selected && <><div className="material-hub-course">{picker}<Link to={`/professor/courses/${selected.id}?tab=overview`}>이 강의실로 이동 ↗</Link></div><CourseStudentOverview key={selected.id} courseId={selected.id} /></>}
  </section>;
}
function CourseStudentOverview({courseId}:{courseId:string}) {
  const sections=useLoad<{items:Section[]}>(`/courses/${courseId}/sections`);
  const [picked,setPicked]=useState("");
  return <div className="student-hub-sections"><div className="teacher-tab-heading"><div><h2>분반별 수강생</h2><p>승인과 분반 이동은 분반 관리에서 진행할 수 있어요.</p></div><Link to={`/professor/courses/${courseId}?tab=sections`}>분반 관리 →</Link></div><ErrorNotice text={sections.error}/>{!sections.data&&!sections.error&&<Notice>분반을 불러오는 중이에요…</Notice>}{sections.data?.items.length===0&&<div className="material-hub-empty"><h2>첫 분반을 만들어 주세요.</h2><p>분반을 등록하고 수강 코드를 안내하면 학생들이 참여할 수 있어요.</p><Link to={`/professor/courses/${courseId}?tab=sections`}>분반 등록하기 →</Link></div>}{(()=>{const list=sections.data?.items||[]; const cur=list.find(x=>x.id===picked)||list[0]; return cur?<StudentRosterPreview key={cur.id} section={cur} courseId={courseId} picker={list.length>1?<div className="roster-section-picker" role="tablist" aria-label="분반 선택">{list.map(x=><button key={x.id} type="button" role="tab" aria-selected={x.id===cur.id} className={x.id===cur.id?"is-active":""} onClick={()=>setPicked(x.id)}>{x.title}</button>)}</div>:null}/>:null;})()}</div>;
}
function StudentRosterPreview({section,courseId,picker}:{section:Section;courseId:string;picker?:ReactNode}) {
  const roster=useLoad<{items:Enrollment[]}>(`/sections/${section.id}/enrollments`);
  const [search,setSearch]=useState("");
  const [status,setStatus]=useState("all");
  const items=roster.data?.items || [];
  const filtered=items.filter(e=>e.display_name.toLowerCase().includes(search.toLowerCase())&&(status==="all"||e.status===status));
  const statusName=(value:string)=>({active:"수강 중",pending:"승인 대기",transferred:"분반 이동",cancelled:"수강 취소"}[value]||value);
  return <section className="student-hub-roster"><div className="student-hub-roster-heading">{picker||<h3>{section.title}</h3>}{roster.data&&<div className="roster-filter-bar"><div className="roster-status-tabs" role="tablist" aria-label="수강 상태">{([["all","전체",items.length],["active","수강 중",items.filter(e=>e.status==="active").length],["pending","승인 대기",items.filter(e=>e.status==="pending").length]] as const).map(([v,label,n])=><button key={v} type="button" role="tab" aria-selected={status===v} className={status===v?"is-active":""} onClick={()=>setStatus(v)}>{label}<span>{n}</span></button>)}</div><label className="roster-search"><span className="sr-only">학생 이름 검색</span><input type="search" placeholder="학생 이름 검색" value={search} onChange={e=>setSearch(e.target.value)}/></label></div>}<button onClick={roster.reload}>새로고침</button></div><ErrorNotice text={roster.error}/>{!roster.data&&!roster.error&&<Notice>수강생을 불러오는 중이에요…</Notice>}{roster.data&&<>{!items.length?<p className="student-hub-roster-empty">아직 참여한 학생이 없어요. 분반 관리에서 수강 코드를 발급해 안내하세요.</p>:!filtered.length?<p className="student-hub-roster-empty">조건에 맞는 학생이 없어요.</p>:<ul className="student-hub-roster-list">{filtered.map(e=><li key={e.id}><strong>{e.display_name}</strong><span className={`is-${e.status}`}>{statusName(e.status)}</span></li>)}</ul>}<div className="student-hub-roster-footer"><span>{filtered.length}명 표시</span><Link to={`/professor/courses/${courseId}?tab=sections`}>수강 승인·분반 이동 →</Link></div></>}</section>;
}
