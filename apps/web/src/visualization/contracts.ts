// 시각화 화면(VisualizationScreen)이 받는 props와 스냅숏 타입.
// 화면은 이 타입만 알면 된다: 실행·기록·재생 단계 선택은 바깥(Host·playback)이 맡는다.
import type { TraceEventKind, TraceFrame, TraceLanguage, TraceObject, TraceStatus, TraceValue } from "../pythonTrace.ts";
import type { VisualizationEvent } from "./executionEvents.ts";

export type { VisualizationEvent } from "./executionEvents.ts";

export type VariableChangeKind = "added" | "changed" | "removed";

export type VariableChange = {
  /** `${frameId}:${name}` */
  id: string;
  kind: VariableChangeKind;
  frameId: string;
  name: string;
  before?: TraceValue;
  after?: TraceValue;
};

/** 직전 단계와 비교한 변화 목록 */
export type ObservationChanges = {
  variables: { added: VariableChange[]; changed: VariableChange[]; removed: VariableChange[] };
  objects: { added: string[]; changed: string[]; removed: string[] };
  enteredFrames: string[];
  exitedFrames: string[];
};

/** 선택한 단계의 전체 관측 상태 */
export type Observation = {
  /** `step-${index}` — 이 실행 안에서만 유효 */
  id: string;
  index: number;
  /** 관측 종류. events 배열과 별개 */
  event: TraceEventKind;
  nextLine: number | null;
  causedByLine: number | null;
  /** 호출 스택: 바깥 → 안쪽 */
  frames: readonly TraceFrame[];
  objects: Readonly<Record<string, TraceObject>>;
  /** 직전 단계 → 이 단계 사이에 확인된 공통 변화 이벤트 */
  events: readonly VisualizationEvent[];
  changes: ObservationChanges;
  stdout: string;
  error?: string;
  returned?: TraceValue;
};

export type Recording = {
  language: TraceLanguage;
  /** 실행 당시 소스 */
  source: string;
  sourceHash: string;
  steps: readonly Observation[];
  status: TraceStatus;
  message: string | null;
  error: string | null;
  /** 최종 표준 출력 */
  stdout: string;
  /** 빈칸 채우기 실습: 마지막 단계는 아직 안 채운 빈칸 줄 직전이다 (오류가 아니다) */
  blankStop?: { blank: number; line: number } | null;
};

export type TransitionKind = "initial" | "next" | "previous" | "seek" | "restart" | "tick";

export type PlaybackState = {
  index: number;
  playing: boolean;
  intervalMs: number;
  /** 마지막 이동 방법. revision은 이동마다 1씩 늘어난다 (같은 단계로 다시 이동해도) */
  transition: { kind: TransitionKind; revision: number };
};

export type PlaybackControls = {
  play(): void;
  pause(): void;
  next(): void;
  previous(): void;
  seek(index: number): void;
  restart(): void;
  setIntervalMs(ms: number): void;
};

export type VisualizationScreenProps = {
  recording: Recording;
  /** 선택한 단계. 단계가 없으면 null */
  current: Observation | null;
  /** 실행 순서상 바로 전 단계 (사용자가 직전에 보던 화면과 다를 수 있다) */
  previous: Observation | null;
  playback: PlaybackState;
  controls: PlaybackControls;
  canNext: boolean;
  canPrevious: boolean;
  /** 코드가 바뀌어 지금 화면이 이전 실행 기록임 */
  stale: boolean;
  /** 운영체제의 동작 줄이기 설정 */
  reducedMotion: boolean;
};
