import type { Shot } from './types'

/* 연출 문법 실험 — 기한 있는 실험실.
   "우리만의 엔진"을 만들기 위해 래퍼런스별 장점을 파라미터로 분리했다:
   1 집중(3Blue1Brown) — 시선 통제: 비화자 디밍 강하게, 카메라 선행, 긴 판단 완급
   2 물성(HRM·디즈니 12원칙) — 질량감: 긴 예고, 묵직한 착지, 느긋한 행동 완급
   3 쫀득(Brilliant) — 보상 비트: 빠른 템포, 강한 플래시, 튀는 착지와 완성 펄스

   같은 엔진·같은 의미층 위에서 연출값만 다르다. 팀이 축별(시선/리듬/물성/보상)로
   채점해 승자 조합을 기본값으로 박은 뒤, 이 스위처와 파일은 정리한다. */

export type StylePreset = {
  key: 'focus' | 'mass' | 'snap'
  label: string
  /** 비화자(비포커스) 배우의 불투명도 — 시선 통제의 세기 (1 = 디밍 없음) */
  dimIdle: number
  /** 카메라가 행동보다 먼저 도착하는 시간(초) */
  camLead: number
  /** 예고(들썩) 길이(초) — 교환·값 이동 직전 */
  anticipation: number
  /** 착지 이징 — 값 갱신·교환 정착의 성격 */
  settleEase: string
  /** 완급 배수 — 판단(비교)·행동(교환) 샷의 길이 */
  paceCompare: number
  paceSwap: number
  /** 쓰기 플래시 피크 불투명도 */
  flashStrength: number
  /** 완성 스윕 펄스 배율 */
  sweepPop: number
}

export const PRESETS: readonly StylePreset[] = [
  {
    key: 'focus', label: '1 집중',
    dimIdle: 0.35, camLead: 0.3, anticipation: 0.1, settleEase: 'power2.out',
    paceCompare: 1.35, paceSwap: 1.15, flashStrength: 0.45, sweepPop: 1.06,
  },
  {
    key: 'mass', label: '2 물성',
    dimIdle: 0.7, camLead: 0.15, anticipation: 0.24, settleEase: 'back.out(1.2)',
    paceCompare: 1.1, paceSwap: 1.4, flashStrength: 0.5, sweepPop: 1.08,
  },
  {
    key: 'snap', label: '3 쫀득',
    dimIdle: 0.55, camLead: 0.08, anticipation: 0.05, settleEase: 'back.out(3.2)',
    paceCompare: 0.95, paceSwap: 0.95, flashStrength: 0.7, sweepPop: 1.14,
  },
] as const

/** 완급 배수를 샷 길이에 반영 — useFilm 경계와 타임라인이 같은 배열을 봐야 하므로
    렌더가 아니라 여기(데이터)에서 늘린다 */
export function applyPresetPacing(shots: Shot[], p: StylePreset): Shot[] {
  return shots.map(sh => {
    const hasSwap = sh.motions.some(m => m.v === 'swap')
    const hasCmp = !hasSwap && sh.motions.some(m => m.v === 'compare')
    const mul = hasSwap ? p.paceSwap : hasCmp ? p.paceCompare : 1
    return mul === 1 ? sh : { ...sh, durationMs: Math.round(sh.durationMs * mul) }
  })
}
