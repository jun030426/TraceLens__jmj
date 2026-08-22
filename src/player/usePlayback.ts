import { useCallback, useEffect, useRef, useState } from 'react'
import type { PlaybackStep } from './expand'

// semantic timeline: index가 곧 확정 seq — 애니메이션 중간 상태는 인스펙터에 노출하지 않는다
export function usePlayback(steps: PlaybackStep[]) {
  const [index, setIndex] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeed] = useState(1)
  const timerRef = useRef<number | null>(null)
  const speedRef = useRef(speed)
  speedRef.current = speed

  const clear = () => {
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current)
      timerRef.current = null
    }
  }

  // steps가 (내용 기준으로) 바뀌면 처음으로 — 참조만 바뀐 재렌더에는 반응하지 않는다
  const signature = `${steps.length}:${steps[0]?.seq ?? -1}:${steps[steps.length - 1]?.seq ?? -1}`
  const prevSignature = useRef(signature)
  useEffect(() => {
    if (prevSignature.current !== signature) {
      prevSignature.current = signature
      clear()
      setIndex(0)
      setPlaying(false)
    }
  }, [signature])

  useEffect(() => {
    if (!playing) {
      clear()
      return
    }
    if (index >= steps.length - 1) {
      setPlaying(false)
      return
    }
    const duration = (steps[index]?.durationMs ?? 800) / speedRef.current
    timerRef.current = window.setTimeout(() => setIndex(i => Math.min(i + 1, steps.length - 1)), duration)
    return clear
  }, [playing, index, steps])

  const play = useCallback(() => {
    setIndex(i => (i >= steps.length - 1 ? 0 : i))   // 끝에서 재생하면 처음부터
    setPlaying(true)
  }, [steps.length])

  const pause = useCallback(() => setPlaying(false), [])

  const seek = useCallback((i: number) => {
    clear()
    setPlaying(false)
    setIndex(Math.max(0, Math.min(i, steps.length - 1)))
  }, [steps.length])

  return { index, playing, speed, play, pause, seek, setSpeed }
}
