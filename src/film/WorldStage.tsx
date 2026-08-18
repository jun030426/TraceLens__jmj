import { useEffect, useMemo, useRef, useState } from 'react'
import gsap from 'gsap'
import type { Motion, Shot, StagePlan } from './types'
import { GRID_CELL, type StageLayout } from './layout'
import { compose, type Camera, type Composition } from './compose'
import { detectTheme } from './theme'
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
  const theme = useMemo(() => detectTheme(plan, shots), [plan, shots])

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
          '[data-obj], [data-var], [data-frame], [data-cell], [data-gcursor], [data-gtrail], .film-chip, .film-error, .film-loop, .cell-flash, .pill-flash, .cell-ring, .pill-ring, .film-scale, .film-scale-stamp, .cell-done',
        ),
        { opacity: 0 },
      )
      // 값 막대는 바닥에서 자란다 — scaleY 하나로 리셋·스크럽이 전부 일관된다
      gsap.set(root.querySelectorAll('.cell-bar'), { scaleY: 0, transformOrigin: '50% 100%' })
      // 셀 그룹의 transform 잔여 청소 — origin 보정 translate가 남으면 칸이 상자를 이탈한다
      gsap.set(root.querySelectorAll('[data-cell]'), { x: 0, y: 0, scale: 1 })
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
      let scaleUp = false // 저울이 무대에 올라와 있는가 — 비교 연속 구간에서 깜빡임 방지

      const actorEl = (key: string) =>
        key.startsWith('o') ? q(objSel(Number(key.slice(1)))) : q(varSel(key.slice(1)))

      // 읽기/쓰기 색 언어 — 쓰기는 따뜻한 플래시(면), 읽기는 accent 링(획).
      // 클래스 토글이 아니라 타임라인 트윈이라 스크럽·되감기에도 상태가 새지 않는다
      const writeFlash = (sel: string, at: string | number, dur = 0.9) => {
        const el = q(sel)
        if (el) tl.fromTo(el, { opacity: 0.5 }, { opacity: 0, duration: sec(dur), ease: 'power2.out' }, at)
      }
      const readRing = (sel: string, at: string | number, dur = 1.0) => {
        const el = q(sel)
        if (el) tl.fromTo(el, { opacity: 1 }, { opacity: 0, duration: sec(dur), ease: 'power2.in' }, at)
      }
      // 값 막대 — 칸 값이 바뀌는 모든 지점에서 높이를 따라 그린다 (음수 없는 숫자 리스트만 DOM에 존재)
      const setBar = (id: number, idx: number, text: string, at: string | number) => {
        const el = q(`${cellSel(id, idx)} .cell-bar`)
        if (!el) return
        const v = Number(text)
        const max = theme.maxAbs.get(id) ?? 1
        const ratio = Number.isFinite(v) ? Math.max(0.05, v / max) : 0
        tl.to(el, { scaleY: ratio, duration: sec(0.3), ease: 'power2.out', transformOrigin: '50% 100%' }, at)
      }

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

      // 라벨은 절대 위치 — useFilm의 샷 경계(durationMs 누적)와 타임라인이 초 단위로
      // 일치해야 스크럽·자막·인덱스가 화면과 같은 것을 가리킨다. 자동 이어붙이기는
      // 샷마다 꼬리가 붙어 경계가 뒤로 밀리고, 끝에서는 자막이 화면보다 여러 샷을 앞서 달렸다.
      let cum = 0
      shots.forEach((shot, si) => {
        const d = sec(shot.durationMs / 1000)
        const label = `s${shot.seq}`
        tl.addLabel(label, cum)
        cum += d
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

        // 등장의 리듬 — 같은 샷의 여러 grow는 칸 순서대로 계단식. 리터럴 탄생이
        // 한꺼번에 터지지 않고 "차오르는" 서사가 된다 (샷 길이 안에 맞춰 압축)
        const grows = shot.motions.filter(m => m.v === 'grow')
        const growStep = grows.length > 1 ? Math.min(sec(0.09), (d * 0.9) / grows.length) : 0
        // 값 이동이 있는 샷 — 도착지의 갱신은 칩이 내려앉는 순간으로 늦춘다 (원인 → 결과)
        const travelM = shot.motions.find(m => m.v === 'travel') as Extract<Motion, { v: 'travel' }> | undefined
        const arriveAt = `${label}+=${sec(0.55)}`

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
            case 'travel': {
              // 값의 이동 — choreograph가 의미(어디서 어디로)를 정했고, 여기는 좌표만 푼다
              const endPoint = (t: typeof m.from) => {
                if (t.kind === 'cell') {
                  const po = comp.get(`o${t.objectId}`)
                  if (!po) return null
                  const local = cellCenterLocal(t.objectId, t.index)
                  return { x: po.x + local.x * po.s, y: po.y + local.y * po.s }
                }
                const pv = comp.get(`v${t.varKey}`)
                if (!pv) return null
                return { x: pv.x + (VAR_W / 2) * pv.s, y: pv.y + (VAR_H / 2) * pv.s }
              }
              const from = endPoint(m.from)
              const to = endPoint(m.to)
              if (from && to) travel(label, m.text, from, to)
              break
            }
            case 'setVar': {
              const key = m.varKey
              const text = m.text
              // 칩이 이 알약으로 날아오는 중이면 값 갱신·펄스는 도착 순간에 — 원인이 결과보다 먼저
              const at = travelM?.to.kind === 'var' && travelM.to.varKey === key ? arriveAt : label
              tl.call(
                () => {
                  const el = root.querySelector(`${varSel(key)} .film-var-value`)
                  if (el) el.textContent = text
                },
                undefined,
                at,
              )
              writeFlash(`${varSel(key)} .pill-flash`, at, d * 0.9)
              const iv = inner(varSel(key))
              if (iv) {
                tl.fromTo(
                  iv,
                  { scale: 1.28 },
                  { scale: 1, duration: d * 0.7, ease: 'back.out(2.4)', transformOrigin: 'center' },
                  at,
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
              // 끈은 없다 — 이름표(label 모션)가 소속을 말하고, 별칭이면 상자가 잠깐 부푼다.
              // 알약 값칸에는 "→ 상자"를 적는다 — 빈 칸은 학습자에게 물음표다
              const key = m.varKey
              tl.call(
                () => {
                  const el = root.querySelector(`${varSel(key)} .film-var-value`)
                  if (el) el.textContent = '→ 상자'
                },
                undefined,
                label,
              )
              writeFlash(`${varSel(key)} .pill-flash`, label, d * 0.9)
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
              // 계단식 등장 — 이 샷의 몇 번째 grow인가가 등장 시점을 정한다.
              // 칩이 이 칸으로 날아오는 중이면 도착 순간에 나타난다
              const arriving =
                travelM?.to.kind === 'cell' && travelM.to.objectId === id && travelM.to.index === idx
              const at = arriving ? arriveAt : growStep ? `${label}+=${grows.indexOf(m) * growStep}` : label
              tl.call(
                () => {
                  const el = root.querySelector(`${cellSel(id, idx)} .film-cell-text`)
                  if (el) el.textContent = fitCell(text)
                },
                undefined,
                at,
              )
              // origin은 셀 트윈 전체에서 'center'로 통일한다 — origin이 트윈마다 다르면
              // GSAP의 SVG origin 보정 translate가 잔여로 남아 칸이 상자를 이탈한다
              tl.fromTo(
                q(cellSel(id, idx))!,
                { opacity: 0, scale: 0.3 },
                { opacity: 1, scale: 1, duration: d, ease: 'back.out(2)', transformOrigin: 'center' },
                at,
              )
              writeFlash(`${cellSel(id, idx)} .cell-flash`, at, d * 0.8)
              setBar(id, idx, text, at)
              break
            }
            case 'setCell': {
              const id = m.objectId
              const idx = m.index
              const text = m.text
              const arriving =
                travelM?.to.kind === 'cell' && travelM.to.objectId === id && travelM.to.index === idx
              const at = arriving ? arriveAt : label
              tl.call(
                () => {
                  const el = root.querySelector(`${cellSel(id, idx)} .film-cell-text`)
                  if (el) el.textContent = fitCell(text)
                },
                undefined,
                at,
              )
              tl.fromTo(
                q(cellSel(id, idx))!,
                { scale: 1.35 },
                { scale: 1, opacity: 1, duration: d, ease: 'back.out(2)', transformOrigin: 'center' },
                at,
              )
              writeFlash(`${cellSel(id, idx)} .cell-flash`, at, d * 0.8)
              setBar(id, idx, text, at)
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
              // 자리를 바꾼 두 칸이 내려앉으며 함께 번쩍인다 — "여기가 바뀌었다"의 마침표
              writeFlash(`${cellSel(id, i)} .cell-flash`, `${label}+=${d * 0.55}`, d * 0.45)
              writeFlash(`${cellSel(id, k)} .cell-flash`, `${label}+=${d * 0.55}`, d * 0.45)
              setBar(id, i, iText, `${label}+=${d * 0.55}`)
              setBar(id, k, kText, `${label}+=${d * 0.55}`)
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
              {
                // 오류 앞에서 저울도 내린다 — 경광등만 남는 화면
                const sc = q('.film-scale')
                if (sc) tl.to(sc, { opacity: 0, duration: d * 0.2 }, label)
                scaleUp = false
              }
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
              {
                // 입문 스킨 — 회차마다 화살이 한 바퀴: "돌고 있다"가 몸으로 보인다
                const spin = q('.film-loop-spin')
                if (spin) {
                  tl.fromTo(
                    spin,
                    { rotation: 0 },
                    { rotation: 360, duration: d * 0.7, ease: 'power1.inOut', transformOrigin: '0px 0px' },
                    label,
                  )
                }
              }
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
            case 'sortedSweep': {
              // 정렬 완성의 마침표 — 칸이 왼쪽부터 초록으로 정착한다. 트레이스가 실제로
              // 오름차순으로 끝났을 때만 오는 모션이라, 이 초록은 항상 진실이다
              const id = m.objectId
              root.querySelectorAll(`[data-cell^="${id}-"]`).forEach((el, ci) => {
                const at = `${label}+=${sec(0.6) + ci * sec(0.09)}`
                const done = el.querySelector('.cell-done')
                if (done) tl.fromTo(done, { opacity: 0 }, { opacity: 0.35, duration: sec(0.3), ease: 'power2.out' }, at)
                tl.fromTo(
                  el,
                  { scale: 1 },
                  { scale: 1.08, duration: sec(0.12), yoyo: true, repeat: 1, ease: 'power1.inOut', transformOrigin: 'center' },
                  at,
                )
              })
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
              const scaleEl = q('.film-scale')
              if (scaleEl && m.a !== undefined && m.b !== undefined) {
                // 판단을 저울로 — 양팔에 값 카드, 무거운 쪽으로 기울고 도장이 찍힌다.
                // 저울은 판단의 흐름 동안 무대에 머문다: 비교가 이어지는 구간에서 샷마다
                // 떴다 사라지면 깜빡임이 된다. 근처에 다음 비교가 있으면 내려놓지 않는다.
                const a = m.a
                const b = m.b
                const opTxt = m.op ?? ''
                const cap = (s: string) => (s.length > 8 ? s.slice(0, 7) + '…' : s)
                tl.call(
                  () => {
                    const ta = root.querySelector('.film-scale-a')
                    const tb = root.querySelector('.film-scale-b')
                    const to = root.querySelector('.film-scale-op')
                    if (ta) ta.textContent = cap(a)
                    if (tb) tb.textContent = cap(b)
                    if (to) to.textContent = opTxt
                  },
                  undefined,
                  label,
                )
                tl.set(root.querySelectorAll('.film-scale-stamp'), { opacity: 0 }, label)
                if (!scaleUp) {
                  tl.fromTo(scaleEl, { opacity: 0 }, { opacity: 1, duration: d * 0.35, ease: 'power2.out' }, label)
                }
                const beam = q('.film-scale-beam')
                const av = Number(a)
                const bv = Number(b)
                if (beam && Number.isFinite(av) && Number.isFinite(bv) && av !== bv) {
                  tl.fromTo(
                    beam,
                    { rotation: 0 },
                    { rotation: av > bv ? -8 : 8, duration: d * 0.5, ease: 'power2.out', transformOrigin: '0px 0px' },
                    `${label}+=${d * 0.15}`,
                  )
                } else if (beam) {
                  tl.set(beam, { rotation: 0 }, label)
                }
                if (m.verdict !== undefined) {
                  const stamp = q(m.verdict ? '.film-scale-stamp--true' : '.film-scale-stamp--false')
                  if (stamp) {
                    tl.fromTo(
                      stamp,
                      { opacity: 0, scale: 1.4 },
                      { opacity: 1, scale: 1, duration: d * 0.35, ease: 'back.out(2)', transformOrigin: 'center' },
                      `${label}+=${d * 0.5}`,
                    )
                  }
                }
                const streak = shots
                  .slice(si + 1, si + 3)
                  .some(s => s.motions.some(mm => mm.v === 'compare'))
                if (streak) {
                  scaleUp = true
                } else {
                  tl.to(scaleEl, { opacity: 0, duration: d * 0.45 }, `${label}+=${d * 1.05}`)
                  scaleUp = false
                }
              }
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
                // 읽기는 파란 링 — 어느 값을 들여다보는지가 색으로 남는다 (쓰기 플래시와 구분)
                readRing(
                  t.kind === 'cell' ? `${cellSel(t.objectId, t.index)} .cell-ring` : `${varSel(t.varKey)} .pill-ring`,
                  label,
                  d * 0.9,
                )
              }
              break
            }
          }
        }
        // 커튼콜 settle 웨이브 — 마지막 샷에서 칸들이 차례로 잔잔히 내려앉는다. 완성의 마침표.
        // sortedSweep이 있으면 그 스윕이 곧 마침표이므로 이중 펄스를 만들지 않는다
        if (si === shots.length - 1 && !shot.motions.some(m => m.v === 'sortedSweep')) {
          root.querySelectorAll('[data-cell]').forEach((el, ci) => {
            tl.fromTo(
              el,
              { scale: 1 },
              { scale: 1.07, duration: sec(0.12), yoyo: true, repeat: 1, ease: 'power1.inOut', transformOrigin: 'center' },
              `${label}+=${sec(0.55) + ci * sec(0.05)}`,
            )
          })
        }

        prevComp = comp
      })
      tl.to({}, { duration: 0.001 }, cum) // 경계 총합까지 길이 보장 — 마지막 샷이 짧아도 어긋나지 않게

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
  }, [shots, register, layout, plan, comps, cams, theme])

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
                  <rect
                    className="cell-done"
                    x={8 + i * layout.cellW}
                    y={8}
                    width={layout.cellW - 6}
                    height={r.h - 16}
                    rx={5}
                  />
                  {theme.barObjects.has(o.objectId) && (
                    <rect
                      className="cell-bar"
                      x={8 + i * layout.cellW + 4}
                      y={12}
                      width={layout.cellW - 14}
                      height={r.h - 24}
                      rx={3}
                    />
                  )}
                  <rect
                    className="cell-flash"
                    x={8 + i * layout.cellW}
                    y={8}
                    width={layout.cellW - 6}
                    height={r.h - 16}
                    rx={5}
                  />
                  <text
                    className="film-cell-text svg-value"
                    x={8 + i * layout.cellW + (layout.cellW - 6) / 2}
                    y={r.h / 2 + 5}
                    textAnchor="middle"
                  />
                  <rect
                    className="cell-ring"
                    x={6 + i * layout.cellW}
                    y={6}
                    width={layout.cellW - 2}
                    height={r.h - 12}
                    rx={7}
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
            <rect className="pill-flash" x={0} y={0} width={VAR_W} height={VAR_H} rx={VAR_H / 2} />
            <text x={14} y={24} className="svg-name">
              {v.name.length > 9 ? v.name.slice(0, 8) + '…' : v.name}
            </text>
            <text className="film-var-value svg-value" x={VAR_W - 14} y={24} textAnchor="end" />
            <rect className="pill-ring" x={-2.5} y={-2.5} width={VAR_W + 5} height={VAR_H + 5} rx={(VAR_H + 5) / 2} />
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

      {/* 반복 배지 — 한 바퀴 도는 화살이 회차마다 돈다 */}
      <g className="film-loop">
        <rect x={24} y={14} width={240} height={30} rx={15} fill="var(--accent-wash)" stroke="var(--accent)" strokeWidth={1.2} />
        <g className="film-loop-spin" transform="translate(42 29)">
          <path d="M 0 -7 A 7 7 0 1 1 -6.4 2.9" fill="none" strokeWidth={2} />
          <polygon points="-1,-11 5,-7 -1,-3" />
        </g>
        <text className="film-loop-text svg-value" x={58} y={34} />
      </g>

      {/* 비교 저울 — 양팔에 값 카드가 올라가고 무거운 쪽으로 기울며 참/거짓 도장.
          받침 삼각형은 허브 핀으로 빔과 접합되고, 접시는 걸이줄로 빔에 매달린다.
          부등호는 빔 위 전용 배지 — 빔이 기울어도 절대 가리지 않는다.
          상단 저울 띠(y≈2~78)는 compose의 AREA.y0(84)가 비워둔다 — 배우와 겹치지 않는 계약 */}
      <g className="film-scale" transform={`translate(${layout.width / 2} 36)`}>
          <polygon className="film-scale-pivot" points="-9,24 9,24 0,2" />
          <rect className="film-scale-base" x={-16} y={24} width={32} height={3} rx={1.5} />
          <g className="film-scale-beam">
            <line x1={-70} y1={0} x2={70} y2={0} />
            <line className="film-scale-hanger" x1={-62} y1={0} x2={-62} y2={6} />
            <line className="film-scale-hanger" x1={62} y1={0} x2={62} y2={6} />
            <g transform="translate(-62 6)">
              <rect className="film-scale-pan" x={-32} y={0} width={64} height={26} rx={7} />
              <text className="film-scale-a svg-name" y={18} textAnchor="middle" />
            </g>
            <g transform="translate(62 6)">
              <rect className="film-scale-pan" x={-32} y={0} width={64} height={26} rx={7} />
              <text className="film-scale-b svg-name" y={18} textAnchor="middle" />
            </g>
            <circle className="film-scale-hub" r={4} />
          </g>
          <g transform="translate(0 -22)">
            <circle className="film-scale-opbadge" r={12} />
            <text className="film-scale-op svg-name" y={5} textAnchor="middle" />
          </g>
          <g className="film-scale-stamp film-scale-stamp--true">
            <rect x={100} y={-14} width={48} height={30} rx={8} />
            <text className="svg-name" x={124} y={7} textAnchor="middle">
              참
            </text>
          </g>
          <g className="film-scale-stamp film-scale-stamp--false">
            <rect x={100} y={-14} width={62} height={30} rx={8} />
            <text className="svg-name" x={131} y={7} textAnchor="middle">
              거짓
            </text>
          </g>
      </g>

      {/* 오류 스트립 — 색 기준: 오류는 빨강 */}
      <g className="film-error">
        <rect x={24} y={14} width={layout.width - 48} height={34} rx={8} fill="var(--panel)" stroke="var(--stop)" strokeWidth={1.4} />
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
