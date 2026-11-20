import { useState } from "react";
import { ErrorNotice, Notice, useLoad } from "./components";
import { ListPager, PagedList } from "./StudentLists";
import { WeaknessSignal } from "./ProfessorWeaknessCard";
import type { Signal } from "./professorWeakness";

export type Counts = {
  submitted: number;
  independent: number;
  correct: number;
  wrong: number;
  assisted: number;
  pending: number;
  accuracy: number | null;
};
export type Topic = {
  id: string;
  name: string;
  count: number;
  name_matches: number;
  source_inferences: number;
  last_at: string;
};
export type ChatSummary = {
  count: number;
  answered: number;
  unclassified: number;
  topics: Topic[];
};
import { initialPeriod, periodQuery, type Period } from "./learningPeriod";
import { PeriodFilter } from "./LearningPeriodFilter";
export { initialPeriod, periodQuery, type Period } from "./learningPeriod";
export { PeriodFilter } from "./LearningPeriodFilter";
export type ConceptInsight = {
  id: string;
  name: string;
  theory: Counts;
  practice: Counts;
  chat_count: number;
  learning: {
    state: string;
    sample: number;
    correct: number;
    success_days: number;
    weakness: number | null;
    trend_points: number | null;
    review: Counts;
    evidence: {
      attempt_id: string;
      correct: boolean;
      day: string;
      review: boolean;
    }[];
  };
};
export type StudentSummary = {
  id: string;
  name: string;
  active: boolean;
  theory: Counts;
  practice_summary: Counts;
  chat: ChatSummary;
  concept_signals: Signal[];
  review_concepts: string[];
  insufficient_concepts: number;
  last_activity_at: string | null;
};
export type Overview = {
  date_from: string;
  date_to: string;
  theory: Counts;
  practice_summary: Counts;
  chat: ChatSummary;
  students: StudentSummary[];
  student_count: number;
  active_students: number;
  participating_students: number;
  concepts: (Omit<ConceptInsight, "learning"> & {
    review_students: number;
    insufficient_students: number;
    mastered_students: number;
  })[];
};
type PracticeRecord = {
  id: string;
  title: string;
  kind: string;
  created_at: string;
  source: string;
  status: string;
  correct: boolean | null;
  independent: boolean;
  feedback: { message: string; passed: number; total: number } | null;
};
type Insight = {
  theory: Counts;
  practice_summary: Counts;
  chat: ChatSummary;
  concepts: ConceptInsight[];
  concept_options: { id: string; name: string }[];
  practice: PracticeRecord[];
  practice_page: {
    total: number;
    offset: number;
    limit: number;
    has_more: boolean;
  };
  latest_plan: {
    day: string;
    week: number;
    day_index: number;
    review_enabled: boolean;
  } | null;
  timeline: { day: string; theory: number; practice: number; chat: number }[];
};
type TheoryRecord = {
  id: string;
  question: string;
  concept: string;
  answer: string;
  created_at: string;
  status: string;
  correct: boolean | null;
  independent: boolean;
  feedback: {
    message: string;
    criteria?: { criterion: string; score: number }[];
  } | null;
};

export const rate = (value: number | null) =>
  value == null ? "집계 전" : `${value}%`;
export const at = (value: string | null) =>
  value
    ? new Date(value).toLocaleString("ko-KR", { timeZone: "Asia/Seoul" })
    : "기록 없음";
