import { VanishPlaceholder } from "./VanishPlaceholder";
import { useAutosizeTextarea } from "./useAutosizeTextarea";
import { isComposingInput } from "./inputKeyboard";
import { TutorFeedback } from "./TutorFeedback";
import { chatPollState, practiceChatBody } from "./learningRequests";
// 실습 퀴즈 옆에서 바로 여는 질문 창 — 지금 푸는 문제·빈칸·채점 결과·시각화 위치를 함께 보내요.
// 답변은 AI 질문 화면과 같은 방식(공개 강의 자료의 원문 근거)으로 오고, 같은 질문 기록에 쌓여요.
// 정답 코드는 보내지도 받지도 않아요: 함께 보내는 건 학생이 쓴 내용과 화면에 이미 보이는 정보뿐이에요.
import { useEffect, useMemo, useRef, useState } from "react";
import { ChatFeedback, type FeedbackValue } from "./ChatFeedback";
import { TypedAnswer } from "./TypedAnswer";
import { api, post, type Answer, type Job } from "./api";
import { ChatCitation, useStudentHandouts } from "./ChatCitation";
import type { BlankVerdict } from "./visualizer/blankCheck";
import { circled, cleanFill, type BlankTemplate } from "./visualizer/blanks";
import { VIZ_LINE_WORD, type VizLine } from "./visualization/vizLine";

export type PracticeChatContext = {
  number?: number;
  exerciseId: string;
  language: string;
  title: string;
  description: string;
  template: BlankTemplate;
  fills: Record<number, string>;
  verdict: BlankVerdict | null;
  /** 시각화가 지금 짚고 있는 줄 (시각화 탭에서 지금 코드로 실행했을 때만) */
  viz: VizLine | null;
  /** 몇 주차 실습인지 — 질문 이력 책갈피에 보여 줘요 */
  week?: number | null;
  /** 지금 푸는 실습 문제 id — 튜터 피드백 기록에 함께 보내요 */
  quizId?: string;
};

/** 빈칸 자리에 학생이 쓴 내용을 넣은 코드 한 줄 — 비어 있으면 ［빈칸 ①］ */
function lineText(ctx: PracticeChatContext, line: number) {
  const parts = ctx.template.lines[line - 1] || [];
  return parts.map(p => typeof p === "string" ? p : cleanFill(ctx.fills[p.blank]) ? `［${circled(p.blank)} ${cleanFill(ctx.fills[p.blank])}］` : `［빈칸 ${circled(p.blank)}］`).join("");
}

const blankNames = (ns: number[]) => ns.map(circled).join("·");

/** 서버로 함께 보내는 풀이 상황 — 사람이 읽어도 알 수 있는 짧은 글 */
export function practiceContextText(ctx: PracticeChatContext) {
  const filled = ctx.template.blanks.filter(b => cleanFill(ctx.fills[b.n])).length;
  const code = ctx.template.lines.map((_, i) => `${i + 1}| ${lineText(ctx, i + 1)}`).join("\n");
  const lines = [
    `실습 문제: ${ctx.title} (${ctx.language})`,
    `문제 설명: ${ctx.description}`,
    ctx.template.blanks.length ? `빈칸: ${ctx.template.blanks.length}개 중 ${filled}개 채움` : "문제 유형: 직접 작성 (학생이 코드를 처음부터 씀)",
    `학생 코드:\n${code}`,
  ];
  if (ctx.verdict) lines.push(`채점 결과: ${ctx.verdict.title}${ctx.verdict.kind === "wrong" ? ` (기대 출력 ${ctx.verdict.expected} / 학생 출력 ${ctx.verdict.actual})` : ""}`);
  if (ctx.viz) lines.push(`시각화 위치: ${ctx.viz.step}/${ctx.viz.total}단계, ${ctx.viz.line}번째 줄 ${VIZ_LINE_WORD[ctx.viz.kind]} — ${lineText(ctx, ctx.viz.line).trim()}`);
  return lines.join("\n").slice(0, 3000);
}

