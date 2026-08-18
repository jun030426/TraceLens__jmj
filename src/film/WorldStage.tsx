import { useEffect, useMemo, useRef, useState } from 'react'
import gsap from 'gsap'
import type { Shot, StagePlan } from './types'
import { GRID_CELL, type StageLayout } from './layout'
import { compose, type Camera, type Composition } from './compose'
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

const VAR_W = 190
const VAR_H = 36

// 연출 무대 — 배우는 전부 로컬 좌표(0,0 기준)로 그려지고, 구성(compose)이 샷마다
// "누가 어디에 얼마나 크게"를 정하면 GSAP이 배우 그룹의 transform을 옮긴다.
// 회로도(전원 지정석 + 전선)가 아니라 애니메이션: 지금 일어나는 일이 중앙에 크게,
// 최근 것은 옆에 작게, 나머지는 무대 밖. 무대 밖 상태는 인스펙터가 들고 있다.
const FIT = { k: 1, tx: 0, ty: 0 }

export default function WorldStage({ plan, layout, shots, film }: Props) {
  const rootRef = useRef<SVGSVGElement | null>(null)
  const { register } = film

  // 프레임은 영화처럼 고정(1200×640) — 콘텐츠를 채우는 건 오토 프레이밍 카메라의 일이다
  const FRAME_H = 640
  const { comps, cams } = useMemo(() => compose(shots, plan, layout), [shots, plan, layout])

  /* 수동 카메라 — 콘텐츠를 담은 <g> 하나만 변환하므로 GSAP 타깃(자식)과 간섭하지 않는다 */
  const [cam, setCam] = useState(FIT)
  const dragRef = useRef<{ x: number; y: number; tx: number; ty: number } | null>(null)

  useEffect(() => {
    setCam(FIT)
  }, [plan])

  const clampK = (k: number) => Math.min(3, Math.max(0.4, k))
  const zoomBy = (f: number) => setCam(c => ({ ...c, k: clampK(c.k * f) }))

  useEffect(() => {
    const svg = rootRef.current
    if (!svg) return
    const onWheel = (ev: WheelEvent) => {
      ev.preventDefault()
      setCam(c => ({ ...c, k: clampK(c.k * (ev.deltaY < 0 ? 1.12 : 0.9)) }))
    }
    svg.addEventListener('wheel', onWheel, { passive: false })
    return () => svg.removeEventListener('wheel', onWheel)
  }, [])

  const unitsPerPx = () => {
    const rect = rootRef.current?.getBoundingClientRect()
    if (!rect || rect.width === 0) return 1
    return Math.max(layout.width / rect.width, FRAME_H / rect.height)
  }
  const onPointerDown = (ev: React.PointerEvent<SVGSVGElement>) => {
    if (cam.k === 1) return
    ev.currentTarget.setPointerCapture(ev.pointerId)
    dragRef.current = { x: ev.clientX, y: ev.clientY, tx: cam.tx, ty: cam.ty }
  }
  const onPointerMove = (ev: React.PointerEvent<SVGSVGElement>) => {
    const drag = dragRef.current
    if (!drag) return
    const u = unitsPerPx()
    setCam(c => ({ ...c, tx: drag.tx + (ev.clientX - drag.x) * u, ty: drag.ty + (ev.clientY - drag.y) * u }))
  }
  const onPointerUp = () => {
    dragRef.current = null
  }

  const camTransform = `translate(${cam.tx + (layout.width / 2) * (1 - cam.k)} ${cam.ty + (FRAME_H / 2) * (1 - cam.k)}) scale(${cam.k})`

  useEffect(() => {
    const root = rootRef.current
    if (!root) return
    const still = document.documentElement.dataset.still === 'true'
    const sec = (x: number) => x * (still ? 0.001 : 1)

    // gsap.context는 쓰지 않는다 — StrictMode 이중 마운트에서 revert가 타임라인을
    // 전역 티커에서 떼어내 재생이 멈춘다. 실제 엘리먼트를 넘기고 kill로만 정리한다.
    const q = (sel: string) => root.querySelector(sel)
    const inner = (sel: string) => root.querySelector(`${sel} .actor-inner`)
    const cellChars = Math.max(2, Math.floor((layout.cellW - 10) / 7.2))
    const fitCell = (t: string) => (t.length > cellChars ? t.slice(0, Math.max(1, cellChars - 1)) + '…' : t)

    // 배우의 로컬 지점 → 무대 좌표 (구성 배치·배율 반영)
    const objH = new Map(plan.objects.map(o => [o.objectId, layout.objPos.get(o.objectId)?.h ?? 64]))
    const cellCenterLocal = (id: number, i: number) => ({
      x: 8 + i * layout.cellW + (layout.cellW - 6) / 2,
      y: (objH.get(id) ?? 64) / 2,
    })

    const build = () => {
      gsap.set(
        root.querySelectorAll(
          '[data-obj], [data-var], [data-frame], [data-cell], [data-gcursor], [data-gtrail], .film-chip, .film-error, .film-loop, .film-compare',
        ),
        { opacity: 0 },
      )
      const autoCam = q('.film-cam-auto')
      if (autoCam) gsap.set(autoCam, { x: 0, y: 0, scale: 1 })
      // 오토 프레이밍 카메라 — 첫 구성의 프레임으로 시작
      const frameCam = q('.film-cam-frame')
      let appliedCam: Camera | null = cams[0] ?? null
      if (frameCam && appliedCam) gsap.set(frameCam, { x: appliedCam.x, y: appliedCam.y, scale: appliedCam.k, transformOrigin: '0px 0px' })
      const tl = gsap.timeline({ paused: true })
      let liveFrame: Element | null = null
      let prevComp: Composition = new Map()
      let chipTurn = 0

      const actorEl = (key: string) =>
        key.startsWith('o') ? q(objSel(Number(key.slice(1)))) : q(varSel(key.slice(1)))

      // 값이 실제로 이동하는 칩 — 미리 만든 2개를 돌려쓴다 (스크럽 안전)
      const travel = (label: string, text: string, from: { x: number; y: number }, to: { x: number; y: number }) => {
        const chip = q(`[data-chip="${chipTurn % 2}"]`)
        chipTurn += 1
        if (!chip) return
        tl.call(
          () => {
            const t = chip.querySelector('text')
            if (t) t.textContent = fitCell(text)
          },
          undefined,
          label,
        )
        tl.set(chip, { x: from.x, y: from.y, opacity: 0 }, label)
        tl.to(chip, { opacity: 1, duration: sec(0.12) }, label)
        tl.to(chip, { x: to.x, y: to.y, duration: sec(0.5), ease: 'power2.inOut' }, `${label}+=${sec(0.1)}`)
        tl.to(chip, { opacity: 0, duration: sec(0.15) }, `${label}+=${sec(0.55)}`)
      }

      shots.forEach((shot, si) => {
        const d = sec(shot.durationMs / 1000)
        const label = `s${shot.seq}`
        tl.addLabel(label)
        const comp = comps[si] ?? new Map()

        // 카메라가 이야기를 따라간다 — 구성 경계가 유의미하게 바뀔 때만 (compose가 감쇠)
        const camNow = cams[si]
        if (frameCam && camNow && camNow !== appliedCam) {
          tl.to(
            frameCam,
            { x: camNow.x, y: camNow.y, scale: camNow.k, duration: sec(0.5), ease: 'power2.inOut', transformOrigin: '0px 0px' },
            label,
          )
          appliedCam = camNow
        }

        // ── 구성 전환 — 배우 가시성·위치·배율의 단일 소유자 ──
        for (const key of prevComp.keys()) {
          if (comp.has(key)) continue
          const el = actorEl(key)
          if (el) tl.to(el, { opacity: 0, duration: sec(0.3), ease: 'power2.in' }, label)
        }
        for (const [key, p] of comp) {
          const el = actorEl(key)
          if (!el) continue
          const was = prevComp.get(key)
          if (!was) {
            tl.fromTo(
              el,
              { opacity: 0, x: p.x, y: p.y + 18, scale: p.s * 0.9, transformOrigin: '0px 0px' },
              { opacity: 1, y: p.y, scale: p.s, duration: sec(0.4), ease: 'power2.out' },
              label,
            )
          } else if (was.x !== p.x || was.y !== p.y || was.s !== p.s) {
            tl.to(
              el,
              { x: p.x, y: p.y, scale: p.s, duration: sec(0.45), ease: 'power2.inOut', transformOrigin: '0px 0px' },
              label,
            )
          }
          if ((was?.focus ?? false) !== p.focus) {
            tl.call(
              () => {
                el.classList.toggle('is-focus', p.focus)
              },
              undefined,
              label,
            )
          }
        }

        // popleft의 그림 — 이번 샷에서 칸이 빠지고(shrink) 변수가 값을 받으면(setVar/bind)
        // 그 칸에서 그 알약으로 칩이 날아간다
        const shrinkM = shot.motions.find(m => m.v === 'shrink') as
          | { objectId: number; index: number }
          | undefined
        const receiveM = shot.motions.find(m => m.v === 'setVar' || m.v === 'bind') as
          | { varKey: string; text?: string }
          | undefined
        if (shrinkM && receiveM) {
          const po = comp.get(`o${shrinkM.objectId}`)
          const pv = comp.get(`v${receiveM.varKey}`)
          if (po && pv) {
            const local = cellCenterLocal(shrinkM.objectId, shrinkM.index)
            travel(
              label,
              receiveM.text ?? '',
              { x: po.x + local.x * po.s, y: po.y + local.y * po.s },
              { x: pv.x + (VAR_W / 2) * pv.s, y: pv.y + (VAR_H / 2) * pv.s },
            )
          }
        }

        // 조명 — 프레임(호출 카드)은 구성 밖이므로 기존 방식대로 켠다
        const focusEl = shot.focus?.kind === 'frame' ? q(frameSel(shot.focus.frameId)) : null
        if (focusEl !== liveFrame) {
          const prevEl = liveFrame
          tl.call(
            () => {
              prevEl?.classList.remove('is-live')
              focusEl?.classList.add('is-live')
            },
            undefined,
            label,
          )
          liveFrame = focusEl
        }

        for (const m of shot.motions) {
          switch (m.v) {
            case 'enterVar':
            case 'enterObj':
            case 'exitVar':
            case 'exitObj':
              break // 배우 가시성은 구성이 소유한다
            case 'setVar': {
              const key = m.varKey
              const text = m.text
              tl.call(
                () => {
                  const el = root.querySelector(`${varSel(key)} .film-var-value`)
                  if (el) el.textContent = text
                },
                undefined,
                label,
              )
              const iv = inner(varSel(key))
              if (iv) {
                tl.fromTo(
                  iv,
                  { scale: 1.28 },
                  { scale: 1, duration: d * 0.7, ease: 'back.out(2.4)', transformOrigin: 'center' },
                  label,
                )
              }
              break
            }
            case 'label': {
              const id = m.objectId
              const text = m.text
              tl.call(
                () => {
                  const el = root.querySelector(`${objSel(id)} .film-obj-name`)
                  if (el) el.textContent = text
                },
                undefined,
                label,
              )
              break
            }
            case 'bind': {
              // 끈은 없다 — 이름표(label 모션)가 소속을 말하고, 별칭이면 상자가 잠깐 부푼다
              if (m.alias) {
                const io = inner(objSel(m.objectId))
                if (io) {
                  tl.fromTo(
                    io,
                    { scale: 1 },
                    { scale: 1.06, duration: d * 0.4, yoyo: true, repeat: 1, transformOrigin: 'center' },
                    label,
                  )
                }
              }
              break
            }
            case 'grow': {
              const id = m.objectId
              const idx = m.index
              const text = m.text
              tl.call(
                () => {
                  const el = root.querySelector(`${cellSel(id, idx)} .film-cell-text`)
                  if (el) el.textContent = fitCell(text)
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
                  if (el) el.textContent = fitCell(text)
                },
                undefined,
                label,
              )
              tl.fromTo(
                q(cellSel(id, idx))!,
                { scale: 1.35 },
                { scale: 1, opacity: 1, duration: d, ease: 'back.out(2)', transformOrigin: 'center' },
                label,
              )
              const cellRect = root.querySelector(`${cellSel(id, idx)} rect`)
              if (cellRect) {
                tl.fromTo(
                  cellRect,
                  { attr: { 'stroke-width': 1 } },
                  { attr: { 'stroke-width': 2.6 }, duration: d * 0.4, yoyo: true, repeat: 1 },
                  label,
                )
              }
              break
            }
            case 'shrink': {
              const el = q(cellSel(m.objectId, m.index))
              if (el) tl.to(el, { opacity: 0, scale: 0.6, duration: d * 0.5, ease: 'power2.in', transformOrigin: 'center' }, label)
              break
            }
            case 'swap': {
              const a = q(cellSel(m.objectId, m.i))
              const b = q(cellSel(m.objectId, m.k))
              if (!a || !b) break
              const dx = (m.k - m.i) * layout.cellW
              const id = m.objectId
              const i = m.i
              const k = m.k
              const iText = m.iText
              const kText = m.kText
              tl.to(a, { x: dx, scale: 1.12, duration: d * 0.55, ease: 'power2.inOut', transformOrigin: 'center' }, label)
              tl.to(b, { x: -dx, scale: 1.12, duration: d * 0.55, ease: 'power2.inOut', transformOrigin: 'center' }, label)
              tl.call(
                () => {
                  const ta = root.querySelector(`${cellSel(id, i)} .film-cell-text`)
                  const tb = root.querySelector(`${cellSel(id, k)} .film-cell-text`)
                  if (ta) ta.textContent = fitCell(iText)
                  if (tb) tb.textContent = fitCell(kText)
                },
                undefined,
                `${label}+=${d * 0.55}`,
              )
              tl.set([a, b], { x: 0 }, `${label}+=${d * 0.55}`)
              tl.to([a, b], { scale: 1, duration: d * 0.3, ease: 'back.out(2)' }, `${label}+=${d * 0.58}`)
              break
            }
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
              tl.to(q('.film-loop')!, { opacity: 0, duration: d * 0.2 }, label)
              tl.to(q('.film-compare')!, { opacity: 0, duration: d * 0.2 }, label)
              tl.fromTo(
                q('.film-error')!,
                { opacity: 0, y: -10 },
                { opacity: 1, y: 0, duration: d * 0.5, ease: 'power3.out' },
                label,
              )
              break
            }
            case 'loop': {
              const text = m.text
              tl.call(
                () => {
                  const el = root.querySelector('.film-loop-text')
                  if (el) el.textContent = text
                },
                undefined,
                label,
              )
              tl.to(q('.film-loop')!, { opacity: 1, duration: d * 0.3 }, label)
              tl.fromTo(
                q('.film-loop')!,
                { scale: 1.05 },
                { scale: 1, duration: d * 0.4, transformOrigin: 'left center' },
                label,
              )
              break
            }
            case 'loopEnd':
              tl.to(q('.film-loop')!, { opacity: 0, duration: d * 0.4 }, label)
              break
            case 'spotlight':
              for (const key of m.varKeys) {
                const el = inner(varSel(key))
                if (el) {
                  tl.fromTo(
                    el,
                    { scale: 1 },
                    { scale: 1.08, duration: d * 0.4, yoyo: true, repeat: 1, transformOrigin: 'center' },
                    label,
                  )
                }
              }
              break
            case 'camera': {
              const autoEl = q('.film-cam-auto')
              if (autoEl) {
                tl.to(
                  autoEl,
                  { x: m.x, y: m.y, scale: m.k, duration: d * 0.9, ease: 'power2.inOut', transformOrigin: '0px 0px' },
                  label,
                )
              }
              break
            }
            case 'gridCell': {
              const cell = q(`[data-gcell="${m.objectId}-${m.r}-${m.c}"]`)
              const txt = q(`[data-gctext="${m.objectId}-${m.r}-${m.c}"]`)
              const text = m.text
              const wall = m.wall
              tl.call(
                () => {
                  if (txt) txt.textContent = text
                  cell?.classList.toggle('is-wall', wall)
                },
                undefined,
                label,
              )
              if (m.flash && cell) {
                tl.fromTo(
                  cell,
                  { scale: 1.3 },
                  { scale: 1, duration: d * 0.8, ease: 'back.out(2)', transformOrigin: 'center' },
                  label,
                )
              }
              break
            }
            case 'gridVisit':
            case 'gridUnvisit': {
              const cell = q(`[data-gcell="${m.objectId}-${m.r}-${m.c}"]`)
              const on = m.v === 'gridVisit'
              tl.call(
                () => {
                  cell?.classList.toggle('is-visited', on)
                },
                undefined,
                label,
              )
              break
            }
            case 'gridCursor': {
              const cur = q(`[data-gcursor="${m.objectId}"]`)
              if (!cur) break
              tl.to(
                cur,
                {
                  attr: { cx: 8 + m.c * GRID_CELL + GRID_CELL / 2, cy: 8 + m.r * GRID_CELL + GRID_CELL / 2 },
                  opacity: 1,
                  duration: d * 0.5,
                  ease: 'power2.inOut',
                },
                label,
              )
              break
            }
            case 'gridTrail': {
              const el = q(`[data-gtrail="${m.objectId}"]`)
              if (!el) break
              const pts = m.points
                .map(([pr, pc]) => `${8 + pc * GRID_CELL + GRID_CELL / 2},${8 + pr * GRID_CELL + GRID_CELL / 2}`)
                .join(' ')
              tl.call(
                () => {
                  el.setAttribute('points', pts)
                },
                undefined,
                label,
              )
              tl.to(el, { opacity: 1, duration: d * 0.5 }, label)
              break
            }
            case 'compare': {
              const text = m.text
              tl.call(
                () => {
                  const el = root.querySelector('.film-compare-text')
                  if (el) el.textContent = text
                },
                undefined,
                label,
              )
              tl.fromTo(
                q('.film-compare')!,
                { opacity: 0, y: -6 },
                { opacity: 1, y: 0, duration: d * 0.3, ease: 'power2.out' },
                label,
              )
              for (const t of m.targets) {
                const el = t.kind === 'cell' ? q(cellSel(t.objectId, t.index)) : inner(varSel(t.varKey))
                if (el) {
                  tl.fromTo(
                    el,
                    { scale: 1 },
                    { scale: 1.14, duration: d * 0.35, yoyo: true, repeat: 1, transformOrigin: 'center' },
                    label,
                  )
                }
              }
              tl.to(q('.film-compare')!, { opacity: 0, duration: d * 0.3 }, `${label}+=${d * 0.95}`)
              break
            }
          }
        }
        prevComp = comp
        tl.to({}, { duration: d * 0.25 })
      })

      return tl
    }

    const tl = build()
    register(tl)
    // 두 번째 인자 false = 이벤트 억제 해제 — 점프 경로의 tl.call(텍스트 세터)까지 전부 실행해야
    // 모션 감소 사용자도 값이 채워진 "완성된 마지막 프레임"을 본다
    if (still) tl.progress(1, false)

    return () => {
      register(null)
      tl.kill()
    }
  }, [shots, register, layout, plan, comps])

  const hudOffset = FRAME_H - layout.height

  return (
    <div className="film-viewport">
      <svg
        ref={rootRef}
        className="stage-svg film-stage"
        viewBox={`0 0 ${layout.width} ${FRAME_H}`}
        role="img"
        aria-label="코드 실행 무성영화"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerLeave={onPointerUp}
        style={{ cursor: cam.k !== 1 ? 'grab' : 'default' }}
      >
      <g transform={camTransform}>
      <g className="film-cam-auto">
      <g className="film-cam-frame">
      {/* 배우: 객체 상자·격자 — 로컬 좌표로 그리고 구성이 transform으로 배치한다 */}
      {plan.objects.map(o => {
        const r = layout.objPos.get(o.objectId)!
        if (o.grid) {
          const { rows, cols } = o.grid
          const gx = (c: number) => 8 + c * GRID_CELL
          const gy = (row: number) => 8 + row * GRID_CELL
          return (
            <g key={`o${o.objectId}`} data-obj={o.objectId}>
              <g className="actor-inner">
                <rect x={0} y={0} width={r.w} height={r.h} rx={10} fill="var(--sunken)" stroke="var(--line-strong)" strokeWidth={2} />
                <text className="film-obj-name svg-name" x={4} y={-8} />
                <text x={r.w} y={-8} textAnchor="end" className="svg-type">{`${o.type} ${rows}×${cols}`}</text>
                {Array.from({ length: rows }, (_, gr) =>
                  Array.from({ length: cols }, (_, gc) => (
                    <g key={`${gr}-${gc}`}>
                      <rect
                        data-gcell={`${o.objectId}-${gr}-${gc}`}
                        className="film-gcell"
                        x={gx(gc)}
                        y={gy(gr)}
                        width={GRID_CELL}
                        height={GRID_CELL}
                      />
                      <text
                        data-gctext={`${o.objectId}-${gr}-${gc}`}
                        className="svg-index"
                        x={gx(gc) + GRID_CELL / 2}
                        y={gy(gr) + GRID_CELL / 2 + 4}
                        textAnchor="middle"
                      />
                    </g>
                  )),
                )}
                {Array.from({ length: rows }, (_, gr) => (
                  <text key={`r${gr}`} className="svg-index" x={-6} y={gy(gr) + GRID_CELL / 2 + 4} textAnchor="end">
                    {gr}
                  </text>
                ))}
                {Array.from({ length: cols }, (_, gc) => (
                  <text key={`c${gc}`} className="svg-index" x={gx(gc) + GRID_CELL / 2} y={r.h + 14} textAnchor="middle">
                    {gc}
                  </text>
                ))}
                <polyline data-gtrail={o.objectId} className="film-gtrail" points="" />
                <circle data-gcursor={o.objectId} r={7} fill="var(--accent)" />
              </g>
            </g>
          )
        }
        const cells = Math.max(o.maxItems, 1)
        return (
          <g key={`o${o.objectId}`} data-obj={o.objectId}>
            <g className="actor-inner">
              <rect x={0} y={0} width={r.w} height={r.h} rx={10} fill="var(--sunken)" stroke="var(--line-strong)" strokeWidth={2} />
              <text className="film-obj-name svg-name" x={4} y={-8} />
              <text x={r.w} y={-8} textAnchor="end" className="svg-type">{o.type}</text>
              {Array.from({ length: cells }, (_, i) => (
                <g key={i} data-cell={`${o.objectId}-${i}`}>
                  <rect
                    x={8 + i * layout.cellW}
                    y={8}
                    width={layout.cellW - 6}
                    height={r.h - 16}
                    rx={5}
                    fill="var(--panel)"
                    stroke="var(--line-strong)"
                    strokeWidth={1}
                  />
                  <text
                    className="film-cell-text svg-value"
                    x={8 + i * layout.cellW + (layout.cellW - 6) / 2}
                    y={r.h / 2 + 5}
                    textAnchor="middle"
                  />
                  <text
                    className="svg-index"
                    x={8 + i * layout.cellW + (layout.cellW - 6) / 2}
                    y={r.h + 14}
                    textAnchor="middle"
                  >
                    {i}
                  </text>
                </g>
              ))}
            </g>
          </g>
        )
      })}

      {/* 배우: 변수 알약 */}
      {plan.variables.map(v => (
        <g key={`v${v.varKey}`} data-var={v.varKey}>
          <g className="actor-inner">
            <rect x={0} y={0} width={VAR_W} height={VAR_H} rx={VAR_H / 2} fill="var(--accent-wash)" stroke="var(--accent)" strokeWidth={1.4} />
            <text x={14} y={24} className="svg-name">
              {v.name.length > 9 ? v.name.slice(0, 8) + '…' : v.name}
            </text>
            <text className="film-var-value svg-value" x={VAR_W - 14} y={24} textAnchor="end" />
          </g>
        </g>
      ))}

      {/* 이동 칩 — 값이 실제로 날아가는 순간을 위한 풀(2개) */}
      {[0, 1].map(i => (
        <g key={`chip${i}`} data-chip={i} className="film-chip">
          <rect x={-44} y={-15} width={88} height={30} rx={15} fill="var(--accent-wash)" stroke="var(--accent)" strokeWidth={1.4} />
          <text textAnchor="middle" y={5} className="svg-name" />
        </g>
      ))}
      </g>{/* /film-cam-frame */}
      </g>{/* /film-cam-auto — 배우와 칩만 카메라를 탄다 */}

      {/* 하단 HUD — 프레임 카드·출력 바는 카메라 밖, 항상 화면 바닥에 */}
      <g transform={`translate(0 ${hudOffset})`}>
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
        <g className="film-stdout">
          <rect x={24} y={layout.height - 52} width={layout.width - 48} height={36} rx={8} fill="var(--sunken)" stroke="var(--line)" strokeWidth={1} />
          <text x={38} y={layout.height - 28} className="svg-type">출력</text>
          <text className="film-stdout-text svg-value" x={92} y={layout.height - 28} />
        </g>
      </g>

      {/* 반복 배지 */}
      <g className="film-loop">
        <rect x={24} y={14} width={240} height={30} rx={15} fill="var(--accent-wash)" stroke="var(--accent)" strokeWidth={1.2} />
        <text className="film-loop-text svg-value" x={40} y={34} />
      </g>

      {/* 비교 칩 */}
      <g className="film-compare">
        <rect x={layout.width / 2 - 130} y={14} width={260} height={30} rx={15} fill="var(--panel)" stroke="var(--accent)" strokeWidth={1.4} />
        <text className="film-compare-text svg-name" x={layout.width / 2} y={34} textAnchor="middle" />
      </g>

      {/* 오류 스트립 */}
      <g className="film-error">
        <rect x={24} y={14} width={layout.width - 48} height={34} rx={8} fill="var(--panel)" stroke="var(--accent)" strokeWidth={1.4} />
        <text className="svg-type" x={40} y={36}>오류</text>
        <text className="film-error-text svg-name" x={92} y={36} />
      </g>
      </g>
      </svg>
      <div className="film-zoom" role="group" aria-label="확대 조절">
        <button type="button" className="tl-btn tl-btn--quiet tl-btn--sm" onClick={() => zoomBy(0.8)} aria-label="축소">
          −
        </button>
        <button type="button" className="tl-btn tl-btn--quiet tl-btn--sm" onClick={() => setCam(FIT)} aria-label="화면 맞춤">
          맞춤
        </button>
        <button type="button" className="tl-btn tl-btn--quiet tl-btn--sm" onClick={() => zoomBy(1.25)} aria-label="확대">
          +
        </button>
      </div>
    </div>
  )
}
