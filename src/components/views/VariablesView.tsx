import type { Snapshot } from '../../trace/snapshots'
import { valueLabel } from '../../player/expand'

// Generic State View 겸용: 이름/값/타입/변경 여부를 항상 표시할 수 있는 최종 안전망
export default function VariablesView({ snapshot, focus }: { snapshot: Snapshot; focus: string[] }) {
  const frame = snapshot.stack[snapshot.stack.length - 1]
  const rows = frame ? [...frame.locals.entries()].slice(0, 10) : []

  return (
    <svg className="stage-svg" viewBox="0 0 720 420" role="img" aria-label="변수 상태">
      <text x={24} y={36} className="svg-title">{frame?.func === '<module>' ? '전역 변수' : `${frame?.func} 지역 변수`}</text>
      {rows.map(([name, v], i) => {
        const active = focus.includes(name)
        const y = 64 + i * 34
        const label = valueLabel(v, snapshot.objects)
        const type = v.k === 'prim' ? v.t : snapshot.objects.get(v.id)?.type ?? 'object'
        return (
          <g key={name} className={active ? 'var-row active' : 'var-row'}>
            <rect x={24} y={y - 20} width={672} height={28} rx={6}
              fill={active ? 'rgba(255,79,216,0.12)' : 'rgba(56,215,232,0.05)'}
              stroke={active ? '#ff4fd8' : '#25303a'} strokeWidth={1} />
            <text x={40} y={y} className="svg-name">{name}</text>
            <text x={200} y={y} className={active ? 'svg-value active' : 'svg-value'}>
              {label.length > 52 ? label.slice(0, 52) + '…' : label}
            </text>
            <text x={648} y={y} className="svg-type" textAnchor="end">{type}</text>
          </g>
        )
      })}
      {rows.length === 0 && <text x={24} y={80} className="svg-type">아직 변수가 없습니다</text>}
    </svg>
  )
}
