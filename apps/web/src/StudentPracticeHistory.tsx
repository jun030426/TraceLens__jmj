import { SubmittedFullCode } from "./SubmittedFullCode";
import { SubmittedBlankCode } from "./SubmittedBlankCode";
import { parseTemplate } from "./visualizer/blanks";
import { useId, useRef, useState } from "react";
import type { Classroom } from "./api";
import { ErrorNotice, Notice, useLoad } from "./components";
import { ListPager } from "./StudentLists";
import { periodQuery, type Period } from "./learningPeriod";

type PracticeHistory = {
  total: number;
  summary: {
    submitted: number;
    independent: number;
    correct: number;
    wrong: number;
    assisted: number;
    pending: number;
    accuracy: number | null;
  };
  items: {
    id: string;
    created_at: string;
    status: string;
    correct: boolean | null;
    independent: boolean;
    title: string;
    concept: string;
    kind: string;
    language: string;
    source_available: boolean;
    source: string;
    template?: string | null;
    feedback: { message?: string; passed?: number; total?: number } | null;
  }[];
};
const kindNames: Record<string, string> = {
  blank: "빈칸 채우기",
  full: "전체 코드 작성",
  cloze: "빈칸 채우기",
  modify: "코드 수정",
  write: "코드 작성",
  trace: "실행 흐름",
};

