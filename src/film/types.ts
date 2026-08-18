export type Lifespan = { from: number; to: number }

export type CastObject = {
  objectId: number
  type: string
  life: Lifespan
  maxItems: number
  changeCount: number
  referencedBy: string[]
  slot: number
  /** 균일한 2차원 프림 리스트 — 한 줄 상자 대신 격자로 그린다. binary = 전 칸이 0/1 (벽 스타일) */
  grid?: { rows: number; cols: number; binary: boolean }
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
  | { v: 'swap'; objectId: number; i: number; k: number; iText: string; kText: string }
  | { v: 'exitObj'; objectId: number }
  | { v: 'pushFrame'; frameId: number }
  | { v: 'popFrame'; frameId: number }
  | { v: 'stdout'; text: string }
  | { v: 'shake'; frameId: number }
  | { v: 'raise'; frameId: number; text: string }
  | { v: 'loop'; text: string }
  | { v: 'loopEnd' }
  | { v: 'compare'; text: string; targets: CompareTarget[] }
  | { v: 'spotlight'; varKeys: string[] }
  | { v: 'camera'; k: number; x: number; y: number }
  | { v: 'gridCell'; objectId: number; r: number; c: number; text: string; wall: boolean }
  | { v: 'gridVisit'; objectId: number; r: number; c: number }
  | { v: 'gridUnvisit'; objectId: number; r: number; c: number }
  | { v: 'gridCursor'; objectId: number; r: number; c: number }
  | { v: 'gridTrail'; objectId: number; points: [number, number][] }

export type Shot = {
  seq: number
  motions: Motion[]
  durationMs: number
  focus: { kind: 'object'; objectId: number } | { kind: 'frame'; frameId: number } | null
  timelapse?: number
}
