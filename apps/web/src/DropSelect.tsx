import { useState } from "react";
import { matchesSearch } from "./listNavigation";

type Choice = { value: string; label: string };

export function DropSelect({ label, value, options, onChange, searchable = false, name, required }: {
  label: string;
  value: string;
  options: Choice[];
  onChange: (value: string) => void;
  searchable?: boolean;
  name?: string;
  required?: boolean;
}) {
  const [search, setSearch] = useState("");
  const matches = options.filter(o => !search || matchesSearch(search, o.label));
  // Keep the submitted value stable while the user narrows the list.
  const visible = options.filter(o => o.value === value || matches.includes(o));
  return <div className="design-picker">
    {searchable && <label>{label} 검색<input type="search" value={search}
      onKeyDown={e => { if (e.key === "Enter") e.preventDefault(); }}
      onChange={e => setSearch(e.target.value)} placeholder="검색어 입력" /></label>}
    <label>{label}<select aria-label={label} name={name} required={required} value={value}
      onChange={e => { onChange(e.target.value); setSearch(""); }}>
      {visible.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
    </select></label>
    {search && !matches.some(o => o.value) && <small role="status">검색 결과가 없어요.</small>}
  </div>;
}
