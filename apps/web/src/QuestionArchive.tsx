import { useState } from "react";
import type { Answer } from "./api";
import { ErrorNotice, Notice, useLoad } from "./components";
import { ListPager } from "./StudentLists";
import { sourceLabel } from "./sourceLabels";

export function QuestionArchive({ sectionId, revision, open, onOpenChange }: { sectionId: string; revision: number; open: boolean; onOpenChange: (open: boolean) => void }) {
  return <details className="chat-archive" open={open} onToggle={e => onOpenChange(e.currentTarget.open)}>
    <summary>이전 질문 찾아보기</summary>
    {open && <Archive key={`${sectionId}:${revision}`} sectionId={sectionId} />}
  </details>;
}

function Archive({ sectionId }: { sectionId: string }) {
  const [input, setInput] = useState("");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(0);
  const query = new URLSearchParams({ limit: "8", offset: String(page * 8), q: search });
  const history = useLoad<{ total: number; items: { id: string; created_at: string; question: string; answer?: Answer; error?: string }[] }>(`/sections/${sectionId}/chat/history?${query}`);
  return <div>
    <form className="student-list-tools" onSubmit={e => { e.preventDefault(); setSearch(input.trim()); setPage(0); }}>
      <label>이전 질문 검색<input type="search" value={input} onChange={e => setInput(e.target.value)} placeholder="내가 질문한 내용으로 검색" maxLength={200} /></label>
      <button type="submit">검색</button>
      <button type="button" onClick={() => { setInput(""); setSearch(""); setPage(0); }}>전체 질문</button>
    </form>
    <ErrorNotice text={history.error} />
    {history.error && <button onClick={history.reload}>다시 불러오기</button>}
    {!history.data && !history.error && <Notice>질문 기록을 불러오는 중이에요…</Notice>}
    {history.data && <>
      <p className="student-list-count" role="status">총 {history.data.total}개 질문 · 최신순</p>
      {!history.data.items.length && <p className="student-list-empty">{search ? "검색한 질문이 없어요. 다른 검색어로 찾아보세요." : "아직 질문 기록이 없어요."}</p>}
      {[...history.data.items].reverse().map(item => <details className="chat-archive-entry" key={item.id}>
        <summary><time dateTime={item.created_at}>{new Date(item.created_at).toLocaleDateString("ko-KR")}</time><span>{item.question}</span></summary>
        {item.answer ? <><p className="answer">{item.answer.answer}</p>{item.answer.citations?.map((c,i) => <a key={i} href={`/api/v1/materials/${c.material_id}/file?version_id=${c.version_id}`}>{c.title} · {sourceLabel(c.locator)} ↗</a>)}</> : item.error ? <ErrorNotice text={item.error} /> : <p>답변을 준비하고 있어요.</p>}
      </details>)}
      <ListPager page={page} pages={Math.ceil(history.data.total / 8)} onChange={setPage} label="질문 기록" />
    </>}
  </div>;
}
