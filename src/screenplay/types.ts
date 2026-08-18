export type PrimitiveKind = 'variables' | 'callStack' | 'sequence' | 'objectGraph' | 'generic'
export type Pacing = 'slow' | 'normal' | 'fast'

/** 연출 동사 — 대상이 없다. 무엇을 확대할지는 엔진이 그 구간의 사실(비교·focus)에서 찾는다. */
export type DirectingVerb = 'zoom' | 'hold' | 'skip'

export type Scene = {
  seqStart: number
  seqEnd: number
  primitive: PrimitiveKind
  focus: string[]
  pacing: Pacing
  direction: DirectingVerb[]
  repeat?: number
  narration: { template: string; bindings: Record<string, { seq: number; name: string }> }
}

export type Chapter = { title: string; scenes: Scene[] }

/** AI의 표현 선택 — 변수명으로 "격자로 봐라 / 보지 마라"만 고른다. 판정·좌표는 도구가 한다. */
export type Staging = { grid: string[]; noGrid: string[] }

export type Screenplay = { chapters: Chapter[]; staging?: Staging }
