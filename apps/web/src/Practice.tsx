import { SubmittedCode, type SubmissionSnapshot } from "./SubmittedCode";
import { archivePath } from "./QuizArchive";
import { notifyPracticeSubmit } from "./xp/practiceXp";
import { isComposingInput } from "./inputKeyboard";
import { practiceSubmitBody } from "./learningRequests";
import { lazy, Suspense, useContext, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { Auth } from "./Auth";
import { api, post, type Classroom } from "./api";
import { ErrorNotice, Notice, useLoad } from "./components";
import { PracticeHints } from "./PracticeHints";
import { STAGE_LABEL, type PracticeRun } from "./visualizer/practiceRun";
import { useCodeTrace } from "./useCodeTrace";
import type { TraceStage } from "./visualizer/trace/tracerClient";
import type { BlankQuiz } from "./blankQuizzes";
import { checkBlanks } from "./visualizer/blankCheck";
import { buildRunnable, circled, cleanFill, parseTemplate, showBlanks, type BlankTemplate } from "./visualizer/blanks";
import "./practice-blanks.css";
import { VizLineContext, type VizLine } from "./visualization/vizLine";
import { lineComment } from "./visualization/screen/lineComment";
import { PracticeChat, type PracticeChatContext } from "./PracticeChat";
import "./practice-chat.css";
import { ghostLines, ghostRest, type SyntaxIssue } from "./practiceRules";
import { useConfirm } from "./ConfirmDialog";
import { quickFix, type QuickFix } from "./quickFix";

import { LearningText } from "./LearningText";
import { PracticeAttemptReview, practiceKindLabel } from "./PracticeReview";

type Language = "Python" | "Java" | "C";

// 시각화 화면(three.js 포함)은 시각화 탭을 열 때만 불러와요.
const CodeTracePlayer = lazy(() => import("./PythonTracePlayer").then(m => ({ default: m.CodeTracePlayer })));
/* 코드 실행 한 번의 기록을 두 탭이 나눠 써요: 실행 결과 = 출력·오류, 시각화 = 같은 기록의 장면 */
function PracticeOutput({ tab, run, stage, code, incomplete, blankLines = [], fixes }: { tab: string; run: PracticeRun | null; stage: TraceStage | null; code: string; incomplete: boolean; blankLines?: { n: number; line: number }[]; /** 실행 전 자동수정 안내 — 실행 결과 창 출력값 위에 보여요 (11-14) */ fixes?: QuickFix[] }) {
  if (stage) return <div className="practice-output-empty"><strong>{STAGE_LABEL[stage]}</strong></div>;
  if (!run) return <div className="practice-output-empty"><strong>{tab === "실행 결과" ? "실행 결과가 여기에 표시돼요." : "코드의 실행 흐름을 장면으로 보여 줘요."}</strong><p>빈칸을 채우거나 "코드 실행"을 누르면 {tab === "실행 결과" ? "출력이 이곳에 나타나요." : "바로 시각화가 준비돼요."}</p></div>;
  const stale = run.code !== code && <p className="practice-run-stale">코드가 바뀌었어요. 다시 실행하면 새 결과를 볼 수 있어요.</p>;
  if (run.kind === "blocked") return <div className="practice-output-empty">{stale}<strong>실행하지 못했어요.</strong><p>{run.text}</p></div>;
  if (run.kind === "syntax") {
    if (incomplete) return <div className="practice-output-empty"><strong>코드 구조의 빈칸을 먼저 채워 주세요.</strong><p>반복문이나 조건문이 빈칸이면 부분 실행이 어려울 수 있어요. 빈칸을 완성하면 문법과 실행 결과를 확인할 수 있어요.</p></div>;
    // 빈칸 실습: 문법 오류가 빈칸이 있는 줄이면 "빈칸 ②를 확인해 보세요"라고 짚어 준다
    const inBlank = blankLines.filter(b => b.line === run.info.line).map(b => circled(b.n)).join("·");
    return <div className="practice-run">{stale}<div className="practice-run-error" role="alert"><strong>{inBlank ? `빈칸 ${inBlank}에 쓴 내용을 확인해 보세요` : run.info.line ? `${run.info.line}번째 줄에서 실행 전에 멈췄어요` : "실행 전에 멈췄어요"} · {run.info.name}</strong>{run.info.text && <code>{showBlanks(run.info.text)}</code>}<p>{run.info.msg}</p></div></div>;
  }
  if (tab === "실행 결과") return <div className="practice-run">{stale}{!!fixes?.length && <FixBanner fixes={fixes} />}<pre className="practice-run-stdout">{run.stdout || "(출력 없음)"}</pre>{run.blankStop && <p className="practice-run-note">빈칸 {circled(run.blankStop.blank)} 앞({run.blankStop.line}번째 줄)까지만 실행했어요. 빈칸을 채우면 이어서 실행돼요.</p>}{run.error && <div className="practice-run-error" role="alert"><strong>실행 중 오류</strong><p>{run.error}</p></div>}{run.clipped && <p className="practice-run-note">실행이 길어 앞부분까지만 기록했어요.</p>}</div>;
  if (!run.trace) return <div className="practice-output-empty">{stale}<strong>보여 줄 실행 장면이 없어요.</strong></div>;
  // 오래된 기록 안내(stale)·오류·부분 기록 안내는 시각화 호스트가 보여 줘요
  return <div className="practice-run"><Suspense fallback={<Notice>시각화 화면을 불러오는 중이에요…</Notice>}><CodeTracePlayer trace={run.trace} source={run.code} stale={run.code !== code} /></Suspense></div>;
}
type PracticeAttempt = { id: string; practice_session_id: string; exercise_id: string; status: string; correct: boolean | null; independent: boolean; source?: string; replay_source?: string; submission_snapshot?: SubmissionSnapshot | null; created_at: string; job_id?: string; feedback?: { message: string; passed?: number; total?: number }; exercise?: { title: string; kind: string } | null };
type PracticeKind = "blank" | "full";
type PracticeProblem = BlankQuiz & {
  display_template?: string | null;
  problem_id?: string;
  variants?: Partial<Record<PracticeKind, { exercise_id: string; template: string; display_template?: string | null; example_input?: string; hint_steps: number; attempt?: PracticeAttempt | null }>>;
  submitted_exercise_id?: string | null;
  attempt?: PracticeAttempt | null;
};
type PracticeDaily = { id?: string; items: PracticeProblem[]; status: string; week: number; message?: string };

function belongsToProblem(problem: PracticeProblem, exerciseId: string) {
  return exerciseId === problem.id || exerciseId === problem.submitted_exercise_id
    || Object.values(problem.variants ?? {}).some(v => v.exercise_id === exerciseId);
}

export function PracticeWorkspace() {
  const { sectionId = "" } = useParams();
  const [params] = useSearchParams();
  const week = params.get("week");
  const rooms = useLoad<{ items: Classroom[] }>("/classrooms");
  const room = rooms.data?.items.find(r => r.section.id === sectionId && r.status === "active");
  const [data, setData] = useState<PracticeDaily>();
  const [error, setError] = useState("");
  const [reload, setReload] = useState(0);
  useEffect(() => {
    let active = true, timer: ReturnType<typeof setTimeout>;
    setData(undefined); setError("");
    const load = async () => {
      try {
        const result = await api<PracticeDaily>(week ? `/sections/${sectionId}/quiz-archive/${encodeURIComponent(week)}/practice` : `/sections/${sectionId}/practice/daily`, post({}));
        if (!active) return;
        setData(result);
        if (result.status === "preparing") timer = setTimeout(load, 7000);
      } catch (e) { if (active) setError((e as Error).message); }
    };
    if (room) void load();
    return () => { active = false; clearTimeout(timer); };
  }, [sectionId, room?.section.id, week, reload]);
  if (!room || !data?.items.length) return <section className="student-home practice-page">
    <Link to={week ? archivePath(sectionId, week) : `/quiz?section=${sectionId}`}>← 퀴즈 목록</Link><h1>{week ? `${week}주차 실습 퀴즈` : "오늘의 실습"}</h1>
    <ErrorNotice text={rooms.error || error} />
    <Notice>{data?.message || (week ? "주차 실습을 불러오는 중이에요." : "이번 주 강의자료의 실습을 준비하고 있어요.")}</Notice>
    <button onClick={() => setReload(v => v + 1)}>다시 확인</button>
  </section>;
  return <PracticeEditor key={`${sectionId}:${data.id}`} room={room} quizzes={data.items} planId={data.id!} week={week} />;
}

function PracticeEditor({ room, quizzes, planId, week }: { room: Classroom; quizzes: PracticeProblem[]; planId: string; week: string | null }) {
  const sectionId = room.section.id;
  const archivePlan = week ? planId : undefined;
  const back = week ? archivePath(sectionId, week) : `/quiz?section=${sectionId}`;
  const navigate = useNavigate();
  const { user } = useContext(Auth);
  const language: Language = ({ python: "Python", java: "Java", c: "C" } as Record<string, Language>)[room.course.teaching_language.toLowerCase()] || "Python";
  const [quizIndex, setQuizIndex] = useState(0);
  const [confirm, confirmDialog] = useConfirm(); // 최종 제출·퀴즈 마침 확인창 (화면 안에 떠요)
  const current = Math.min(quizIndex, quizzes.length - 1);
  const problem = quizzes[current];
  const submissions = useLoad<{ items: PracticeAttempt[] }>(
    `/sections/${sectionId}/practice/attempts?plan_id=${encodeURIComponent(planId)}&by_exercise=true`, true);
  const [justSubmitted, setJustSubmitted] = useState<Record<string, PracticeAttempt>>({});
  const attemptFor = (exerciseId: string, fallback?: PracticeAttempt | null) =>
    submissions.data?.items.find(a => a.exercise_id === exerciseId)
    ?? justSubmitted[exerciseId]
    ?? (fallback?.exercise_id === exerciseId ? fallback : undefined);
  const [selectedKind, setSelectedKind] = useState<PracticeKind | null>(null);
  const kindsOf = (p: PracticeProblem) => (["blank", "full"] as const).filter(kind => p.variants
    ? !!p.variants[kind] : kind === (p.kind ?? "blank"));
  const kinds = kindsOf(problem);
  // 빈칸 채우기와 전체 구현은 유형마다 따로 한 번씩 제출해요. 제출 기록도 유형(exercise)별로 찾아요.
  const variantAttempt = (p: PracticeProblem, kind: PracticeKind) => {
    const v = p.variants?.[kind];
    return v ? attemptFor(v.exercise_id, v.attempt ?? p.attempt) : attemptFor(p.id, p.attempt);
  };
  // 문제 탭의 ✓는 한 유형이라도 제출하면 붙어요 — 진행률·'퀴즈 마침' 확인과 같은 기준이에요.
  const submittedAny = (p: PracticeProblem) => !!p.submitted_exercise_id || kindsOf(p).some(kind => !!variantAttempt(p, kind));
  const shownKind = selectedKind && kinds.includes(selectedKind)
    ? selectedKind : problem.kind && kinds.includes(problem.kind) ? problem.kind : kinds[0];
  const variant = problem.variants?.[shownKind];
  const quiz = variant ? { ...problem, kind: shownKind, id: variant.exercise_id, template: variant.template, display_template: variant.display_template, example_input: variant.example_input ?? problem.example_input } : problem;
  const latest = attemptFor(quiz.id, variant?.attempt ?? problem.attempt);
  const replaySource = latest?.replay_source ?? latest?.source;
  const editable = !!submissions.data && !latest;
  // 문제 유형 — 빈칸 채우기 / 직접 작성(풀코딩). 직접 작성은 학생 코드 전체를 fills[0]에 담아 같은 저장·실행·채점 흐름을 써요.
  const isFull = quiz.kind === "full";
  const [fillsByQuiz, setFillsByQuiz] = useState<Record<string, Record<number, string>>>({});
  const fills = fillsByQuiz[quiz.id] || {};
  const fullCode = isFull ? (fills[0] ?? quiz.template) : "";
  const displayTemplate = quiz.display_template ?? quiz.template;
  const template = useMemo(() => parseTemplate(isFull ? fullCode : displayTemplate), [isFull, fullCode, displayTemplate]);
  // 수정 제안은 회색으로 표시하며, 학생이 적용한 코드만 실행·제출한다.
  const fix = useMemo(() => isFull ? quickFix(fullCode, language) : null, [isFull, fullCode, language]);
  const runnable = useMemo(() => isFull ? { code: fullCode, stopLines: {}, unfilled: [] as number[] } : buildRunnable(template, fills), [isFull, fullCode, template, fills]);
  const [resultTab, setResultTab] = useState("실행 결과"); // 처음엔 실행 결과를 보여 주고, 시각화는 탭을 눌러 따로 봐요
  const [vizLine, setVizLine] = useState<VizLine | null>(null);
  // "빈칸 앞까지 실행" 표시는 학생이 직접 실행한 뒤에만 — 문제를 열 때 자동으로 도는 미리보기에는 붙이지 않는다
  const [userRan, setUserRan] = useState(false);
  const [copyRan, setCopyRan] = useState(false);
  const [saved, setSaved] = useState("");
  const { run, stage, execute: runCode, reset: resetRun } = useCodeTrace(language, sectionId);
  const key = `lerny-practice-blanks:${user?.id}:${sectionId}:${planId}`;
  useEffect(() => {
    setFillsByQuiz({}); setSaved(""); resetRun(); setUserRan(false);
    try {
      const value = JSON.parse(sessionStorage.getItem(key) || "{}");
      if (value && typeof value === "object" && !Array.isArray(value)) setFillsByQuiz(value);
    } catch { setSaved("이 탭에서는 답안 저장을 사용할 수 없어요."); }
  }, [key]);
  // 빈칸 앞까지 미리 실행 — Python은 학생 브라우저에서 돌아서 문제를 열자마자, 빈칸을 채울 때마다 바로 보여 줄 수 있다.
  // Java·C는 서버 격리 실행이라 "코드 실행"을 눌렀을 때만 돈다.
  const canPreview = language === "Python";
  const execute = async () => {
    if (!editable || stage) return;
    setUserRan(true);
    await runCode(runnable.code, runnable.stopLines);
  };
  // 빈칸을 채운 뒤(입력 칸을 벗어나거나 Enter) 그 내용으로 다시 돈다 — 타이핑 중에는 돌지 않는다
  const [committed, setCommitted] = useState<{ code: string; stopLines: Record<number, number> } | null>(null);
  const lastAuto = useRef("");
  useEffect(() => {
    if (!editable || !canPreview || !room || stage || (isFull && !committed)) return;
    const target = committed ?? runnable;
    const sig = `${quiz.id}\n${target.code}`;
    if (lastAuto.current === sig) return;
    lastAuto.current = sig;
    void runCode(target.code, target.stopLines);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editable, canPreview, room?.section.id, quiz.id, committed, stage]);
  const fill = (n: number, text: string) => {
    if (isFull ? text.length > 5000 : text.length > 300) { setSaved(isFull ? "코드는 5000자까지 쓸 수 있어요." : "빈칸 하나에는 300자까지 쓸 수 있어요."); return; }
    const next = { ...fillsByQuiz, [quiz.id]: { ...fills, [n]: text } };
    setFillsByQuiz(next);
    try { sessionStorage.setItem(key, JSON.stringify(next)); setSaved("이 탭에 답안 저장됨"); }
    catch { setSaved("답안을 저장하지 못했어요. 내용을 복사해 보관해 주세요."); }
  };
  const filledCount = template.blanks.length - runnable.unfilled.length;
  // 채점 — 학생이 직접 실행한 뒤, 지금 빈칸 내용으로 돈 실행일 때만 맞았는지 틀렸는지 알려 준다
  const rawVerdict = userRan && !stage && run && run.code === runnable.code ? checkBlanks(run, runnable.unfilled, template.blanks, quiz.expected) : null;
  const verdict = rawVerdict && isFull && rawVerdict.kind === "correct" ? { ...rawVerdict, text: "직접 쓴 코드의 출력이 예시와 같아요. 최종 채점은 제출 후 확인해요." } : rawVerdict;
  const badBlanks = verdict && verdict.kind !== "correct" ? verdict.badBlanks : [];
  const [submitting, setSubmitting] = useState(false);
  const [assistBusy, setAssistBusy] = useState(false);
  const requestBusy = useRef(false);
  const [submitError, setSubmitError] = useState("");
  // 채점은 한 번에 한 건만 진행돼요. 다른 유형·다른 문제의 채점이 끝나야 다음 제출을 받을 수 있어요.
  const hasPending =Object.values(justSubmitted).some(a => attemptFor(a.exercise_id)?.status === "pending")
    || !!submissions.data?.items.some(a => a.status === "pending");
  useEffect(() => {
    if (!hasPending) return;
    const timer = setInterval(submissions.reload, 2500);
    return () => clearInterval(timer);
  }, [hasPending, submissions.reload]);
  const logHelp = async (kind: "chat") => {
    try { await api(`/sections/${sectionId}/practice/help`, post({ exercise_id: quiz.id, kind, plan_id: archivePlan })); }
    catch (e) { setSubmitError((e as Error).message); }
  };
  const complete = isFull ? fullCode.trim().length > 0 && fullCode.trim() !== quiz.template.trim() : runnable.unfilled.length === 0;
  const submitFinal = async () => {
    if (!editable || requestBusy.current || assistBusy || hasPending || stage || !complete) return;
    requestBusy.current = true;
    setSubmitting(true); setSubmitError("");
    const source = !isFull && quiz.display_template
      ? buildRunnable(parseTemplate(quiz.template), fills).code : runnable.code;
    try {
      if (!await confirm({ title: "최종 제출할까요?", message: "제출한 코드는 변경할 수 없어요. 제출 후 내 코드를 확인하고 답지를 따라 써 볼 수 있어요.", confirmLabel: "제출하기", cancelLabel: "더 풀어 볼게요" })) return;
      const editor = { template: quiz.template, fills: isFull ? undefined : template.blanks.map(({ n }) => cleanFill(fills[n])) };
      const submitted = await api<PracticeAttempt>(`/sections/${sectionId}/practice/submit`, post({...practiceSubmitBody(quiz.id, source, editor), plan_id: archivePlan}));
      setJustSubmitted(previous => ({ ...previous, [quiz.id]: { ...submitted, source: submitted.source ?? source } }));
      notifyPracticeSubmit();
      submissions.reload();
    } catch (e) { setSubmitError((e as Error).message); submissions.reload(); }
    finally { requestBusy.current = false; setSubmitting(false); }
  };
  const syntaxIssue: SyntaxIssue | null = runnable.unfilled.length === 0 && run?.kind === "syntax" && run.code === runnable.code
    ? { line: run.info.line ?? null, message: run.info.msg, name: run.info.name } : null;
  const resetEditor = () => {
    setCopyRan(false); resetRun(); setCommitted(null); lastAuto.current = ""; setUserRan(false); setVizLine(null);
    setSubmitError(""); setSaved(""); setChatOpen(false); setChatDraft(null);
  };
  const goToQuiz = (index: number) => {
    if (stage || submitting || assistBusy || index < 0 || index >= quizzes.length) return;
    resetEditor(); setResultTab(tab => tab === "내 제출 코드" ? "실행 결과" : tab); setSelectedKind(null); setQuizIndex(index);
  };
  const [finishing, setFinishing] = useState(false);
  const finishQuiz = async () => {
    if (requestBusy.current || stage) return;
    requestBusy.current = true;
    setFinishing(true);
    setSubmitError("");
    try {
      const progress = await api<{ items: { remaining_exercise_ids: string[] }[] }>(
        `/my/practice-progress?session_id=${encodeURIComponent(planId)}`,
      );
      const plan = progress.items[0];
      if (plan) {
        const remaining = quizzes.flatMap((q, index) =>
          plan.remaining_exercise_ids.some(id => belongsToProblem(q, id)) ? [index + 1] : []);
        if (remaining.length && !await confirm({
          title: "아직 제출하지 않은 문제가 있어요",
          message: `${remaining.join("·")}번 문제는 최종 제출하지 않았어요. 퀴즈 목록으로 돌아갈까요?`,
          confirmLabel: "퀴즈 마치기", cancelLabel: "계속 풀기", tone: "warn",
        })) return;
      }
      navigate(back);
    } catch (error) {
      setSubmitError((error as Error).message);
    } finally {
      requestBusy.current = false;
      setFinishing(false);
    }
  };
  // 질문 창 — 지금 문제·빈칸·채점·시각화 위치를 함께 넘겨요
  const [chatOpen, setChatOpen] = useState(false);
  const [chatDraft, setChatDraft] = useState<{ text: string; seq: number } | null>(null);
  const shownViz = resultTab === "시각화" && run?.kind === "ran" && run.code === runnable.code ? vizLine : null;
  // 코드를 실행하면 편집기의 코드 줄마다 바로 위에 설명 주석을 붙인다 (문제 코드는 그대로, 화면에만).
  // 빈칸을 고치면 실행한 코드와 달라지므로 다시 실행할 때까지 숨긴다.

  // 자동수정 안내는 학생이 실행한 뒤에만 — 고칠 곳을 학생이 직접 따라 쓰면 사라져요. 답지를 켜면 답지가 우선이에요.
  const fixShown = isFull && userRan && !!fix?.fixes.length;
  const chatContext = useMemo<PracticeChatContext>(() => ({ exerciseId: quiz.id, number: current + 1, language, title: quiz.title, description: quiz.description, template, fills, verdict, viz: shownViz, week: week ? Number(week) : room.current_week }), [week, language, quiz.id, quiz.title, quiz.description, current, template, fills, verdict, shownViz, room?.current_week]);
  const askAbout = (text: string) => { setChatDraft(d => ({ text, seq: (d?.seq || 0) + 1 })); void logHelp("chat"); setChatOpen(true); };
  return <section className="student-home practice-page">
    {confirmDialog}
    <Link className="cr-back" to={back}>← {week ? `${week}주차 퀴즈` : "퀴즈 목록"}</Link>
    <div className="practice-heading"><div><h1>{week ? `${week}주차 실습 퀴즈` : "오늘의 실습"}</h1><p>{room?.course.title.split(/\s+[—–]\s+/)[0] || "실습"}{room ? ` · ${room.section.title}` : ""} · 수업 언어 {language}</p></div><div className="practice-heading-side"><span className="practice-draft-note">수업에 지정된 언어로 실습을 진행해요.</span></div></div>
    <ErrorNotice text={submitError || submissions.error} />
    {submissions.error && <button onClick={submissions.reload}>제출 기록 다시 불러오기</button>}
    <>
    {/* 화면 배치: 왼쪽 한 칸에 문제 → 힌트 → 코드, 오른쪽에 문제 이동 버튼 → 실행 결과·시각화 (문제 번호는 왼쪽 칸 위 책갈피 탭) */}
    <div className="practice-layout is-split">
      <div className="practice-left">
        <section className="practice-card">
          <div className="practice-tabbar">
            <div className="practice-num-tabs" role="group" aria-label={week ? "주차 실습 문제" : "오늘의 문제"}>{quizzes.map((q, i) => <button key={q.problem_id ?? q.id} type="button" disabled={!!stage || submitting || assistBusy} aria-pressed={i === current} title={q.title} onClick={() => goToQuiz(i)}>문제 {i + 1}{submittedAny(q) && <span aria-label="제출 완료"> ✓</span>}</button>)}</div>
            <div className="practice-types" aria-label="일일 실습 구성"><span className="practice-types__count">{week ? "주차 전체" : "하루"} {quizzes.length}문제</span><div className="material-week-split practice-type-picker" role="group" aria-label="현재 문제의 실습 유형">
              {kinds.map(kind => {
                // 한 유형을 제출해도 다른 유형은 잠기지 않아요. 제출한 유형에만 ✓를 붙여요.
                const done = !!variantAttempt(problem, kind);
                return <button key={kind} type="button" aria-pressed={shownKind === kind}
                  disabled={submitting || assistBusy || !!stage}
                  onClick={() => { if (kind !== shownKind) { resetEditor(); setResultTab(tab => tab === "내 제출 코드" ? "실행 결과" : tab); setSelectedKind(kind); } }}>
                  {done && <svg className="practice-type-status" role="img"
                    aria-label="제출 완료" width="13" height="13" viewBox="0 0 24 24"
                    fill="none" stroke="currentColor" strokeWidth="2.7" strokeLinecap="round" strokeLinejoin="round">
                    <path d="m5 12 4 4L19 6" />
                  </svg>}
                  {kind === "blank" ? "빈칸 채우기" : "전체 구현"}
                </button>;
              })}
            </div></div>
          </div>
          <div className="practice-q-head">
            <h2>문제{current + 1}. {quiz.title}</h2>
          </div>
          <div className="practice-problem-description"><LearningText text={quiz.description} /></div>
          {!!quiz.requirements?.length && <ul className="practice-requirements">{quiz.requirements.map((text, i) => <li key={i}>{text}</li>)}</ul>}
          {quiz.helpers_guide_text
            ? <div className="practice-problem-description"><LearningText text={quiz.helpers_guide_text} /></div>
            : !!quiz.available_helpers?.length && <p className="muted">사용 가능한 도구: {quiz.available_helpers.join(", ")}</p>}
          {quiz.example_input && <div className="practice-example"><div><h4>예시 입력 선언</h4><pre><code>{quiz.example_input}</code></pre></div></div>}
          {latest ? <>
            <PracticeAnswerCopy key={latest.id} sectionId={sectionId} planId={archivePlan}
              exerciseId={latest.exercise_id} starter={displayTemplate} isFull={isFull} language={language}
              submittedSource={replaySource} running={!!stage} onRun={(code, stopLines) => {
                setCopyRan(true);
                setResultTab("실행 결과");
                void runCode(code, stopLines);
              }} />
          </> : editable ? <>
          <details className="practice-hint-drawer" key={quiz.id}><summary>막힐 때 단계별 힌트 보기</summary><PracticeHints planId={archivePlan} sectionId={sectionId} exerciseId={quiz.id} onBusyChange={setAssistBusy} /></details>
          <section className="practice-editor-panel" aria-labelledby="practice-editor-title">
            <div className="practice-editor-toolbar">
              <div className="practice-editor-title"><h2 id="practice-editor-title">{isFull ? "코드 작성" : "빈칸 채우기"}</h2><PracticeGuide full={isFull} /></div>
              <div className="practice-editor-actions practice-editor-buttons">
                <button type="button" onClick={execute} disabled={!!stage || submitting || (!canPreview && runnable.unfilled.length > 0)}>{stage ? "실행 중…" : "코드 실행"}</button>
                <button type="button" className="primary" disabled={!complete || !!stage || hasPending || submitting || assistBusy || !submissions.data} onClick={() => void submitFinal()}>{submitting ? "제출 중…" : hasPending ? "채점 기다리는 중…" : <>최종 제출 <span className="go-arrow" aria-hidden="true">→</span></>}</button>
              </div>
            </div>
            <p id="practice-answer-rule" className="practice-answer-rule">{kinds.length > 1 ? "빈칸 채우기와 전체 구현은 각각 한 번씩 최종 제출할 수 있어요." : "한 번만 최종 제출할 수 있어요."} 제출 후 답지를 따라 써 볼 수 있어요.</p>
  <div className="practice-file-bar"><span>{language === "Python" ? "main.py" : language === "Java" ? "Main.java" : "main.c"}</span><span aria-live="polite">{saved || (isFull ? `${fullCode.split("\n").length}줄` : `빈칸 ${filledCount}/${template.blanks.length} 채움`)}</span></div>
  
            {isFull ? <CodeEditor value={fullCode} onChange={v => fill(0, v)} onCommit={() => { setUserRan(true); setCommitted({ code: runnable.code, stopLines: {} }); }} ghost={fixShown ? fix!.code : undefined} fixes={fixShown ? fix!.fixes : undefined} vizLine={shownViz} label={`${language} 코드 작성`} syntax={syntaxIssue} /> : <BlankEditor template={template} fills={fills} onFill={fill} onCommit={() => { setUserRan(true); setCommitted({ code: runnable.code, stopLines: runnable.stopLines }); }} stopBlank={userRan && resultTab === "시각화" && vizLine?.kind === "blank" && run?.kind === "ran" && run.code === runnable.code ? run.blankStop?.blank : undefined} vizLine={shownViz} badBlanks={badBlanks} syntax={syntaxIssue} />}
            {syntaxIssue && <p className="practice-syntax-note" role="status"><b>✕ {syntaxIssue.line ? `${syntaxIssue.line}번째 줄` : "문법"}</b> {syntaxIssue.message} <span>· 문법 오류는 시도 횟수에 들어가지 않아요</span></p>}
            {fixShown && <button type="button" disabled={!!stage || submitting} onClick={() => { fill(0, fix!.code); resetRun(); setCommitted(null); setUserRan(false); }}>수정안 적용하기</button>}
            <div id="practice-vartable-slot" className="practice-vartable-slot" />
            <p className="practice-editor-note">{isFull ? "코드를 다 쓴 뒤 '코드 실행'을 누르면 예시 출력을 비교해요. 최종 채점은 제출 후 확인해요." : canPreview ? "빈칸을 채우고 Enter를 누르면 다음 빈칸 앞까지 바로 실행돼요." : "빈칸을 모두 채운 뒤 실행할 수 있어요."}</p>
          </section>
          </> : !submissions.error && <p role="status">제출 기록을 불러오는 중이에요.</p>}
        </section>
      </div>
      <div className="practice-right">
        <nav className="practice-quiz-nav" aria-label="문제 이동">
          <button type="button" onClick={() => goToQuiz(current - 1)} disabled={current <= 0}>← 이전 문제</button>
          <span className="practice-quiz-nav__count">{current + 1} / {quizzes.length}</span>
          {current < quizzes.length - 1
            ? <button type="button" className="practice-quiz-nav__go" onClick={() => goToQuiz(current + 1)}>다음 문제 →</button>
            : <button type="button" className="practice-quiz-nav__go practice-quiz-nav__finish" disabled={finishing || submitting || !!stage} onClick={() => void finishQuiz()}>퀴즈 마침 ✓</button>}
        </nav>

        {latest && <Notice><span><strong>마지막 제출 결과 · </strong>{latest.status === "pending" ? "답안을 저장했고 격리 환경에서 검증 중이에요." : latest.feedback?.message || "제출 결과를 확인하고 있어요."}
          {latest.feedback?.total != null && ` (${latest.feedback.passed}/${latest.feedback.total})`}
          {!latest.independent && " · 도움을 받은 풀이"}
          {latest.status === "held" && latest.job_id && <button onClick={async () => { try { await api(`/jobs/${latest.job_id}/retry`, post({})); submissions.reload(); } catch (e) { setSubmitError((e as Error).message); } }}>검증 다시 시도</button>}
          </span>
          <Link className="practice-submission-history" to={`/classrooms/${sectionId}/practice/results?plan=${encodeURIComponent(planId)}${week ? "&week="+week : ""}`}>
            <span>제출 기록 보기</span><span aria-hidden="true">→</span>
          </Link>
        </Notice>}
        {(editable || latest) && <section className="practice-output-panel"><div className="practice-output-tabs" role="tablist" aria-label="결과 보기">{(latest ? ["내 제출 코드", "실행 결과", "시각화"] : ["실행 결과", "시각화"]).map(t => <button role="tab" id={`practice-tab-${t}`} aria-selected={resultTab === t} aria-controls="practice-output" key={t} onClick={() => setResultTab(t)}>{t}</button>)}</div>
          <div id="practice-output" role="tabpanel" aria-labelledby={`practice-tab-${resultTab}`} aria-live="polite" className="practice-output-body">
            {latest && resultTab === "내 제출 코드" && <section className="practice-explanation" aria-label="내 제출 코드">
              <SubmittedCode source={latest.source ?? ""} snapshot={latest.submission_snapshot} />
            </section>}
            {resultTab !== "내 제출 코드" && <VizLineContext.Provider value={setVizLine}><PracticeOutput tab={resultTab} run={run} stage={stage} code={copyRan ? run?.code ?? "" : runnable.code} incomplete={!copyRan && runnable.unfilled.length > 0} blankLines={template.blanks} fixes={!copyRan && fixShown ? fix!.fixes : undefined} /></VizLineContext.Provider>}
            {resultTab === "시각화" && replaySource && !stage && (run?.kind !== "ran" || !run.trace) &&
              <div className="practice-run">
                <button type="button" onClick={() => {
                  setCopyRan(true);
                  void runCode(replaySource);
                }}>제출 코드로 시각화 보기</button>
              </div>}
            {resultTab === "실행 결과" && <div className="practice-expected"><span>예시 출력</span><code>{quiz.expected || "(출력 없음)"}</code></div>}
          </div>
          {editable && verdict && resultTab === "실행 결과" && <div className={`blank-verdict is-${verdict.kind === "correct" ? "correct" : "wrong"} `} role={verdict.kind === "correct" ? "status" : "alert"}>
            <strong><span aria-hidden="true">{verdict.kind === "correct" ? "✓" : "✕"}</span> {verdict.title}</strong>
            <p>{verdict.text}{verdict.kind === "syntax" && " 문법 오류는 시도 횟수에 들어가지 않아요."}</p>
            {verdict.kind === "wrong" && <dl className="blank-verdict__cmp"><div><dt>출력 값</dt><dd><code>{verdict.expected}</code></dd></div><div><dt>내 출력</dt><dd><code>{verdict.actual}</code></dd></div></dl>}
            {verdict.kind !== "correct" && <button type="button" className="blank-verdict__ask" onClick={() => askAbout(verdict.kind === "syntax" ? (verdict.badBlanks.length ? `빈칸 ${verdict.badBlanks.map(circled).join("·")}에 쓴 코드가 왜 문법에 맞지 않나요?` : "코드가 왜 문법에 맞지 않는지 알려 주세요.") : verdict.kind === "runtime" ? "실행 중에 오류가 난 이유가 궁금해요." : verdict.kind === "endless" ? "반복이 끝나지 않는 이유가 뭘까요?" : "실행은 됐는데 결과가 왜 기대와 다르게 나왔나요?")}>이 결과에 대해 질문하기 →</button>}
          </div>}</section>}
      </div>
    </div><p className="practice-mobile-note">실습 코드 작성은 넓은 데스크톱 화면에서 이용하면 더 편리해요.</p>
    {editable && <><PracticeChat planId={archivePlan} key={`${sectionId}:${quiz.id}`} sectionId={sectionId} courseId={room.course.id} open={chatOpen} onClose={() => setChatOpen(false)} context={chatContext} draftRequest={chatDraft} />
    {/* 질문 창은 오른쪽 아래 둥근 아이콘으로 열고 닫아요 — 지금 문제·코드·채점 상황은 그대로 함께 보내요 */}
    <button type="button" className={`practice-chat-fab ${chatOpen ? "is-open" : ""}`} onClick={() => setChatOpen(v => !v)} aria-expanded={chatOpen} aria-label={chatOpen ? "질문 창 닫기" : "이 문제 질문하기"}>
      {chatOpen ? <svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" /></svg>
        : <svg viewBox="0 0 24 24" width="26" height="26" aria-hidden="true"><path d="M4 5.5A2.5 2.5 0 0 1 6.5 3h11A2.5 2.5 0 0 1 20 5.5v8a2.5 2.5 0 0 1-2.5 2.5H10l-4.2 3.6c-.5.4-1.3.1-1.3-.6V16A2.5 2.5 0 0 1 4 13.5z" fill="currentColor" /><circle cx="8.5" cy="9.6" r="1.1" fill="var(--fab-dot, #fff)" /><circle cx="12" cy="9.6" r="1.1" fill="var(--fab-dot, #fff)" /><circle cx="15.5" cy="9.6" r="1.1" fill="var(--fab-dot, #fff)" /></svg>}
      <span className="practice-chat-fab__label" aria-hidden="true">이 문제 질문하기</span>
    </button></>}</>
  </section>;
}

/** 진행 방법 — 편집기 제목 옆 '?'를 누르면 말풍선으로 떠요. 바깥을 누르거나 Esc로 닫아요 */
function PracticeGuide({ full }: { full: boolean }) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false); };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", onDown); document.removeEventListener("keydown", onKey); };
  }, [open]);
  return <span className="practice-help" ref={box}>
    <button type="button" className="practice-help__btn" aria-expanded={open} aria-controls="practice-help-pop" aria-label={full ? "직접 작성 실습 진행 방법" : "빈칸 실습 진행 방법"} onClick={() => setOpen(v => !v)}>?</button>
    {open && <div id="practice-help-pop" className="practice-help__pop" role="dialog" aria-label="진행 방법">
      <strong>{full ? "직접 작성 실습은 이렇게 진행해요" : "빈칸 실습은 이렇게 진행해요"}</strong>
      {full ? <ol><li>시작 코드 아래에 필요한 코드를 처음부터 써요.</li><li>'코드 실행'으로 예시 출력과 비교해요. 최종 채점은 '최종 제출' 후 여러 입력으로 진행해요.</li><li>막히면 시각화로 값이 어떻게 바뀌는지 한 줄씩 따라가 봐요.</li><li>최종 제출이 저장되면 답지·해설에서 모범 코드와 비교할 수 있어요.</li></ol>
        : <ol><li>먼저 시각화로 빈칸 앞까지 코드가 어떻게 움직이는지 봐요.</li><li>멈춘 장면의 값을 보고 빈칸 {circled(1)}부터 채워요.</li><li>채우면 다음 빈칸 앞까지 이어서 실행돼요. 모두 채우면 끝까지 실행돼요.</li><li>'최종 제출'로 답안을 저장한 뒤 채점 결과와 답지·해설을 확인해요.</li></ol>}
    </div>}
  </span>;
}

