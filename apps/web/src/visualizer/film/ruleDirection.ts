import type { Screenplay } from '../screenplay/types.ts'
import type { Shot } from './types.ts'

// 규칙 연출 지시 — AI 감독 대신 사실에서 고른다. 확대(zoom)는 판단·교환·값 이동이 일어난
// 장면, 여운(hold)은 오류와 마지막 장면. 상한·간격은 decorate가 지킨다 (zoom 3곳, hold 2곳).
export function directByRule(screenplay: Screenplay, shots: Shot[]): Screenplay {
  const scenes = screenplay.chapters.flatMap(c => c.scenes)
  const last = scenes[scenes.length - 1]
  const has = (from: number, to: number, kinds: string[]) =>
    shots.some(sh => sh.seq >= from && sh.seq <= to && sh.motions.some(m => kinds.includes(m.v)))
  return {
    ...screenplay,
    chapters: screenplay.chapters.map(ch => ({
      ...ch,
      scenes: ch.scenes.map(sc => {
        const direction: ('zoom' | 'hold')[] = []
        const crash = has(sc.seqStart, sc.seqEnd, ['raise', 'crashEnd'])
        if (sc.pacing !== 'fast' && has(sc.seqStart, sc.seqEnd, ['swap', 'compare', 'travel'])) direction.push('zoom')
        if (crash || sc === last) direction.push('hold')
        return { ...sc, direction, pacing: crash ? 'slow' : sc.pacing }
      }),
    })),
  }
}
