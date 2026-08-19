import type { Pacing, Scene, Screenplay } from '../screenplay/types'
import type { StageLayout } from './layout'
import type { CompareTarget, Motion, Shot, StagePlan } from './types'

const FACTOR: Record<Pacing, number> = { slow: 1.5, normal: 1, fast: 0.6 }
const MAX_ZOOM_SCENES = 3 // AI가 남발해도 연출은 절제된다 — 결정적 캡
const MAX_HOLD_SCENES = 2

/** 강조 배율 — 좌표는 배치를 아는 compose가 정한다. 여기서는 "얼마나 당길지"만 말한다 */
const EMPHASIS_K = 1.45
/** 강조끼리의 최소 간격(샷) — 앞쪽에 몰리면 강조가 아니라 도입부 연출이 된다 */
const MIN_EMPHASIS_GAP = 6

// zoom의 대상은 AI가 아니라 여기서 찾는다 — 그 구간의 사실 중 가장 구체적인 것:
// 비교가 짚은 상자 → focus 객체 → focus 프레임. 없으면 zoom은 조용히 무시된다.
// 좌표가 아니라 "어느 샷이 그 비트인가"만 고른다 (배치는 compose의 소유).
function emphasisShotOf(sceneShots: Shot[], layout: StageLayout): number | null {
  for (let i = 0; i < sceneShots.length; i++) {
    const sh = sceneShots[i]
    const cmp = sh.motions.find(m => m.v === 'compare') as { targets: CompareTarget[] } | undefined
    const cell = cmp?.targets.find(t => t.kind === 'cell') as { objectId: number } | undefined
    if (cell && layout.objPos.has(cell.objectId)) return i
    const sw = sh.motions.find(m => m.v === 'swap') as { objectId: number } | undefined
    if (sw && layout.objPos.has(sw.objectId)) return i
    if (sh.focus?.kind === 'object' && layout.objPos.has(sh.focus.objectId)) return i
  }
  // 프레임(호출 카드)은 후보가 아니다 — 하단 HUD라 카메라 그룹 바깥이고, 당겨도 움직이지
  // 않는다. 강조할 수 없는 샷에 예산을 쓰면 강조가 조용히 사라진다 (compose와 기준 일치)
  return null
}

// AI 대본은 완급·시선·연출 동사만 보탠다 — 모션 종류·값·좌표는 규칙 콘티의 것 그대로.
// AI가 없거나 실패하면 이 함수가 안 불릴 뿐, 영화는 이미 완성돼 있다.
export function decorateShots(shots: Shot[], screenplay: Screenplay, plan: StagePlan, layout: StageLayout): Shot[] {
  const scenes = screenplay.chapters.flatMap(c => c.scenes)
  const sceneOf = new Map<Shot, Scene>()
  const shotsOf = new Map<Scene, Shot[]>()
  for (const sh of shots) {
    const sc = scenes.find(s => sh.seq >= s.seqStart && sh.seq <= s.seqEnd)
    if (!sc) continue
    sceneOf.set(sh, sc)
    shotsOf.set(sc, [...(shotsOf.get(sc) ?? []), sh])
  }

  // 연출 동사 → 샷별 계획 (skip이 있으면 그 장면의 zoom·hold는 무시)
  let holdBudget = MAX_HOLD_SCENES
  const holdAt = new Set<Shot>()
  const skipped = new Set<Scene>()
  const candidates: number[] = [] // 강조 후보의 전역 샷 인덱스 (장면 순 = 샷 순)
  for (const sc of scenes) {
    const verbs = sc.direction ?? []
    const sceneShots = shotsOf.get(sc) ?? []
    if (sceneShots.length === 0) continue
    if (verbs.includes('skip')) {
      skipped.add(sc)
      continue
    }
    if (verbs.includes('zoom')) {
      const local = emphasisShotOf(sceneShots, layout)
      if (local !== null) candidates.push(shots.indexOf(sceneShots[local]))
    }
    if (verbs.includes('hold') && holdBudget > 0) {
      holdBudget -= 1
      holdAt.add(sceneShots[sceneShots.length - 1])
    }
  }
  // 앞에서부터 3개가 아니라 고르게 3개 — 붙어 있는 후보는 건너뛴다
  const emphAt = new Set<Shot>()
  let lastPicked = -Infinity
  for (const idx of candidates) {
    if (emphAt.size >= MAX_ZOOM_SCENES) break
    if (idx - lastPicked < MIN_EMPHASIS_GAP) continue
    lastPicked = idx
    emphAt.add(shots[idx])
  }

  return shots.map(sh => {
    if (sh.timelapse) return sh // 압축 샷은 이미 자기 리듬이 있다
    const sc = sceneOf.get(sh)
    if (!sc) return sh

    let durationMs: number
    if (skipped.has(sc)) {
      durationMs = Math.max(150, Math.round(sh.durationMs * 0.3))
    } else {
      durationMs = Math.min(1800, Math.max(220, Math.round(sh.durationMs * FACTOR[sc.pacing])))
      if (holdAt.has(sh)) durationMs = Math.min(3000, Math.round(durationMs * 1.9))
    }

    let motions = sh.motions
    if (!skipped.has(sc) && sc.pacing === 'slow' && sc.focus.length > 0) {
      const varKeys = sc.focus
        .map(name => plan.variables.find(v => v.name === name && v.life.from <= sh.seq && sh.seq <= v.life.to))
        .filter(v => v !== undefined)
        .map(v => v.varKey)
      if (varKeys.length > 0) motions = [...motions, { v: 'spotlight', varKeys }]
    }
    if (emphAt.has(sh)) motions = [...motions, { v: 'emphasis', k: EMPHASIS_K }]

    return { ...sh, durationMs, motions }
  })
}
