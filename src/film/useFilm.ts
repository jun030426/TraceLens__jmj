import { useCallback, useRef, useState } from 'react'
import type { Shot } from './types'

/** 이 훅이 타임라인에게 요구하는 것 전부 — GSAP 타임라인이 이 모양을 만족한다 */
export type Timeline = {
  timeScale(x: number): unknown
  eventCallback(name: string, cb: (() => void) | null): unknown
  time(): number
  time(t: number): unknown
  progress(): number
  progress(p: number): unknown
  play(): unknown
  pause(): unknown
}

// 재생 제어가 "스텝 번호 전진"이 아니라 "타임라인 시간 이동"이다.
// 그래서 모션 도중에도 멈출 수 있고 스크럽이 부드럽다.
export function useFilm(shots: Shot[]) {
  const tlRef = useRef<Timeline | null>(null)
  const [index, setIndex] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeed] = useState(1)
  const speedRef = useRef(speed)
  speedRef.current = speed

  const register = useCallback(
    (tl: Timeline | null) => {
      tlRef.current = tl
      setIndex(0)
      setPlaying(false)
      if (!tl) return
      tl.timeScale(speedRef.current)
      const bounds: number[] = []
      let acc = 0
      for (const s of shots) {
        acc += s.durationMs / 1000
        bounds.push(acc)
      }
      tl.eventCallback('onUpdate', () => {
        const t = tl.time()
        let i = bounds.findIndex(b => t <= b)
        if (i < 0) i = shots.length - 1
        setIndex(Math.max(0, i))
      })
      tl.eventCallback('onComplete', () => setPlaying(false))
    },
    [shots],
  )

  const play = useCallback(() => {
    const tl = tlRef.current
    if (!tl) return
    if (tl.progress() >= 1) tl.progress(0)
    tl.play()
    setPlaying(true)
  }, [])

  const pause = useCallback(() => {
    tlRef.current?.pause()
    setPlaying(false)
  }, [])

  const seek = useCallback(
    (shotIndex: number) => {
      const tl = tlRef.current
      if (!tl) return
      const clamped = Math.max(0, Math.min(shotIndex, shots.length - 1))
      const t = shots.slice(0, clamped).reduce((a, s) => a + s.durationMs / 1000, 0)
      tl.pause()
      tl.time(t)
      setIndex(clamped)
      setPlaying(false)
    },
    [shots],
  )

  const changeSpeed = useCallback((x: number) => {
    setSpeed(x)
    tlRef.current?.timeScale(x)
  }, [])

  return { index, playing, speed, play, pause, seek, setSpeed: changeSpeed, register }
}
