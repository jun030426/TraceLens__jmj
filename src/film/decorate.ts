import type { Pacing, Screenplay } from '../screenplay/types'
import type { Shot, StagePlan } from './types'

const FACTOR: Record<Pacing, number> = { slow: 1.5, normal: 1, fast: 0.6 }

// AI 대본은 완급과 시선만 보탠다 — 모션 종류·값·좌표는 규칙 콘티의 것 그대로.
// AI가 없거나 실패하면 이 함수가 안 불릴 뿐, 영화는 이미 완성돼 있다.
export function decorateShots(shots: Shot[], screenplay: Screenplay, plan: StagePlan): Shot[] {
  const scenes = screenplay.chapters.flatMap(c => c.scenes)
  return shots.map(sh => {
    if (sh.timelapse) return sh // 압축 샷은 이미 자기 리듬이 있다
    const sc = scenes.find(s => sh.seq >= s.seqStart && sh.seq <= s.seqEnd)
    if (!sc) return sh
    const durationMs = Math.min(1800, Math.max(220, Math.round(sh.durationMs * FACTOR[sc.pacing])))
    let motions = sh.motions
    if (sc.pacing === 'slow' && sc.focus.length > 0) {
      const varKeys = sc.focus
        .map(name => plan.variables.find(v => v.name === name && v.life.from <= sh.seq && sh.seq <= v.life.to))
        .filter(v => v !== undefined)
        .map(v => v.varKey)
      if (varKeys.length > 0) motions = [...sh.motions, { v: 'spotlight', varKeys }]
    }
    return { ...sh, durationMs, motions }
  })
}
