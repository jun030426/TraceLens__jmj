import { useEffect, useState, type ReactNode } from "react";

/* 이론·실습 공통 힌트 카드 (2026-11-14 개편).
   - 버튼은 하나예요. 누를 때마다 다음 힌트가 1 → 2 → 3 … 순서로 하나씩 열려요.
   - 힌트 개수는 문제마다 달라요: 개념 퀴즈 1개 · 빈칸 채우기 3개 · 직접 작성(풀코딩)은 문제마다 정한 단계 수.
   - 제목 옆 알약 모양 칸이 '연 힌트 / 남은 힌트'를 보여 줘요. 칠해진 칸 = 연 힌트, 빈 칸 = 남은 힌트.
   - 한 번 연 힌트는 다시 닫히지 않아요(접기·펼치기만 돼요). 다른 문제에 갔다 와도 연 만큼 그대로예요.
   - 뒤 단계일수록(is-step-1 → 3) 힌트 칸 색이 진해져요 — 뒤 힌트일수록 정답에 가까워요. */
export function StepHints({ storageKey, hints, onUsed, labels, initialUsed = 0 }: {
  storageKey: string;
  hints: ReactNode[];
  onUsed?: (used: number) => void | Promise<void>;
  /** 단계 이름 (예: 1단계 · 2단계). 없으면 "힌트 1" · 힌트가 1개면 "힌트" */
  labels?: string[];
  /** 이 문제에서 이미 열어 본 힌트 수 — 다른 문제에 갔다가 돌아오면 그만큼 열린 채로 보여요 */
  initialUsed?: number;
}) {
  const total = hints.length;
  const name = (step: number) => labels?.[step - 1] || (total === 1 ? "힌트" : `힌트 ${step}`);
  const start = Math.min(initialUsed, total);
  const [used, setUsed] = useState(start); // 연 힌트 수 (1..used가 보여요)
  const [folded, setFolded] = useState(false);
  const [closed, setClosed] = useState<number[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    setClosed([]);
    setUsed(start);
    setFolded(false);
  }, [storageKey, total]); // eslint-disable-line react-hooks/exhaustive-deps
  const left = total - used;
  const openNext = async () => {
    if (busy || used >= total) return;
    setBusy(true); setError("");
    try {
      await onUsed?.(used + 1);
      setFolded(false); setUsed(used + 1);
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  };
  // 단계 색은 3단계로 나눠요 — 힌트가 4개면 1·2 → 연한 색, 3 → 중간, 4 → 진한 색처럼
  const tone = (step: number) => total <= 3 ? step : Math.max(1, Math.ceil((step * 3) / total));
  const shown = folded ? [] : Array.from({ length: used }, (_, i) => i + 1).filter(step => !closed.includes(step));
  const allHidden = used > 0 && shown.length === 0; // 전체 접기 했거나, 연 힌트를 하나씩 모두 닫았을 때
  const toggleAll = () => {
    if (allHidden) { setFolded(false); setClosed([]); }
    else setFolded(true);
  };
  const closeOne = (step: number) => setClosed(prev => prev.includes(step) ? prev : [...prev, step]);
  const allWord = total > 1 ? "전체 " : "";

  return <section className={`step-hints ${left === 0 ? "is-all-open" : ""}`} aria-label="힌트">
    <div className="step-hints-head">
      <div className="step-hints-title">
        <h3>힌트</h3>
        <span className="hint-meter" role="img" aria-label={`힌트 ${total}개 중 ${used}개 열었어요. ${left}개 남았어요.`}>
          {hints.map((_, i) => <span key={i} className={`hint-meter__pip is-tone-${tone(i + 1)} ${i < used ? "is-used" : ""} ${i === used ? "is-next" : ""}`} />)}
        </span>
        <span className={`hint-left ${left === 0 ? "is-zero" : ""}`}>{left > 0 ? <>남은 힌트 <b>{left}</b></> : "힌트를 모두 열었어요"}</span>
      </div>
      <div className="step-hints-actions">
        {used > 0 && <button type="button" className="step-hints-fold" aria-expanded={!allHidden} onClick={toggleAll}>{allHidden ? `${allWord}펼치기` : `${allWord}접기`}</button>}
        {left > 0 && <button type="button" disabled={busy} className={`step-hints-next is-tone-${tone(used + 1)}`} onClick={() => void openNext()} title={`${name(used + 1)} 열기`}>
          <svg aria-hidden="true" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"><path d="M9 18h6M10 21h4M12 3a6 6 0 0 0-3.6 10.8c.6.5 1 1.2 1 2V16h5.2v-.2c0-.8.4-1.5 1-2A6 6 0 0 0 12 3Z" /></svg>
          {used === 0 ? (total === 1 ? "힌트 보기" : `${name(1)} 보기`) : `${name(used + 1)} 보기`}
        </button>}
      </div>
    </div>
    {shown.length > 0 && <ol className="step-hints-list">{shown.map(step => <li key={step} className={`is-step-${tone(step)} ${step === used ? "is-latest" : ""}`}><b>{name(step)}</b><div>{hints[step - 1]}</div>
      <button type="button" className="step-hints-close" onClick={() => closeOne(step)} aria-label={`${name(step)} 닫기`} title="이 힌트 닫기">
        <svg aria-hidden="true" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3.2" strokeLinecap="round"><path d="M6 6l12 12M18 6 6 18" /></svg>
      </button></li>)}</ol>}
    {error && <p role="alert">{error}</p>}
  </section>;
}