export function Summary({
  theory,
  practice,
  chat,
}: {
  theory: Counts;
  practice: Counts;
  chat: ChatSummary;
}) {
  return (
    <div className="prof-domain-metrics">
      <article>
        <h4>이론 독립 정답률</h4>
        <strong>{rate(theory.accuracy)}</strong>
        <p>
          정답 {theory.correct} / 독립 풀이 {theory.independent}건
        </p>
        <small>
          제출 {theory.submitted} · 도움·재학습 {theory.assisted} · 대기·보류{" "}
          {theory.pending}
        </small>
      </article>
      <article>
        <h4>고정 실습 독립 통과율</h4>
        <strong>{rate(practice.accuracy)}</strong>
        <p>
          통과 {practice.correct} / 독립 제출 {practice.independent}건
        </p>
        <small>
          제출 {practice.submitted} · 도움·재학습 {practice.assisted} ·
          대기·보류 {practice.pending}
        </small>
      </article>
      <article>
        <h4>AI 질문</h4>
        <strong>{chat.count}건</strong>
        <p>
          응답 기록 {chat.answered} · 개념 미분류 {chat.unclassified}
        </p>
        <small>질문 횟수는 취약 지표에 반영하지 않아요.</small>
      </article>
    </div>
  );
}

export function ChatTopics({ chat }: { chat: ChatSummary }) {
  return (
    <section className="prof-topic-summary" aria-label="질문 개념 요약">
      <h4>질문한 개념</h4>
      <p>
        질문의 개념명 또는 현재 공개된 답변 근거로 분류해요. 질문 원문은
        표시하지 않으며, 어려움이나 오개념을 확정한 결과가 아니에요. 최근 90일
        이내 기록만 집계해요.
      </p>
      {!chat.topics.length && (
        <p className="prof-empty">
          분류된 질문 개념이 없어요. 미분류 질문 {chat.unclassified}건.
        </p>
      )}
      <PagedList
        items={chat.topics}
        size={6}
        label="질문 개념"
        resetKey={JSON.stringify(chat.topics)}
      >
        {(items) => (
          <ul className="prof-topic-list">
            {items.map((topic) => (
              <li key={topic.id}>
                <strong>{topic.name}</strong>
                <span>{topic.count}건</span>
                <small>
                  개념명 일치 {topic.name_matches} · 단일 개념 근거 추정{" "}
                  {topic.source_inferences} · 최근 {at(topic.last_at)}
                </small>
              </li>
            ))}
          </ul>
        )}
      </PagedList>
      {!!chat.topics.length && (
        <small>한 질문이 여러 개념과 연결되면 각 개념에 집계돼요.</small>
      )}
    </section>
  );
}

function ConceptEvidence({
  item,
  onSelect,
}: {
  item: ConceptInsight;
  onSelect: () => void;
}) {
  const learning = item.learning;
  return (
    <details className="prof-concept-evidence">
      <summary>
        <WeaknessSignal
          signal={{ id: item.id, name: item.name, ...learning }}
        />
        <span className="pw-evidence-toggle">판단 근거 보기</span>
      </summary>
      <div className="prof-evidence-body">
        <p>
          최근 독립 풀이 {learning.sample}건 중 정답 {learning.correct}건 ·
          정답을 기록한 날짜 {learning.success_days}일
        </p>
        <p>
          {learning.trend_points == null
            ? "이전 5건과의 변화는 독립 풀이가 10건 이상일 때 표시해요."
            : `이전 5건 대비 정답률 ${learning.trend_points > 0 ? "+" : ""}${learning.trend_points}%p`}
        </p>
        <dl className="prof-evidence-counts">
          <div>
            <dt>기간 내 이론 오답</dt>
            <dd>{item.theory.wrong}건</dd>
          </div>
          <div>
            <dt>도움·재학습</dt>
            <dd>{item.theory.assisted}건</dd>
          </div>
          <div>
            <dt>독립 복습 정답</dt>
            <dd>
              {learning.review.correct}/{learning.review.independent}건
            </dd>
          </div>
          <div>
            <dt>실습 독립 통과</dt>
            <dd>
              {item.practice.correct}/{item.practice.independent}건
            </dd>
          </div>
        </dl>
        {!!learning.evidence.length && (
          <>
            <h5>판단에 사용한 최근 독립 풀이</h5>
            <ol>
              {learning.evidence.map((e) => (
                <li key={e.attempt_id}>
                  {e.day} · {e.correct ? "정답" : "오답"}
                  {e.review ? " · 복습 문항" : ""}
                </li>
              ))}
            </ol>
          </>
        )}
        <button type="button" onClick={onSelect}>
          이 개념의 답안·실습 기록 보기
        </button>
      </div>
    </details>
  );
}