/** 지금 상황에 맞는 질문 예시 — 누르면 질문 칸에 적혀요 (바로 보내지는 않아요) */
export function suggestedQuestions(ctx: PracticeChatContext): string[] {
  const out: string[] = [];
  const v = ctx.verdict;
  if (v?.kind === "syntax") out.push(v.badBlanks.length ? `빈칸 ${blankNames(v.badBlanks)}에 쓴 코드가 왜 문법에 맞지 않나요?` : "코드가 왜 문법에 맞지 않는지 알려 주세요.");
  else if (v?.kind === "runtime") out.push(v.badBlanks.length ? `빈칸 ${blankNames(v.badBlanks)}이 있는 줄에서 왜 오류가 났나요?` : "실행 중에 오류가 난 이유가 궁금해요.");
  else if (v?.kind === "wrong") out.push("실행은 됐는데 결과가 왜 기대와 다르게 나왔나요?");
  else if (v?.kind === "endless") out.push("반복이 끝나지 않는 이유가 뭘까요?");
  else if (v?.kind === "correct") out.push("제 풀이가 왜 맞는지 개념으로 설명해 주세요.");
  if (ctx.viz?.kind === "blank") {
    const b = ctx.template.blanks.find(x => x.line === ctx.viz!.line);
    if (b) out.push(`빈칸 ${circled(b.n)}에는 어떤 개념을 써야 하나요?`);
  } else if (ctx.viz && ctx.viz.kind !== "error") {
    out.push(`${ctx.viz.line}번째 줄 「${lineText(ctx, ctx.viz.line).trim()}」은 무슨 일을 하나요?`);
  } else if (ctx.viz?.kind === "error" && !v) out.push(`${ctx.viz.line}번째 줄에서 오류가 난 이유가 궁금해요.`);
  out.push(`「${ctx.title}」에 쓰이는 개념을 설명해 주세요.`);
  return [...new Set(out)].slice(0, 3);
}

