import type { Snapshot } from '../trace/snapshots'
import type { PlaybackStep } from '../player/expand'
import VariablesView from './views/VariablesView'
import CallStackView from './views/CallStackView'
import SequenceView from './views/SequenceView'
import ObjectGraphView from './views/ObjectGraphView'

const refsOf = (s: Snapshot) => s.stack.flatMap(f => [...f.locals.values()]).filter(v => v.k === 'ref')

/** 고른 그림이 그릴 게 없으면 빈 화면을 내놓지 않고 값 단위로 내려간다 (기획안 §7 폴백) */
function canRender(primitive: PlaybackStep['primitive'], s: Snapshot): boolean {
  if (primitive === 'sequence') return refsOf(s).some(v => v.k === 'ref' && (s.objects.get(v.id)?.items?.length ?? 0) > 0)
  if (primitive === 'objectGraph') return refsOf(s).some(v => v.k === 'ref' && s.objects.has(v.id))
  if (primitive === 'callStack') return s.stack.length > 0
  return true
}

export default function Stage({ snapshot, step }: { snapshot?: Snapshot; step?: PlaybackStep }) {
  if (!snapshot || !step) {
    return (
      <div className="stage-empty">
        왼쪽에 파이썬 코드를 붙여넣고 실행을 누르면, 그 실행이 남긴 기록이 여기에 그려집니다
      </div>
    )
  }
  const props = { snapshot, focus: step.focus }
  const primitive = canRender(step.primitive, snapshot) ? step.primitive : 'variables'
  switch (primitive) {
    case 'sequence':
      return <SequenceView {...props} />
    case 'objectGraph':
      return <ObjectGraphView {...props} />
    case 'callStack':
      return <CallStackView {...props} />
    default:
      return <VariablesView {...props} />
  }
}
