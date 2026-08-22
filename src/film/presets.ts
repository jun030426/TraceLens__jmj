import type { Shot } from './types'

/* 연출 문법 — 프리셋 3종 실험(2026-08-19)의 수렴 결과.
   팀 채점: 리듬은 물성(2번) 승 → 긴 예고·묵직한 착지·느긋한 행동 완급 채택.
   보상은 완성 스윕(색 정착)만 생존. 시선·물성 축은 파라미터가 아니라 구조의
   문제로 판정 — 시선은 인덱스 포인터화로, 물성은 값 토큰 지속성(다음 수술)으로 푼다. */

export type StyleGrammar = {
  /** 비화자(비포커스) 배우의 불투명도 */
  dimIdle: number
  /** 카메라가 행동보다 먼저 도착하는 시간(초) */
  camLead: number
  /** 예고(들썩) 길이(초) — 교환·값 이동 직전 */
  anticipation: number
  /** 착지 이징 */
  settleEase: string
  /** 완급 배수 — 판단(비교)·행동(교환) 샷 */
  paceCompare: number
  paceSwap: number
  /** 쓰기 플래시 피크 불투명도 */
  flashStrength: number
  /** 완성 스윕 펄스 배율 */
  sweepPop: number
}

export const GRAMMAR: StyleGrammar = {
  dimIdle: 0.5,
  camLead: 0.15,
  anticipation: 0.24,
  settleEase: 'back.out(1.2)',
  paceCompare: 1.1,
  paceSwap: 1.4,
  flashStrength: 0.5,
  sweepPop: 1.1,
}

/** 완급 배수를 샷 길이에 반영 — useFilm 경계와 타임라인이 같은 배열을 봐야 하므로
    렌더가 아니라 여기(데이터)에서 늘린다 */
export function applyGrammarPacing(shots: Shot[], g: StyleGrammar = GRAMMAR): Shot[] {
  return shots.map(sh => {
    const hasSwap = sh.motions.some(m => m.v === 'swap')
    const hasCmp = !hasSwap && sh.motions.some(m => m.v === 'compare')
    const mul = hasSwap ? g.paceSwap : hasCmp ? g.paceCompare : 1
    return mul === 1 ? sh : { ...sh, durationMs: Math.round(sh.durationMs * mul) }
  })
}
