// @vitest-environment jsdom
import { describe, it, expect, vi } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { usePlayback } from './usePlayback'
import type { PlaybackStep } from './expand'

const step = (seq: number): PlaybackStep =>
  ({ seq, chapterIndex: 0, primitive: 'variables', focus: [], narration: '', durationMs: 100 })

describe('usePlayback', () => {
  it('play하면 전진하고 끝에서 멈춘다', () => {
    vi.useFakeTimers()
    const { result } = renderHook(() => usePlayback([step(0), step(1), step(2)]))
    act(() => result.current.play())
    act(() => vi.advanceTimersByTime(120))
    expect(result.current.index).toBe(1)
    act(() => vi.advanceTimersByTime(300))
    expect(result.current.index).toBe(2)
    expect(result.current.playing).toBe(false)
    vi.useRealTimers()
  })
  it('seek은 즉시 반영되고 재생을 멈춘다', () => {
    const { result } = renderHook(() => usePlayback([step(0), step(1), step(2)]))
    act(() => result.current.seek(2))
    expect(result.current.index).toBe(2)
    expect(result.current.playing).toBe(false)
  })
  it('배속이 대기 시간을 줄인다', () => {
    vi.useFakeTimers()
    const { result } = renderHook(() => usePlayback([step(0), step(1)]))
    act(() => result.current.setSpeed(2))
    act(() => result.current.play())
    act(() => vi.advanceTimersByTime(60))
    expect(result.current.index).toBe(1)
    vi.useRealTimers()
  })
})
