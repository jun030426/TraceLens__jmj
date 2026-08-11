import type { Snapshot } from '../../trace/snapshots'
import type { ObjectSnap } from '../../trace/types'
import { valueLabel } from '../../player/expand'

type Link = { name: string; objectId: number }

function collectLinks(snapshot: Snapshot): Link[] {
  const links: Link[] = []
  for (const f of snapshot.stack) {
    for (const [name, v] of f.locals) {
      if (v.k === 'ref' && snapshot.objects.has(v.id)) links.push({ name, objectId: v.id })
    }
  }
  return links.slice(0, 6)
}

function ObjectBox({ obj, x, y, objects }: { obj: ObjectSnap; x: number; y: number; objects: Snapshot['objects'] }) {
  const items = obj.items ?? []
  const entries = obj.entries ?? []
  const w = Math.max(180, items.length * 64 + 24)
  return (
    <g>
      <text x={x + 12} y={y - 10} className="svg-type">{obj.type} · #{obj.id % 100000}</text>
      <rect x={x} y={y} width={w} height={entries.length ? 24 + entries.length * 24 : 72} rx={10}
        fill="rgba(104,255,122,0.07)" stroke="#68ff7a" strokeWidth={1.4} />
      {items.map((v, i) => (
        <g key={i}>
          <rect x={x + 12 + i * 64} y={y + 12} width={56} height={40} rx={6}
            fill="rgba(56,215,232,0.12)" stroke="#38d7e8" strokeWidth={1} />
          <text x={x + 40 + i * 64} y={y + 37} textAnchor="middle" className="svg-value">
            {valueLabel(v, objects).slice(0, 6)}
          </text>
        </g>
      ))}
      {entries.map(([k, v], i) => (
        <text key={k} x={x + 14} y={y + 24 + i * 24} className="svg-value">
          {k}: {valueLabel(v, objects).slice(0, 18)}
        </text>
      ))}
      {!items.length && !entries.length && (
        <text x={x + 14} y={y + 42} className="svg-type">{obj.unsupported ? '표시 불가 객체' : '빈 컬렉션'}</text>
      )}
    </g>
  )
}

export default function ObjectGraphView({ snapshot, focus }: { snapshot: Snapshot; focus: string[] }) {
  const links = collectLinks(snapshot)
  const objectIds = [...new Set(links.map(l => l.objectId))].slice(0, 3)

  const tagY = (i: number) => 90 + i * 64
  const objY = (i: number) => 90 + i * 120

  return (
    <svg className="stage-svg" viewBox="0 0 720 420" role="img" aria-label="객체 참조 그래프">
      <defs>
        <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto">
          <path d="M0 0L10 5L0 10z" fill="#ff4fd8" />
        </marker>
      </defs>
      <text x={24} y={36} className="svg-title">메모리 (객체 참조)</text>
      {links.map((l, i) => {
        const oi = objectIds.indexOf(l.objectId)
        const active = focus.includes(l.name)
        const y1 = tagY(i) + 16
        const y2 = objY(oi < 0 ? 0 : oi) + 30
        return (
          <g key={`${l.name}-${l.objectId}`}>
            <rect x={40} y={tagY(i)} width={110} height={34} rx={17}
              fill={active ? 'rgba(255,79,216,0.15)' : 'rgba(56,215,232,0.10)'}
              stroke={active ? '#ff4fd8' : '#38d7e8'} strokeWidth={active ? 2 : 1} />
            <text x={95} y={tagY(i) + 22} textAnchor="middle" className="svg-name">{l.name}</text>
            {oi >= 0 && (
              <path d={`M 150 ${y1} C 210 ${y1}, 220 ${y2}, 268 ${y2}`}
                fill="none" stroke="#ff4fd8" strokeWidth={1.6} markerEnd="url(#arrow)" opacity={0.9} />
            )}
          </g>
        )
      })}
      {objectIds.map((id, i) => {
        const obj = snapshot.objects.get(id)
        return obj ? <ObjectBox key={id} obj={obj} x={276} y={objY(i)} objects={snapshot.objects} /> : null
      })}
      {links.length === 0 && <text x={24} y={80} className="svg-type">참조 객체가 없습니다</text>}
    </svg>
  )
}
