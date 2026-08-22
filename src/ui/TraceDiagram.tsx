import { useEffect, useMemo } from 'react'
import fixture from '../fixtures/aliasing.trace.json'
import type { TraceEvent, Value } from '../trace/types'
import { buildSnapshots } from '../trace/snapshots'
import { buildScreenplay } from '../screenplay/ruleDirector'
import { expandScreenplay, valueLabel } from '../player/expand'
import { usePlayback } from '../player/usePlayback'

/* 이 다이어그램은 데모가 아니라 제품이다. 같은 fixture 트레이스를 제품과 같은
   파이프라인(buildSnapshots → buildScreenplay → expandScreenplay → usePlayback)에
   통과시키고, 화면의 모든 값은 그 결과에서만 읽는다. 아래 SOURCE는 이 fixture를
   만들어낸 실제 파이썬 코드다 (scripts/gen_fixtures.py의 'aliasing' 샘플). */
const SOURCE = ['team_a = ["kim", "lee"]', 'team_b = team_a', 'team_b.append("park")', 'print(team_a)']

const events = (fixture as { events: TraceEvent[] }).events

const ROW_H = 40
const NAME_W = 132
const NAME_X = 8
const OBJ_X = 252
const CELL_W = 84
const CELL_H = 44

export default function TraceDiagram({ still = false }: { still?: boolean }) {
  const { snaps, steps } = useMemo(() => {
    const s = buildSnapshots(events)
    return { snaps: s, steps: expandScreenplay(buildScreenplay(events), s) }
  }, [])

  const { index, playing, play, pause, seek } = usePlayback(steps)
  const atEnd = index >= steps.length - 1

  useEffect(() => {
    if (still) seek(steps.length - 1)
    else play()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [still, steps.length])

  useEffect(() => {
    if (still || playing || !atEnd) return
    const t = window.setTimeout(play, 2600)
    return () => window.clearTimeout(t)
  }, [still, playing, atEnd, play])

  const step = steps[index]
  const snap = snaps.find(s => s.seq === step?.seq)
  const focus = new Set(step?.focus ?? [])

  const view = useMemo(() => {
    const frame = snap?.stack[snap.stack.length - 1]
    if (!snap || !frame) return { rows: [] as { name: string; v: Value }[], objId: null as number | null, cells: [] as string[], objType: '' }
    const rows = [...frame.locals].map(([name, v]) => ({ name, v }))
    const byId = new Map<number, number>()
    for (const { v } of rows) if (v.k === 'ref') byId.set(v.id, (byId.get(v.id) ?? 0) + 1)
    let objId: number | null = null
    for (const [id, n] of byId) if (objId === null || n > (byId.get(objId) ?? 0)) objId = id
    const obj = objId === null ? undefined : snap.objects.get(objId)
    return {
      rows,
      objId,
      objType: obj?.type ?? '',
      cells: (obj?.items ?? []).map(v => valueLabel(v, snap.objects)),
    }
  }, [snap])

  const { rows, objId, cells, objType } = view
  const refRows = rows.filter(r => r.v.k === 'ref' && r.v.id === objId)
  const height = Math.max(190, 44 + rows.length * ROW_H + 30)
  const objY = refRows.length ? 40 + (rows.findIndex(r => r.name === refRows[0].name) * ROW_H + (refRows.length - 1) * ROW_H) / 2 : 46
  const line = snap?.line ?? 0

  return (
    <figure
      className="tl-demo"
      style={{ margin: 0 }}
      tabIndex={0}
      role="group"
      aria-label="실행 기록 재생 — 스페이스로 재생과 정지, 좌우 화살표로 장면 이동"
      onKeyDown={e => {
        if (e.key === ' ' || e.key === 'Enter') {
          e.preventDefault()
          if (playing) pause()
          else play()
        } else if (e.key === 'ArrowRight') {
          e.preventDefault()
          seek(index + 1)
        } else if (e.key === 'ArrowLeft') {
          e.preventDefault()
          seek(index - 1)
        } else if (e.key === 'Home') {
          e.preventDefault()
          seek(0)
        }
      }}
    >
      <div className="tl-panel tl-demo__panel">
        <div className="tl-panel__bar">
          <span className="tl-label">실행 기록 재생</span>
          <span className="tl-tag tl-tag--ok">실제 트레이스</span>
          <span className="tl-demo__count tl-num">
            {steps.length ? `${index + 1} / ${steps.length}` : '—'}
          </span>
        </div>

        <div className="tl-demo__split">
          {/* ── 코드 ── */}
          <div className="tl-demo__code">
            {SOURCE.map((text, i) => (
              <div key={i} className={`tl-codeline ${line === i + 1 ? 'is-current' : ''}`}>
                <span className="tl-codeline__n">{i + 1}</span>
                <code>{text}</code>
              </div>
            ))}
          </div>

          {/* ── 상태 다이어그램 ── */}
          <div className="tl-demo__diagram">
            <svg viewBox={`0 0 520 ${height}`} role="img" aria-label="두 변수가 같은 리스트 객체를 가리키는 상태 다이어그램" style={{ width: '100%', height: 'auto', display: 'block' }}>
              <defs>
                <marker id="tl-arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
                  <path d="M0 0.6 L 7.4 4 L 0 7.4 z" fill="var(--accent)" />
                </marker>
              </defs>

              <text x={NAME_X} y="18" className="tl-svg-label">
                변수
              </text>
              {objId !== null && (
                <text x={OBJ_X} y="18" className="tl-svg-label">
                  {objType} 객체
                </text>
              )}

              {rows.map((r, i) => {
                const y = 32 + i * ROW_H
                const hot = focus.has(r.name)
                return (
                  <g key={r.name}>
                    <rect
                      x={NAME_X}
                      y={y}
                      width={NAME_W}
                      height={30}
                      rx="6"
                      fill={hot ? 'var(--accent-wash)' : 'var(--panel)'}
                      stroke={hot ? 'var(--accent)' : 'var(--line-strong)'}
                      style={{ transition: 'fill 200ms var(--ease), stroke 200ms var(--ease)' }}
                    />
                    <text
                      x={NAME_X + 12}
                      y={y + 20}
                      className="tl-svg-name"
                      fill={hot ? 'var(--accent-ink)' : 'var(--ink)'}
                      style={{ transition: 'fill 200ms var(--ease)' }}
                    >
                      {r.name}
                    </text>
                    {r.v.k === 'prim' ? (
                      <text x={NAME_X + NAME_W + 12} y={y + 20} className="tl-svg-val">
                        = {r.v.v}
                      </text>
                    ) : r.v.id === objId ? (
                      <path
                        d={`M ${NAME_X + NAME_W + 6} ${y + 15} C ${NAME_X + NAME_W + 56} ${y + 15}, ${OBJ_X - 56} ${objY + CELL_H / 2}, ${OBJ_X - 9} ${objY + CELL_H / 2}`}
                        fill="none"
                        stroke="var(--accent)"
                        strokeWidth="1.5"
                        markerEnd="url(#tl-arrow)"
                      />
                    ) : null}
                  </g>
                )
              })}

              {cells.length > 0 && (
                <g>
                  {cells.map((label, i) => (
                    <g key={i} className="tl-cell">
                      <rect
                        x={OBJ_X + i * CELL_W}
                        y={objY}
                        width={CELL_W}
                        height={CELL_H}
                        fill="var(--panel)"
                        stroke="var(--line-strong)"
                        strokeWidth="1"
                      />
                      <text x={OBJ_X + i * CELL_W + CELL_W / 2} y={objY + 27} textAnchor="middle" className="tl-svg-val" fill="var(--ink)">
                        {label}
                      </text>
                      <text x={OBJ_X + i * CELL_W + CELL_W / 2} y={objY + CELL_H + 15} textAnchor="middle" className="tl-svg-idx">
                        {i}
                      </text>
                    </g>
                  ))}
                  {refRows.length > 1 && (
                    <text x={OBJ_X} y={objY + CELL_H + 36} className="tl-svg-note">
                      {refRows.map(r => r.name).join(' 와 ')} 가 같은 객체를 가리킵니다
                    </text>
                  )}
                </g>
              )}
            </svg>

            {snap?.stdout ? (
              <div className="tl-demo__out">
                <span className="tl-label">stdout</span>
                <code className="tl-mono">{snap.stdout.trim()}</code>
              </div>
            ) : null}
          </div>
        </div>

        <div className="tl-demo__foot">
          <button
            type="button"
            className="tl-btn tl-btn--quiet tl-btn--sm"
            onClick={playing ? pause : play}
            aria-label={playing ? '일시정지' : '재생'}
          >
            {playing ? '일시정지' : atEnd ? '다시 재생' : '재생'}
          </button>
          <p className="tl-demo__caption" aria-live="polite">
            {step?.narration ?? '실행을 기다리는 중'}
          </p>
        </div>
      </div>

      <figcaption className="tl-note tl-demo__source">
        위 코드를 실제로 실행해 기록한 트레이스를 그대로 재생하고 있습니다. 값과 순서는 그 실행에서만 나왔습니다.
        <span className="tl-demo__keys"> 포커스한 뒤 스페이스로 정지, 좌우 화살표로 장면 이동.</span>
      </figcaption>
    </figure>
  )
}
