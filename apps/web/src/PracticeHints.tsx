import { useEffect, useRef, useState } from "react";
import { api, post } from "./api";

type HelpState = { hints_used: number; hints: string[]; max_hint_steps: number; can_view_answer: boolean };

function HintText({ hint }: { hint: string }) {
  const lines = hint.replace(/([^\s])[ \t]*(?=💡)/gu, "$1\n").split("\n");
  return <div className="step-hints-text">
    {lines.map((line, index) => (
      <div key={index}>
        {line.trimStart().startsWith("💡") ? <mark>{line.trimStart()}</mark> : line || <br />}
      </div>
    ))}
  </div>;
}

export function PracticeHints({ sectionId, exerciseId, onBusyChange, planId }: {
  planId?: string; sectionId: string; exerciseId: string; onBusyChange: (busy: boolean) => void;
}) {
  const [state, setState] = useState<HelpState>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [closed, setClosed] = useState<number[]>([]);
  const [folded, setFolded] = useState(true);
  const [revision, setRevision] = useState(0);
  const active = useRef(false);
  useEffect(() => {
    let cancelled = false;
    active.current = true; setState(undefined); setError("");
    api<HelpState>(`/sections/${sectionId}/practice/help`, post({ exercise_id: exerciseId, plan_id: planId, kind: "state" }))
      .then(result => { if (!cancelled) { setState(result); } })
      .catch(e => { if (!cancelled) setError((e as Error).message); });
    return () => { cancelled = true; active.current = false; };
  }, [sectionId, exerciseId, planId, revision]);
  const next = async () => {
    if (!state || busy) return;
    setBusy(true); onBusyChange(true); setError("");
    try {
      const result = await api<HelpState>(`/sections/${sectionId}/practice/help`, post({
        exercise_id: exerciseId, plan_id: planId, kind: "hint", step: state.hints_used + 1,
      }));
      if (active.current) { setState(result); }
    } catch (e) { if (active.current) setError((e as Error).message); }
    finally { if (active.current) { setBusy(false); onBusyChange(false); } }
  };
  const total = state?.max_hint_steps || 0;
  const used = state?.hints_used || 0;
  const allHidden = folded || (!!used && Array.from({ length: used }, (_, i) => i).every(i => closed.includes(i)));
  const tone = (step: number) => total <= 3 ? step : Math.ceil(step * 3 / total);
  return <section className={`step-hints ${state && used === total ? "is-all-open" : ""}`} aria-label="단계별 힌트">
    <div className="step-hints-head"><div className="step-hints-title"><h3>힌트</h3>
      <span className="hint-meter" role="img" aria-label={`힌트 ${total}개 중 ${used}개 열었어요`}>
        {Array.from({length: total}, (_, i) => <span key={i} className={`hint-meter__pip is-tone-${tone(i + 1)} ${i < used ? "is-used" : ""} ${i === used ? "is-next" : ""}`} />)}
      </span><span className="hint-left">{!state ? "불러오는 중…" : used < total ? <>남은 힌트 <b>{total - used}</b></> : "힌트를 모두 열었어요"}</span>
    </div><div className="step-hints-actions">
      {error && !state && <button type="button" onClick={() => setRevision(v => v + 1)}>다시 불러오기</button>}
      {used > 0 && <button type="button" className="step-hints-fold" aria-expanded={!allHidden} onClick={() => { setFolded(!allHidden); if (allHidden) setClosed([]); }}>{allHidden ? "전체 펼치기" : "전체 접기"}</button>}
      {state && used < total && <button type="button" className={`step-hints-next is-tone-${tone(used + 1)}`} disabled={busy} onClick={() => { setFolded(false); void next(); }}>{busy ? "불러오는 중…" : `힌트 ${used + 1} 보기`}</button>}
    </div></div>
    {!folded && !!state?.hints.length && <ol className="step-hints-list">{state.hints.map((hint, i) => closed.includes(i) ? null : <li className={`is-step-${tone(i + 1)} ${i + 1 === used ? "is-latest" : ""}`} key={i}><b>힌트 {i + 1}</b><HintText hint={hint} /><button type="button" className="step-hints-close" aria-label={"힌트 " + (i + 1) + " 닫기"} onClick={() => setClosed(prev => [...prev, i])}>×</button></li>)}</ol>}
    <p className="muted">힌트는 순서대로 열 수 있어요. 답지·해설은 이 문제를 최종 제출한 뒤 공개돼요.</p>
    {error && <p role="alert">{error}</p>}
  </section>;
}
