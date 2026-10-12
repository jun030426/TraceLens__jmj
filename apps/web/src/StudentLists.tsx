import { useRef, useState, type ReactNode } from "react";
import { listPage } from "./listNavigation";
import "./student-lists.css";

export function ListPager({ page, pages, onChange, label }: {
  page: number; pages: number; onChange: (page: number) => void; label: string;
}) {
  if (pages <= 1) return null;
  return <nav className="student-list-pager" aria-label={`${label} 페이지`}>
    <button type="button" disabled={page === 0} onClick={() => onChange(page - 1)}>← 이전</button>
    <span aria-live="polite">{page + 1} / {pages} 페이지</span>
    <button type="button" disabled={page + 1 >= pages} onClick={() => onChange(page + 1)}>다음 →</button>
  </nav>;
}

export function PagedList<T>({ items, children, label, size = 6, resetKey = "", className = "", initialPage = 0 }: {
  items: T[]; children: (items: T[]) => ReactNode; label: string;
  size?: number; resetKey?: string; className?: string; initialPage?: number;
}) {
  const [position, setPosition] = useState({ key: resetKey, page: initialPage });
  const start = useRef<HTMLDivElement>(null);
  const result = listPage(items, position.key === resetKey ? position.page : initialPage, size);
  return <div className={`student-paged-list ${className}`} ref={start}>
    {items.length > size && <p className="student-list-count" role="status">{label} {items.length}개 · {result.page * size + 1}–{result.page * size + result.items.length}번째</p>}
    {children(result.items)}
    <ListPager page={result.page} pages={result.pages} label={label} onChange={page => {
      setPosition({ key: resetKey, page });
      requestAnimationFrame(() => start.current?.scrollIntoView({ block: "start" }));
    }} />
  </div>;
}