export function StudentInsights({
  sectionId,
  studentId,
  period: provided,
  initialConcept,
}: {
  sectionId: string;
  studentId: string;
  period?: Period;
  initialConcept?: { id: string; name: string };
}) {
  const [localPeriod, setLocalPeriod] = useState(initialPeriod);
  const period = provided || localPeriod;
  return (
    <section
      className="prof-student-insights"
      aria-label="학생별 상세 학습 분석"
    >
      {!provided && <PeriodFilter value={period} onChange={setLocalPeriod} />}
      <StudentContent
        key={`${sectionId}:${studentId}:${period.from}:${period.to}:${initialConcept?.id || ""}`}
        sectionId={sectionId}
        studentId={studentId}
        period={period}
        initialConcept={initialConcept}
      />
    </section>
  );
}

function StudentContent({
  sectionId,
  studentId,
  period,
  initialConcept,
}: {
  sectionId: string;
  studentId: string;
  period: Period;
  initialConcept?: { id: string; name: string };
}) {
  const [concept, setConcept] = useState(
    initialConcept || { id: "", name: "전체 개념" },
  );
  const [practicePage, setPracticePage] = useState(0);
  const [theoryPage, setTheoryPage] = useState(0);
  const query = periodQuery(period);
  if (concept.id) query.set("concept_id", concept.id);
  const detailQuery = new URLSearchParams(query);
  detailQuery.set("practice_offset", String(practicePage * 10));
  const historyQuery = new URLSearchParams(query);
  historyQuery.set("offset", String(theoryPage * 10));
  historyQuery.set("limit", "10");
  const base = `/sections/${sectionId}/students/${studentId}`;
  const detail = useLoad<Insight>(`${base}/insights?${detailQuery}`);
  const history = useLoad<{ items: TheoryRecord[]; total: number }>(
    `${base}/learning?${historyQuery}`,
  );
  const selectConcept = (id: string, name: string) => {
    setConcept({ id, name });
    setPracticePage(0);
    setTheoryPage(0);
  };
  return (
    <>
      <div className="prof-list-tools">
        <label>
          개념
          <select
            value={concept.id}
            onChange={(e) =>
              selectConcept(e.target.value, e.target.selectedOptions[0].text)
            }
          >
            <option value="">전체 개념</option>
            {detail.data
              ? detail.data.concept_options.map((c) => (
                  <option value={c.id} key={c.id}>
                    {c.name}
                  </option>
                ))
              : concept.id && (
                  <option value={concept.id}>{concept.name}</option>
                )}
          </select>
        </label>
        <button
          type="button"
          onClick={() => {
            detail.reload();
            history.reload();
          }}
        >
          기록 새로고침
        </button>
      </div>
      <ErrorNotice text={detail.error} />
      {!detail.data && !detail.error && (
        <Notice>학생별 기록을 분석하고 있어요…</Notice>
      )}
      {detail.data && (
        <>
          {detail.data.latest_plan && (
            <p className="prof-period-note">
              최근 배정 {detail.data.latest_plan.day} ·{" "}
              {detail.data.latest_plan.week}주차{" "}
              {detail.data.latest_plan.day_index}일차 ·{" "}
              {detail.data.latest_plan.review_enabled
                ? "복습 반영 계획"
                : "새 개념 학습 계획"}
            </p>
          )}
          <section aria-label="개념별 이론 근거">
            <h4>개념별 취약도와 판단 근거</h4>
            {!!detail.data.concepts.length && (
              <p className="pw-detail-summary">
                복습 필요{" "}
                <strong>
                  {
                    detail.data.concepts.filter(
                      (c) => c.learning.state === "review",
                    ).length
                  }
                  개
                </strong>{" "}
                · 표본 부족{" "}
                <strong>
                  {
                    detail.data.concepts.filter(
                      (c) => c.learning.state === "insufficient",
                    ).length
                  }
                  개
                </strong>{" "}
                · 취약도는 높을수록 복습이 필요해요.
              </p>
            )}
            <p className="prof-method-note">
              선택 기간의 최근 독립 풀이 5건으로 이론 취약 지표를 계산해요. 5건
              미만이면 표본 부족, 4건 이상 정답이고 서로 다른 날짜에 2회 이상
              정답이면 기준 충족이에요. 지표는 최근 오답 비율이며 실습과 질문
              횟수는 합산하지 않아요.
            </p>
            {!detail.data.concepts.length && (
              <p className="prof-empty">이 기간에 확인할 학습 기록이 없어요.</p>
            )}
            <PagedList
              items={detail.data.concepts}
              size={6}
              label="개념"
              resetKey={concept.id}
            >
              {(items) => (
                <div>
                  {items.map((item) => (
                    <ConceptEvidence
                      key={item.id}
                      item={item}
                      onSelect={() => selectConcept(item.id, item.name)}
                    />
                  ))}
                </div>
              )}
            </PagedList>
          </section>
          <details className="pw-aggregate">
            <summary>선택 조건의 이론·실습·질문 집계</summary>
            <Summary
              theory={detail.data.theory}
              practice={detail.data.practice_summary}
              chat={detail.data.chat}
            />
          </details>
          <ChatTopics chat={detail.data.chat} />
          <details className="prof-timeline">
            <summary>
              날짜별 활동 기록 ({detail.data.timeline.length}일)
            </summary>
            <PagedList
              items={detail.data.timeline}
              size={10}
              label="활동 날짜"
              resetKey={concept.id}
            >
              {(items) => (
                <ul>
                  {items.map((day) => (
                    <li key={day.day}>
                      {day.day} · 이론 제출 {day.theory} · 실습 제출{" "}
                      {day.practice} · 질문 {day.chat}
                    </li>
                  ))}
                </ul>
              )}
            </PagedList>
          </details>
        </>
      )}
      <section aria-label="이론 답안 상세">
        <h4>이론 답안·피드백</h4>
        <ErrorNotice text={history.error} />
        {!history.data && !history.error && (
          <Notice>답안 기록을 불러오는 중이에요…</Notice>
        )}
        {history.data && (
          <>
            <p>선택 기간·개념의 제출 {history.data.total}건</p>
            {!history.data.items.length && (
              <p className="prof-empty">조건에 맞는 이론 답안이 없어요.</p>
            )}
            {history.data.items.map((record) => (
              <details className="prof-answer" key={record.id}>
                <summary>
                  <span className="prof-answer-meta">
                    {at(record.created_at)} · {record.concept} ·{" "}
                    {outcome(record)}
                  </span>
                  <span className="prof-answer-question">
                    {record.question}
                  </span>
                </summary>
                <div className="prof-answer-body">
                  <h5>제출 답안</h5>
                  <p>{record.answer}</p>
                  <h5>피드백</h5>
                  <p>{record.feedback?.message || "제공된 피드백이 없어요."}</p>
                  {record.feedback?.criteria?.map((c, i) => (
                    <p key={i}>
                      {c.criterion} · {c.score}점
                    </p>
                  ))}
                  <small>
                    {record.independent ? "독립 풀이" : "도움·재학습 풀이"} ·{" "}
                    {record.status === "graded" &&
                    record.correct !== null &&
                    record.independent
                      ? "정답률 집계 포함"
                      : "정답률 집계 제외"}
                  </small>
                </div>
              </details>
            ))}
            <ListPager
              page={theoryPage}
              pages={Math.ceil(history.data.total / 10)}
              onChange={setTheoryPage}
              label="이론 답안"
            />
          </>
        )}
      </section>
      {detail.data && (
        <section aria-label="고정 실습 제출 상세">
          <h4>고정 실습 제출·검증 결과</h4>
          <p>
            총 {detail.data.practice_page.total}건 · 이 기록은 이론 복습 선정에
            반영하지 않아요.
          </p>
          {!detail.data.practice.length && (
            <p className="prof-empty">조건에 맞는 실습 제출이 없어요.</p>
          )}
          {detail.data.practice.map((record) => (
            <details className="prof-answer" key={record.id}>
              <summary>
                <span className="prof-answer-meta">
                  {at(record.created_at)} ·{" "}
                  {record.kind === "blank" ? "빈칸" : "풀코딩"} ·{" "}
                  {outcome(record, true)}
                </span>
                <span className="prof-answer-question">{record.title}</span>
              </summary>
              <div className="prof-answer-body">
                <p>
                  {record.independent ? "독립 제출" : "도움·재학습 제출"} ·{" "}
                  {record.feedback?.message || "검증 결과 대기"}
                </p>
                {record.feedback && (
                  <p>
                    검증 입력 통과 {record.feedback.passed}/
                    {record.feedback.total}
                  </p>
                )}
                <pre>
                  <code>{record.source}</code>
                </pre>
              </div>
            </details>
          ))}
          <ListPager
            page={practicePage}
            pages={Math.ceil(detail.data.practice_page.total / 10)}
            onChange={setPracticePage}
            label="실습 제출"
          />
        </section>
      )}
    </>
  );
}

