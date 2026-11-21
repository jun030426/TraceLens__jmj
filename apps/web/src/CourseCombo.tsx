import { useEffect, useId, useState } from "react";
import { isComposingInput } from "./inputKeyboard";
import { matchesSearch } from "./listNavigation";

type CourseChoice = { value: string; label: string };

export function CourseCombo({ label, value, options, onChange, numericInput }: {
  label: string;
  value: string;
  options: CourseChoice[];
  onChange: (value: string) => void;
  numericInput?: { id: string; disabled: boolean; max: number };
}) {
  const listId = useId();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState<string | null>(null);
  const [index, setIndex] = useState(-1);
  const selected = options.find(option => option.value === value);
  const matches = options.filter(option => matchesSearch(query ?? "", option.label));
  const active = open ? matches[index] : undefined;
  const activeId = active ? listId + "-" + active.value : undefined;

  useEffect(() => {
    if (activeId) document.getElementById(activeId)?.scrollIntoView({ block: "nearest" });
  }, [activeId]);

  function close() {
    setOpen(false);
    setQuery(null);
    setIndex(-1);
  }

  function choose(option: CourseChoice) {
    close();
    onChange(option.value);
  }

  return <div className="course-combo question-combo">
    <input id={numericInput?.id} disabled={numericInput?.disabled} required={!!numericInput}
      inputMode={numericInput ? "numeric" : undefined}
      pattern={numericInput ? options.map(option => option.value).join("|") : undefined}
      title={numericInput ? `1부터 ${numericInput.max}까지의 주차를 입력하세요.` : undefined}
      role="combobox" aria-label={label} aria-autocomplete="list" autoComplete="off"
      aria-expanded={open} aria-controls={open ? listId : undefined} aria-activedescendant={activeId}
      placeholder={label} value={numericInput ? value : query ?? selected?.label ?? ""}
      onFocus={event => { event.currentTarget.select(); setOpen(true); }}
      onClick={() => setOpen(true)} onBlur={close}
      onChange={event => { setQuery(event.target.value); if (numericInput) onChange(event.target.value); setIndex(-1); setOpen(true); }}
      onKeyDown={event => {
        if (isComposingInput(event.nativeEvent)) return;
        if (event.key === "ArrowDown" || event.key === "ArrowUp") {
          event.preventDefault();
          setOpen(true);
          const last = matches.length - 1;
          setIndex(event.key === "ArrowDown" ? Math.min(index + 1, last) : index < 0 ? last : Math.max(0, index - 1));
        } else if (open && event.key === "Escape") {
          event.preventDefault();
          close();
        } else if (open && event.key === "Enter") {
          event.preventDefault();
          const option = active ?? (matches.length === 1 ? matches[0] : undefined);
          if (option) choose(option);
        }
      }} />
    <span className="course-combo-caret" aria-hidden="true">⌄</span>
    {open && <ul className="question-combo-list" id={listId} role="listbox" aria-label={label}>
      {matches.map(option => <li key={option.value} id={listId + "-" + option.value} role="option"
        aria-selected={option.value === value} className={(active ?? selected)?.value === option.value ? "is-active" : ""}
        onMouseDown={event => event.preventDefault()} onClick={() => choose(option)}>{option.label}</li>)}
      {!matches.length && <li role="option" aria-selected={false} aria-disabled="true" className="is-empty">{numericInput ? "선택할 수 있는 주차가 없어요." : "맞는 수업이 없어요."}</li>}
    </ul>}
  </div>;
}
