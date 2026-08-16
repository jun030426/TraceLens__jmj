import { useEffect, useRef } from 'react'
import gsap from 'gsap'
import type { Shot, StagePlan } from './types'
import type { StageLayout } from './layout'
import type { useFilm } from './useFilm'

type Props = {
  plan: StagePlan
  layout: StageLayout
  shots: Shot[]
  film: ReturnType<typeof useFilm>
}

const esc = (s: string) => s.replace(/[^a-zA-Z0-9_-]/g, m => `\\${m}`)
const objSel = (id: number) => `[data-obj="${id}"]`
const cellSel = (id: number, i: number) => `[data-cell="${id}-${i}"]`
const varSel = (key: string) => `[data-var="${esc(key)}"]`
const frameSel = (id: number) => `[data-frame="${id}"]`
const ropeSel = (key: string, id: number) => `[data-rope="${esc(`${key}-${id}`)}"]`

// 3패스 — 등장인물을 처음부터 전부 무대에 올려두고(숨긴 채),
// 마스터 타임라인이 나타내고·움직이고·지운다. 프레임마다 다시 그리지 않으므로
// 물체가 시각적 정체성을 유지한다.
export default function WorldStage({ plan, layout, shots, film }: Props) {
  const rootRef = useRef<SVGSVGElement | null>(null)
  const { register } = film

  useEffect(() => {
    const root = rootRef.current
    if (!root) return
    const still = document.documentElement.dataset.still === 'true'

    // gsap.context는 쓰지 않는다 — StrictMode 이중 마운트에서 revert가 타임라인을
    // 전역 티커에서 떼어내 재생이 멈춘다. 대신 실제 엘리먼트를 직접 넘기고 kill로만 정리한다.
    const q = (sel: string) => root.querySelector(sel)
    const build = () => {
      gsap.set(
        root.querySelectorAll('[data-obj], [data-var], [data-frame], [data-rope], [data-cell], .film-error'),
        { opacity: 0 },
      )
      const tl = gsap.timeline({ paused: true })

      for (const shot of shots) {
        const d = (shot.durationMs / 1000) * (still ? 0.001 : 1)
        const label = `s${shot.seq}`
        tl.addLabel(label)
        for (const m of shot.motions) {
          switch (m.v) {
            case 'enterVar':
              tl.to(q(varSel(m.varKey))!, { opacity: 1, duration: d * 0.6, ease: 'power2.out' }, label)
              break
            case 'setVar': {
              const key = m.varKey
              const text = m.text
              tl.to(q(varSel(key))!, { opacity: 1, duration: d * 0.3 }, label)
              tl.call(
                () => {
                  const el = root.querySelector(`${varSel(key)} .film-var-value`)
                  if (el) el.textContent = text
                },
                undefined,
                label,
              )
              tl.fromTo(
                q(varSel(key))!,
                { scale: 1.14 },
                { scale: 1, duration: d * 0.7, ease: 'back.out(2.4)', transformOrigin: 'center' },
                label,
              )
              break
            }
            case 'exitVar':
              tl.to(q(varSel(m.varKey))!, { opacity: 0.18, duration: d * 0.5 }, label)
              break
            case 'bind':
              tl.to(q(objSel(m.objectId))!, { opacity: 1, duration: d * 0.4 }, label)
              tl.to(
                q(ropeSel(m.varKey, m.objectId))!,
                { opacity: 1, duration: m.alias ? d : d * 0.7, ease: 'power2.inOut' },
                label,
              )
              if (m.alias) {
                tl.fromTo(
                  q(objSel(m.objectId))!,
                  { scale: 1 },
                  { scale: 1.06, duration: d * 0.4, yoyo: true, repeat: 1, transformOrigin: 'center' },
                  label,
                )
              }
              break
            case 'enterObj':
              tl.to(q(objSel(m.objectId))!, { opacity: 1, duration: d * 0.6, ease: 'power2.out' }, label)
              break
            case 'grow': {
              const id = m.objectId
              const idx = m.index
              const text = m.text
              tl.to(q(objSel(id))!, { opacity: 1, duration: d * 0.2 }, label)
              tl.call(
                () => {
                  const el = root.querySelector(`${cellSel(id, idx)} .film-cell-text`)
                  if (el) el.textContent = text
                },
                undefined,
                label,
              )
              tl.fromTo(
                q(cellSel(id, idx))!,
                { opacity: 0, scaleY: 0.2 },
                { opacity: 1, scaleY: 1, duration: d, ease: 'back.out(2)', transformOrigin: 'center bottom' },
                label,
              )
              break
            }
            case 'setCell': {
              const id = m.objectId
              const idx = m.index
              const text = m.text
              tl.call(
                () => {
                  const el = root.querySelector(`${cellSel(id, idx)} .film-cell-text`)
                  if (el) el.textContent = text
                },
                undefined,
                label,
              )
              tl.fromTo(
                q(cellSel(id, idx))!,
                { scale: 1.2 },
                { scale: 1, opacity: 1, duration: d, ease: 'back.out(2)', transformOrigin: 'center' },
                label,
              )
              break
            }
            case 'exitObj':
              tl.to(q(objSel(m.objectId))!, { opacity: 0.15, duration: d }, label)
              break
            case 'pushFrame':
              tl.fromTo(
                q(frameSel(m.frameId))!,
                { opacity: 0, x: -26 },
                { opacity: 1, x: 0, duration: d, ease: 'power3.out' },
                label,
              )
              break
            case 'popFrame':
              tl.to(q(frameSel(m.frameId))!, { opacity: 0, x: -26, duration: d, ease: 'power2.in' }, label)
              break
            case 'stdout': {
              const text = m.text
              tl.call(
                () => {
                  const el = root.querySelector('.film-stdout-text')
                  if (el) el.textContent = text.trim().slice(0, 70)
                },
                undefined,
                label,
              )
              tl.fromTo(q('.film-stdout')!, { opacity: 0.5 }, { opacity: 1, duration: d, ease: 'power2.out' }, label)
              break
            }
            case 'shake':
              tl.fromTo(q(frameSel(m.frameId))!, { x: 0 }, { x: 8, duration: d * 0.12, repeat: 5, yoyo: true }, label)
              break
            case 'raise': {
              const text = m.text
              tl.call(
                () => {
                  const el = root.querySelector('.film-error-text')
                  if (el) el.textContent = text.slice(0, 80)
                },
                undefined,
                label,
              )
              tl.fromTo(
                q('.film-error')!,
                { opacity: 0, y: -10 },
                { opacity: 1, y: 0, duration: d * 0.5, ease: 'power3.out' },
                label,
              )
              break
            }
          }
        }
        tl.to({}, { duration: d * 0.25 })
      }

      return tl
    }

    const tl = build()
    register(tl)
    if (still) tl.progress(1)

    return () => {
      register(null)
      tl.kill()
    }
  }, [shots, register])

  return (
    <svg
      ref={rootRef}
      className="stage-svg film-stage"
      viewBox={`0 0 ${layout.width} ${layout.height}`}
      role="img"
      aria-label="코드 실행 무성영화"
    >
      {plan.frames.map(f => {
        const r = layout.framePos.get(f.frameId)!
        return (
          <g key={`f${f.frameId}`} data-frame={f.frameId}>
            <rect x={r.x} y={r.y} width={r.w} height={r.h} rx={10} fill="var(--panel)" stroke="var(--line-strong)" strokeWidth={1.2} />
            <text x={r.x + 14} y={r.y + 34} className="svg-name">
              {f.func === '<module>' ? '프로그램' : `${f.func}()`}
            </text>
          </g>
        )
      })}

      {plan.variables.flatMap(v =>
        plan.objects.map(o => {
          const a = layout.varPos.get(v.varKey)!
          const b = layout.objPos.get(o.objectId)!
          const x1 = a.x + a.w
          const y1 = a.y + a.h / 2
          const x2 = b.x
          const y2 = b.y + b.h / 2
          return (
            <path
              key={`r${v.varKey}-${o.objectId}`}
              data-rope={`${v.varKey}-${o.objectId}`}
              d={`M ${x1} ${y1} C ${(x1 + x2) / 2} ${y1}, ${(x1 + x2) / 2} ${y2}, ${x2} ${y2}`}
              fill="none"
              stroke="var(--accent)"
              strokeWidth={2.4}
              strokeLinecap="round"
            />
          )
        }),
      )}

      {plan.objects.map(o => {
        const r = layout.objPos.get(o.objectId)!
        const cells = Math.max(o.maxItems, 1)
        return (
          <g key={`o${o.objectId}`} data-obj={o.objectId}>
            <rect x={r.x} y={r.y} width={r.w} height={r.h} rx={10} fill="var(--sunken)" stroke="var(--line)" strokeWidth={1.4} />
            <text x={r.x + 4} y={r.y - 8} className="svg-type">{o.type}</text>
            {Array.from({ length: cells }, (_, i) => (
              <g key={i} data-cell={`${o.objectId}-${i}`}>
                <rect
                  x={r.x + 8 + i * layout.cellW}
                  y={r.y + 8}
                  width={layout.cellW - 6}
                  height={r.h - 16}
                  rx={5}
                  fill="var(--panel)"
                  stroke="var(--line-strong)"
                  strokeWidth={1}
                />
                <text
                  className="film-cell-text svg-value"
                  x={r.x + 8 + i * layout.cellW + (layout.cellW - 6) / 2}
                  y={r.y + r.h / 2 + 5}
                  textAnchor="middle"
                />
              </g>
            ))}
          </g>
        )
      })}

      {plan.variables.map(v => {
        const r = layout.varPos.get(v.varKey)!
        return (
          <g key={`v${v.varKey}`} data-var={v.varKey}>
            <rect x={r.x} y={r.y} width={r.w} height={r.h} rx={r.h / 2} fill="var(--accent-wash)" stroke="var(--accent)" strokeWidth={1.4} />
            <text x={r.x + 14} y={r.y + 24} className="svg-name">{v.name}</text>
            <text className="film-var-value svg-value" x={r.x + r.w - 14} y={r.y + 24} textAnchor="end" />
          </g>
        )
      })}

      {/* 오류 스트립 — 첫 행(y=70) 위의 빈 띠. 터진 순간 내려와 끝까지 남는다 */}
      <g className="film-error">
        <rect x={24} y={14} width={layout.width - 48} height={34} rx={8} fill="var(--panel)" stroke="var(--accent)" strokeWidth={1.4} />
        <text className="svg-type" x={40} y={36}>오류</text>
        <text className="film-error-text svg-name" x={92} y={36} />
      </g>

      <g className="film-stdout">
        <rect x={24} y={layout.height - 52} width={layout.width - 48} height={36} rx={8} fill="var(--sunken)" stroke="var(--line)" strokeWidth={1} />
        <text x={38} y={layout.height - 28} className="svg-type">출력</text>
        <text className="film-stdout-text svg-value" x={92} y={layout.height - 28} />
      </g>
    </svg>
  )
}