function outcome(
  record: { status: string; correct: boolean | null },
  practice = false,
) {
  if (record.status !== "graded" || record.correct === null)
    return "채점 대기·보류";
  return record.correct
    ? practice
      ? "통과"
      : "정답"
    : practice
      ? "미통과"
      : "오답";
}

export function downloadOverview(data: Overview) {
  const columns = [
    "학생",
    "시작일",
    "종료일",
    "이론 제출",
    "이론 독립 풀이",
    "이론 정답",
    "이론 오답",
    "이론 정답률",
    "이론 도움·재학습",
    "이론 대기·보류",
    "실습 제출",
    "실습 독립 제출",
    "실습 통과",
    "실습 미통과",
    "실습 통과율",
    "실습 도움·재학습",
    "실습 대기·보류",
    "질문",
    "복습 확인 개념",
    "표본 부족 개념",
    "개념별 취약도(최근 독립 풀이 5건)",
  ];
  const metrics = (c: Counts) => [
    c.submitted,
    c.independent,
    c.correct,
    c.wrong,
    c.accuracy ?? "",
    c.assisted,
    c.pending,
  ];
  const rows = data.students.map((s) => [
    s.name,
    data.date_from,
    data.date_to,
    ...metrics(s.theory),
    ...metrics(s.practice_summary),
    s.chat.count,
    s.review_concepts.join(" / "),
    s.insufficient_concepts,
    s.concept_signals
      .map(
        (c) =>
          `${c.name}: ${c.weakness == null ? `판단 전(${c.sample}/5건)` : `${c.weakness}/100`}`,
      )
      .join(" / "),
  ]);
  const escape = (value: string | number) => {
    const text = String(value);
    return `"${(/^[\s]*[=+@-]/.test(text) ? "'" + text : text).replaceAll('"', '""')}"`;
  };
  const content = [columns, ...rows]
    .map((row) => row.map(escape).join(","))
    .join("\r\n");
  const url = URL.createObjectURL(
    new Blob(["\ufeff", content], { type: "text/csv;charset=utf-8" }),
  );
  const link = document.createElement("a");
  link.href = url;
  link.download = `learning-${data.date_from}-${data.date_to}.csv`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
