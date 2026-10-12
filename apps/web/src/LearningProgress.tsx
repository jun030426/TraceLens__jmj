import { useState } from "react";
import { Link } from "react-router-dom";
import type { Classroom } from "./api";
import { ErrorNotice, Notice, useLoad } from "./components";
import {
  conceptStatus,
  reviewReason,
  suggestedConcepts,
  type LearningConcept,
} from "./conceptProgress";
import { weekLabel, type LearningRecord } from "./studentOverview";
import "./learning-progress.css";

const statusLabels: Record<string, string> = {
  review: "복습 권장",
  learning: "학습 중",
  new: "학습 기록 없음",
  mastered: "기준 충족",
};
const PAGE_SIZE = 10;

export function LearningProgress({ room }: { room: Classroom }) {
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
        <ConceptProgress room={room} />
      </div>
      {tab === "history" && <LearningHistory sectionId={room.section.id} />}
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
      <span aria-hidden="true">↗</span>
    </Link>
  );
}

function ConceptProgress({ room }: { room: Classroom }) {
  const result = useLoad<{
    items: LearningConcept[];
    today: string;
    current_week: number | null;
  }>(`/sections/${room.section.id}/my-learning`);
  const [search, setSearch] = useState("");
  const [scope, setScope] = useState("current");
  const [status, setStatus] = useState("all");
  const [week, setWeek] = useState("all");
  const [page, setPage] = useState(0);
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
            <Link to={`/classrooms/${room.section.id}`}>강의실로 ↗</Link>
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
              <details className="concept-detail">
                <summary>{item.concept} 학습 상세</summary>
                <div>
                  <p>
                    최근 독립 답안 {item.valid_recent}건 · 정답{" "}
                    {item.correct_recent}건
                    {item.review_due && ` · 복습 권장 ${item.review_due}`}
                  </p>
                  <p>
                    {item.valid_recent
                      ? "최근 독립 풀이 최대 5건을 기준으로 표시해요. 도움받은 풀이·재학습·채점 대기는 이 수치에 포함되지 않아요."
                      : "집계할 독립 풀이 기록이 아직 없어요. 이해 수준을 판단한 결과는 아니에요."}
                  </p>
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

export function LearningHistory({ sectionId, classrooms = [] }: { sectionId?: string; classrooms?: Classroom[] }) {
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [range, setRange] = useState({ from: "", to: "" });
  const [page, setPage] = useState(0);
  const query = new URLSearchParams({
    limit: "10",
    offset: String(page * 10),
  });
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
        <span>최신 기록부터 확인해요.</span>
      </div>
      <form
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
      </form>
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
                {record.submitted ? "답안·해설 보기 ↗" : "학습 내역 보기 ↗"}
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
