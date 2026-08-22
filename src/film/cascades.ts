import type { TraceEvent } from '../trace/types'

/* 일직선 사슬 감지 — 깊은 재귀의 빨리감기(부록 A 08-22)의 사실 층.
   하강: 같은 함수의 연속 call이 각각 직전 call의 자식인 구간 (사이의 그 프레임 line 포함).
   unwind: 연속 return이 각각 직전 반환의 부모로 이어지는 구간 (같은 함수의 exception 끼임 허용).
   line·이질 call이 끼면 사슬이 끊긴다 — try/except가 잡는 장면은 구조적으로 접히지 않는다.
   문턱은 루프 빨리감기와 같은 10, 머리는 "그 단계가 새 사실을 보여주는 동안"이다:
   하강은 n 알약이, 값 반환은 반환 칩이 매회 새 값이라 10 — 같은 문장의 반복(조용한 종료·
   크래시 전파)은 3이면 선다. 생략분은 정산 샷이 개수로 밝힌다. */

/** 접힌 사슬 — [from, to]의 이벤트는 모션을 내지 않고 정산 샷 하나로 접힌다 */
export type CascadeFold = {
  from: number
  to: number
  count: number
  func: string
  kind: 'descent' | 'unwindValue' | 'unwindQuiet' | 'unwindCrash'
}

export const CHAIN_FULL = 10 // 사슬은 10단까지 온전히 — 루프의 FULL_ITERATIONS와 같은 값
const HEADS_REPEAT = 3 // 새 사실 없는 반복(조용한 종료·크래시 전파)의 머리

export function detectCascades(
  events: TraceEvent[],
  exclude: { from: number; to: number }[] = [],
): CascadeFold[] {
  const folds: CascadeFold[] = []
  const overlaps = (a: number, b: number) => exclude.some(r => a <= r.to && b >= r.from)
  const push = (fold: CascadeFold) => {
    if (!overlaps(fold.from, fold.to)) folds.push(fold)
  }

  // ── 하강 사슬 ──
  let dOpen: { func: string; calls: TraceEvent[]; lastFrame: number } | null = null
  const closeDescent = () => {
    if (dOpen && dOpen.calls.length > CHAIN_FULL) {
      const folded = dOpen.calls.slice(CHAIN_FULL)
      push({
        from: folded[0].seq,
        to: folded[folded.length - 1].seq,
        count: folded.length,
        func: dOpen.func,
        kind: 'descent',
      })
    }
    dOpen = null
  }
  for (const e of events) {
    if (e.kind === 'call') {
      if (dOpen && e.func === dOpen.func && e.parentFrameId === dOpen.lastFrame) {
        dOpen.calls.push(e)
        dOpen.lastFrame = e.frameId
      } else {
        closeDescent()
        dOpen = { func: e.func, calls: [e], lastFrame: e.frameId }
      }
    } else if (e.kind === 'return' || e.kind === 'exception') {
      // 하강이 끝났다 — 되돌아오기 시작했거나 터졌다 (line은 깊은 프레임의 몸통이라 안 끊는다)
      closeDescent()
    }
  }
  closeDescent()

  // ── unwind 사슬 ──
  type Step = { ret: TraceEvent; excSeq?: number }
  let uOpen: { func: string; steps: Step[]; expect: number | null; allReturned: boolean; sawExc: boolean } | null = null
  let pendingExcSeq: number | undefined
  const closeUnwind = () => {
    if (uOpen && uOpen.steps.length > CHAIN_FULL) {
      const heads = uOpen.sawExc || !uOpen.allReturned ? HEADS_REPEAT : CHAIN_FULL
      const folded = uOpen.steps.slice(heads)
      const last = folded[folded.length - 1]
      push({
        // 접힌 첫 단계의 전파(exception)부터 접는다 — 닫힘만 접고 전파를 남기면 문장이 반 토막 난다
        from: folded[0].excSeq ?? folded[0].ret.seq,
        to: last.ret.seq,
        count: folded.length,
        func: uOpen.func,
        kind: uOpen.sawExc ? 'unwindCrash' : uOpen.allReturned ? 'unwindValue' : 'unwindQuiet',
      })
    }
    uOpen = null
    pendingExcSeq = undefined
  }
  for (const e of events) {
    if (e.kind === 'return') {
      if (uOpen && e.frameId === uOpen.expect && e.func === uOpen.func) {
        uOpen.steps.push({ ret: e, ...(pendingExcSeq !== undefined ? { excSeq: pendingExcSeq } : {}) })
        uOpen.expect = e.parentFrameId
        uOpen.allReturned = uOpen.allReturned && e.returned !== undefined
        pendingExcSeq = undefined
      } else {
        closeUnwind()
        uOpen = {
          func: e.func, steps: [{ ret: e }], expect: e.parentFrameId,
          allReturned: e.returned !== undefined, sawExc: false,
        }
      }
    } else if (e.kind === 'exception') {
      // 전파의 재관측이 사슬 위에 도착했다 — 다음 단계(그 프레임의 닫힘)의 앞부분이다
      if (uOpen && e.frameId === uOpen.expect && e.func === uOpen.func) {
        uOpen.sawExc = true
        pendingExcSeq = e.seq
      } else {
        closeUnwind()
      }
    } else {
      // line = 어딘가에서 실행이 재개됐다 (잡혔다), call = 새 하강 — 캐스케이드는 끝났다
      closeUnwind()
    }
  }
  closeUnwind()

  return folds.sort((a, b) => a.from - b.from)
}
