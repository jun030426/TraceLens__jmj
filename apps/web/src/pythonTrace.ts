// 세 언어(Python·C·Java)가 공유하는 값·객체·실행 기록 타입. 파일 이름은 호환성을 위해 pythonTrace다.
// 시각화 화면은 이 기록을 직접 읽지 않고 visualization/traceAdapter.ts가 만든 Recording을 받는다.
// 배열 위치와 단계 번호는 0부터, 소스 줄 번호는 1부터 센다.

export type TraceLanguage = "python" | "java" | "c";

/** 값 하나. primitive의 text는 디버거가 준 표시 문자열이다 (숫자로 바꾸지 않는다). */
export type TraceValue = {
  kind: "primitive" | "reference" | "unsupported";
  text?: string;
  /** reference일 때 objects의 키. 찾을 수 없으면 화면은 '찾을 수 없는 참조'로 그린다 */
  object_id?: string | null;
  truncated?: boolean;
};

/** 객체 하나. list·array는 items, Java object·C struct·dict는 entries([키, 값])에 담긴다. */
export type TraceObject = {
  id: string;
  type: string;
  items?: TraceValue[];
  entries?: [string, TraceValue][];
  /** 잘리기 전 실제 원소 수 (items가 잘렸을 때만) */
  length?: number;
  truncated?: boolean;
  unsupported?: boolean;
};

export type TraceVariable = { name: string; value: TraceValue };

/** 호출 스택의 프레임 하나. frames 배열은 바깥(모듈·main) → 안쪽(지금 실행 중) 순서다. */
export type TraceFrame = {
  id: string;
  name: string;
  line: number | null;
  variables: TraceVariable[];
};

export type TraceEventKind = "line" | "call" | "return" | "exception";

/** 관측 한 번 = 단계 하나. 그 순간의 전체 상태를 담는다 (누적 diff가 아니다). */
export type TraceStep = {
  event: TraceEventKind;
  /** 이 상태를 만든 직전 실행 줄 */
  causedByLine: number | null;
  /** 아직 실행하기 전인 다음 줄 */
  nextLine: number | null;
  frames: TraceFrame[];
  objects: Record<string, TraceObject>;
  /** 이 단계까지 쌓인 표준 출력 */
  stdout: string;
  /** exception 단계의 예외 설명 */
  error?: string;
  /** return 단계의 반환값 */
  returned?: TraceValue;
};

export type TraceStatus = "ok" | "error" | "partial";

/** 실행 한 번의 기록. status=partial이면 너무 길어서 앞부분까지만 기록했다는 뜻이다. */
export type ExecutionTrace = {
  language: TraceLanguage;
  status: TraceStatus;
  steps: TraceStep[];
  /** 학생에게 보여 줄 한 줄 안내 (부분 기록 등) */
  message?: string | null;
  /** 실행 오류 */
  error?: string | null;
  /** 최종 표준 출력 */
  stdout: string;
  /** 빈칸 채우기 실습: 안 채운 빈칸 줄 직전에서 기록을 끝냈다 (오류가 아니다) */
  blankStop?: { blank: number; line: number };
};