export function StudentPracticeHistory({
  room,
  period,
}: {
  room: Classroom;
  period: Period;
}) {
  const [page, setPage] = useState(0);
  const [order, setOrder] = useState("desc");
  const [sortOpen, setSortOpen] = useState(false);
  const sortTrigger = useRef<HTMLButtonElement>(null);
  const sortOptionsId = useId();
  const query = periodQuery(period);
  query.set("offset", String(page * 10));
  query.set("limit", "10");
  query.set("order", order);
  const result = useLoad<PracticeHistory>(
    `/sections/${room.section.id}/my-practice?${query}`,
  );
  if (result.error)
    return (
      <>
        <ErrorNotice text={result.error} />
        <button onClick={result.reload}>다시 불러오기</button>
      </>
    );
  if (!result.data) return <Notice>실습 제출 기록을 불러오는 중이에요…</Notice>;
  const { summary: s, items, total } = result.data;
  return (
    <section className="student-practice-history" aria-label="실습 제출 기록">
      <div className="progress-practice-heading">
        <div>
          <h3>실습 제출과 채점 결과</h3>
          <p>선택 기간에 이 강의에서 제출한 고정 실습 기록이에요.</p>
        </div>
        <span className="progress-course-language">
          수업 언어 · {room.course.teaching_language}
        </span>
      </div>
      <div className="progress-practice-metrics">
        <div>
          <span>전체 제출</span>
          <strong>
            {s.submitted}
            <small>건</small>
          </strong>
        </div>
        <div>
          <span>독립 풀이 통과</span>
          <strong>
            {s.correct}
            <small> / {s.independent}건</small>
          </strong>
        </div>
        <div>
          <span>독립 통과율</span>
          <strong>{s.accuracy == null ? "—" : `${s.accuracy}%`}</strong>
        </div>
      </div>
      <p className="student-practice-breakdown">
        독립 미통과 {s.wrong}건 · 도움·재학습 {s.assisted}건 · 채점 대기·보류{" "}
        {s.pending}건
      </p>
      <p className="muted">
        교수자 화면과 동일하게, 채점이 완료된 독립 풀이로 통과율을 계산해요.
        단순 코드 실행은 제출 기록에 포함되지 않아요.
      </p>
      <div className="concept-section-heading">
        <h3>최근 실습 제출</h3>
        <div className="practice-history-sort"
          onBlur={event => {
            if (!event.currentTarget.contains(event.relatedTarget)) setSortOpen(false);
          }}
          onKeyDown={event => {
            if (event.key !== "Escape" || !sortOpen) return;
            setSortOpen(false);
            sortTrigger.current?.focus();
          }}>
          <span>날짜 정렬</span>
          <button ref={sortTrigger} type="button" aria-expanded={sortOpen}
            aria-controls={sortOptionsId} aria-label={`날짜 정렬: ${order === "desc" ? "최신순" : "오래된순"}`}
            onClick={() => setSortOpen(open => !open)}>
            {order === "desc" ? "최신순" : "오래된순"}
            <svg aria-hidden="true" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7"><path d="m6 9 6 6 6-6" /></svg>
          </button>
          <div id={sortOptionsId} className="practice-history-sort-options" hidden={!sortOpen}>
            {([["desc", "최신순"], ["asc", "오래된순"]] as const).map(([value, label]) => (
              <button key={value} type="button" aria-pressed={value === order}
                onClick={() => {
                  setSortOpen(false);
                  sortTrigger.current?.focus();
                  setOrder(value);
                  setPage(0);
                }}>{label}</button>
            ))}
          </div>
        </div>
      </div>
      <p className="learning-history-count" role="status">
        총 {total}건 · {period.from} ~ {period.to}
      </p>
      {!items.length && (
        <Notice>
          이 기간에 제출한 실습이 없어요. 실습을 제출하면 코드와 채점 결과를
          확인할 수 있어요.
        </Notice>
      )}
      <div className="student-practice-records">
        {items.map((a) => {
          const graded = a.status === "graded" && a.correct != null;
          const state = graded
            ? a.correct
              ? "통과"
              : "미통과"
            : a.status === "held"
              ? "채점 보류"
              : "채점 대기";
          return (
            <article className="student-practice-record" key={a.id}>
              <div className="student-practice-record-heading">
                <h4>{a.title}</h4>
                <span
                  className={`practice-result ${graded ? (a.correct ? "passed" : "failed") : "pending"}`}
                >
                  {state}
                </span>
              </div>
              <p>
                {a.concept || "개념 정보 비공개"} ·{" "}
                {kindNames[a.kind] || a.kind} · {a.language} ·{" "}
                {a.independent ? "독립 풀이" : "도움·재학습"}
              </p>
              <time dateTime={a.created_at}>
                {new Date(a.created_at).toLocaleString("ko-KR", {
                  timeZone: "Asia/Seoul",
                })}
              </time>
              {!a.source_available && (
                <p className="muted">
                  자료 공개 범위가 변경되어 문제 정보와 피드백은 표시하지
                  않아요. 내 제출 기록은 유지돼요.
                </p>
              )}
              <details>
                <summary>제출 코드·결과 보기</summary>
                {a.source_available && (
                  <div className="student-practice-feedback">
                    <strong>채점 결과</strong>
                    <p>
                      {a.feedback?.message ||
                        (graded
                          ? "채점이 완료되었어요."
                          : a.status === "held"
                            ? "자동 채점을 마치지 못해 검토를 기다리고 있어요."
                            : "채점이 끝나면 결과가 표시돼요.")}
                    </p>
                    {a.feedback?.total != null && (
                      <p>
                        검증 통과 {a.feedback.passed ?? 0} / {a.feedback.total}
                        개
                      </p>
                    )}
                  </div>
                )}
                <strong>내 제출 코드</strong>
                <pre className="practice-submitted-code">
                  <code>{a.template && (a.kind === "blank" || a.kind === "cloze")
                    ? <SubmittedBlankCode source={a.source} template={parseTemplate(a.template)} />
                    : a.kind === "full" && a.template != null
                      ? <SubmittedFullCode source={a.source} starter={a.template} />
                      : a.source}</code>
                </pre>
              </details>
            </article>
          );
        })}
      </div>
      <ListPager
        page={page}
        pages={Math.max(1, Math.ceil(total / 10))}
        onChange={setPage}
        label="실습 제출"
      />
    </section>
  );
}
