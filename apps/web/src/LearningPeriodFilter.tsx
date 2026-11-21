import { useState } from "react";
import { ErrorNotice } from "./components";
import { initialPeriod, type Period } from "./learningPeriod";
export function PeriodFilter({
  value,
  onChange,
  variant,
}: {
  value: Period;
  variant?: "calendar";
  onChange: (value: Period) => void;
}) {
  const [error, setError] = useState("");
  const calendar = variant === "calendar";
  return (
    <>
      <form
        key={`${value.from}:${value.to}`}
        className={calendar ? "prof-list-tools student-period-calendar" : "prof-list-tools"}
        onSubmit={(event) => {
          event.preventDefault();
          const form = new FormData(event.currentTarget);
          const from = String(form.get("from")),
            to = String(form.get("to"));
          if (
            from > to ||
            (Date.parse(to) - Date.parse(from)) / 86400000 > 365
          ) {
            setError("시작일 이후, 최대 366일 범위로 선택해 주세요.");
            return;
          }
          setError("");
          onChange({ from, to });
        }}
      >
        <label>
          {!calendar && "시작일"}
          <input type="date" name="from" aria-label={calendar ? "시작일" : undefined} required defaultValue={value.from} />
        </label>
        {calendar && <span className="student-period-separator" aria-hidden="true">~</span>}
        <label>
          {!calendar && "종료일"}
          <input type="date" name="to" aria-label={calendar ? "종료일" : undefined} required defaultValue={value.to} />
        </label>
        <button type="submit">기간 적용</button>
        <button
          type="button"
          onClick={(event) => {
            event.currentTarget.form?.reset();
            setError("");
            onChange(initialPeriod());
          }}
        >
          최근 30일
        </button>
      </form>
      <ErrorNotice text={error} />
    </>
  );
}
