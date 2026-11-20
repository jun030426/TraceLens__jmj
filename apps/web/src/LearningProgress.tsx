import { PeriodFilter } from "./LearningPeriodFilter";
import { DropSelect } from "./DropSelect";
import { useCallback, useState } from "react";
import { Link } from "react-router-dom";
import { api, type Classroom } from "./api";
import { ErrorNotice, Notice, useLoad } from "./components";
import {
  conceptStatus,
  reviewReason,
  suggestedConcepts,
  type LearningConcept,
} from "./conceptProgress";
import { weekLabel, type LearningRecord } from "./studentOverview";
import type { Daily } from "./Theory";
import "./learning-progress.css";
import { initialPeriod, periodQuery, type Period } from "./learningPeriod";

const statusLabels: Record<string, string> = {
  review: "복습 필요",
  learning: "추가 확인",
  insufficient: "표본 부족",
  no_data: "이론 기록 없음",
  mastered: "기준 충족",
};
const PAGE_SIZE = 10;

export function LearningProgress({ room, period }: { room: Classroom; period: Period }) {
  const [tab, setTab] = useState("concepts");
  return (
    <div className="learning-progress">
      <div className="learning-view-tabs" aria-label="학습 기록 보기 방식">
        <button
          aria-pressed={tab === "concepts"}
          onClick={() => setTab("concepts")}
        >
          개념별 학습
        </button>
        <button
          aria-pressed={tab === "history"}
          onClick={() => setTab("history")}
        >
          날짜별 기록
        </button>
      </div>
      <div hidden={tab !== "concepts"}>
        <ConceptProgress key={`${period.from}:${period.to}`} room={room} period={period} />
      </div>
      {tab === "history" && <LearningHistory key={`${period.from}:${period.to}`} sectionId={room.section.id} period={period} />}
    </div>
  );
}

function ConceptAction({
  concept,
  sectionId,
}: {
  concept: LearningConcept;
  sectionId: string;
}) {
  const review = concept.review_session_id && concept.review_question_id;
  return (
    <Link
      className="concept-study-link"
      to={
        review
          ? `/quiz/results/${concept.review_session_id}#question-${concept.review_question_id}`
          : `/classrooms/${sectionId}${concept.weeks.length ? `#material-week-${concept.weeks[0]}` : ""}`
      }
    >
      {review ? "답안·해설 보기" : "강의 자료 보기"}{" "}
      <span className="go-arrow" aria-hidden="true">→</span>
    </Link>
  );
}

