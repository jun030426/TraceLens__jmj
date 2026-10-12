import { ResourceBrowser } from "./ResourceBrowser";
import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, post } from "./api";
import { Form, Input, ErrorNotice, Notice, field, useLoad } from "./components";
import "./professor-analysis.css";
type Plan = { id:string; title:string; start_week:number; end_week:number; published:boolean; revision:number };
type PracticeQuestion = {id:string;kind:string;prompt:string;options:string[]};
export function ExamPlans({ courseId }: { courseId: string }) {
  const plans = useLoad<{ items: Plan[] }>(`/courses/${courseId}/exam-plans`);
  const [editor, setEditor] = useState<Plan | "new" | null>(null);
  const [message, setMessage] = useState("");
  const editing = editor && editor !== "new" ? editor : null;
  const editorPanel = useRef<HTMLElement>(null);
  useEffect(() => { if (editor) editorPanel.current?.focus(); }, [editor]);
  return <div className="teacher-exams-page exam-manager">
    <div className="teacher-tab-heading"><div><h2>시험 대비</h2><p>주차 범위를 정하면, 준비된 복습 문항을 학생에게 모아 보여줘요.</p></div><button className="exam-add" aria-expanded={!!editor} aria-controls="exam-range-editor" onClick={() => { setEditor(editor ? null : "new"); setMessage(""); }}>{editor ? "설정 닫기" : "+ 시험 범위 추가"}</button></div>
    <ErrorNotice text={plans.error} />{message && <Notice>{message}</Notice>}
    {editor && <section id="exam-range-editor" className="panel exam-range-editor" ref={editorPanel} tabIndex={-1} aria-label={editing ? "시험 범위 수정" : "새 시험 범위"}><h3>{editing ? "시험 범위 수정" : "새 시험 범위"}</h3><p>이름과 범위를 확인한 뒤, 학생 공개 여부를 선택하세요.</p>
      <Form key={editing?.id || "new"} label={editing ? "변경 저장" : "시험 범위 저장"} onCancel={() => setEditor(null)} onSubmit={async f => {
        const start = Number(field(f, "start")), end = Number(field(f, "end"));
        if (end < start) throw new Error("종료 주차는 시작 주차보다 같거나 커야 해요.");
        const body = { title: field(f, "title").trim(), start_week: start, end_week: end, published: f.has("published") };
        if (!body.title) throw new Error("시험 이름을 입력해 주세요.");
        if (editing) await api(`/exam-plans/${editing.id}`, { method: "PATCH", headers: { "If-Match": String(editing.revision) }, body: JSON.stringify(body) });
        else await api(`/courses/${courseId}/exam-plans`, post(body));
        setEditor(null); setMessage(body.published ? "시험 범위를 저장하고 학생에게 공개했어요." : "시험 범위를 비공개로 저장했어요."); plans.reload();
      }}>
        <label className="exam-title-field">시험 이름<input name="title" placeholder="예: 중간고사" maxLength={100} defaultValue={editing?.title || ""} required /></label>
        <div className="exam-week-fields"><label>시작 주차<input name="start" type="number" min="1" max="52" defaultValue={editing?.start_week || 1} required /></label><span aria-hidden="true">—</span><label>종료 주차<input name="end" type="number" min="1" max="52" defaultValue={editing?.end_week || 8} required /></label></div>
        <label className="exam-publish-field"><input type="checkbox" name="published" defaultChecked={editing?.published || false} /><span><strong>학생에게 공개</strong><small>선택하지 않으면 교수님만 볼 수 있어요.</small></span></label>
      </Form>
    </section>}
    {!plans.data && !plans.error && <Notice>시험 범위를 불러오는 중이에요…</Notice>}
    {plans.data?.items.length === 0 && <section className="exam-empty"><span className="student-eyebrow">PREPARE FOR THE NEXT STEP</span><h3>시험 범위만 정해 주세요.</h3><p>강의 자료에서 준비된 문항으로 학생들이 복습할 수 있어요.<br />기출이나 연습 자료가 있다면 함께 제공할 수 있습니다.</p><span className="exam-empty-foot">평소 퀴즈는 시험 범위 설정 없이도 이어집니다.</span></section>}
    {!!plans.data?.items.length && <div className="exam-ranges"><div className="exam-list-label">등록된 시험 범위 <span>{plans.data.items.length}</span></div>{plans.data.items.map(p => <article className="exam-range-row" key={p.id}><div className="exam-range-info"><h3>{p.title}</h3><div className="exam-range-meta"><p className="exam-range-weeks"><strong>{p.start_week}–{p.end_week}주차</strong></p><span className={`exam-visibility ${p.published ? "is-public" : ""}`}>{p.published ? "학생 공개" : "비공개"}</span></div></div><div className="exam-range-actions"><button onClick={() => { setEditor(p); setMessage(""); }}>범위 수정</button><Form actionRole="secondary" label={p.published ? "공개 중지" : "학생에게 공개"} onSubmit={async () => { await api(`/exam-plans/${p.id}`, { method: "PATCH", headers: { "If-Match": String(p.revision) }, body: JSON.stringify({ title: p.title, start_week: p.start_week, end_week: p.end_week, published: !p.published }) }); setEditor(null); plans.reload(); }}><span /></Form></div></article>)}</div>}
    <details className="exam-resource-help"><summary>기출·연습 자료도 함께 제공하고 싶다면 <span aria-hidden="true">⌄</span></summary><p>강의 자료에서 해당 주차에 기출 또는 과제 안내 자료를 올려 공개하세요. 시험 범위에 포함된 자료를 학생이 확인할 수 있어요. 정답·해설은 비공개로 보관할 수 있습니다.</p><Link to={`/professor/courses/${courseId}?tab=materials`}>강의 자료로 이동 →</Link></details>
  </div>;
}
export function StudentExamPrep() {
  const [params] = useSearchParams();
  const courseId = params.get("course") || "";
  const plans = useLoad<{ items: Plan[] }>(`/courses/${courseId}/exam-plans`);
  const [selected, setSelected] = useState("");
  const plan = plans.data?.items.find(p => p.id === selected) || plans.data?.items[0];
  return <section className="student-home student-exam-page exam-study">
    <Link to="/courses" className="teacher-course-back">← 내 강의</Link>
    <header className="exam-study-heading"><span className="student-eyebrow">PREPARE WITH YOUR CLASS</span><h1>시험 대비</h1><p>시험 범위를 따라, 배운 내용을 다시 연결해 보세요.</p></header>
    <ErrorNotice text={plans.error} />
    {!plans.data && !plans.error && <Notice>공개된 시험 범위를 확인하고 있어요…</Notice>}
    {plans.data?.items.length === 0 && <div className="exam-study-empty"><span className="student-eyebrow">YOUR NEXT REVIEW</span><h2>시험 범위가 공개되면 여기서 만나요.</h2><p>지금은 강의실의 퀴즈로 배운 내용을 복습할 수 있어요.</p><Link to="/quiz" className="exam-study-cta">퀴즈로 복습하기 ↗</Link></div>}
    {!!plans.data?.items.length && <div className="student-list-tools"><label>시험 범위 선택<select value={plan?.id || ""} onChange={e => setSelected(e.target.value)}>{plans.data.items.map(p => <option key={p.id} value={p.id}>{p.title} · {p.start_week}–{p.end_week}주차</option>)}</select></label></div>}
    {plan && <ExamPractice key={plan.id} plan={plan} />}
  </section>;
}
function ExamPractice({ plan }: { plan: Plan }) {
  const data = useLoad<{ questions: PracticeQuestion[]; resources: { id: string; title: string; week: number }[] }>(`/exam-plans/${plan.id}/practice`);
  const [active, setActive] = useState(0);
  const questions = data.data?.questions || [];
  const question = questions[active];
  return <><ErrorNotice text={data.error} />
    <div className="exam-study-summary"><div><span className="student-eyebrow">REVIEW SCOPE</span><h2>{plan.title}</h2><p>{plan.start_week}–{plan.end_week}주차 · 공개된 강의 자료 기준</p></div><div className="exam-study-count"><strong>{data.data ? questions.length : "—"}</strong><span>복습 문항</span></div></div>
    {!data.data && !data.error && <Notice>범위에 맞는 자료와 문항을 불러오고 있어요…</Notice>}
    {data.data && <>
      <section className="exam-study-resources"><div className="exam-study-section-title"><div><h2>교수님 제공 자료</h2><p>공개된 기출·연습 자료를 내려받아 확인하세요.</p></div><span>{data.data.resources.length}개 자료</span></div>
      {data.data.resources.length ? <ResourceBrowser items={data.data.resources} label="시험 참고 자료">{visible => <div className="exam-resource-list">{visible.map(r => <a key={r.id} href={`/api/v1/materials/${r.id}/file`}><span>{r.week}주차</span><strong>{r.title}</strong><b aria-label="다운로드">↓</b></a>)}</div>}</ResourceBrowser> : <p className="exam-study-no-resources">별도로 공개된 참고 자료는 없어요. 아래 복습 문제로 학습을 이어가세요.</p>}</section>
      <section className="exam-study-questions"><div className="exam-study-section-title"><div><h2>강의 기반 복습 문제</h2><p>강의 자료로 생성한 연습 문제예요. 실제 기출문제와는 구분됩니다.</p></div></div>
        {!questions.length ? <div className="exam-study-empty compact"><h3>이 범위의 복습 문항을 준비하고 있어요.</h3><p>평소 퀴즈에서 먼저 학습을 이어갈 수 있습니다.</p><Link to="/quiz" className="exam-study-cta">퀴즈로 이동 ↗</Link></div> : <>
          <div className="student-list-tools exam-question-jump"><label>복습 문제 이동<select value={active} onChange={e => setActive(Number(e.target.value))}>{questions.map((q,i) => <option key={q.id} value={i}>{i+1}번 · {q.kind === "mcq" ? "객관식" : "서술형"}</option>)}</select></label></div>
          <div className="exam-study-progress"><span>{active + 1} / {questions.length} 문항</span><span>답을 확인한 뒤 해설을 살펴보세요.</span></div>
          {questions.map((q, i) => <div key={q.id} hidden={i !== active}><ExamPracticeItem q={q} planId={plan.id} number={i + 1} /></div>)}
          <div className="exam-question-pager"><button disabled={active === 0} onClick={() => setActive(active - 1)}>← 이전 문제</button><span>{question?.kind === "mcq" ? "객관식" : "서술형"}</span><button disabled={active === questions.length - 1} onClick={() => setActive(active + 1)}>다음 문제 →</button></div>
        </>}
        <details className="exam-study-policy"><summary>시험 대비 학습 기록 안내</summary><p>시험 대비 풀이는 연속 학습에 집계되지 않아요. 연속 학습은 오늘의 이론 또는 실습 묶음을 최종 제출하면 인정됩니다.</p></details>
      </section>
    </>}
  </>;
}
function ExamPracticeItem({q,planId,number}:{q:PracticeQuestion;planId:string;number:number}){
 const [answer,setAnswer]=useState("");const [result,setResult]=useState<{correct:boolean|null;message:string;solution:{explanation:string;criteria:string[]}}>();
 return <article className="exam-practice-item"><span>{number}번 · {q.kind==="mcq"?"객관식":"서술형"}</span><h3>{q.prompt}</h3><Form label={q.kind==="mcq"?"답 확인":"해설과 비교하기"} onSubmit={async()=>{setResult(await api(`/exam-plans/${planId}/questions/${q.id}/review`,post({answer})));}}>{q.kind==="mcq"?q.options.map((o,i)=><label className="check" key={i}><input type="radio" name={`answer-${q.id}`} required value={i} checked={answer===String(i)} onChange={()=>{setAnswer(String(i));setResult(undefined);}}/>{o}</label>):<label>내 답안<textarea required maxLength={5000} value={answer} onChange={e=>{setAnswer(e.target.value);setResult(undefined);}}/></label>}</Form>{result&&<div className="exam-practice-feedback" role="status"><strong>{result.message}</strong><p>{result.solution.explanation}</p>{q.kind==="essay"&&<ul>{result.solution.criteria.map((c,i)=><li key={i}>{c}</li>)}</ul>}</div>}</article>;
}
