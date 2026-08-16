export type Lifespan = { from: number; to: number }

export type CastObject = {
  objectId: number
  type: string
  life: Lifespan
  maxItems: number
  changeCount: number
  referencedBy: string[]
  slot: number
}

export type CastVariable = {
  varKey: string
  frameId: number
  name: string
  life: Lifespan
  holdsRef: boolean
}

export type CastFrame = {
  frameId: number
  func: string
  parentFrameId: number | null
  life: Lifespan
  depth: number
  recursionIndex: number
}

export type StagePlan = {
  objects: CastObject[]
  variables: CastVariable[]
  frames: CastFrame[]
  slotCount: number
  maxStackDepth: number
  maxListLength: number
  leadObjectId: number | null
}

export type CompareTarget =
  | { kind: 'cell'; objectId: number; index: number }
  | { kind: 'var'; varKey: string }

export type Motion =
  | { v: 'enterVar'; varKey: string }
  | { v: 'setVar'; varKey: string; text: string }
  | { v: 'exitVar'; varKey: string }
  | { v: 'bind'; varKey: string; objectId: number; alias: boolean }
  | { v: 'enterObj'; objectId: number }
  | { v: 'grow'; objectId: number; index: number; text: string }
  | { v: 'setCell'; objectId: number; index: number; text: string }
  | { v: 'shrink'; objectId: number; index: number }
  | { v: 'exitObj'; objectId: number }
  | { v: 'pushFrame'; frameId: number }
  | { v: 'popFrame'; frameId: number }
  | { v: 'stdout'; text: string }
  | { v: 'shake'; frameId: number }
  | { v: 'raise'; frameId: number; text: string }
  | { v: 'loop'; text: string }
  | { v: 'loopEnd' }
  | { v: 'compare'; text: string; targets: CompareTarget[] }

export type Shot = {
  seq: number
  motions: Motion[]
  durationMs: number
  focus: { kind: 'object'; objectId: number } | { kind: 'frame'; frameId: number } | null
  timelapse?: number
}
