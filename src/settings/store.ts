import { useSyncExternalStore } from 'react'
import { MAX_EVENTS, EXEC_TIMEOUT_MS } from '../trace/types'

export type CaptionSize = 'sm' | 'md' | 'lg'
/** intro = 비유 물체(막대·저울)로 흐름을 보여주는 입문 스킨, precise = 구조 그대로의 정밀 스킨 */
export type Presentation = 'intro' | 'precise'

export type Settings = {
  /** false = local-only: 코드를 외부로 보내지 않고 규칙 기반 대본만 사용 */
  aiDirector: boolean
  autoplay: boolean
  speed: number
  reduceMotion: boolean
  captionSize: CaptionSize
  presentation: Presentation
  maxEvents: number
  timeoutMs: number
}

export const DEFAULTS: Settings = {
  aiDirector: true,
  autoplay: true,
  speed: 1,
  reduceMotion: false,
  captionSize: 'md',
  presentation: 'intro',
  maxEvents: MAX_EVENTS,
  timeoutMs: EXEC_TIMEOUT_MS,
}

export const LIMITS = {
  maxEvents: { min: 500, max: 50000, step: 500 },
  timeoutSec: { min: 3, max: 60, step: 1 },
  speeds: [0.5, 1, 1.5, 2, 4],
} as const

const KEY = 'tracelens.settings.v1'

function read(): Settings {
  if (typeof localStorage === 'undefined') return DEFAULTS
  try {
    const raw = localStorage.getItem(KEY)
    if (!raw) return DEFAULTS
    const parsed = JSON.parse(raw) as Partial<Settings>
    return sanitize({ ...DEFAULTS, ...parsed })
  } catch {
    return DEFAULTS
  }
}

function clamp(n: number, min: number, max: number, fallback: number) {
  return Number.isFinite(n) ? Math.min(max, Math.max(min, Math.round(n))) : fallback
}

function sanitize(s: Settings): Settings {
  return {
    aiDirector: !!s.aiDirector,
    autoplay: !!s.autoplay,
    speed: (LIMITS.speeds as readonly number[]).includes(s.speed) ? s.speed : DEFAULTS.speed,
    reduceMotion: !!s.reduceMotion,
    captionSize: (['sm', 'md', 'lg'] as const).includes(s.captionSize) ? s.captionSize : DEFAULTS.captionSize,
    presentation: (['intro', 'precise'] as const).includes(s.presentation) ? s.presentation : DEFAULTS.presentation,
    maxEvents: clamp(s.maxEvents, LIMITS.maxEvents.min, LIMITS.maxEvents.max, DEFAULTS.maxEvents),
    timeoutMs: clamp(s.timeoutMs, LIMITS.timeoutSec.min * 1000, LIMITS.timeoutSec.max * 1000, DEFAULTS.timeoutMs),
  }
}

let current = read()
const listeners = new Set<() => void>()

function emit() {
  for (const l of listeners) l()
}

export function getSettings(): Settings {
  return current
}

export function setSetting<K extends keyof Settings>(key: K, value: Settings[K]) {
  current = sanitize({ ...current, [key]: value })
  try {
    localStorage.setItem(KEY, JSON.stringify(current))
  } catch {
    /* private mode — 세션 동안만 유지된다 */
  }
  emit()
}

export function resetSettings() {
  current = { ...DEFAULTS }
  try {
    localStorage.removeItem(KEY)
  } catch {
    /* ignore */
  }
  emit()
}

function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

export function useSettings(): Settings {
  return useSyncExternalStore(subscribe, getSettings, () => DEFAULTS)
}

/** OS 설정과 제품 설정 중 하나라도 모션 감소를 원하면 정지한다. */
export function prefersStill(s: Settings): boolean {
  if (s.reduceMotion) return true
  if (typeof window === 'undefined' || !window.matchMedia) return false
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches
}
