import {
  REVIEW_LABEL,
  signalNote,
  type Signal,
  type ReviewState,
} from "./professorWeakness";

export function WeaknessSignal({
  signal,
  onSelect,
}: {
  signal: Signal;
  onSelect?: () => void;
}) {
  const content = (
    <>
      <span className="pw-signal-heading">
        <strong>{signal.name}</strong>
        <span className={`pw-status is-${signal.state}`}>
          {REVIEW_LABEL[signal.state as ReviewState] || "확인 필요"}
        </span>
      </span>
      <span className="pw-signal-score">
        {signal.weakness == null ? (
          <b>{signal.sample}/5건</b>
        ) : (
          <>
            <b>
              {signal.weakness}
              <small>/100</small>
            </b>
            <span>취약도 · 높을수록 복습 필요</span>
          </>
        )}
      </span>
      {signal.weakness != null && (
        <span className="pw-meter" aria-hidden="true">
          <span
            style={{ width: `${Math.min(100, Math.max(0, signal.weakness))}%` }}
          />
        </span>
      )}
      <span className="pw-signal-note">{signalNote(signal)}</span>
      {onSelect && (
        <span className="pw-signal-action">판단 근거·답안 보기 →</span>
      )}
    </>
  );
  return onSelect ? (
    <button
      type="button"
      className={`pw-signal is-${signal.state}`}
      aria-label={`${signal.name} 판단 근거·답안 보기`}
      onClick={onSelect}
    >
      {content}
    </button>
  ) : (
    <div className={`pw-signal is-${signal.state}`}>{content}</div>
  );
}