/* 빈칸 채우기 편집기 — 문제 코드는 읽기만 하고, 빈칸 자리에만 입력 칸이 있다 */
/** 직접 작성(풀코딩) 편집기 — 줄 번호, Tab 들여쓰기, 답지는 같은 자리에 회색 글씨로 깔아 따라 쓰게 해요 */
/** 실행 전 자동수정 안내 배너 — 몇 군데를 고쳤는지, 줄마다 무엇을 붙였는지 */
function FixBanner({ fixes }: { fixes: QuickFix[] }) {
  return <div className="quick-fix-banner" role="status">
    <div className="quick-fix-banner__head">
      <span className="quick-fix-banner__icon" aria-hidden="true"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18l3 3 6.3-6.3a4 4 0 0 0 5.4-5.4l-2.5 2.5-2.4-.6-.6-2.4 2.5-2.5Z" /></svg></span>
      <strong>문법 수정 제안 {fixes.length}곳을 찾았어요</strong>
      <small>회색 글씨를 확인하고 직접 고치거나 수정안을 적용해 주세요. 실행·제출에는 작성한 코드가 사용돼요.</small>
    </div>
    <ul>{fixes.map(f => <li key={f.line}><b>{f.line}번째 줄</b><code>{f.add}</code><span>{f.message}</span></li>)}</ul>
  </div>;
}

