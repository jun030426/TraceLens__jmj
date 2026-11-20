import type { TraceEvent } from './trace/types.ts'
import { buildStage } from './film/buildStage.ts'
import { layoutStage, type StageLayout } from './film/layout.ts'
import { choreograph } from './film/choreograph.ts'
import { decorateShots } from './film/decorate.ts'
import { applyGrammarPacing } from './film/presets.ts'
import { directByRule } from './film/ruleDirection.ts'
import type { SourceLang } from './film/sourceRules.ts'
import type { Shot, StagePlan } from './film/types.ts'
import { buildScreenplay } from './screenplay/ruleDirector.ts'

export type Film = {
  plan: StagePlan
  layout: StageLayout
  shots: Shot[]
  /** 샷마다 속한 챕터 제목 — 진행바·자막 머리표 */
  chapterOf: string[]
  chapters: string[]
  /** 원본 실행 기록 — 3D 무대가 샷마다 실제 값을 다시 읽는다 */
  events: TraceEvent[]
  /** 수업 언어 — 언어마다 시각화 캐릭터가 다르다 */
  lang: SourceLang
}

/**
 * 실행 기록 → 재생할 필름. 전부 규칙이다 (AI 호출 없음).
 * 렌더러(지금의 2D WorldStage, 이후의 3D 무대)는 이 결과만 받는다:
 * plan = 등장인물, layout = 기본 자리, shots[].motions = 샷마다 일어나는 동작, caption = 자막.
 */
export function buildFilm(events: TraceEvent[], code: string, lang: SourceLang, runError?: string): Film {
  const plan = buildStage(events)
  const layout = layoutStage(plan)
  const raw = choreograph(events, plan, code, runError, lang)
  const screenplay = directByRule(buildScreenplay(events), raw)
  const shots = applyGrammarPacing(decorateShots(raw, screenplay, plan, layout))
  const titled = screenplay.chapters.flatMap(ch => ch.scenes.map(sc => ({ title: ch.title, from: sc.seqStart })))
  const chapterOf = shots.map(sh => {
    let title = titled[0]?.title ?? ''
    for (const t of titled) if (t.from <= sh.seq) title = t.title
    return title
  })
  return { plan, layout, shots, chapterOf, chapters: screenplay.chapters.map(c => c.title), events, lang }
}
