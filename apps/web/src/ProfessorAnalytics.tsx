import { useEffect, useRef, useState } from "react";
import { ErrorNotice, Notice, useLoad } from "./components";
import { ListPager, PagedList } from "./StudentLists";
import { matchesSearch } from "./listNavigation";
import "./professor-analysis.css";

type Counts = {
  participation: number;
  valid: number;
  correct: number;
  accuracy: number | null;
  pending: number;
};
type NamedCounts = Counts & { id: string; name: string };
type Analysis = {
  summary: Counts;
  concepts: NamedCounts[];
  students: NamedCounts[];
};
const accuracy = (value: number | null) =>
  value === null ? "집계 전" : `${value}%`;

function ConceptResult({ concept }: { concept: NamedCounts }) {
  const scored = concept.valid > 0 && concept.accuracy !== null;
  return (
    <div className="prof-concept-row">
      <strong className="prof-concept-name">{concept.name}</strong>
      <div className="prof-concept-score">
        {scored && (
          <span className="prof-score-track" aria-hidden="true">
            <span style={{ width: `${concept.accuracy}%` }} />
          </span>
        )}
        <b>{accuracy(concept.accuracy)}</b>
      </div>
      <span className="prof-concept-sample">
        {scored
          ? `정답 ${concept.correct}/${concept.valid}건`
          : "집계된 답안 없음"}
      </span>
    </div>
  );
}

export function Analytics({ sectionId }: { sectionId: string }) {
  const r = useLoad<Analysis>(`/sections/${sectionId}/analytics`);
  const [view, setView] = useState("concepts");
  return (
    <section className="panel teacher-analytics-panel prof-analysis">
      <div className="teacher-analysis-toolbar">
        <span>선택한 분반의 이론 퀴즈 기록</span>
        <div>
          <button onClick={r.reload}>새로고침</button>
          <a
            className="link-button"
            href={`/api/v1/sections/${sectionId}/analytics.csv`}
          >
            CSV 내려받기
          </a>
        </div>
      </div>
      <ErrorNotice text={r.error} />
      {!r.data && !r.error && <Notice>학습 분석을 불러오는 중이에요…</Notice>}
      {r.data && (
        <>
          <div className="teacher-analysis-metrics">
            <div>
              <span>제출 답안</span>
              <strong>
                {r.data.summary.participation}
                <small>건</small>
              </strong>
            </div>
            <div>
              <span>정답률 집계 답안</span>
              <strong>
                {r.data.summary.valid}
                <small>건</small>
              </strong>
            </div>
            <div>
              <span>정답률</span>
              <strong
                className={
                  r.data.summary.accuracy === null ? "prof-no-rate" : ""
                }
              >
                {r.data.summary.accuracy ?? "집계 전"}
                {r.data.summary.accuracy !== null && <small>%</small>}
              </strong>
            </div>
          </div>
          <div className="prof-count-note">
            <p>
              정답률은 채점이 끝난 첫 독립 답안 기준입니다. 동일 문항
              재학습·채점 대기·보류는 집계에서 제외돼요.
            </p>
            <small>
              학생 수가 아닌 답안 수 기준이며, 분반 이동 전 제출은 원래 분반에
              남습니다.
            </small>
          </div>
          <div
            className="prof-view-switch"
            role="group"
            aria-label="학습 현황 보기"
          >
            <button
              aria-pressed={view === "concepts"}
              onClick={() => setView("concepts")}
            >
              개념별 이해도 <span>{r.data.concepts.length}</span>
            </button>
            <button
              aria-pressed={view === "students"}
              onClick={() => setView("students")}
            >
              학생별 학습 기록 <span>{r.data.students.length}</span>
            </button>
          </div>
          <div hidden={view !== "concepts"}>
            <Concepts concepts={r.data.concepts} />
          </div>
          <div hidden={view !== "students"}>
            <Students
              sectionId={sectionId}
              students={r.data.students}
              concepts={r.data.concepts}
            />
          </div>
        </>
      )}
    </section>
  );
}

