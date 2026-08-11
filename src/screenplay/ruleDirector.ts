import type { TraceEvent } from '../trace/types'
import { buildSnapshots, aliasGroups } from '../trace/snapshots'
import type { Screenplay, Chapter, Scene, PrimitiveKind } from './types'

const focusNames = (e: TraceEvent) => e.localsDelta.map(d => d.name)

export function buildScreenplay(events: TraceEvent[]): Screenplay {
  if (events.length === 0) return { chapters: [] }
  const snaps = buildSnapshots(events)
  const lineCount = new Map<string, number>()

  const sceneFor = (e: TraceEvent, i: number): Scene => {
    const aliases = aliasGroups(snaps[i])
    const touchedAlias = aliases.find(g =>
      e.objectsDelta.some(d => d.obj?.id === g.id) ||
      e.localsDelta.some(d => d.value?.k === 'ref' && d.value.id === g.id))
    let primitive: PrimitiveKind = 'variables'
    let template = ''
    const bindings: Scene['narration']['bindings'] = {}
    const firstSet = e.localsDelta.find(d => d.op === 'set')

    if (e.kind === 'call') {
      if (e.func === '<module>') { primitive = 'variables'; template = '실행을 시작합니다' }
      else { primitive = 'callStack'; template = `${e.func} 함수가 호출됩니다` }
    }
    else if (e.kind === 'return') {
      if (e.func === '<module>') { primitive = 'variables'; template = '실행이 끝났습니다' }
      else { primitive = 'callStack'; template = `${e.func} 함수가 값을 돌려주고 종료됩니다` }
    }
    else if (e.kind === 'exception') { primitive = 'variables'; template = `여기서 ${e.error ?? '예외'}가 발생합니다` }
    else if (touchedAlias) {
      primitive = 'objectGraph'
      const [a, b] = touchedAlias.names
      template = e.localsDelta.some(d => d.value?.k === 'ref')
        ? `${b}는 새 객체가 아니라 ${a}와 같은 객체를 가리킵니다`
        : `${touchedAlias.names.join('/')}가 함께 변경됩니다 — 같은 객체이기 때문입니다`
    }
    else if (e.objectsDelta.some(d => ['list', 'tuple', 'set'].includes(d.obj?.type ?? ''))) {
      primitive = 'sequence'
      const name = firstSet?.name ?? focusNames(e)[0] ?? '컬렉션'
      template = `${name}의 내용이 변경됩니다`
    }
    else if (firstSet) {
      template = `${firstSet.name}이(가) {value}로 설정됩니다`
      bindings.value = { seq: e.seq, name: firstSet.name }
    }
    else template = `${e.observedAtLine}행으로 이동합니다`

    return {
      seqStart: e.seq, seqEnd: e.seq, primitive,
      focus: focusNames(e), pacing: touchedAlias ? 'slow' : 'normal',
      narration: { template, bindings },
    }
  }

  const scenes: Scene[] = []
  let folding: Scene | null = null
  events.forEach((e, i) => {
    const key = `${e.frameId}:${e.observedAtLine}`
    const n = (lineCount.get(key) ?? 0) + 1
    lineCount.set(key, n)
    if (n >= 3 && e.kind === 'line') {
      if (folding) { folding.seqEnd = e.seq; folding.repeat = (folding.repeat ?? 1) + 1 }
      else folding = {
        seqStart: e.seq, seqEnd: e.seq, primitive: 'variables', focus: [],
        pacing: 'fast', repeat: 1,
        narration: { template: '같은 반복이 계속됩니다', bindings: {} },
      }
      return
    }
    if (folding) { scenes.push(folding); folding = null }
    scenes.push(sceneFor(e, i))
  })
  if (folding) scenes.push(folding)

  const bySeq = new Map(events.map(e => [e.seq, e]))
  const chapters: Chapter[] = []
  let current: Chapter = { title: '변수 준비', scenes: [] }
  let sawCall = false
  for (const sc of scenes) {
    const ev = bySeq.get(sc.seqStart)!
    if (ev.kind === 'call' && ev.parentFrameId === 0) {
      if (current.scenes.length) chapters.push(current)
      current = { title: `${ev.func} 실행`, scenes: [sc] }
      sawCall = true
      continue
    }
    if (ev.kind === 'exception' && current.title !== '예외 발생') {
      if (current.scenes.length) chapters.push(current)
      current = { title: '예외 발생', scenes: [sc] }
      continue
    }
    if (sawCall && ev.frameId === 0 && ev.kind === 'line' && current.title.endsWith('실행')) {
      chapters.push(current)
      current = { title: '마무리', scenes: [sc] }
      sawCall = false
      continue
    }
    current.scenes.push(sc)
  }
  if (current.scenes.length) chapters.push(current)
  if (chapters.length === 1) chapters[0].title = '실행'
  return { chapters }
}
