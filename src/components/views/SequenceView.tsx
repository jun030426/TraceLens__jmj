import { useEffect, useRef } from 'react'
import gsap from 'gsap'
import type { Snapshot } from '../../trace/snapshots'
import type { ObjectSnap, Value } from '../../trace/types'
import { valueLabel } from '../../player/expand'

function pickList(snapshot: Snapshot, focus: string[]): { name: string; obj: ObjectSnap } | null {
  const frames = [...snapshot.stack].reverse()
  const candidates = [...focus, ...frames.flatMap(f => [...f.locals.keys()])]
  for (const name of candidates) {
    for (const f of frames) {
      const v = f.locals.get(name) as Value | undefined
      if (v?.k === 'ref') {
        const o = snapshot.objects.get(v.id)
        if (o?.items) return { name, obj: o }
      }
    }
  }
  return null
}

export default function SequenceView({ snapshot, focus }: { snapshot: Snapshot; focus: string[] }) {
  const found = pickList(snapshot, focus)
  const groupRef = useRef<SVGGElement | null>(null)
  const count = found?.obj.items?.length ?? 0

  useEffect(() => {
    if (!groupRef.current) return
    const cells = groupRef.current.querySelectorAll('.seq-cell-new')
    if (cells.length) {
      gsap.fromTo(cells, { scale: 0.6, opacity: 0, transformOrigin: 'center' },
        { scale: 1, opacity: 1, duration: 0.45, ease: 'back.out(2)' })
    }
  }, [count])

  if (!found) {
    return (
      <svg className="stage-svg" viewBox="0 0 720 420" role="img" aria-label="시퀀스">
        <text x={24} y={36} className="svg-title">시퀀스</text>
        <text x={24} y={80} className="svg-type">표시할 리스트가 없습니다</text>
      </svg>
    )
  }

  const items = found.obj.items ?? []
  const cellW = Math.min(88, Math.max(52, 600 / Math.max(items.length, 1)))
  const startX = 360 - (items.length * (cellW + 8) - 8) / 2
  const y = 180

  return (
    <svg className="stage-svg" viewBox="0 0 720 420" role="img" aria-label="시퀀스">
      <text x={24} y={36} className="svg-title">{found.name} · {found.obj.type} · {items.length}개</text>
      <g ref={groupRef}>
        {items.map((v, i) => {
          const x = startX + i * (cellW + 8)
          const isLast = i === items.length - 1
          const label = valueLabel(v, snapshot.objects)
          return (
            <g key={i} className={isLast ? 'seq-cell-new' : undefined}>
              <rect x={x} y={y} width={cellW} height={64} rx={8}
                fill={isLast ? 'rgba(255,79,216,0.14)' : 'rgba(56,215,232,0.10)'}
                stroke={isLast ? '#ff4fd8' : '#38d7e8'} strokeWidth={isLast ? 2 : 1} />
              <text x={x + cellW / 2} y={y + 38} textAnchor="middle" className="svg-value">
                {label.length > 8 ? label.slice(0, 8) + '…' : label}
              </text>
              <text x={x + cellW / 2} y={y + 86} textAnchor="middle" className="svg-type">{i}</text>
            </g>
          )
        })}
        {found.obj.truncated && (
          <text x={startX + items.length * (cellW + 8) + 8} y={y + 38} className="svg-type">…</text>
        )}
      </g>
    </svg>
  )
}
