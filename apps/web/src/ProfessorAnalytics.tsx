import { WeakConcepts } from "./WeakConcepts";
import { useEffect, useRef, useState } from "react";
import { ErrorNotice, Notice, useLoad } from "./components";
import { PagedList } from "./StudentLists";
import { matchesSearch } from "./listNavigation";
import {
  at,
  ChatTopics,
  downloadOverview,
  initialPeriod,
  PeriodFilter,
  periodQuery,
  rate,
  StudentInsights,
  Summary,
  type Overview,
  type StudentSummary,
} from "./ProfessorInsights";
import "./professor-analysis.css";
import {
  prioritySignals,
  reviewCounts,
  reviewStudents,
  reviewState,
  signalsFor,
  REVIEW_LABEL,
  REVIEW_STATES,
  type Signal,
} from "./professorWeakness";
import { WeaknessSignal } from "./ProfessorWeaknessCard";
import "./professor-weakness.css";

export function Analytics({ sectionId }: { sectionId: string }) {
  return <ProfessorAnalysis key={sectionId} sectionId={sectionId} />;
}

function ProfessorAnalysis({ sectionId }: { sectionId: string }) {
  const [period, setPeriod] = useState(initialPeriod);
  const [view, setView] = useState("students");
  const [selected, setSelected] = useState<StudentSummary>();
  const [selectedConcept, setSelectedConcept] = useState<{
    id: string;
    name: string;
  }>();
  const [concept, setConcept] = useState("");
  const [enrollment, setEnrollment] = useState("active");
  const [search, setSearch] = useState("");
  const [scope, setScope] = useState("all");
  const [sort, setSort] = useState("review");
  const [conceptSearch, setConceptSearch] = useState("");
  const [conceptScope, setConceptScope] = useState("all");
  const [conceptSort, setConceptSort] = useState("review");
  const trigger = useRef<string | null>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const overviewHeading = useRef<HTMLHeadingElement>(null);
  const data = useLoad<Overview>(
    `/sections/${sectionId}/insights?${periodQuery(period)}`,
  );
  useEffect(() => {
    if (selected) heading.current?.focus();
    else if (trigger.current) {
      (
        document.getElementById(trigger.current) || overviewHeading.current
      )?.focus();
      trigger.current = null;
    }
  }, [selected?.id]);
  const roster = (data.data?.students || []).filter(
    (s) => enrollment !== "active" || s.active,
  );
  const matching = reviewStudents(roster, {
    search,
    concept,
    scope: "all",
    sort,
  });
  const counts = reviewCounts(matching, concept);
  const visible = reviewStudents(matching, {
    search: "",
    concept,
    scope,
    sort,
  });
  const openStudent = (student: StudentSummary, signal?: Signal) => {
    trigger.current =
      (document.activeElement as HTMLElement)?.id ||
      `prof-student-${sectionId}-${student.id}`;
    setSelectedConcept(
      signal ? { id: signal.id, name: signal.name } : undefined,
    );
    setSelected(student);
  };
  const visibleConcepts = (data.data?.concepts || [])
    .filter((c) => matchesSearch(conceptSearch, c.name))
    .filter(
      (c) =>
        conceptScope === "all" ||
        (conceptScope === "scored"
          ? c.theory.independent > 0
          : c.theory.independent === 0),
    )
    .sort((a, b) => {
      const difference =
        conceptSort === "accuracy"
          ? (a.theory.accuracy ?? 101) - (b.theory.accuracy ?? 101)
          : conceptSort === "samples"
            ? b.theory.independent - a.theory.independent
            : conceptSort === "review"
              ? b.review_students - a.review_students
              : 0;
      return difference || a.name.localeCompare(b.name, "ko");
    });
  return (
    <section
      className="panel teacher-analytics-panel prof-analysis"
      aria-label="교수자 학습 분석"
    >
      <div className="prof-section-heading">
        <h3 ref={overviewHeading} tabIndex={-1}>
          학생별 취약 개념
        </h3>
        <p>
          누가 어떤 개념을 복습해야 하는지 확인하고, 점수를 누르면 판단 근거를
          볼 수 있어요.
        </p>
      </div>
      <details className="pw-period" open>
        <summary>
          조회 기간 · {period.from} ~ {period.to}
          <span>기간 변경</span>
        </summary>
        <PeriodFilter value={period} onChange={setPeriod} />
        <p className="prof-period-note">한국 시간 기준 제출·질문 기록</p>
      </details>
      <div className="teacher-analysis-toolbar">
        {!selected && <span>최근 독립 풀이를 기준으로 학생별 복습 대상을 확인해요.</span>}
        <div>
          {!selected && <button type="button" onClick={data.reload}>
            새로고침
          </button>}
          <button
            type="button"
            disabled={!data.data}
            onClick={() => {
              if (data.data) downloadOverview(data.data);
            }}
          >
            {selected ? "선택 기간 분반 CSV" : "선택 기간 CSV"}
          </button>
        </div>
      </div>
      {selected && (
        <>
          <button
            className="prof-back"
            type="button"
            onClick={() => setSelected(undefined)}
          >
            ← 전체 학생 현황
          </button>
          <h3 ref={heading} tabIndex={-1}>
            {selected.name} · 개인 학습 상세
          </h3>
          <StudentInsights
            key={`${selected.id}:${selectedConcept?.id || ""}`}
            sectionId={sectionId}
            studentId={selected.id}
            period={period}
            initialConcept={selectedConcept}
          />
        </>
      )}
      <div hidden={!!selected}>
        <ErrorNotice text={data.error} />
        {!data.data && !data.error && (
          <Notice>분반 학습 현황을 불러오는 중이에요…</Notice>
        )}
        {data.data && (
          <>
            <WeakConcepts view={view} onChange={setView} />
            {view === "students" && (
              <section aria-label="학생별 학습 기록 목록">
                <p className="pw-method">
                  취약도는 선택 기간의 최근 독립 풀이 5건 중 오답 비율이에요.{" "}
                  <strong>높을수록 복습이 필요해요.</strong> 5건 미만은 점수
                  대신 ‘표본 부족’으로 표시해요.
                </p>
                <div
                  className="pw-counts"
                  role="group"
                  aria-label="학생 취약 상태 필터"
                >
                  {["all", ...REVIEW_STATES].map((state) => (
                    <button
                      key={state}
                      type="button"
                      className={`is-${state}`}
                      aria-pressed={scope === state}
                      onClick={() => setScope(state)}
                    >
                      <span>
                        {state === "all"
                          ? "전체"
                          : REVIEW_LABEL[
                              state as (typeof REVIEW_STATES)[number]
                            ]}
                      </span>
                      <strong>
                        {counts[state]}
                        <small>명</small>
                      </strong>
                    </button>
                  ))}
                </div>
                <div className="prof-list-tools pw-student-filters">
                  <label>
                    학생·개념 검색
                    <input
                      type="search"
                      placeholder="학생 이름 또는 개념"
                      value={search}
                      onChange={(e) => setSearch(e.target.value)}
                    />
                  </label>
                  <label>
                    개념 선택
                    <select
                      value={concept}
                      onChange={(e) => setConcept(e.target.value)}
                    >
                      <option value="">전체 개념</option>
                      {data.data.concepts.map((c) => (
                        <option key={c.id} value={c.id}>
                          {c.name}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    수강 범위
                    <select
                      value={enrollment}
                      onChange={(e) => setEnrollment(e.target.value)}
                    >
                      <option value="active">현재 수강생</option>
                      <option value="all">수강 이력 포함</option>
                    </select>
                  </label>
                  <label>
                    정렬
                    <select
                      value={sort}
                      onChange={(e) => setSort(e.target.value)}
                    >
                      <option value="review">복습 필요·취약도 높은 순</option>
                      <option value="accuracy">기간 이론 정답률 낮은 순</option>
                      <option value="recent">최근 활동 순</option>
                      <option value="name">이름순</option>
                    </select>
                  </label>
                  {(search ||
                    concept ||
                    scope !== "all" ||
                    enrollment !== "active" ||
                    sort !== "review") && (
                    <button
                      type="button"
                      onClick={() => {
                        setSearch("");
                        setConcept("");
                        setScope("all");
                        setEnrollment("active");
                        setSort("review");
                      }}
                    >
                      필터 초기화
                    </button>
                  )}
                </div>
                <p className="prof-result-count" role="status">
                  {enrollment === "active" ? "현재 수강생" : "수강 이력 포함"} ·
                  검색 결과 {matching.length}명 중 {visible.length}명 · 상태
                  건수는 검색·개념 조건 기준이에요.
                </p>
                {!visible.length && (
                  <p className="prof-empty">조건에 맞는 학생이 없어요.</p>
                )}
                <PagedList
                  items={visible}
                  size={10}
                  label="학생"
                  resetKey={`${search}:${scope}:${sort}:${concept}:${enrollment}:${period.from}:${period.to}`}
                >
                  {(items) => (
                    <ul className="pw-students">
                      {items.map((student) => {
                        const signals = prioritySignals(
                          signalsFor(student, concept),
                        );
                        const state = reviewState(signals);
                        return (
                          <li key={student.id} className="pw-student">
                            <div className="pw-student-main">
                              <div className="pw-student-identity">
                                <button
                                  type="button"
                                  id={`prof-student-${sectionId}-${student.id}`}
                                  className="prof-student-link"
                                  aria-label={`${student.name} 개인 학습 분석 보기`}
                                  onClick={() => openStudent(student)}
                                >
                                  <strong>{student.name}</strong>
                                  <span>전체 기록 →</span>
                                </button>
                                <span className={`pw-status is-${state}`}>
                                  {REVIEW_LABEL[state]}
                                </span>
                                <small>
                                  {!student.active && "현재 수강 외 이력 · "}
                                  {
                                    signals.filter((c) => c.state === "review")
                                      .length
                                  }
                                  개 개념 복습 필요
                                </small>
                              </div>
                              <div className="pw-signals">
                                {signals.slice(0, 3).map((signal) => (
                                  <WeaknessSignal
                                    key={signal.id}
                                    signal={signal}
                                    onSelect={() =>
                                      openStudent(student, signal)
                                    }
                                  />
                                ))}
                                {!signals.length && (
                                  <p className="pw-empty">
                                    {concept ? "이 개념의" : "선택 기간의"} 이론
                                    기록이 없어요. 아직 취약 여부를 판단할 수
                                    없어요.
                                  </p>
                                )}
                                {signals.length > 3 && (
                                  <button
                                    type="button"
                                    className="pw-more"
                                    onClick={() => openStudent(student)}
                                  >
                                    나머지 {signals.length - 3}개 개념 보기 →
                                  </button>
                                )}
                              </div>
                            </div>
                            <p className="pw-student-meta">
                              기간 이론 정답률 {rate(student.theory.accuracy)} (
                              {student.theory.independent}건) · 실습 통과율{" "}
                              {rate(student.practice_summary.accuracy)} · 질문{" "}
                              {student.chat.count}건 · 최근 활동{" "}
                              {at(student.last_activity_at)}
                            </p>
                          </li>
                        );
                      })}
                    </ul>
                  )}
                </PagedList>
              </section>
            )}
            {view === "concepts" && (
              <section aria-label="분반 개념별 학습 현황">
                <h4>개념별 이론·실습 현황</h4>
                <p className="prof-method-note">
                  복습 확인 인원은 학생마다 최근 독립 풀이 5건을 확인해
                  집계해요. 표본 부족은 낮은 성취로 분류하지 않아요.
                </p>
                <div className="prof-list-tools">
                  <label>
                    개념 검색
                    <input
                      type="search"
                      placeholder="개념 이름"
                      value={conceptSearch}
                      onChange={(e) => setConceptSearch(e.target.value)}
                    />
                  </label>
                  <label>
                    개념 집계 상태
                    <select
                      value={conceptScope}
                      onChange={(e) => setConceptScope(e.target.value)}
                    >
                      <option value="all">전체 개념</option>
                      <option value="scored">이론 집계된 개념</option>
                      <option value="unscored">이론 집계 전</option>
                    </select>
                  </label>
                  <label>
                    개념 정렬
                    <select
                      value={conceptSort}
                      onChange={(e) => setConceptSort(e.target.value)}
                    >
                      <option value="review">복습 확인 인원 많은 순</option>
                      <option value="accuracy">이론 정답률 낮은 순</option>
                      <option value="samples">집계 답안 많은 순</option>
                      <option value="name">이름순</option>
                    </select>
                  </label>
                </div>
                {!visibleConcepts.length && (
                  <p className="prof-empty">조건에 맞는 개념이 없어요.</p>
                )}
                <PagedList
                  items={visibleConcepts}
                  size={8}
                  label="개념"
                  resetKey={`${period.from}:${period.to}:${conceptSearch}:${conceptScope}:${conceptSort}`}
                >
                  {(items) => (
                    <div className="prof-class-concepts">
                      {items.map((concept) => (
                        <article key={concept.id}>
                          <h5>{concept.name}</h5>
                          <dl className="prof-evidence-counts">
                            <div>
                              <dt>이론 정답률</dt>
                              <dd>
                                {rate(concept.theory.accuracy)} (
                                {concept.theory.independent}건)
                              </dd>
                            </div>
                            <div>
                              <dt>실습 통과율</dt>
                              <dd>
                                {rate(concept.practice.accuracy)} (
                                {concept.practice.independent}건)
                              </dd>
                            </div>
                            <div>
                              <dt>복습 확인</dt>
                              <dd>{concept.review_students}명</dd>
                            </div>
                            <div>
                              <dt>표본 부족</dt>
                              <dd>{concept.insufficient_students}명</dd>
                            </div>
                            <div>
                              <dt>기준 충족</dt>
                              <dd>{concept.mastered_students}명</dd>
                            </div>
                            <div>
                              <dt>관련 질문</dt>
                              <dd>{concept.chat_count}건</dd>
                            </div>
                          </dl>
                          <div className="pw-concept-students">
                            <p>
                              복습이 필요한 학생 <small>수강 이력 포함</small>
                            </p>
                            {reviewStudents(data.data!.students, {
                              search: "",
                              concept: concept.id,
                              scope: "review",
                              sort: "review",
                            })
                              .slice(0, 6)
                              .map((student) => {
                                const signal = student.concept_signals.find(
                                  (c) => c.id === concept.id,
                                )!;
                                return (
                                  <button
                                    key={student.id}
                                    type="button"
                                    onClick={() => openStudent(student, signal)}
                                  >
                                    {student.name}
                                    {!student.active
                                      ? " (수강 이력)"
                                      : ""} · {signal.weakness}/100 →
                                  </button>
                                );
                              })}
                            {concept.review_students > 6 && (
                              <button
                                type="button"
                                onClick={() => {
                                  setView("students");
                                  setConcept(concept.id);
                                  setScope("review");
                                  setEnrollment("all");
                                  setSearch("");
                                }}
                              >
                                복습 대상 {concept.review_students}명 모두 보기
                                →
                              </button>
                            )}
                            {!concept.review_students && (
                              <small>
                                최근 5건으로 확인된 복습 대상이 없어요.
                              </small>
                            )}
                          </div>
                        </article>
                      ))}
                    </div>
                  )}
                </PagedList>
              </section>
            )}
            {view === "questions" && <ChatTopics chat={data.data.chat} />}
            <p className="prof-period-note">
              현재 수강 {data.data.active_students}명 · 수강 이력 포함{" "}
              {data.data.student_count}명 · 기간 내 활동{" "}
              {data.data.participating_students}명
            </p>
            <details className="pw-aggregate">
              <summary>
                분반 전체 이론·실습·질문 집계 <small>수강 이력 포함</small>
              </summary>
              <Summary
                theory={data.data.theory}
                practice={data.data.practice_summary}
                chat={data.data.chat}
              />
              <p className="prof-method-note">
                정답률·통과율은 채점된 독립 제출 기준이에요. 도움·재학습과 채점
                대기·보류는 별도 집계하고, 학생별 비율을 평균하지 않아요. 이론
                취약 지표와 실습 성적은 합산하지 않아요.
              </p>
            </details>
          </>
        )}
      </div>
    </section>
  );
}