function Concepts({ concepts }: { concepts: NamedCounts[] }) {
  const [scope, setScope] = useState("scored");
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState("accuracy");
  const scored = concepts.filter((c) => c.valid > 0);
  const review = scored
    .filter((c) => c.accuracy !== null && c.accuracy < 70)
    .sort((a, b) => a.accuracy! - b.accuracy! || b.valid - a.valid)
    .slice(0, 3);
  const visible = concepts
    .filter(
      (c) =>
        (scope === "all" || (scope === "scored" ? c.valid > 0 : !c.valid)) &&
        matchesSearch(search, c.name),
    )
    .sort(
      (a, b) =>
        (sort === "accuracy"
          ? (a.accuracy ?? 101) - (b.accuracy ?? 101)
          : sort === "samples"
            ? b.valid - a.valid
            : 0) || a.name.localeCompare(b.name, "ko"),
    );
  return (
    <section aria-label="개념별 이해도 목록">
      {review.length > 0 && (
        <aside className="prof-review">
          <h3>다음 수업에서 짚어볼 개념</h3>
          <p>
            정답률 70% 미만인 개념 중 최대 3개입니다. 답안 수와 함께 살펴보세요.
          </p>
          {review.map((c) => (
            <ConceptResult key={c.id} concept={c} />
          ))}
        </aside>
      )}
      <div className="prof-section-heading">
        <h3>개념별 이해도</h3>
        <p>이론 퀴즈 정답률을 기준으로 비교합니다.</p>
      </div>
      <div className="prof-filters" role="group" aria-label="개념 집계 상태">
        {[
          ["scored", "집계된 개념", scored.length],
          ["unscored", "집계 전", concepts.length - scored.length],
          ["all", "전체", concepts.length],
        ].map(([value, label, count]) => (
          <button
            key={value}
            aria-pressed={scope === value}
            onClick={() => setScope(String(value))}
          >
            {label} <span>{count}</span>
          </button>
        ))}
      </div>
      <div className="prof-list-tools">
        <label>
          개념 검색
          <input
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="개념 이름"
          />
        </label>
        <label>
          개념 정렬
          <select value={sort} onChange={(e) => setSort(e.target.value)}>
            <option value="accuracy">정답률 낮은 순</option>
            <option value="samples">집계 답안 많은 순</option>
            <option value="name">이름순</option>
          </select>
        </label>
      </div>
      {!visible.length && (
        <p className="prof-empty">
          {search
            ? "조건에 맞는 개념이 없어요. 검색어나 집계 상태를 바꿔 보세요."
            : scope === "scored"
              ? "아직 집계된 개념이 없어요. ‘집계 전’ 또는 ‘전체’에서 모든 개념을 확인할 수 있어요."
              : "표시할 개념이 없어요."}
        </p>
      )}
      <PagedList
        items={visible}
        size={10}
        label="개념"
        resetKey={`${scope}:${search}:${sort}`}
      >
        {(items) => (
          <div className="prof-concept-list">
            {items.map((c) => (
              <ConceptResult key={c.id} concept={c} />
            ))}
          </div>
        )}
      </PagedList>
    </section>
  );
}

function Students({
  sectionId,
  students,
  concepts,
}: {
  sectionId: string;
  students: NamedCounts[];
  concepts: NamedCounts[];
}) {
  const [search, setSearch] = useState("");
  const [student, setStudent] = useState<NamedCounts>();
  const trigger = useRef<HTMLButtonElement | null>(null);
  const visible = students
    .filter((s) => matchesSearch(search, s.name))
    .sort((a, b) => a.name.localeCompare(b.name, "ko"));
  return (
    <section aria-label="학생별 학습 기록 목록">
      <div hidden={!!student}>
        <div className="prof-section-heading">
          <h3>학생별 학습 기록</h3>
          <p>학생을 선택하면 날짜·개념별 답안을 확인할 수 있어요.</p>
        </div>
        <div className="prof-list-tools">
          <label>
            학생 검색
            <input
              type="search"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="학생 이름"
            />
          </label>
        </div>
        {!visible.length && (
          <p className="prof-empty">
            {search ? "검색한 학생이 없어요." : "아직 학생 기록이 없어요."}
          </p>
        )}
        <PagedList items={visible} size={10} label="학생" resetKey={search}>
          {(items) => (
            <ul className="prof-student-list">
              {items.map((s) => (
                <li key={s.id}>
                  <button
                    className="prof-student-link"
                    aria-label={`${s.name} 답안 보기`}
                    onClick={(e) => {
                      trigger.current = e.currentTarget;
                      setStudent(s);
                    }}
                  >
                    <strong>{s.name}</strong>
                    <span>답안 보기 →</span>
                  </button>
                  <div className="prof-student-rate">
                    <span>정답률</span>
                    <b>{accuracy(s.accuracy)}</b>
                  </div>
                  <dl className="prof-student-counts">
                    <div>
                      <dt>제출</dt>
                      <dd>{s.participation}건</dd>
                    </div>
                    <div>
                      <dt>집계 답안</dt>
                      <dd>{s.valid}건</dd>
                    </div>
                    <div>
                      <dt>대기·보류</dt>
                      <dd>{s.pending}건</dd>
                    </div>
                  </dl>
                </li>
              ))}
            </ul>
          )}
        </PagedList>
      </div>
      {student && (
        <StudentDetail
          key={student.id}
          sectionId={sectionId}
          student={student}
          concepts={concepts}
          onClose={() => {
            setStudent(undefined);
            requestAnimationFrame(() => trigger.current?.focus());
          }}
        />
      )}
    </section>
  );
}

type StudentAttempt = {
  id: string;
  status: string;
  correct: boolean | null;
  independent: boolean;
  question: string;
  answer: string;
  concept: string;
  created_at: string;
  feedback: {
    message: string;
    criteria?: { criterion: string; score: number }[];
  } | null;
};
const attemptStatus = (a: StudentAttempt) =>
  a.status === "pending"
    ? "채점 대기"
    : a.status !== "graded"
      ? "채점 보류"
      : a.correct === true
        ? "정답"
        : a.correct === false
          ? "오답"
          : "채점 완료";
