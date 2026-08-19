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
  | { v: 'travel'; from: CompareTarget; to: CompareTarget; text: string }
  | { v: 'enterVar'; varKey: string }
  | { v: 'setVar'; varKey: string; text: string }
  | { v: 'exitVar'; varKey: string }
  | { v: 'bind'; varKey: string; objectId: number; alias: boolean }
  | { v: 'enterObj'; objectId: number }
  | { v: 'grow'; objectId: number; index: number; text: string }
  | { v: 'setCell'; objectId: number; index: number; text: string }
  | { v: 'shrink'; objectId: number; index: number }
  /** 한 칸 삭제 + 당겨짐 — index가 빠지고 뒤 토큰들이 미끄러져 메운다. texts = 슬롯 index..끝의 착지 값 */
  | { v: 'shiftLeft'; objectId: number; index: number; texts: string[] }
  | { v: 'swap'; objectId: number; i: number; k: number; iText: string; kText: string }
  | { v: 'exitObj'; objectId: number }
  | { v: 'pushFrame'; frameId: number }
  | { v: 'popFrame'; frameId: number }
  | { v: 'stdout'; text: string }
  | { v: 'shake'; frameId: number }
  | { v: 'raise'; frameId: number; text: string }
  | { v: 'loop'; text: string }
  | { v: 'loopEnd' }
  /** a·op·b·verdict — 저울 렌더용 구조 필드. detectCompare가 접지한 실제 값이며, 숫자 판정이 안 되면 verdict는 없다 */
  | { v: 'compare'; text: string; targets: CompareTarget[]; a?: string; op?: string; b?: string; verdict?: boolean }
  | { v: 'spotlight'; varKeys: string[] }
  /** 강조 — AI가 "여기가 중요하다"고 표시한 샷. 좌표는 배치를 아는 compose가 산출한다 */
  | { v: 'emphasis'; k: number }
  | { v: 'label'; objectId: number; text: string }
  | { v: 'gridCell'; objectId: number; r: number; c: number; text: string; wall: boolean; flash?: boolean }
  | { v: 'gridVisit'; objectId: number; r: number; c: number }
  | { v: 'gridUnvisit'; objectId: number; r: number; c: number }
  | { v: 'gridCursor'; objectId: number; r: number; c: number }
  | { v: 'gridTrail'; objectId: number; points: [number, number][] }
  /** 커튼콜 — 리스트가 실제로 오름차순으로 끝났을 때만 방출되는 "정렬 완성" 스윕 */
  | { v: 'sortedSweep'; objectId: number }
  /** 인덱스 변수 선언 — 소스에서 NAME[IDX]로 접지된 변수는 알약이 아니라 그 배열 아래 화살표로 산다 */
  | { v: 'pointer'; varKey: string; objectId: number }

export type Shot = {
  seq: number
  motions: Motion[]
  durationMs: number
  focus: { kind: 'object'; objectId: number } | { kind: 'frame'; frameId: number } | null
  timelapse?: number
  /** 학습자 자막 — 모션에서 결정적으로 생성된 한 문장. 화면과 원리적으로 일치한다 */
  caption?: string
}
