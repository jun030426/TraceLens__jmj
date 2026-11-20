import { useEffect, useState, type ReactNode } from "react";
import type { Answer } from "./api";
import { ErrorNotice, useLoad } from "./components";

/* 이전 질문 찾아보기 (11-15 다듬기)
   - 검색: 돋보기 칸 하나로, 입력을 멈추면 바로 찾아요. ×로 검색어를 지워요.
   - 이력: 날짜별(오늘·어제·날짜)로 묶고 최근순/오래된 순으로 고를 수 있어요. 한 페이지에 5개씩, 옆으로 넘겨요.
   - 질문을 누르면 펼치지 않고, 그 질문을 했던 대화 자리로 바로 이동해요. */
export type HistoryItem = { id: string; created_at: string; question: string; answer?: Answer; error?: string; thread_id?: string | null; source?: string | null; quiz_title?: string | null };
/* 퀴즈 질문 탭 (11-15): 서버가 질문마다 source("quiz")를 주면 그걸로 정확히 나누고,
   아직 주지 않으면 퀴즈에서 넘어올 때 미리 채워지는 문장('…해설…')이 들어간 질문을 퀴즈 질문으로 봐요. */
const QUIZ_WORD = "해설";
/* 퀴즈 이름 (11-15): 서버가 quiz_title 을 주면 그걸 쓰고, 아직이면 이 브라우저에서 퀴즈 질문을 보낼 때 적어 둔 이름을
   같은 질문 문장 + 보낸 시각(앞뒤 3분)으로 찾아 붙여요. */
export function quizNameOf(x: HistoryItem) {
  if (x.quiz_title) return x.quiz_title;
  return x.question.includes("[함께 보내는 퀴즈와 내 답안]") ? "개념 퀴즈" : "";
}
const isQuizQuestion = (x: HistoryItem) => x.source ? x.source === "quiz" : x.question.includes(QUIZ_WORD) || !!quizNameOf(x);
const PAGE = 5; // 한 페이지에 질문 5개씩, 옆으로 넘겨 봐요 (11-15)

export function QuestionArchive({ sectionId, revision, open, onOpenChange, onOpenItem }: { sectionId: string; revision: number; open: boolean; onOpenChange: (open: boolean) => void; onOpenItem?: (item: HistoryItem) => void }) {
  return <details className="chat-archive" open={open} onToggle={e => onOpenChange(e.currentTarget.open)}>
    <summary>이전 질문 찾아보기</summary>
    {open && <Archive key={`${sectionId}:${revision}`} sectionId={sectionId} onOpenItem={onOpenItem} />}
  </details>;
}

const kstDate = (d: Date) => new Intl.DateTimeFormat("sv-SE", { timeZone: "Asia/Seoul" }).format(d);
const WEEKDAY = ["일", "월", "화", "수", "목", "금", "토"];
function dayLabel(iso: string) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "날짜 없음";
  const key = kstDate(d);
  const today = kstDate(new Date());
  const yesterday = kstDate(new Date(Date.now() - 864e5));
  const [y, m, dd] = key.split("-").map(Number);
  const base = `${m}월 ${dd}일 (${WEEKDAY[new Date(y, m - 1, dd).getDay()]})`;
  if (key === today) return `오늘 · ${base}`;
  if (key === yesterday) return `어제 · ${base}`;
  return Number(kstDate(new Date()).slice(0, 4)) === y ? base : `${y}년 ${base}`;
}
function highlight(text: string, word: string): ReactNode {
  if (!word) return text;
  const at = text.toLocaleLowerCase().indexOf(word.toLocaleLowerCase());
  if (at < 0) return text;
  return <>{text.slice(0, at)}<mark>{text.slice(at, at + word.length)}</mark>{highlight(text.slice(at + word.length), word)}</>;
}

