import type { Snapshot } from '../trace/snapshots'
import { valueLabel } from '../player/expand'

// 일시정지 시에만 표시 — 확정된 seq의 상태를 그대로 조회 (semantic timeline)
export default function Inspector({ snapshot }: { snapshot: Snapshot }) {
  return (
    <div className="inspector-panel" aria-label="상태 인스펙터">
      <h3>일시정지 · seq {snapshot.seq} 상태</h3>
      <table>
        <tbody>
          {snapshot.stack.flatMap(f =>
            [...f.locals.entries()].map(([name, v]) => (
              <tr key={`${f.frameId}-${name}`}>
                <td>{f.func === '<module>' ? name : `${f.func}.${name}`}</td>
                <td>{valueLabel(v, snapshot.objects)}</td>
              </tr>
            )),
          )}
          {snapshot.stdout && (
            <tr>
              <td>stdout</td>
              <td style={{ whiteSpace: 'pre-wrap' }}>{snapshot.stdout}</td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  )
}
