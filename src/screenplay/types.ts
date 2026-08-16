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
export type Screenplay = { chapters: Chapter[] }