function Archive({ sectionId, onOpenItem }: { sectionId: string; onOpenItem?: (item: HistoryItem) => void }) {
  const [input, setInput] = useState("");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(0);
  const [tab, setTab] = useState<"all" | "quiz">("all");
  const quiz = tab === "quiz";
  // 정렬: 최근순(기본) · 오래된 순 (11-15). 서버는 최근순으로만 주므로, 오래된 순은 전체 개수로 뒤에서부터 잘라 받아요.
  const [order, setOrder] = useState<"new" | "old">("new");
  const [counted, setCounted] = useState<{ q: string; n: number } | null>(null);
  const known = counted && counted.q === search ? counted.n : null;
  // 입력을 잠깐 멈추면 바로 찾아요 (Enter 를 눌러도 돼요)
  useEffect(() => {
    const t = setTimeout(() => { if (input.trim() !== search) { setSearch(input.trim()); setPage(0); } }, 350);
    return () => clearTimeout(t);
  }, [input, search]);
  const old = order === "old";
  const offset = !old ? page * PAGE : known === null ? 0 : Math.max(0, known - (page + 1) * PAGE);
  const limit = !old ? PAGE : known === null ? 1 : Math.max(1, Math.min(PAGE, known - page * PAGE));
  const query = new URLSearchParams({ limit: String(limit), offset: String(offset), q: search });
  // 퀴즈 질문 탭은 최근 퀴즈 질문 50개를 한 번에 받아 화면에서 검색·정렬·페이지를 나눠요
  const quizQuery = new URLSearchParams({ limit: "50", offset: "0", q: QUIZ_WORD });
  const history = useLoad<{ total: number; items: HistoryItem[] }>(`/sections/${sectionId}/chat/history?mode=theory&${quiz ? quizQuery : query}`);
  const quizAll = quiz && history.data
    ? history.data.items.filter(isQuizQuestion).filter(x => !search || x.question.toLocaleLowerCase().includes(search.toLocaleLowerCase()))
    : [];
  // 서버가 개수를 주지 않아도 'NaN 페이지'가 나오지 않게 지금 받은 목록 수로 대신해요
  const total = !history.data ? 0 : quiz ? quizAll.length : (Number.isFinite(history.data.total) ? history.data.total : history.data.items.length);
  useEffect(() => {
    if (!quiz && history.data && (!counted || counted.q !== search || counted.n !== total)) setCounted({ q: search, n: total });
  }, [quiz, history.data, search, total, counted]);
  const ready = !!history.data && (quiz || !old || known !== null);
  const sortByDate = (list: HistoryItem[]) => [...list].sort((a, b) => (old ? 1 : -1) * String(a.created_at).localeCompare(String(b.created_at)));
  const items = !ready ? [] : quiz ? sortByDate(quizAll).slice(page * PAGE, page * PAGE + PAGE) : sortByDate(history.data!.items);
  const groups: { label: string; items: HistoryItem[] }[] = [];
  for (const item of items) {
    const label = dayLabel(item.created_at);
    const last = groups[groups.length - 1];
    if (last && last.label === label) last.items.push(item); else groups.push({ label, items: [item] });
  }
  return <div className="qa-archive">
    <div className="qa-tabs" role="tablist" aria-label="질문 종류">
      {([["all", "전체 질문"], ["quiz", "퀴즈 질문"]] as const).map(([key, label]) => (
        <button key={key} type="button" role="tab" aria-selected={tab === key} className={tab === key ? "is-active" : ""} onClick={() => { if (tab !== key) { setTab(key); setPage(0); } }}>{label}</button>
      ))}
    </div>
    <form className="qa-search" role="search" onSubmit={e => { e.preventDefault(); setSearch(input.trim()); setPage(0); }}>
      <svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"><circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" /></svg>
      <input type="search" aria-label="이전 질문 검색" value={input} onChange={e => setInput(e.target.value)} placeholder="질문 내용으로 찾기" maxLength={200} />
      {input && <button type="button" className="qa-search-clear" aria-label="검색어 지우기" onClick={() => { setInput(""); setSearch(""); setPage(0); }}>×</button>}
    </form>
    {history.data && <div className="qa-toolbar">
      <p className="qa-count" role="status">
        {search ? <>‘{search}’ 검색 결과 <b>{total}</b>개</> : <>{quiz ? "퀴즈 질문" : "질문"} <b>{total}</b>개</>}
      </p>
      <div className="qa-order" role="group" aria-label="질문 정렬">
        {([["new", "최근순"], ["old", "오래된 순"]] as const).map(([key, label]) => (
          <button key={key} type="button" aria-pressed={order === key} onClick={() => { if (order !== key) { setOrder(key); setPage(0); } }}>{label}</button>
        ))}
      </div>
    </div>}
    <ErrorNotice text={history.error} />
    {history.error && <button type="button" className="qa-retry" onClick={history.reload}>다시 불러오기</button>}
    {!ready && !history.error && <p className="qa-empty">질문 기록을 불러오는 중이에요…</p>}
    {ready && !items.length && <p className="qa-empty">{search ? "찾는 질문이 없어요. 다른 낱말로 찾아보세요." : quiz ? "아직 퀴즈에서 물어본 질문이 없어요. 퀴즈 결과에서 ‘AI에게 물어보기’를 눌러 보세요." : "아직 질문한 기록이 없어요. 궁금한 점을 먼저 물어보세요."}</p>}
    {groups.map(group => <section className="qa-group" key={group.label}>
      <h4>{group.label}</h4>
      <ul>
        {group.items.map(item => <li key={item.id} className="qa-item">
          {/* 누르면 그 질문을 했던 대화로 이동해요 (11-15) */}
          <button type="button" className="qa-item-head" title="이 질문을 했던 대화로 이동" onClick={() => onOpenItem?.(item)}>
            <span className="qa-q-wrap">
              {quizNameOf(item) && <span className="qa-quiz-name">{quizNameOf(item)}</span>}
              <span className="qa-q">{highlight(item.question, search)}</span>
            </span>
            <span className="qa-meta">
              <span className="qa-go">대화 보기 <span aria-hidden="true">→</span></span>
            </span>
          </button>
        </li>)}
      </ul>
    </section>)}
    <QaPager page={page} pages={Math.ceil(total / PAGE)} onChange={setPage} />
  </div>;
}

