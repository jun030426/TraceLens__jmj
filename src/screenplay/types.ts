export type PrimitiveKind = 'variables' | 'callStack' | 'sequence' | 'objectGraph' | 'generic'
export type Pacing = 'slow' | 'normal' | 'fast'

export type Scene = {
  seqStart: number
  seqEnd: number
  primitive: PrimitiveKind
  focus: string[]
  pacing: Pacing
  repeat?: number
  narration: { template: string; bindings: Record<string, { seq: number; name: string }> }
}

export type Chapter = { title: string; scenes: Scene[] }
export type Screenplay = { chapters: Chapter[] }
