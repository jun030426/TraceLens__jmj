import { useState, type ReactNode } from "react";
import { PagedList } from "./StudentLists";
import { matchesSearch } from "./listNavigation";

export function ResourceBrowser<T extends { id: string; title: string; week: number }>({ items, label, children }: {
  items: T[]; label: string; children: (items: T[]) => ReactNode;
}) {
  const [search, setSearch] = useState("");
  const [week, setWeek] = useState("");
  const weeks = [...new Set(items.map(item => item.week))].sort((a,b) => a-b);
  const filtered = items.filter(item => matchesSearch(search,item.title) && (!week || item.week === Number(week)));
  return <div className="resource-browser">
    {items.length > 6 && <div className="student-list-tools">
      <label>{label} 검색<input type="search" placeholder="자료 이름으로 검색" value={search} onChange={e => setSearch(e.target.value)} /></label>
      {weeks.length > 1 && <label>{label} 주차<select value={week} onChange={e => setWeek(e.target.value)}><option value="">전체 주차</option>{weeks.map(w => <option key={w} value={w}>{w}주차</option>)}</select></label>}
    </div>}
    {!filtered.length && items.length > 0 && <p className="student-list-empty">조건에 맞는 자료가 없어요. 검색어와 주차를 바꿔 보세요.</p>}
    <PagedList items={filtered} label={label} resetKey={`${search}:${week}`}>{children}</PagedList>
  </div>;
}
