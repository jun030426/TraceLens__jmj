export type Value =
  | { k: 'prim'; v: string; t: string }
  | { k: 'ref'; id: number }

export type ObjectSnap = {
  id: number
  type: string
  items?: Value[]
  entries?: [string, Value][]
  /** 실제 원소 수 — 20개 상한으로 잘려도 화면이 "20 / 500"이라고 말할 수 있게 (빌트인 컬렉션만) */
  n?: number
  truncated?: boolean
  unsupported?: boolean
}

export type LocalsDelta = { name: string; op: 'set' | 'delete'; value?: Value }
export type ObjectsDelta = { op: 'set' | 'delete'; obj?: ObjectSnap; id?: number }

export type TraceEvent = {
  seq: number
  kind: 'line' | 'call' | 'return' | 'exception'
  frameId: number
  parentFrameId: number | null
  func: string
  causedByLine: number | null
  observedAtLine: number
  localsDelta: LocalsDelta[]
  objectsDelta: ObjectsDelta[]
  stdout: string
  error?: string
  /** return 이벤트의 반환값 — sys.settrace의 arg. 예외 unwind와 None은 실리지 않는다
      (arg=None이 `return None`과 구분되지 않으므로 없는 반환을 지어내지 않는다) */
  returned?: Value
}

/** 구문 오류의 구조 정보 — 파서가 아는 사실. 실행은 0줄이었다 (트레이서가 compile 단계에서 싣는다) */
export type SyntaxErrorInfo = {
  name: string // SyntaxError | IndentationError | TabError
  line: number | null
  offset: number | null // 1-기준 글자 위치
  text: string | null // 문제의 소스 줄 (개행 제거)
  msg: string
}

export type TraceResult = {
  events: TraceEvent[]
  clipped: boolean
  error?: string
  syntaxError?: SyntaxErrorInfo
}

export const MAX_EVENTS = 20000   // 스파이크 실측 근거: fib(15)=7,896 이벤트, 20k×~300B ≈ 6MB
export const EXEC_TIMEOUT_MS = 10000