const submittedAt = (value: string) =>
  new Date(value).toLocaleString("ko-KR", {
    timeZone: "Asia/Seoul",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });

function StudentDetail({
  sectionId,
  student,
  concepts,
  onClose,
}: {
  sectionId: string;
  student: NamedCounts;
  concepts: NamedCounts[];
  onClose: () => void;
}) {
  const heading = useRef<HTMLHeadingElement>(null);
  const [filters, setFilters] = useState({ from: "", to: "", concept: "" });
  const [page, setPage] = useState(0);
  const [error, setError] = useState("");
  const query = new URLSearchParams({ limit: "10", offset: String(page * 10) });
  if (filters.from) query.set("date_from", filters.from);
  if (filters.to) query.set("date_to", filters.to);
  if (filters.concept) query.set("concept_id", filters.concept);
  const r = useLoad<{ items: StudentAttempt[]; total: number }>(
    `/sections/${sectionId}/students/${student.id}/learning?${query}`,
  );
  useEffect(() => {
    heading.current?.focus();
  }, []);
  return (
    <section
      className="prof-student-detail"
      aria-labelledby="prof-student-title"
    >
      <button className="prof-back" onClick={onClose}>
        ← 학생 목록
      </button>
      <div className="prof-section-heading">
        <h3 id="prof-student-title" ref={heading} tabIndex={-1}>
          {student.name} · 답안 기록
        </h3>
        <p>최근 제출부터 표시합니다. 날짜는 한국 시간 기준입니다.</p>
      </div>
      <form
        className="prof-list-tools prof-answer-filters"
        onReset={() => {
          setFilters({ from: "", to: "", concept: "" });
          setPage(0);
          setError("");
        }}
        onSubmit={(e) => {
          e.preventDefault();
          const data = new FormData(e.currentTarget);
          const from = String(data.get("from") || ""),
            to = String(data.get("to") || "");
          if (from && to && from > to) {
            setError("종료일은 시작일보다 같거나 늦어야 해요.");
            return;
          }
          setError("");
          setFilters({ from, to, concept: String(data.get("concept") || "") });
          setPage(0);
        }}
      >
        <label>
          시작일
          <input type="date" name="from" />
        </label>
        <label>
          종료일
          <input type="date" name="to" />
        </label>
        <label>
          답안 개념
          <select name="concept">
            <option value="">전체 개념</option>
            {[...concepts]
              .sort((a, b) => a.name.localeCompare(b.name, "ko"))
              .map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
          </select>
        </label>
        <div className="prof-filter-actions">
          <button type="submit">조회</button>
          <button type="reset">초기화</button>
        </div>
      </form>
      <ErrorNotice text={error || r.error} />
      {r.error && <button onClick={r.reload}>다시 불러오기</button>}
      {!r.data && !r.error && <Notice>답안 기록을 불러오는 중이에요…</Notice>}
      {r.data && (
        <>
          <p className="prof-result-count" role="status">
            총 {r.data.total}건
            {r.data.items.length > 0 &&
              ` · ${page * 10 + 1}–${page * 10 + r.data.items.length}번째`}
          </p>
          {!r.data.items.length && (
            <p className="prof-empty">선택한 조건의 답안 기록이 없어요.</p>
          )}
          <div className="prof-answer-list">
            {r.data.items.map((a) => (
              <details className="prof-answer" key={a.id}>
                <summary>
                  <span className="prof-answer-meta">
                    <time dateTime={a.created_at}>
                      {submittedAt(a.created_at)}
                    </time>
                    <span>
                      {a.concept} · {attemptStatus(a)}
                    </span>
                  </span>
                  <span className="prof-answer-question">{a.question}</span>
                  <span className="prof-answer-toggle">
                    답안·피드백 <span aria-hidden="true">⌄</span>
                  </span>
                </summary>
                <div className="prof-answer-body">
                  <h4>제출 답안</h4>
                  <p>{a.answer}</p>
                  <h4>피드백</h4>
                  <p>
                    {a.feedback?.message ||
                      (a.status === "pending"
                        ? "채점 결과를 기다리고 있어요."
                        : "아직 제공된 피드백이 없어요.")}
                  </p>
                  {!!a.feedback?.criteria?.length && (
                    <ul>
                      {a.feedback.criteria.map((c, i) => (
                        <li key={i}>
                          {c.criterion} · {c.score}점
                        </li>
                      ))}
                    </ul>
                  )}
                  <small>
                    {a.status === "graded" && a.independent
                      ? "정답률 집계에 포함된 답안입니다."
                      : "정답률 집계에서 제외된 답안입니다."}
                  </small>
                </div>
              </details>
            ))}
          </div>
          <ListPager
            page={page}
            pages={Math.ceil(r.data.total / 10)}
            label="학생 답안"
            onChange={(value) => {
              setPage(value);
              heading.current?.focus();
            }}
          />
        </>
      )}
    </section>
  );
}
