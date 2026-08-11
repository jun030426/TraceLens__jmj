import type { Snapshot } from '../trace/snapshots'
import type { PlaybackStep } from '../player/expand'
import VariablesView from './views/VariablesView'
import CallStackView from './views/CallStackView'
import SequenceView from './views/SequenceView'
import ObjectGraphView from './views/ObjectGraphView'

export default function Stage({ snapshot, step }: { snapshot?: Snapshot; step?: PlaybackStep }) {
  if (!snapshot || !step) {
    return <div className="stage-empty">Run을 누르면 실행 영상이 시작됩니다</div>
  }
  const props = { snapshot, focus: step.focus }
  switch (step.primitive) {
    case 'sequence': return <SequenceView {...props} />
    case 'objectGraph': return <ObjectGraphView {...props} />
    case 'callStack': return <CallStackView {...props} />
    default: return <VariablesView {...props} />
  }
}