type Item = { id?: string; pending?: string; question: string; withContext: boolean; answer?: Answer; error?: string; fresh?: boolean };
/** 실습 질문 이력 한 줄 — AI 질문 화면과 따로, 서버에 저장된 실습 질문만 모아 보여 줘요 */
type Saved = { id?: string; feedback?: FeedbackValue; at: string; week?: number | null; problem: string; question: string; answer: string; citations?: Answer["citations"] };
export function PracticeChat({ planId, sectionId, courseId, open, onClose, context, draftRequest }: {
  planId?: string;
  sectionId: string;
  courseId: string;
  open: boolean;
  onClose: () => void;
  context: PracticeChatContext;
  /** 바깥(예: 채점 결과)에서 질문 칸에 미리 적어 둘 내용 — 바뀔 때마다 적어요 */
  draftRequest?: { text: string; seq: number } | null;
}) {
  const handouts = useStudentHandouts(courseId, open);
  const [draft, setDraft] = useState("");
  const [sent, setSent] = useState<{ text: string; key: number }>();
  const [withContext, setWithContext] = useState(true);
  const [items, setItems] = useState<Item[]>([]);
  const [thread, setThread] = useState<string>();
  const [job, setJob] = useState<string>();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [feedbackBusy, setFeedbackBusy] = useState(false);
  const sendBusy = useRef(false);
  const fastPollUntil = useRef(0);
  const [history, setHistory] = useState<Saved[]>([]);
  const [showHistory, setShowHistory] = useState<string | null>(null);
  // 문제별로 묶어서 책갈피 하나씩 — 최근에 질문한 문제가 위로
  const groups = useMemo(() => { const m = new Map<string, { key: string; week?: number | null; problem: string; items: Saved[] }>(); for (const h of history) { const key = `${h.week ?? ""}|${h.problem}`; if (!m.has(key)) m.set(key, { key, week: h.week, problem: h.problem, items: [] }); m.get(key)!.items.push(h); } return [...m.values()]; }, [history]);
  const group = groups.find(g => g.key === showHistory);
  const groupLabel = (g: { week?: number | null; problem: string }) => `${g.week ? `${g.week}주차 · ` : ""}${g.problem}`;
  const [openSaved, setOpenSaved] = useState<number | null>(0);
  useEffect(() => {
    let active = true;
    setHistory([]);
    api<{items: {id: string; created_at: string; question: string; answer?: Answer; feedback?: FeedbackValue;
        context: {practice_title?: string; practice_week?: number}}[]}>(`/sections/${sectionId}/chat/history?mode=practice&limit=50`)
      .then(result => { if (active) setHistory(result.items.filter(item => item.answer).reverse().map(item => ({
        id: item.id, feedback: item.feedback, at: item.created_at, question: item.question,
        answer: item.answer!.answer, citations: item.answer!.citations,
        problem: item.context.practice_title || "실습", week: item.context.practice_week,
      }))); })
      .catch(e => { if (active) setError((e as Error).message); });
    return () => { active = false; };
  }, [sectionId]);
  const remember = (item: Saved) => setHistory(old => [item, ...old].slice(0, 50));
  const askedRef = useRef<{ question: string; problem: string; week?: number | null } | null>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  const list = useRef<HTMLDivElement>(null);
  const suggestions = useMemo(() => suggestedQuestions(context), [context]);
  const filled = context.template.blanks.filter(b => cleanFill(context.fills[b.n])).length;

  useEffect(() => { if (open) setTimeout(() => input.current?.focus(), 60); }, [open]);
  // 질문이 길어지면 입력칸이 저절로 길어져요 (최대 높이를 넘으면 칸 안에서 스크롤)
  useAutosizeTextarea(input, draft, open);
  useEffect(() => { if (draftRequest) setDraft(draftRequest.text); }, [draftRequest?.seq]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  // 새 대화가 아래에 붙으면 맨 아래로
  useEffect(() => { const el = list.current; if (el) el.scrollTop = el.scrollHeight; }, [items]);
  // 답변 기다리기 — AI 질문 화면과 같은 작업 확인 방식
  useEffect(() => {
    if (!job) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    const settle = (patch: Partial<Item>) => setItems(old => old.map((x, i) => i === old.length - 1 ? { ...x, ...patch } : x));
    const poll = async () => {
      try {
        const r = await api<Job>("/jobs/" + job);
        if (stopped) return;
        if (["succeeded", "failed", "cancelled"].includes(r.status)) {
          settle({ pending: undefined, answer: r.result || undefined, fresh: !!r.result, error: r.error ? "답변 처리에 실패했어요. 다시 질문해 주세요." : r.status === "cancelled" ? "취소됐어요." : undefined });
          const asked = askedRef.current;
          if (r.status === "succeeded" && r.result && asked) remember({ id: r.result.message_id, at: new Date().toISOString(), week: asked.week, problem: asked.problem, question: asked.question, answer: (r.result as Answer).answer, citations: (r.result as Answer).citations });
          setJob(undefined);
        } else {
          const { message, delayMs } = chatPollState(r, performance.now() < fastPollUntil.current);
          settle({ pending: message });
          timer = setTimeout(poll, delayMs);
        }
      } catch (e) {
        if (!stopped) { settle({ error: (e as Error).message }); setJob(undefined); }
      }
    };
    void poll();
    return () => { stopped = true; clearTimeout(timer); };
  }, [job]);

  const send = async (text?: string) => {
    const question = (text ?? draft).trim();
    if (!question || job || sendBusy.current) return;
    sendBusy.current = true;
    fastPollUntil.current = performance.now() + 10_000;
    setBusy(true); setError("");
    try {
      const r = await api<{ job_id: string; thread_id: string; resource_id: string }>(`/sections/${sectionId}/chat/messages`, {
        ...post({...practiceChatBody(question, context.exerciseId, thread, withContext ? practiceContextText(context) : undefined), plan_id: planId}),
        headers: { "Idempotency-Key": crypto.randomUUID() },
      });
      setThread(r.thread_id);
      setItems(v => [...v, { id: r.resource_id, question, withContext }]);
      askedRef.current = { question, problem: context.title, week: context.week };
      if (text === undefined) { setSent({ text: question, key: Date.now() }); setDraft(""); }
      setJob(r.job_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "질문을 보내지 못했어요.");
      if (text !== undefined) throw e;
    } finally { sendBusy.current = false; setBusy(false); }
  };

  const lastAnswer = items.at(-1);

  return <>
    <div className={`practice-chat-scrim ${open ? "is-open" : ""}`} onClick={onClose} aria-hidden="true" />
    <aside className={`practice-chat ${open ? "is-open" : ""}`} aria-label="실습 질문하기" aria-hidden={!open} inert={!open}>
      <header className="practice-chat__head">
        <div><strong>이 문제 질문하기</strong><span>강의 자료에서 근거를 찾고, 스스로 떠올리도록 되물어요 · 정답 코드는 알려 주지 않아요</span></div>
        <button type="button" className="practice-chat__close" onClick={onClose} aria-label="질문 창 닫기">✕</button>
      </header>

      <section className="practice-chat__ctx" aria-label="함께 보내는 풀이 상황">
        <label className="practice-chat__ctx-toggle"><input type="checkbox" checked={withContext} onChange={e => setWithContext(e.target.checked)} /> 지금 풀이 상황 함께 보내기</label>
        <details open key={context.exerciseId}><summary>{context.week ? `${context.week}주차 · ` : ""}{context.title} 풀이 상황</summary>
        <ul className={withContext ? "" : "is-off"}>
          <li><span>{context.number ? `문제 ${context.number}` : "문제"}</span>{context.title}</li>
          {context.template.blanks.length ? <li><span>빈칸</span>{context.template.blanks.length}개 중 {filled}개 채움</li> : <li><span>유형</span>직접 작성 · {context.template.lines.length}줄</li>}
          <li><span>채점</span>{context.verdict ? <b className={context.verdict.kind === "correct" ? "is-correct" : "is-wrong"}>{context.verdict.title}</b> : "아직 채점 전"}</li>
          <li><span>시각화</span>{context.viz ? `${context.viz.step}/${context.viz.total}단계 · ${context.viz.line}번째 줄 ${VIZ_LINE_WORD[context.viz.kind]}` : "시각화 탭에서 장면을 고르면 함께 보내요"}</li>
        </ul></details>
      </section>

      <div className="practice-chat__list" ref={list} aria-live="polite">
        {items.length === 0 && <div className="practice-chat__empty"><p>풀다가 막힌 부분을 물어보세요.<br />지금 보고 있는 문제와 장면을 함께 알려 줄게요.</p></div>}
        {items.map((item, i) => <article key={i} className="practice-chat__pair">
          <p className="practice-chat__me">{item.question}{item.withContext && <small>풀이 상황 함께 보냄</small>}</p>
          <div className="practice-chat__ai">
            <span>AI 강사{(item.answer as { mode?: string } | undefined)?.mode === "test_sample" && <em className="practice-chat__sample">테스트용 예시 답변</em>}</span>
            {item.answer ? <>
              <TypedAnswer text={item.answer.answer} animate={!!item.fresh}>
                {item.answer.answer_kind === "insufficient" && <p className="practice-chat__tip">왼쪽의 단계별 힌트를 열거나, 질문을 개념 이름으로 바꿔 다시 물어보세요.</p>}
                {item.answer.citations?.map((c, n) => <ChatCitation key={n} citation={c} handouts={handouts} newTab />)}
                {item.answer.follow_up && <p className="practice-chat__followup"><b>🤔 생각해 볼 질문</b>{item.answer.follow_up}</p>}
              </TypedAnswer>
            </> : item.error ? <p className="practice-chat__error" role="alert">{item.error}</p> : item.pending ? <p className="practice-chat__typing" role="status">{item.pending}</p> : <p className="practice-chat__typing chat-typing" role="status"><span className="chat-dots" aria-hidden="true"><i /><i /><i /></span><span>AI 강사가 답변을 적고 있어요</span></p>}
          </div>
        </article>)}
      </div>

      {items.length > 0 && <TutorFeedback sectionId={sectionId} jobId={job}
        messageId={lastAnswer?.answer ? lastAnswer.id || lastAnswer.answer.message_id : undefined}
        disabled={busy} onBusyChange={setFeedbackBusy}
        onConfused={() => send("방금 설명이 헷갈려요. 더 쉬운 예로, 한 단계씩 다시 설명해 주세요.")}
        onStop={() => {
          setJob(undefined); setThread(undefined); askedRef.current = null;
          setItems(old => old.map((item, i) => i === old.length - 1 && !item.answer ? { ...item, error: "요청을 취소했어요." } : item));
        }} />}
      <form className="practice-chat__form" onSubmit={e => { e.preventDefault(); if (!feedbackBusy) void send(); }}>
        {suggestions.length > 0 && <div className="practice-chat__chips" aria-label="질문 예시">{suggestions.map(s => <button type="button" key={s} onClick={() => { setDraft(s); input.current?.focus(); }}>{s}</button>)}</div>}
        <div className="practice-chat__inputbox"><textarea ref={input} value={draft} onChange={e => setDraft(e.target.value)} rows={1} maxLength={4000} aria-label="질문"
          disabled={!!job || feedbackBusy}
          onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey && !isComposingInput(e.nativeEvent)) { e.preventDefault(); void send(); } }} />
        <VanishPlaceholder textarea={input} examples={["이 반복은 몇 번 돌고, 언제 멈추나요?", "이 줄에서 변수 값은 어떻게 바뀌나요?"]} hidden={!!draft} sent={sent} />
          <button type="submit" className="practice-chat__send" aria-label={job ? "답변 기다리는 중" : "질문 보내기"} title={job ? "답변 기다리는 중…" : "질문 보내기 (Enter)"} disabled={!draft.trim() || !!job || busy || feedbackBusy}>
            {job ? <span className="practice-chat__send-spin" aria-hidden="true" /> : <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M19 5v7a3 3 0 0 1-3 3H6" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" /><path d="m10 10.5-4.5 4.5 4.5 4.5" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" /></svg>}
          </button>
        </div>
        {error && <p className="practice-chat__error" role="alert">{error}</p>}
      </form>
      <div className={`practice-chat__side ${group ? "is-open" : ""}`}>
        {groups.length > 0 && <nav className="practice-chat__bookmarks" aria-label="실습 질문 이력">{groups.map((g, n) => <button key={g.key} type="button" className={`practice-chat__bookmark tone-${n % 4}`} aria-pressed={showHistory === g.key} aria-label={`${groupLabel(g)} 질문 ${g.items.length}개`} onClick={() => { setShowHistory(showHistory === g.key ? null : g.key); setOpenSaved(0); }}>
          <span className="practice-chat__bookmark-week">{g.week ? `${g.week}주차` : "실습"}</span>
          <span className="practice-chat__bookmark-tip" aria-hidden="true">{groupLabel(g)}<small>질문 {g.items.length}개</small></span>
        </button>)}</nav>}
        {group && <section id="practice-chat-history" className="practice-chat__history" aria-label={`${groupLabel(group)} 질문 이력`}>
          <header><div><small>{group.week ? `${group.week}주차 실습` : "실습"}</small><strong>{group.problem}</strong></div><button type="button" onClick={() => setShowHistory(null)} aria-label="질문 이력 닫기">✕</button></header>
          <p className="practice-chat__history-note">이 문제에서 한 질문 {group.items.length}개</p>
          <ul>{group.items.map((h, n) => <li key={h.at + n} className={openSaved === n ? "is-open" : ""}>
            <button type="button" aria-expanded={openSaved === n} onClick={() => setOpenSaved(openSaved === n ? null : n)}>
              <small>{new Date(h.at).toLocaleDateString("ko-KR", { month: "long", day: "numeric" })} {new Date(h.at).toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit" })}</small>
              <strong>{h.question}</strong>
            </button>
            {openSaved === n && <div className="practice-chat__history-answer"><span>AI 강사</span><p>{h.answer}</p><ChatFeedback sectionId={sectionId} messageId={h.id} initial={h.feedback} />{h.citations?.map((c, k) => <ChatCitation key={k} citation={c} handouts={handouts} newTab />)}<button type="button" className="practice-chat__ask-again" onClick={() => { setDraft(h.question); setShowHistory(null); setTimeout(() => input.current?.focus(), 60); }}>이 질문 다시 하기</button></div>}
          </li>)}</ul>
        </section>}
      </div>
    </aside>
  </>;
}
