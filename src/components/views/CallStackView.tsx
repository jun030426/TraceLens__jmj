import type { Snapshot } from '../../trace/snapshots'
import { valueLabel } from '../../player/expand'

export default function CallStackView({ snapshot }: { snapshot: Snapshot; focus: string[] }) {
  const stack = snapshot.stack
  const cardH = 76
  const baseY = 380

  return (
    <svg className="stage-svg" viewBox="0 0 720 420" role="img" aria-label="호출 스택">
      <text x={24} y={36} className="svg-title">호출 스택 · 깊이 {stack.length}</text>
      {stack.map((f, i) => {
        const y = baseY - (i + 1) * (cardH + 10)
        const top = i === stack.length - 1
        const locals = [...f.locals.entries()].slice(0, 3)
        return (
          <g key={f.frameId}>
            <rect x={160} y={y} width={400} height={cardH} rx={10}
              fill={top ? 'var(--accent-wash)' : 'var(--panel)'}
              stroke={top ? 'var(--accent)' : 'var(--line-strong)'} strokeWidth={top ? 2 : 1} />
            <text x={180} y={y + 26} className="svg-name">
              {f.func === '<module>' ? '<모듈>' : `${f.func}()`}
            </text>
            <text x={180} y={y + 52} className="svg-type">
              {locals.length
                ? locals.map(([n, v]) => `${n}=${valueLabel(v, snapshot.objects)}`).join('  ').slice(0, 44)
                : '지역 변수 없음'}
            </text>
          </g>
        )
      })}
    </svg>
  )
}
