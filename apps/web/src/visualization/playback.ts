// 재생 엔진 — 재생·정지·앞뒤 이동·단계 이동. 단계 선택은 여기서만 한다 (화면은 controls만 부른다).
import { useCallback, useEffect, useMemo, useReducer } from "react";
import type { PlaybackControls, PlaybackState, TransitionKind } from "./contracts";

export const MIN_INTERVAL_MS = 100;
export const MAX_INTERVAL_MS = 10000;
export const DEFAULT_INTERVAL_MS = 1000;

const clampInterval = (ms: number) => Math.min(MAX_INTERVAL_MS, Math.max(MIN_INTERVAL_MS, Math.round(Number.isFinite(ms) ? ms : DEFAULT_INTERVAL_MS)));

export type PlaybackAction =
  | { type: "play" }
  | { type: "pause" }
  | { type: "next" }
  | { type: "previous" }
  | { type: "seek"; index: number }
  | { type: "restart" }
  | { type: "tick" }
  | { type: "interval"; ms: number }
  | { type: "reset"; count: number };

export function initialPlayback(intervalMs = DEFAULT_INTERVAL_MS): PlaybackState {
  return { index: 0, playing: false, intervalMs: clampInterval(intervalMs), transition: { kind: "initial", revision: 0 } };
}

const move = (s: PlaybackState, index: number, kind: TransitionKind, playing: boolean): PlaybackState => ({
  ...s,
  index,
  playing,
  transition: { kind, revision: s.transition.revision + 1 },
});

/** count = 단계 수. 0이면 어떤 이동도 하지 않는다 */
export function playbackReducer(count: number) {
  return (s: PlaybackState, a: PlaybackAction): PlaybackState => {
    const last = count - 1;
    switch (a.type) {
      case "reset":
        return { ...initialPlayback(s.intervalMs), transition: { kind: "initial", revision: s.transition.revision + 1 } };
      case "interval":
        return { ...s, intervalMs: clampInterval(a.ms) };
      case "pause":
        return s.playing ? { ...s, playing: false } : s;
      case "play":
        if (count <= 1) return s;
        // 마지막 단계에서 재생하면 처음부터
        return s.index >= last ? move(s, 0, "restart", true) : { ...s, playing: true };
      case "tick":
        if (!s.playing) return s;
        if (s.index >= last) return { ...s, playing: false };
        return move(s, s.index + 1, "tick", s.index + 1 < last);
      case "next":
        return s.index >= last ? { ...s, playing: false } : move(s, s.index + 1, "next", false);
      case "previous":
        return s.index <= 0 ? { ...s, playing: false } : move(s, s.index - 1, "previous", false);
      case "seek": {
        if (count === 0) return s;
        const index = Math.min(last, Math.max(0, Math.trunc(a.index)));
        return move(s, index, "seek", false);
      }
      case "restart":
        return count === 0 ? s : move(s, 0, "restart", false);
    }
  };
}

/**
 * 단계 수(count)와 기록 열쇠(recordingKey)로 재생 상태를 만든다. 새 기록이 오면 처음 단계로 돌아간다.
 * 재생 중에는 intervalMs마다 한 단계씩 넘긴다. 탭이 숨겨지면 멈춘다.
 */
export function usePlayback(count: number, recordingKey: unknown) {
  const reducer = useMemo(() => playbackReducer(count), [count]);
  const [state, dispatch] = useReducer(reducer, undefined, () => initialPlayback());

  useEffect(() => {
    dispatch({ type: "reset", count });
  }, [recordingKey, count]);

  useEffect(() => {
    if (!state.playing) return;
    const t = window.setTimeout(() => dispatch({ type: "tick" }), state.intervalMs);
    return () => window.clearTimeout(t);
  }, [state.playing, state.index, state.intervalMs, state.transition.revision]);

  useEffect(() => {
    const onHide = () => {
      if (document.hidden) dispatch({ type: "pause" });
    };
    document.addEventListener("visibilitychange", onHide);
    return () => {
      document.removeEventListener("visibilitychange", onHide);
      dispatch({ type: "pause" });
    };
  }, []);

  const play = useCallback(() => dispatch({ type: "play" }), []);
  const pause = useCallback(() => dispatch({ type: "pause" }), []);
  const next = useCallback(() => dispatch({ type: "next" }), []);
  const previous = useCallback(() => dispatch({ type: "previous" }), []);
  const seek = useCallback((index: number) => dispatch({ type: "seek", index }), []);
  const restart = useCallback(() => dispatch({ type: "restart" }), []);
  const setIntervalMs = useCallback((ms: number) => dispatch({ type: "interval", ms }), []);
  const controls: PlaybackControls = useMemo(() => ({ play, pause, next, previous, seek, restart, setIntervalMs }), [play, pause, next, previous, seek, restart, setIntervalMs]);

  const index = count === 0 ? -1 : Math.min(state.index, count - 1);
  return {
    state: { ...state, index: Math.max(0, index) },
    controls,
    canNext: count > 0 && index < count - 1,
    canPrevious: index > 0,
  };
}
