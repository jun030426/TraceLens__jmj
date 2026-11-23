// 재생 엔진과 화면(VisualizationScreen)을 잇는 호스트.
// 실행 오류·부분 기록·stale 안내는 여기서도 보여 준다 (화면 CSS가 가려도 남도록).
// 화면 코드가 터져도 실습 페이지 전체가 멈추지 않게 오류 경계로 감싼다.
import { Component, useContext, useEffect, useLayoutEffect, useState, type ReactNode } from "react";
import type { Recording } from "./contracts";
import { usePlayback } from "./playback";
import { VisualizationScreen } from "./VisualizationScreen";
import { VizLineContext, vizLineOf } from "./vizLine";

class ScreenBoundary extends Component<{ children: ReactNode; resetKey: unknown }, { failed: boolean; key: unknown }> {
  state = { failed: false, key: this.props.resetKey };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  static getDerivedStateFromProps(props: { resetKey: unknown }, state: { failed: boolean; key: unknown }) {
    return props.resetKey !== state.key ? { failed: false, key: props.resetKey } : null;
  }
  render() {
    if (this.state.failed)
      return <div className="vz-host__notice" role="alert">시각화 화면을 그리다 문제가 생겼어요. 실행 결과 탭에서 출력은 그대로 볼 수 있어요.</div>;
    return this.props.children;
  }
}

function useReducedMotion() {
  const query = "(prefers-reduced-motion: reduce)";
  const [reduced, setReduced] = useState(() => typeof window !== "undefined" && !!window.matchMedia?.(query).matches);
  useEffect(() => {
    const mq = window.matchMedia?.(query);
    if (!mq) return;
    const on = () => setReduced(mq.matches);
    mq.addEventListener?.("change", on);
    return () => mq.removeEventListener?.("change", on);
  }, []);
  return reduced;
}

export function VisualizationHost({ recording, stale = false }: { recording: Recording; stale?: boolean }) {
  const count = recording.steps.length;
  const { state, controls, canNext, canPrevious } = usePlayback(count, recording);
  const reducedMotion = useReducedMotion();
  const current = count ? recording.steps[state.index] ?? null : null;
  const previous = current && current.index > 0 ? recording.steps[current.index - 1] : null;
  // 지금 보여 주는 줄을 바깥(실습 편집기)에도 알린다. 이전 실행 기록(stale)이면 줄이 안 맞을 수 있어 알리지 않는다
  const reportLine = useContext(VizLineContext);
  const viz = stale ? null : vizLineOf(recording, current);
  const vizKey = viz ? `${viz.line}:${viz.kind}:${viz.step}:${viz.total}` : "";
  useLayoutEffect(() => { reportLine?.(viz); }, [reportLine, vizKey]); // eslint-disable-line react-hooks/exhaustive-deps
  useLayoutEffect(() => () => reportLine?.(null), [reportLine]);
  return (
    <div className="vz-host">
      {stale && <p className="vz-host__notice is-stale">코드가 바뀌었어요. 지금 장면은 이전 실행 기록이에요.</p>}
      {recording.status === "partial" && <p className="vz-host__notice">{recording.message ?? "실행이 길어 앞부분까지만 기록했어요."}</p>}
      {/* 실행 오류는 여기서 바로 알리지 않는다 — 재생이 오류 단계에 닿으면 무대가 어디서·왜 멈췄는지 보여 준다.
          단, 기록에 오류 단계가 없으면(장면으로 보여 줄 수 없으면) 글로 알린다 */}
      {recording.error && !recording.steps.some(s => s.event === "exception") && (
        <p className="vz-host__notice is-error" role="alert">실행 중 오류: {recording.error}</p>
      )}
      {count === 0 ? (
        <p className="vz-host__notice">보여 줄 실행 기록이 없어요.</p>
      ) : (
        <ScreenBoundary resetKey={recording}>
          <VisualizationScreen
            recording={recording}
            current={current}
            previous={previous}
            playback={state}
            controls={controls}
            canNext={canNext}
            canPrevious={canPrevious}
            stale={stale}
            reducedMotion={reducedMotion}
          />
        </ScreenBoundary>
      )}
    </div>
  );
}
