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
  /** unwound — 오류에 밀려 닫히는 프레임 (pendingCrash가 선 채 반환). 자막이 갈라진다 */
  | { v: 'popFrame'; frameId: number; unwound?: true }
  /** 반환 칩 — 닫히는 프레임 카드에서 값이 떠서 부모 카드로 내려앉는다.
      트레이스의 returned가 있을 때만 (예외 unwind·None은 애초에 오지 않는다) */
  | { v: 'returnValue'; frameId: number; toFrameId: number; text: string }
  | { v: 'stdout'; text: string }
  | { v: 'shake'; frameId: number }
  /** passed — 같은 오류의 재관측(전파). 발생과 다른 문장을 받는다 */
  | { v: 'raise'; frameId: number; text: string; passed?: true; caught?: true }
  | { v: 'loop'; text: string }
  /** 터진 실행의 마침표 — 잡히지 않은 예외로 모듈 프레임이 닫힐 때. 자막이 멈춤을 말하고
      축하(sortedSweep)를 접는 근거가 된다. 렌더는 없음 — 오류 스트립은 raise가 이미 세웠다 */
  | { v: 'crashEnd'; text: string }
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
  /** 전부가 아니다 — 상한에 잘렸거나(shown/total) 안을 볼 수 없는(total 없음) 상자.
      화면이 아는 것과 모르는 것의 경계를 스스로 밝힌다 */
  | { v: 'partial'; objectId: number; shown: number; total?: number }
  /** 커튼콜 — 리스트가 실제로 오름차순으로 끝났을 때만 방출되는 "정렬 완성" 스윕 */
  | { v: 'sortedSweep'; objectId: number }
  /** 인덱스 변수 선언 — 소스에서 NAME[IDX]로 접지된 변수는 알약이 아니라 그 배열 아래 화살표로 산다 */
  | { v: 'pointer'; varKey: string; objectId: number }
  /** 이름이 겹쳐 알약에서 물러난 그 프레임의 변수들 — 값은 프레임 카드가 든다.
      varKeys는 구성이 알약에서 뺄 목록, texts는 카드가 적을 `이름 = 값` (같은 순서).
      바뀔 때만 방출한다 (label·partial과 같은 스크럽 안전 패턴) */
  | { v: 'foldVars'; frameId: number; varKeys: string[]; texts: string[] }

export type Shot = {
  seq: number
  motions: Motion[]
  durationMs: number
  focus: { kind: 'object'; objectId: number } | { kind: 'frame'; frameId: number } | null
  timelapse?: number
  /** 학습자 자막 — 모션에서 결정적으로 생성된 한 문장. 화면과 원리적으로 일치한다 */
  caption?: string
}