/* 페이지 넘기기: ‹ 1 2 3 … 9 › (현재 페이지 주변만 보여요) */
function QaPager({ page, pages, onChange }: { page: number; pages: number; onChange: (page: number) => void }) {
  if (!(pages > 1)) return null;
  const nums: (number | "…")[] = [];
  const near = new Set([0, pages - 1, page - 1, page, page + 1]);
  if (page <= 2) [1, 2, 3].forEach(n => near.add(n));
  if (page >= pages - 3) [pages - 2, pages - 3, pages - 4].forEach(n => near.add(n));
  for (let i = 0; i < pages; i++) {
    if (near.has(i)) nums.push(i);
    else if (nums[nums.length - 1] !== "…") nums.push("…");
  }
  return <nav className="qa-pager" aria-label="질문 기록 페이지">
    <button type="button" className="qa-pager-arrow" aria-label="이전 페이지" disabled={page === 0} onClick={() => onChange(page - 1)}>‹</button>
    {nums.map((n, i) => n === "…"
      ? <span key={`gap${i}`} className="qa-pager-gap" aria-hidden="true">…</span>
      : <button key={n} type="button" className="qa-pager-num" aria-current={n === page ? "page" : undefined} aria-label={`${n + 1}페이지`} onClick={() => n !== page && onChange(n)}>{n + 1}</button>)}
    <button type="button" className="qa-pager-arrow" aria-label="다음 페이지" disabled={page + 1 >= pages} onClick={() => onChange(page + 1)}>›</button>
  </nav>;
}