function PracticeAnswerCopy({ sectionId, planId, exerciseId, starter, isFull, language, submittedSource, running, onRun }: {
  sectionId: string;
  planId?: string;
  exerciseId: string;
  starter: string;
  isFull: boolean;
  language: Language;
  submittedSource?: string;
  running: boolean;
  onRun: (code: string, stopLines: Record<number, number>) => void;
}) {
  const [showAnswer, setShowAnswer] = useState(true);
  const [answer, setAnswer] = useState<{ answers: string[]; explanation?: { blank_comments?: Record<string, string> } }>();
  const answers = answer?.answers;
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  const [copyCode, setCopyCode] = useState(starter);
  const [copyFills, setCopyFills] = useState<Record<number, string>>({});
  const template = useMemo(() => parseTemplate(isFull ? "" : starter), [isFull, starter]);
  useEffect(() => {
    let active = true;
    setError("");
    api<NonNullable<typeof answer>>(`/sections/${sectionId}/practice/help`, post({
      exercise_id: exerciseId, plan_id: planId, kind: "answer",
    })).then(result => {
      if (!active) return;
      if (!result.answers?.length) throw new Error("표시할 답지를 아직 불러오지 못했어요.");
      setAnswer(result);
    }).catch(cause => {
      if (active) setError((cause as Error).message);
    });
    return () => { active = false; };
  }, [sectionId, planId, exerciseId, retry]);

  const blankRun = buildRunnable(template, copyFills);
  const practiceSource = isFull
    ? (copyCode.trim() && copyCode !== starter ? copyCode : undefined)
    : (blankRun.unfilled.length === 0 ? blankRun.code : undefined);
  const runnableSource = practiceSource ?? submittedSource;
  const fileName = language === "Python" ? "main.py" : language === "Java" ? "Main.java" : "main.c";
  const comments = showAnswer && answers && !isFull ? template.lines.map(parts => {
    const notes = parts.flatMap(part => typeof part === "string" ? [] : [answer?.explanation?.blank_comments?.[part.blank]]);
    if (notes.length) return [...new Set(notes.filter(Boolean))].join(" · ") || null;
    const code = parts.join("");
    if (/^\s*(#|\/\/)/.test(code)) return null;
    return lineComment(code) || null;
  }) : undefined;

  return <section className="practice-editor-panel" aria-label="답지 따라쓰기">
    <div className="practice-editor-toolbar">
      <div className="practice-editor-title"><h2>{isFull ? "코드 작성" : "빈칸 채우기"}</h2><PracticeGuide full={isFull} /></div>
      <div className="practice-editor-actions practice-editor-buttons">
        <span className="practice-answer-wrap">
          <button type="button" aria-describedby="submitted-practice-answer-tip"
            aria-pressed={showAnswer && !!answers} disabled={!answers}
            onClick={() => setShowAnswer(value => !value)}>
            {showAnswer && answers ? "답지 숨기기" : "답지 보기"}
          </button>
          <span id="submitted-practice-answer-tip" className="practice-answer-tip" role="tooltip">
            최종 제출을 마쳤어요. 회색 답지를 켜고 끌 수 있어요.
          </span>
        </span>
        <button type="button" disabled={running || !runnableSource?.trim()}
          onClick={() => { if (runnableSource) onRun(runnableSource, {}); }}>
          {running ? "실행 중…" : "코드 실행"}
        </button>
        <button type="button" className="primary" disabled>제출 완료 ✓</button>
      </div>
    </div>
    <div className="practice-file-bar">
      <span>{fileName}</span>
      <span>{isFull ? `${copyCode.split("\n").length}줄` : `빈칸 ${template.blanks.length - blankRun.unfilled.length}/${template.blanks.length} 채움`}</span>
    </div>
    {error ? <>
      <ErrorNotice text={error} />
      <button type="button" onClick={() => setRetry(value => value + 1)}>답지 다시 불러오기</button>
    </> : !answers && <p className="practice-answer-rule" role="status">답지를 불러오는 중이에요…</p>}
    {isFull
      ? <CodeEditor value={copyCode} onChange={setCopyCode} onCommit={() => {}}
          ghost={showAnswer ? answers?.[0] : undefined} label={`${language} 답지 따라쓰기`} />
      : <BlankEditor template={template} fills={copyFills}
          onFill={(index, value) => setCopyFills(previous => ({ ...previous, [index]: value }))}
          onCommit={() => {}} comments={comments} commentMark={language === "Python" ? "#" : "//"}
          ghosts={showAnswer && answers ? Object.fromEntries(answers.map((answer, index) => [index + 1, answer])) : undefined} />}
    <p className="practice-editor-note">회색 글씨를 따라 쓰면 친 만큼 지워져요. 답지 글씨는 복사할 수 없어요.</p>
  </section>;
}

function CodeEditor({ value, onChange, onCommit, ghost, fixes, vizLine, label, syntax }: { value: string; onChange: (v: string) => void; onCommit: () => void; ghost?: string; /** 실행 전 자동수정한 줄 — 빨간색으로 표시해요 (이때 ghost는 고친 코드) */ fixes?: QuickFix[]; vizLine?: VizLine | null; label: string; syntax?: SyntaxIssue | null }) {
  const lines = Math.max(value.split("\n").length, ghost ? ghost.split("\n").length : 0, 8);
  const textLines = value.split("\n");
  const fixed = new Map((fixes || []).map(f => [f.line, f]));
  return <div className={`code-editor ${ghost ? "has-ghost" : ""} ${fixes?.length ? "has-fix" : ""}`}>
    <ol className="code-editor__ln" aria-hidden="true">{Array.from({ length: lines }, (_, i) => <li key={i} className={`${vizLine?.line === i + 1 ? `is-viz is-viz-${vizLine.kind}` : ""} ${syntax?.line === i + 1 ? "is-syntax" : ""} ${fixed.has(i + 1) ? "is-fixed" : ""}`}>{i + 1}</li>)}</ol>
    <div className="code-editor__body" style={{ height: `calc(${lines} * 1.9em + 24px)` }}>
      {/* 회색 따라쓰기: 학생이 친 글자는 투명하게 자리만 차지하고, 남은 글씨만 회색으로 보여요. 선택·복사·클릭이 안 돼요. */}
      {ghost && <pre className="code-editor__ghost" aria-hidden="true" onCopy={e => e.preventDefault()}>{ghostLines(ghost, value).map((g, i) => <span key={i} className={`code-editor__ghost-line ${g.matched ? "" : "is-miss"}`}><span className="ghost-typed">{g.typed}</span>{g.rest}{"\n"}</span>)}</pre>}
      {/* 자동수정한 줄: 줄 전체를 연한 빨간 바탕 + 빨간 밑줄로 표시해요 (글씨는 투명, 자리만) */}
      {fixed.size > 0 && <pre className="code-editor__fixes" aria-hidden="true">{textLines.map((t, i) => { const f = fixed.get(i + 1); return <span key={i}>{f ? <span className="fix-line" title={f.message}>{t}<span className="fix-add">{f.add}</span></span> : <span className="ghost-typed">{t}</span>}{"\n"}</span>; })}</pre>}
      {/* 문법 오류 줄에 빨간 물결 밑줄 */}
      {syntax?.line && <pre className="code-editor__syntax" aria-hidden="true">{textLines.map((t, i) => <span key={i}>{i + 1 === syntax.line ? <span className="syntax-squiggle" title={syntax.message}>{t || " "}</span> : <span className="ghost-typed">{t}</span>}{"\n"}</span>)}</pre>}
      <textarea className="code-editor__input" value={value} aria-label={label} spellCheck={false} autoCapitalize="none" autoComplete="off" wrap="off"
        onChange={e => onChange(e.target.value)} onBlur={onCommit}
        onKeyDown={e => {
          if (e.key !== "Tab") return;
          e.preventDefault();
          const t = e.currentTarget, a = t.selectionStart, b = t.selectionEnd;
          onChange(value.slice(0, a) + "    " + value.slice(b));
          requestAnimationFrame(() => { t.selectionStart = t.selectionEnd = a + 4; });
        }} />
    </div>
  </div>;
}

function BlankEditor({ template, fills, onFill, onCommit, stopBlank, vizLine, badBlanks = [], ghosts, syntax, comments, commentMark = "#" }: { template: BlankTemplate; fills: Record<number, string>; onFill: (n: number, text: string) => void; onCommit: () => void; stopBlank?: number; vizLine?: VizLine | null; badBlanks?: number[]; ghosts?: Record<number, string>; syntax?: SyntaxIssue | null; comments?: (string | null)[] | null; commentMark?: string }) {
  // 시각화가 보여 주는 줄이 편집기 밖으로 나가면 편집기 안에서만 스크롤한다 (페이지는 움직이지 않는다)
  const box = useRef<HTMLOListElement>(null);
  useEffect(() => {
    const ol = box.current; const li = ol?.querySelector<HTMLElement>("li.is-viz");
    if (!ol || !li) return;
    if (li.offsetTop < ol.scrollTop || li.offsetTop + li.offsetHeight > ol.scrollTop + ol.clientHeight) ol.scrollTop = li.offsetTop - ol.clientHeight / 3;
  }, [vizLine?.line]);
  return <ol className="blank-editor" ref={box} aria-label="빈칸이 있는 코드">
    {template.lines.map((parts, i) => { const viz = vizLine?.line === i + 1 ? vizLine : null; const stop = parts.some(p => typeof p !== "string" && p.blank === stopBlank); const bad = syntax?.line === i + 1; const note = comments?.[i]; const indent = typeof parts[0] === "string" ? parts[0].match(/^[ \t]*/)?.[0] ?? "" : ""; const lead = indent.replace(/\t/g, "    ").length; return [note && <li key={`c${i}`} className={`blank-editor__cmt ${viz ? `is-viz-${viz.kind}` : ""}`} aria-label={`${i + 1}번째 줄 설명`}>
      <span className="blank-editor__ln" aria-hidden="true" />
      <span className="blank-editor__cmt-text" style={{ paddingLeft: `${lead}ch` }}><span aria-hidden="true">{commentMark} </span>{note}</span>
    </li>, <li key={i} className={`${stop ? "is-stop" : ""} ${viz ? `is-viz is-viz-${viz.kind}` : ""} ${bad ? "is-syntax" : ""}`} aria-current={viz ? "step" : undefined} title={bad ? syntax!.message : undefined}>
      <span className="blank-editor__ln" aria-hidden="true">{i + 1}</span>
      <code className="blank-editor__line" style={{ paddingInlineStart: `min(${lead}ch, 35%)` }}>{parts.map((p, k) => typeof p === "string" ? <span key={k}>{k === 0 ? p.slice(indent.length) : p}</span> : <label key={k} style={{ width: `calc(${Math.max(6, (fills[p.blank] || "").length + 2, (ghosts?.[p.blank] || "").length + 2)}ch + 1.5em)` }} className={`blank-editor__slot ${cleanFill(fills[p.blank]) ? "is-filled" : ""} ${badBlanks.includes(p.blank) ? "is-bad" : ""} ${ghosts?.[p.blank] ? "has-ghost" : ""}`}>
        <span className="blank-editor__num" aria-hidden="true">{circled(p.blank)}</span>
        <textarea rows={1} className="blank-editor__input" value={fills[p.blank] || ""} aria-label={`빈칸 ${p.blank}`} spellCheck={false} autoCapitalize="none" autoComplete="off"
          onChange={e => onFill(p.blank, e.target.value.replace(/\r?\n/g, " "))}
          onBlur={onCommit}
          onKeyDown={e => { if (e.key === "Enter" && !isComposingInput(e.nativeEvent)) { e.preventDefault(); onCommit(); } }} />
        <span className="blank-editor__measure" aria-hidden="true">{fills[p.blank] || " "}</span>
        {ghosts?.[p.blank] && (() => { const g = ghostRest(ghosts[p.blank], fills[p.blank] || ""); return <span className={`blank-editor__ghost ${g.matched ? "" : "is-miss"}`} aria-hidden="true" onCopy={e => e.preventDefault()}><span className="ghost-typed">{g.typed}</span>{g.rest}</span>; })()}
      </label>)}{parts.length === 1 && parts[0] === "" ? " " : null}</code>
      {stop ? <span className="blank-editor__stop">빈칸 앞까지 실행</span> : viz ? <span className={`blank-editor__viz is-${viz.kind}`}>{viz.kind === "error" ? "✕ 오류" : viz.kind === "ran" ? "✓ 방금 실행" : "▶ 시각화 중"}</span> : null}
    </li>]; })}
  </ol>;
}

export function PracticeResults() {
  const { sectionId = "" } = useParams();
  const [params] = useSearchParams();
  const plan = params.get("plan");
  const week = params.get("week");
  const result = useLoad<{ items: PracticeAttempt[] }>(`/sections/${sectionId}/practice/attempts${plan ? "?plan_id="+encodeURIComponent(plan)+"&by_exercise=true" : ""}`);
  const rows = result.data?.items || [];
  const [selected, setSelected] = useState("");
  const current = rows.find(r => r.id === selected) || rows[0];
  const [tab, setTab] = useState("테스트 결과");
  useEffect(() => {
    if (!rows.some(r => r.status === "pending")) return;
    const timer = setInterval(result.reload, 3000);
    return () => clearInterval(timer);
  }, [result.data, result.reload]);
  return <section className="student-home practice-results-page">
    <Link className="cr-back" to={week ? archivePath(sectionId, week) : `/quiz?section=${sectionId}`}>← 퀴즈 목록</Link>
    <div className="result-titlebar"><h1>실습 결과와 복습</h1><p className="result-intro">제출한 코드와 검증 결과를 다시 확인하세요.</p></div>
    <ErrorNotice text={result.error} />
    <section className="practice-result-summary"><h2>{week ? `${week}주차 실습 제출 기록` : plan ? "오늘 배정된 실습 제출 기록" : "내 실습 제출 기록"}</h2>
      <div className="practice-result-metrics"><div><span>제출한 답안</span><strong>{rows.length}</strong></div><div><span>검증 통과</span><strong>{rows.filter(r => r.correct).length}</strong></div><div><span>검증 대기·보류</span><strong>{rows.filter(r => r.status !== "graded").length}</strong></div></div>
    </section>
    {!rows.length && <Notice>{result.data ? "아직 최종 제출한 실습이 없어요." : "제출 기록을 불러오는 중이에요."}</Notice>}
    <div className="practice-result-grid"><section className="practice-result-card"><h2>문항별 제출 결과</h2>
      {rows.map(r => <button key={r.id} aria-pressed={current?.id === r.id} onClick={() => setSelected(r.id)}>{r.exercise && <b>{practiceKindLabel(r.exercise.kind)}</b>}{r.exercise?.title || "자료가 변경된 실습"} · {r.status === "graded" ? r.correct ? "검증 통과" : "복습 필요" : "검증 대기·보류"}<small>{new Date(r.created_at).toLocaleString("ko-KR")}</small></button>)}
    </section><section className="practice-result-card">
      <div className="practice-output-tabs">{["테스트 결과", "제출 코드", "답지·해설"].map(t => <button key={t} aria-pressed={tab === t} onClick={() => setTab(t)}>{t}</button>)}</div>
      {current && (tab === "답지·해설" ? <PracticeAttemptReview key={current.id} sectionId={sectionId} attemptId={current.id} /> : tab === "제출 코드" ? <SubmittedCode source={current.source ?? ""} snapshot={current.submission_snapshot} /> : <><h3>{current.feedback?.message || "격리 실행 결과를 기다리고 있어요."}</h3><p>{current.feedback?.total != null && `${current.feedback.passed}/${current.feedback.total}개 입력 검증 통과`}</p><p>{current.independent ? "독립적으로 제출한 풀이" : "도움을 받은 풀이"}</p></>)}
    </section></div><div className="practice-results-actions"><Link className="ln-cta" to={`/classrooms/${sectionId}/practice${week ? "?week="+week : ""}`}>실습 풀이로 이동 <span aria-hidden="true">→</span></Link></div>
  </section>;
}
