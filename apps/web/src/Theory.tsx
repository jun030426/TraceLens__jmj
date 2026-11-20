import { DropSelect } from "./DropSelect";
import { Link } from "react-router-dom";
import { useState } from "react";
import { kindLabel } from "./questionKinds";
import { api, type Concept } from "./api";
import { ErrorNotice, Form, Notice, useLoad } from "./components";

type Attempt = {
  id: string;
  status: string;
  score: number | null;
  correct: boolean | null;
  appealed: boolean;
  feedback: {
    message: string;
    criteria?: { criterion: string; score: number }[];
  } | null;
};
type Question = {
  id: string;
  concept_id?: string;
  kind: string;
  prompt: string;
  options: string[];
  revision: number;
  status: string;
  attempt?: Attempt | null;
  explanation?: string;
  submitted_answer?: string;
  correct_option?: string;
  sources_current?: boolean;
  solution?: { explanation: string };
};
export type Daily = {
  id: string;
  section_id: string;
  day: string;
  items: Question[];
  shortage: number;
  target_count?: number;
  status?: string;
  job_id?: string;
  week?: number;
  day_index?: number;
  message?: string;
  retry_at?: string | null;
};

export function QuestionBank({
  courseId,
  concepts,
}: {
  courseId: string;
  concepts: Concept[];
}) {
  const [chosenConcept, setConcept] = useState("");
  const bank = useLoad<{ items: Question[] }>(`/courses/${courseId}/questions`);
  const filtered = (bank.data?.items || []).filter(q => !chosenConcept || q.concept_id === chosenConcept);
  return (
    <section className="panel teacher-question-bank">
      <h2>이론 문항 관리</h2>
      <div className="teacher-question-create">
        <h3>수업 자료로 문항 만들기</h3>
        <p>강의 자료에서 주차별 콘텐츠를 생성하고 검토한 뒤 학생에게 공개하세요.</p>
        <Link className="link-button" to={`/professor/courses/${courseId}?tab=materials`}>주차별 콘텐츠 생성·검토로 →</Link>
      </div>
      <DropSelect searchable label="학습 개념" value={chosenConcept}
        options={[{ value: "", label: "전체 개념" }, ...concepts.map(c => ({ value: c.id, label: c.name }))]}
        onChange={setConcept} />
      <ErrorNotice text={bank.error} />
      <div className="teacher-question-list-heading"><h3>등록된 문항 {bank.data && <small>{filtered.length}개</small>}</h3><button onClick={bank.reload}>목록 새로고침</button></div>
      {!bank.data && !bank.error && <Notice>문항을 불러오는 중이에요…</Notice>}
      {bank.data?.items.length === 0 && <Notice>아직 등록된 문항이 없어요. 공개된 자료와 학습 개념을 준비하고 문항을 생성해 주세요.</Notice>}
      {bank.data && bank.data.items.length > 0 && !filtered.length && <Notice>이 개념에 등록된 문항이 없어요.</Notice>}
      {filtered.map((q) => (
        <article className="quiz-card" key={q.id}>
          <small>
            {kindLabel(q.kind)} · {q.status === "active" ? "사용 중" : q.status === "stopped" ? "사용 중지" : q.status} ·{" "}
            {q.sources_current ? "현재 자료 근거" : "근거 갱신 필요"}
          </small>
          <h3>{q.prompt}</h3>
          {q.options.map((o, i) => (
            <p key={i}>
              {i + 1}. {o}
            </p>
          ))}
          <details>
            <summary>해설</summary>
            <p>{q.solution?.explanation}</p>
          </details>
          <Form
            label={q.status === "active" ? "문항 사용 중지" : "문항 다시 사용"}
            actionRole="secondary"
            onSubmit={async () => {
              await api(`/questions/${q.id}`, {
                method: "PATCH",
                headers: { "If-Match": String(q.revision) },
                body: JSON.stringify({
                  status: q.status === "active" ? "stopped" : "active",
                }),
              });
              bank.reload();
            }}
          >
            <span />
          </Form>
        </article>
      ))}
    </section>
  );
}

export { Analytics } from "./ProfessorAnalytics";
