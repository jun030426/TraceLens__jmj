import type { Pacing, Scene, Screenplay } from '../screenplay/types'
import type { Rect, StageLayout } from './layout'
import type { CompareTarget, Motion, Shot, StagePlan } from './types'

const FACTOR: Record<Pacing, number> = { slow: 1.5, normal: 1, fast: 0.6 }
const MAX_ZOOM_SCENES = 3 // AI가 남발해도 연출은 절제된다 — 결정적 캡
const MAX_HOLD_SCENES = 2

// zoom의 대상은 AI가 아니라 여기서 찾는다 — 그 구간의 사실 중 가장 구체적인 것:
// 비교가 짚은 상자 → focus 객체 → focus 프레임. 없으면 zoom은 조용히 무시된다.
function zoomRectOf(sceneShots: Shot[], layout: StageLayout): { rect: Rect; shotIdx: number } | null {
  for (let i = 0; i < sceneShots.length; i++) {
    const sh = sceneShots[i]
    const cmp = sh.motions.find(m => m.v === 'compare') as { targets: CompareTarget[] } | undefined
    const cell = cmp?.targets.find(t => t.kind === 'cell') as { objectId: number } | undefined
    if (cell) {
      const r = layout.objPos.get(cell.objectId)
      if (r) return { rect: r, shotIdx: i }
    }
    if (sh.focus?.kind === 'object') {
      const r = layout.objPos.get(sh.focus.objectId)
      if (r) return { rect: r, shotIdx: i }
    }
  }
  for (let i = 0; i < sceneShots.length; i++) {
    const sh = sceneShots[i]
    if (sh.focus?.kind === 'frame') {
      const r = layout.framePos.get(sh.focus.frameId)
      if (r) return { rect: r, shotIdx: i }
    }
  }
  return null
}

// 연출 무대에서는 구성이 이미 액션을 중앙에 두므로, zoom은 "중앙으로 당겨 보기"다.
// (대상 rect는 zoomRectOf가 "확대할 가치가 있는가"의 게이트로만 쓴다)
function cameraFor(_rect: Rect, layout: StageLayout): Motion {
  const k = 1.45
  return {
    v: 'camera',
    k,
    x: (layout.width / 2) * (1 - k),
    y: (layout.height / 2) * (1 - k),
  }
}

const CAMERA_RESET: Motion = { v: 'camera', k: 1, x: 0, y: 0 }

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
  let zoomBudget = MAX_ZOOM_SCENES
  let holdBudget = MAX_HOLD_SCENES
  const camAt = new Map<Shot, Motion>()
  const lateResets: Shot[] = []
  const holdAt = new Set<Shot>()
  const skipped = new Set<Scene>()
  for (const sc of scenes) {
    const verbs = sc.direction ?? []
    const sceneShots = shotsOf.get(sc) ?? []
    if (sceneShots.length === 0) continue
    if (verbs.includes('skip')) {
      skipped.add(sc)
      continue
    }
    if (verbs.includes('zoom') && zoomBudget > 0) {
      const target = zoomRectOf(sceneShots, layout)
      if (target) {
        zoomBudget -= 1
        const targetShot = sceneShots[target.shotIdx]
        camAt.set(targetShot, cameraFor(target.rect, layout))
        const last = sceneShots[sceneShots.length - 1]
        if (last !== targetShot) {
          camAt.set(last, CAMERA_RESET)
        } else {
          // 줌 샷이 곧 장면의 끝 — 복귀는 다음 샷에서 (다음 샷이 또 줌이면 그 줌이 이어받는다)
          const next = shots[shots.indexOf(last) + 1]
          if (next) lateResets.push(next)
        }
      }
    }
    if (verbs.includes('hold') && holdBudget > 0) {
      holdBudget -= 1
      holdAt.add(sceneShots[sceneShots.length - 1])
    }
  }
  for (const sh of lateResets) if (!camAt.has(sh)) camAt.set(sh, CAMERA_RESET)

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
    const cam = camAt.get(sh)
    if (cam) motions = [...motions, cam]

    return { ...sh, durationMs, motions }
  })
}
