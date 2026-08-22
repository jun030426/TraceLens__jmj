import { ChevronLeft, ChevronRight, Pause, Play, RotateCcw } from 'lucide-react'
import type { PlaybackStep } from '../player/expand'
import type { Screenplay } from '../screenplay/types'

const speedOptions = [0.5, 1, 1.5, 2]

type Props = {
  steps: PlaybackStep[]
  screenplay: Screenplay
  index: number
  playing: boolean
  speed: number
  onPlay(): void
  onPause(): void
  onSeek(i: number): void
  onSpeed(x: number): void
}

export default function PlayerBar({ steps, screenplay, index, playing, speed, onPlay, onPause, onSeek, onSpeed }: Props) {
  const chapters = screenplay.chapters
  const currentChapter = chapters[steps[index]?.chapterIndex ?? 0]

  // 챕터별 스텝 수 → 진행바 세그먼트 폭
  const counts = chapters.map((_, ci) => steps.filter(s => s.chapterIndex === ci).length)
  const total = steps.length || 1

  const seekWithin = (ci: number, ratio: number) => {
    const inChapter = steps.map((s, i) => ({ s, i })).filter(x => x.s.chapterIndex === ci)
    if (!inChapter.length) return
    const pick = inChapter[Math.min(inChapter.length - 1, Math.floor(ratio * inChapter.length))]
    onSeek(pick.i)
  }

  return (
    <div className="playback">
      <div className="chapter-progress" aria-label="챕터 진행바">
        {chapters.map((ch, ci) => {
          const before = steps.filter(s => s.chapterIndex < ci).length
          const inCh = counts[ci]
          const done = Math.max(0, Math.min(inCh, index + 1 - before))
          return (
            <div
              key={ci}
              className="chapter-seg"
              style={{ flexGrow: Math.max(inCh, 1) / total }}
              title={ch.title}
              onClick={e => {
                const r = e.currentTarget.getBoundingClientRect()
                seekWithin(ci, (e.clientX - r.left) / r.width)
              }}
            >
              <div className="seg-fill" style={{ transform: `scaleX(${done / Math.max(inCh, 1)})` }} />
            </div>
          )
        })}
      </div>

      <div className="primary-control">
        <button type="button" onClick={() => onSeek(0)} title="처음으로" aria-label="처음으로">
          <RotateCcw size={15} />
        </button>
        <button type="button" onClick={() => onSeek(index - 1)} title="이전 장면" aria-label="이전 장면">
          <ChevronLeft size={17} />
        </button>
        <button
          className="accent"
          type="button"
          onClick={playing ? onPause : onPlay}
          title={playing ? '일시정지' : '재생'}
          aria-label={playing ? '일시정지' : '재생'}
        >
          {playing ? <Pause size={16} fill="currentColor" /> : <Play size={16} fill="currentColor" />}
        </button>
        <button type="button" onClick={() => onSeek(index + 1)} title="다음 장면" aria-label="다음 장면">
          <ChevronRight size={17} />
        </button>

        <span className="tl-playhead">
          {currentChapter?.title ?? ''} · <span className="tl-num">{index + 1}/{steps.length}</span>
        </span>

        <div className="speed-control" aria-label="재생 속도">
          <span>배속</span>
          <div className="speed-options">
            {speedOptions.map(x => (
              <button key={x} type="button" aria-pressed={speed === x} onClick={() => onSpeed(x)}>
                {x}×
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