function ConceptProgress({ room, period }: { room: Classroom; period: Period }) {
  const result = useLoad<{
    items: LearningConcept[];
    today: string;
    current_week: number | null;
  }>(`/sections/${room.section.id}/my-learning?${periodQuery(period)}`);
  const [search, setSearch] = useState("");
  const [scope, setScope] = useState("current");
  const [status, setStatus] = useState("all");
  const [week, setWeek] = useState("all");
  const [page, setPage] = useState(0);
  const quizzes = useConceptQuizzes(room.section.id, period);
  const change = (setter: (value: string) => void, value: string) => {
    setter(value);
    setPage(0);
  };
  if (result.error)
    return (
      <>
        <ErrorNotice text={result.error} />
        <button onClick={result.reload}>다시 불러오기</button>
      </>
    );
  if (!result.data) return <Notice>개념별 학습을 불러오는 중이에요…</Notice>;
  const { items, today, current_week: currentWeek } = result.data;
  const suggested = suggestedConcepts(items, today, currentWeek);
  const weeks = [...new Set(items.flatMap((item) => item.weeks))].sort(
    (a, b) => a - b,
  );
  const filtered = items
    .filter(
      (item) =>
        item.concept
          .toLocaleLowerCase()
          .includes(search.trim().toLocaleLowerCase()) &&
        (scope === "all" ||
          (scope === "current" ? item.in_scope : !item.in_scope)) &&
        (status === "all" || conceptStatus(item, today) === status) &&
        (week === "all" ||
          (week === "none"
            ? item.weeks.length === 0
            : item.weeks.includes(Number(week)))),
    )
    .sort(
      (a, b) =>
        Number(b.in_scope) - Number(a.in_scope) ||
        (a.weeks[0] ?? 999) - (b.weeks[0] ?? 999) ||
        a.concept.localeCompare(b.concept, "ko"),
    );
  const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const currentPage = Math.min(page, pageCount - 1);
  const visible = filtered.slice(
    currentPage * PAGE_SIZE,
    (currentPage + 1) * PAGE_SIZE,
  );
  return (
    <>
      <section
        className="concept-recommendations"
        aria-labelledby="concept-recommendation-title"
      >
        <div className="concept-section-heading">
          <div>
            <span className="concept-kicker">{weekLabel(currentWeek)}</span>
            <h3 id="concept-recommendation-title">
              {suggested.review ? "다시 살펴볼 개념" : "지금 살펴볼 개념"}
            </h3>
          </div>
          <span>
            {suggested.review
              ? `복습 권장 ${suggested.total}개`
              : "현재 진도 기준"}
          </span>
        </div>
        {suggested.items.length ? (
          <div className="concept-suggestions">
            {suggested.items.map((item) => (
              <article className="concept-suggestion" key={item.id}>
                <div>
                  <strong>{item.concept}</strong>
                  <p>
                    {reviewReason(item, today) ||
                      (currentWeek != null && item.weeks.includes(currentWeek)
                        ? "현재 주차의 개념이에요. 강의 자료와 연결해 확인해 보세요."
                        : "지금까지 배운 범위의 개념이에요. 자료와 함께 확인해 보세요.")}
                  </p>
                </div>
                <ConceptAction concept={item} sectionId={room.section.id} />
              </article>
            ))}
          </div>
        ) : (
          <p className="concept-quiet">
            {items.length
              ? "현재 진도에 연결된 개념이 아직 없어요. 전체 개념이나 공개된 주차 자료를 살펴볼 수 있어요."
              : "등록된 개념이 아직 없어요. 강의 자료부터 확인해 보세요."}{" "}
            <Link to={`/classrooms/${room.section.id}`}>강의실로 <span className="go-arrow" aria-hidden="true">→</span></Link>
          </p>
        )}
        {suggested.review && suggested.total > 3 && (
          <button
            className="concept-text-button"
            onClick={() => {
              setScope("current");
              setStatus("review");
              setWeek("all");
              setSearch("");
              setPage(0);
            }}
          >
            복습 권장 개념 {suggested.total}개 모두 찾기 ↓
          </button>
        )}
      </section>
      <section
        className="concept-browser"
        aria-labelledby="concept-browser-title"
      >
        <div className="concept-section-heading">
          <h3 id="concept-browser-title">
            전체 개념 찾아보기 <span>{items.length}</span>
          </h3>
          <span>이름과 학습 경로는 항상 확인할 수 있어요.</span>
        </div>
        <div className="concept-filters">
          <label className="concept-search">
            개념 검색
            <input
              type="search"
              placeholder="개념 이름으로 검색"
              value={search}
              onChange={(event) => change(setSearch, event.target.value)}
            />
          </label>
          <label>
            학습 범위
            <select
              value={scope}
              onChange={(event) => change(setScope, event.target.value)}
            >
              <option value="current">
                배운 범위 ({items.filter((item) => item.in_scope).length})
              </option>
              <option value="all">전체 개념 ({items.length})</option>
              <option value="outside">현재 진도 밖</option>
            </select>
          </label>
          <label>
            주차
            <select
              value={week}
              onChange={(event) => change(setWeek, event.target.value)}
            >
              <option value="all">전체 주차</option>
              {weeks.map((value) => (
                <option key={value} value={value}>
                  {value}주차
                </option>
              ))}
              {items.some((item) => !item.weeks.length) && (
                <option value="none">주차 미지정</option>
              )}
            </select>
          </label>
          <label>
            학습 상태
            <select
              value={status}
              onChange={(event) => change(setStatus, event.target.value)}
            >
              <option value="all">전체 상태</option>
              {Object.entries(statusLabels).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
        </div>
        <div className="concept-result-caption">
          <span role="status">
            {filtered.length}개 개념
            {visible.length > 0 &&
              ` · ${currentPage * PAGE_SIZE + 1}–${currentPage * PAGE_SIZE + visible.length}번째 표시`}
          </span>
          <button
            className="concept-text-button"
            onClick={() => {
              setSearch("");
              setScope("all");
              setStatus("all");
              setWeek("all");
              setPage(0);
            }}
          >
            전체 개념 보기
          </button>
        </div>
        {!visible.length && (
          <p className="concept-quiet">
            조건에 맞는 개념이 없어요. 범위를 넓히거나 검색어를 바꿔 보세요.
          </p>
        )}
        <div className="concept-list">
          {visible.map((item) => (
            <article className="concept-list-item" key={item.id}>
              <div className="concept-item-main">
                <div>
                  <h4>{item.concept}</h4>
                  <span className="concept-week-label">
                    {item.weeks.length
                      ? `${item.weeks.join("·")}주차`
                      : "주차 미지정"}
                    {!item.in_scope && " · 현재 진도 밖"}
                  </span>
                </div>
                <span
                  className={`concept-status is-${conceptStatus(item, today)}`}
                >
                  {statusLabels[conceptStatus(item, today)]}
                </span>
                <ConceptAction concept={item} sectionId={room.section.id} />
              </div>
              <details className="concept-detail" onToggle={(e) => { if (e.currentTarget.open) quizzes.load(); }}>
                <summary>{item.concept} 학습 상세 · 풀었던 퀴즈</summary>
                <div>
                  <p>
                    최근 독립 답안 {item.valid_recent}건 · 정답{" "}
                    {item.correct_recent}건
                    {item.review_due && ` · 복습 권장 ${item.review_due}`}
                  </p>
                  <p>
                    {item.valid_recent
                      ? "선택 기간의 최근 독립 풀이 5건을 기준으로 해요. 5건 미만은 표본 부족, 4건 이상 정답과 2일 이상 정답 기록이 있어야 기준 충족이에요. 도움받은 풀이·재학습·채점 대기는 이 수치에 포함되지 않아요."
                      : "집계할 독립 풀이 기록이 아직 없어요. 이해 수준을 판단한 결과는 아니에요."}
                  </p>
                  <ConceptQuizzes conceptId={item.id} state={quizzes} />
                </div>
              </details>
            </article>
          ))}
        </div>
        {pageCount > 1 && (
          <Pager
            page={currentPage}
            pages={pageCount}
            onChange={setPage}
            label="개념 목록"
          />
        )}
      </section>
    </>
  );
}

function Pager({
  page,
  pages,
  onChange,
  label,
}: {
  page: number;
  pages: number;
  onChange: (page: number) => void;
  label: string;
}) {
  return (
    <nav className="learning-pager" aria-label={`${label} 페이지`}>
      <button disabled={page === 0} onClick={() => onChange(page - 1)}>
        ← 이전
      </button>
      <span aria-live="polite">
        {page + 1} / {pages} 페이지
      </span>
      <button disabled={page + 1 >= pages} onClick={() => onChange(page + 1)}>
        다음 →
      </button>
    </nav>
  );
}

// A date without a year refers to its most recent occurrence in the Korean calendar.
function archiveDay(text: string, today: string): string | null {
  const day = text.trim();
  if (day === "오늘") return today;
  if (day === "어제") return new Date(Date.parse(today) - 86400000).toISOString().slice(0, 10);
  const match = day.match(/^(?:(\d{4})[.\/년-]\s*)?(\d{1,2})[.\/월-]\s*(\d{1,2})일?$/);
  if (!match) return null;
  const monthDay = match[2].padStart(2, "0")+"-"+match[3].padStart(2, "0");
  const year = match[1] || String(Number(today.slice(0, 4)) - Number(monthDay > today.slice(5)));
  const value = year+"-"+monthDay;
  const parsed = new Date(value+"T00:00:00Z");
  return Number.isFinite(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value ? value : null;
}

export function ArchivePeriodFilter({ value, onChange, children }: {
  value: Period; onChange: (range: Period) => void; children: React.ReactNode;
}) {
  const [text, setText] = useState("");
  const [error, setError] = useState("");
  const [calendarOpen, setCalendarOpen] = useState(false);
  const apply = (range: Period) => {
    setText(range.from === range.to ? range.from : range.from+" ~ "+range.to);
    setError(""); setCalendarOpen(false); onChange(range);
  };
  return <div className="learning-history archive-date-search">
    <div className="history-toolbar history-toolbar-with-tabs">
      {children}
      <form className="history-search" role="search" aria-label="날짜로 기록 검색" onSubmit={e => {
        e.preventDefault();
        if (!text.trim()) { setError(""); onChange(initialPeriod()); return; }
        const today = initialPeriod().to;
        const days = text.split(/\s*[~～]\s*/).map(part => archiveDay(part, today));
        const from = days[0], to = days.at(-1);
        if (days.length > 2 || !from || !to || from > to || Date.parse(to) - Date.parse(from) > 365 * 86400000) {
          setError("오늘, 11월 19일 또는 11.1~11.19처럼 최대 366일 범위를 입력해 주세요."); return;
        }
        apply({ from, to });
      }}>
        <input type="search" aria-label="날짜 검색" className="history-search-text" value={text}
          placeholder="오늘, 11월 19일, 11.1~11.19" onChange={e => { setText(e.target.value); setError(""); }} />
        <button type="button" className="history-search-cal" aria-label="달력에서 고르기" aria-expanded={calendarOpen}
          onClick={() => setCalendarOpen(open => !open)}>
          <svg aria-hidden="true" width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
            <rect x="3.5" y="5" width="17" height="15" rx="2.5"/><path d="M3.5 10h17M8 3v4M16 3v4"/>
          </svg>
        </button>
        <button type="submit" className="history-search-go">검색</button>
      </form>
    </div>
    {calendarOpen && <PeriodFilter value={value} onChange={apply} />}
    <ErrorNotice text={error} />
    <small className="archive-range-note">조회 기간 {value.from} ~ {value.to}</small>
  </div>;
}

export function LearningHistory({ sectionId, classrooms = [], period }: { sectionId?: string; classrooms?: Classroom[]; period?: Period }) {
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [ownRange, setRange] = useState({ from: "", to: "" });
  const [order, setOrder] = useState("desc");
  const range = period || ownRange;
  const [page, setPage] = useState(0);
  const query = new URLSearchParams({
    limit: "10",
    offset: String(page * 10),
  });
  query.set("order", order);
  if (sectionId) query.set("section_id", sectionId);
  if (range.from) query.set("date_from", range.from);
  if (range.to) query.set("date_to", range.to);
  const records = useLoad<{ items: LearningRecord[]; total: number }>(
    `/my/learning-sessions?${query}`,
  );
  return (
    <section className="learning-history">
      <div className="concept-section-heading">
        <h3>날짜별 학습 기록</h3>
        <DropSelect label="날짜 정렬" value={order} onChange={value => { setOrder(value); setPage(0); }}
          options={[{ value: "desc", label: "최신순" }, { value: "asc", label: "오래된순" }]} />
      </div>
      {!period && <form
        className="learning-date-filter"
        onSubmit={(event) => {
          event.preventDefault();
          setRange({ from, to });
          setPage(0);
        }}
      >
        <label>
          시작일
          <input
            type="date"
            value={from}
            max={to || undefined}
            onChange={(event) => setFrom(event.target.value)}
          />
        </label>
        <label>
          종료일
          <input
            type="date"
            value={to}
            min={from || undefined}
            onChange={(event) => setTo(event.target.value)}
          />
        </label>
        <button type="submit">기간 적용</button>
        <button
          type="button"
          onClick={() => {
            setFrom("");
            setTo("");
            setRange({ from: "", to: "" });
            setPage(0);
          }}
        >
          전체 기간
        </button>
      </form>}
      <ErrorNotice text={records.error} />
      {records.error && <button onClick={records.reload}>다시 불러오기</button>}
      {!records.data && !records.error && (
        <Notice>날짜별 기록을 불러오는 중이에요…</Notice>
      )}
      {records.data && (
        <>
          <p className="learning-history-count" role="status">
            총 {records.data.total}건
            {(range.from || range.to) &&
              ` · ${range.from || "처음"} ~ ${range.to || "최근"}`}
          </p>
          {!records.data.items.length && (
            <p className="concept-quiet">이 기간에 학습 기록이 없어요.</p>
          )}
          {records.data.items.map((record) => (
            <article className="learning-history-item" key={record.id}>
              <time dateTime={record.day}>{record.day}</time>
              <div>
                {!sectionId && <span>{classrooms.find(room => room.section.id === record.section_id)?.course.title}</span>}
                <strong>
                  {record.total > 0 && record.submitted >= record.total
                    ? "제출 완료"
                    : "진행 중"}
                </strong>
                <span>
                  {record.submitted}/{record.total}문항 제출
                  {record.pending > 0 &&
                    ` · 채점·검토 대기 ${record.pending}문항`}
                </span>
              </div>
              <Link to={`/quiz/results/${record.id}`}>
                {record.submitted ? "답안·해설 보기" : "학습 내역 보기"} <span className="go-arrow" aria-hidden="true">→</span>
              </Link>
            </article>
          ))}
          {records.data.total > 10 && (
            <Pager
              page={page}
              pages={Math.ceil(records.data.total / 10)}
              onChange={setPage}
              label="날짜별 기록"
            />
          )}
        </>
      )}
    </section>
  );
}

/* 개념별 학습 안의 '풀었던 퀴즈와 해설' (11-15)
   지난 이론 퀴즈를 한 번만 불러와 문항을 개념별로 모아 둬요. 상세를 처음 펼칠 때 불러와요. */
type QuizItem = Daily["items"][number] & { concept_id?: string };
type ConceptQuiz = { sessionId: string; day: string; title: string; total: number; right: number; wrong: number; pending: number };
type QuizState = { status: "idle" | "loading" | "ready" | "error"; byConcept: Record<string, ConceptQuiz[]>; load: () => void };
const WEEKDAY = ["일", "월", "화", "수", "목", "금", "토"];
const quizDay = (day: string) => {
  const [y, m, d] = day.split("-").map(Number);
  return `${m}월 ${d}일 (${WEEKDAY[new Date(y, m - 1, d).getDay()]})`;
};

function useConceptQuizzes(sectionId: string, period: Period): QuizState {
  const [status, setStatus] = useState<QuizState["status"]>("idle");
  const [byConcept, setByConcept] = useState<Record<string, ConceptQuiz[]>>({});
  const load = useCallback(() => {
    if (status === "loading" || status === "ready") return;
    setStatus("loading");
    (async () => {
      const list = await api<{ items: LearningRecord[] }>(
        `/my/learning-sessions?section_id=${encodeURIComponent(sectionId)}&limit=100&${periodQuery(period)}`,
      );
      const sessions = list.items.filter((r) => r.submitted > 0);
      const details: Daily[] = [];
      for (let i = 0; i < sessions.length; i += 6) {
        const part = await Promise.all(
          sessions.slice(i, i + 6).map((r) => api<Daily>(`/learning-sessions/${r.id}`).catch(() => null)),
        );
        details.push(...part.filter((d): d is Daily => !!d));
      }
      const grouped: Record<string, ConceptQuiz[]> = {};
      for (const d of details) {
        const items = d.items as QuizItem[];
        const done = items.filter((q) => q.attempt);
        const graded = done.filter((q) => q.attempt!.status === "graded");
        const entry: ConceptQuiz = {
          sessionId: d.id,
          day: d.day,
          title: (d as Daily & { title?: string }).title || "",
          total: items.length,
          right: graded.filter((q) => q.attempt!.correct).length,
          wrong: graded.filter((q) => !q.attempt!.correct).length,
          pending: done.length - graded.length,
        };
        for (const cid of new Set(done.map((q) => q.concept_id).filter((c): c is string => !!c)))
          (grouped[cid] ||= []).push(entry);
      }
      for (const k of Object.keys(grouped)) grouped[k].sort((a, b) => a.day.localeCompare(b.day));
      setByConcept(grouped);
      setStatus("ready");
    })().catch(() => setStatus("error"));
  }, [sectionId, status, period.from, period.to]);
  return { status, byConcept, load };
}

function ConceptQuizzes({ conceptId, state }: { conceptId: string; state: QuizState }) {
  const [all, setAll] = useState(false);
  if (state.status === "idle" || state.status === "loading")
    return <p className="concept-quiz-note">풀었던 퀴즈를 불러오는 중이에요…</p>;
  if (state.status === "error")
    return <p className="concept-quiz-note">풀었던 퀴즈를 불러오지 못했어요. 잠시 뒤 다시 펼쳐 보세요.</p>;
  const list = state.byConcept[conceptId] || [];
  if (!list.length) return <p className="concept-quiz-note">이 개념이 나온 퀴즈를 아직 풀지 않았어요.</p>;
  const shown = all ? list : list.slice(-5);
  return (
    <div className="concept-quizzes">
      <strong className="concept-quizzes-title">이 개념이 나온 퀴즈 {list.length}개</strong>
      {list.length > 5 && (
        <button type="button" className="concept-text-button concept-quiz-more" onClick={() => setAll(!all)}>
          {all ? "최근 5개만 보기" : `이전 퀴즈 ${list.length - 5}개 더 보기 ↑`}
        </button>
      )}
      <ol>
        {shown.map((x) => (
          <li key={x.sessionId} className="concept-quiz">
            <Link to={`/quiz/results/${x.sessionId}`}>
              <span className="concept-quiz-name">{x.title || quizDay(x.day)}</span>
              <span className="concept-quiz-meta">
                {x.title && <><time dateTime={x.day}>{quizDay(x.day)}</time> · </>}이론 퀴즈 · {x.total}문항
              </span>
              <span className="concept-quiz-score">
                <em className="right">정답 {x.right}</em>
                <em className="wrong">오답 {x.wrong}</em>
                {x.pending > 0 && <em className="pending">채점 중 {x.pending}</em>}
              </span>
              <span className="concept-quiz-go">결과와 해설 보기 <span className="go-arrow" aria-hidden="true">→</span></span>
            </Link>
          </li>
        ))}
      </ol>
    </div>
  );
}
