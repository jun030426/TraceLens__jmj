import { useEffect, useMemo, useRef, useState } from 'react'
import gsap from 'gsap'
import type { Motion, Shot, StagePlan } from './types'
import { GRID_CELL, STACK_SLOTS, type StageLayout } from './layout'
import { compose, type Camera, type Composition } from './compose'
import { detectTheme } from './theme'
import { GRAMMAR } from './presets'
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
/** 값 토큰 — 슬롯 층 위의 독립 층에 산다 (겹침 순서 계약) */
const tokSel = (id: number, i: number) => `[data-token="${id}-${i}"]`
const varSel = (key: string) => `[data-var="${esc(key)}"]`
const ptrSel = (key: string) => `[data-ptr="${esc(key)}"]`
const frameSel = (id: number) => `[data-frame="${id}"]`

/** 프레임 카드가 든 값 줄 — 카드 밖으로 나가지 않게 **실제 렌더 폭**으로 맞추고, 못 넣은
    것은 개수로 밝힌다 (`⋯ 앞선 호출 k개`·`20 / 500`과 같은 계열). 글자폭 상수를 추정하지
    않는 이유: 폰트가 바뀌면 상수는 조용히 틀린다. 기준은 **가장 좁은 슬롯**의 폭이라
    창이 스크롤해 카드가 슬롯을 옮겨도 다시 재지 않는다. */
const fitFrameVals = (el: SVGTextElement, texts: string[], maxW: number) => {
  if (texts.length === 0) {
    el.textContent = ''
    return
  }
  for (let n = texts.length; n >= 1; n--) {
    const hidden = texts.length - n
    el.textContent = texts.slice(0, n).join(' · ') + (hidden ? ` +${hidden}` : '')
    if (el.getComputedTextLength() <= maxW) return
  }
  // 하나도 통째로는 안 들어간다 — 글자를 줄이고 나머지는 개수로 밝힌다
  const tail = texts.length > 1 ? ` +${texts.length - 1}` : ''
  for (let cut = texts[0].length - 1; cut >= 1; cut--) {
    el.textContent = texts[0].slice(0, cut) + '…' + tail
    if (el.getComputedTextLength() <= maxW) return
  }
}

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
  const { comps, cams, scales, autos, stacks } = useMemo(() => compose(shots, plan, layout), [shots, plan, layout])
  const theme = useMemo(() => detectTheme(plan, shots), [plan, shots])

  // 인덱스 포인터 — pointer 모션으로 접지된 변수들. 알약 대신 배열 아래 화살표로 산다
  const pointers = useMemo(() => {
    const map = new Map<string, { objectId: number; row: number; name: string }>()
    const perObj = new Map<number, number>()
    for (const sh of shots)
      for (const m of sh.motions)
        if (m.v === 'pointer' && !map.has(m.varKey)) {
          const row = perObj.get(m.objectId) ?? 0
          perObj.set(m.objectId, row + 1)
          const name = plan.variables.find(v => v.varKey === m.varKey)?.name ?? m.varKey
          map.set(m.varKey, { objectId: m.objectId, row, name })
        }
    return map
  }, [shots, plan])

  // 칸 번호는 포인터가 붙은 배열에만 — 코드가 실제로 인덱스로 접근할 때만 "j가 가리키는 칸"의
  // 대응이 가르칠 게 있다. 그 외의 0·1·2…는 초보에게 걸림돌이자 소음이다 (표기 걷어내기)
  const numberedObjs = useMemo(() => {
    const s = new Set<number>()
    for (const p of pointers.values()) s.add(p.objectId)
    return s
  }, [pointers])

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
      /* 카메라는 transform 속성을 직접 쓴다.
         GSAP의 x/y/scale은 SVG에서 origin(transformOrigin은 bbox 기준, svgOrigin은 그 나름의
         규칙)을 거치는데, 안쪽 프레임 카메라가 움직이면 바깥 강조 카메라의 bbox가 따라 밀려
         origin이 흔들리고, smoothOrigin이 그 변화를 x에 구워버린다 (실측: 190px, 185px).
         compose가 계산한 값이 곧 행렬이어야 하므로 프록시를 트윈하고 속성을 직접 쓴다. */
      type Cam3 = { k: number; x: number; y: number }
      const camWrite = (el: Element, v: Cam3) =>
        el.setAttribute('transform', `translate(${v.x} ${v.y}) scale(${v.k})`)
      const camStates = new Map<Element, Cam3>()
      const camInit = (el: Element, v: Cam3) => {
        gsap.set(el, { clearProps: 'transform' }) // GSAP이 남긴 style transform 제거 — 속성만 쓴다
        const st = { ...v }
        camStates.set(el, st)
        camWrite(el, st)
        return st
      }
      const camTo = (el: Element, v: Cam3, dur: number, at: number | string) => {
        const st = camStates.get(el)
        if (!st) return
        tl.to(st, { k: v.k, x: v.x, y: v.y, duration: dur, ease: 'power2.inOut', onUpdate: () => camWrite(el, st) }, at)
      }
      gsap.set(
        root.querySelectorAll(
          '[data-obj], [data-var], [data-frame], [data-cell], [data-token], [data-gcursor], [data-gtrail], .film-chip, .film-error, .film-loop, .cell-flash, .pill-flash, .cell-ring, .pill-ring, .film-scale, .film-scale-stamp, .cell-done, .film-obj-partial, .film-stack-more, .film-frame-vals, .film-return-chip',
        ),
        { opacity: 0 },
      )
      // 값 막대는 바닥에서 자란다 — scaleY 하나로 리셋·스크럽이 전부 일관된다
      gsap.set(root.querySelectorAll('.cell-bar'), { scaleY: 0, transformOrigin: '50% 100%' })
      // 카드가 든 값 — 텍스트와 이름 자리를 초기 상태로 되돌린다. 이름의 y는 attr이라
      // GSAP의 opacity 리셋 대상 밖이고, 남으면 다음 재생에서 이름이 올라간 채 시작한다
      for (const f of plan.frames) {
        const card = q(frameSel(f.frameId))
        if (!card) continue
        const vt = card.querySelector('.film-frame-vals')
        if (vt) vt.textContent = ''
        card.querySelector('.svg-name')?.setAttribute('y', String(layout.framePos.get(0)!.y + 34))
      }
      // 저울 빔의 잔여 회전 청소 (attr 기반이라 GSAP 리셋 대상 밖)
      root.querySelector('.film-scale-beam')?.setAttribute('transform', 'rotate(0)')
      // 인덱스 포인터 — 0번 칸 밑에서 숨은 채 시작, 첫 setVar가 자리로 데려간다
      for (const [key, p] of pointers) {
        const el = q(ptrSel(key))
        if (!el) continue
        const h = objH.get(p.objectId) ?? 64
        gsap.set(el, { x: 8 + (layout.cellW - 6) / 2, y: h + 22 + p.row * 26, opacity: 0 })
      }
      // 셀 그룹의 transform 잔여 청소 — origin 보정 translate가 남으면 칸이 상자를 이탈한다.
      // clearProps로 GSAP의 origin 캐시까지 비운 뒤, 모든 칸 트윈과 같은 origin(center)으로 재설정
      // (origin이 섞이면 보정 translate 잔여가 칸 전체를 몇 px씩 밀고, 포인터 같은 바깥 기준점과 어긋난다)
      // 슬롯·토큰 두 층 모두 같은 규율 — 비행의 x·y 잔여를 지우고 origin을 center로 통일한다.
      // smoothOrigin은 반드시 끈다: 토큰 bbox는 글자가 채워지며 커지고(빈 글자 → 값), 그때
      // 'center'가 가리키는 점이 옮겨간다. smoothOrigin이 그 이동을 "튀지 않게" 보정하면서
      // y 오프셋을 영구히 구워버려, 막대와 숫자가 칸보다 9px 아래로 내려앉았다 (실측).
      gsap.set(root.querySelectorAll('[data-cell], [data-token]'), { clearProps: 'transform' })
      gsap.set(root.querySelectorAll('[data-cell], [data-token]'), {
        x: 0, y: 0, scale: 1, transformOrigin: 'center', smoothOrigin: false,
      })
      // 저울은 홈(상단 띠 중앙)에서 시작한다 — 자리는 compose(scales)가 샷마다 소유한다
      gsap.set(root.querySelectorAll('.film-scale'), { x: layout.width / 2, y: 36 })
      // 강조 카메라 — origin은 리셋과 트윈이 반드시 같아야 한다. 리셋만 기본값(center)이면
      // 트윈이 '0px 0px'로 바꾸는 순간 smoothOrigin이 보정 오프셋을 구워, 배율만 오르고
      // 중심 이동이 어긋난다 (토큰의 9px 오프셋과 같은 함정)
      const autoCam0 = q('.film-cam-auto')
      if (autoCam0) camInit(autoCam0, { k: 1, x: 0, y: 0 })
      // 오토 프레이밍 카메라 — 첫 구성의 프레임으로 시작
      const frameCam = q('.film-cam-frame')
      let appliedCam: Camera | null = cams[0] ?? null
      if (frameCam && appliedCam) camInit(frameCam, { k: appliedCam.k, x: appliedCam.x, y: appliedCam.y })
      const tl = gsap.timeline({ paused: true })
      let liveFrame: Element | null = null
      let prevComp: Composition = new Map()
      let chipTurn = 0
      const frameSlot = new Map<number, number>() // 프레임이 지금 앉아 있는 슬롯
      let prevHidden = 0
      const autoEl = q('.film-cam-auto')
      let appliedAuto = { k: 1, x: 0, y: 0 }
      const scaleEl = q('.film-scale')
      let scaleUp = false // 저울이 무대에 올라와 있는가 — 비교 연속 구간에서 깜빡임 방지
      let scalePos = { x: layout.width / 2, y: 36 } // 저울의 현재 자리 — 홈에서 출발
      let prevRot = 0 // 빔의 직전 기울기 — 수평 스냅 없이 이어서 스윙한다
      let prevStamp: Element | null = null // 직전 판정 도장 — 즉시 리셋 대신 부드럽게 교체

      const actorEl = (key: string) =>
        key.startsWith('o') ? q(objSel(Number(key.slice(1)))) : q(varSel(key.slice(1)))

      // 읽기/쓰기 색 언어 — 쓰기는 따뜻한 플래시(면), 읽기는 accent 링(획).
      // 클래스 토글이 아니라 타임라인 트윈이라 스크럽·되감기에도 상태가 새지 않는다
      const writeFlash = (sel: string, at: string | number, dur = 0.9) => {
        const el = q(sel)
        if (el) tl.fromTo(el, { opacity: GRAMMAR.flashStrength }, { opacity: 0, duration: sec(dur), ease: 'power2.out' }, at)
      }
      const readRing = (sel: string, at: string | number, dur = 1.0) => {
        const el = q(sel)
        if (el) tl.fromTo(el, { opacity: 1 }, { opacity: 0, duration: sec(dur), ease: 'power2.in' }, at)
      }
      // 값 막대 — 칸 값이 바뀌는 모든 지점에서 높이를 따라 그린다 (음수 없는 숫자 리스트만 DOM에 존재)
      // 칸의 자리와 물건은 함께 등장·퇴장한다 — 한쪽만 잡으면 슬롯과 토큰이 따로 논다
      const cellPair = (id: number, idx: number) => [q(cellSel(id, idx)), q(tokSel(id, idx))].filter(Boolean) as Element[]
      const setBar = (id: number, idx: number, text: string, at: string | number) => {
        const el = q(`${tokSel(id, idx)} .cell-bar`)
        if (!el) return
        const v = Number(text)
        const max = theme.maxAbs.get(id) ?? 1
        const ratio = Number.isFinite(v) ? Math.max(0.05, v / max) : 0
        tl.to(el, { scaleY: ratio, duration: sec(0.3), ease: 'power2.out', transformOrigin: '50% 100%' }, at)
      }

      // 값이 실제로 이동하는 칩 — 미리 만든 2개를 돌려쓴다 (스크럽 안전).
      // delay = 출발 전 예고(들썩)의 몫 — 출발지가 먼저 꿈틀하고, 칩이 떠난다
      const travel = (label: string, text: string, from: { x: number; y: number }, to: { x: number; y: number }, delay = 0) => {
        const chip = q(`[data-chip="${chipTurn % 2}"]`)
        chipTurn += 1
        if (!chip) return
        tl.call(
          () => {
            const t = chip.querySelector('text')
            if (t) t.textContent = fitCell(text)
          },
          undefined,
          `${label}+=${delay}`,
        )
        tl.set(chip, { x: from.x, y: from.y, opacity: 0 }, `${label}+=${delay}`)
        tl.to(chip, { opacity: 1, duration: sec(0.12) }, `${label}+=${delay}`)
        tl.to(chip, { x: to.x, y: to.y, duration: sec(0.5), ease: 'power2.inOut' }, `${label}+=${delay + sec(0.1)}`)
        tl.to(chip, { opacity: 0, duration: sec(0.15) }, `${label}+=${delay + sec(0.55)}`)
      }

      // 반환 칩 — 같은 "값의 이동" 은유지만 좌표계가 다르다. 프레임 카드는 카메라 밖(HUD)에
      // 살아서 위의 이동 칩(카메라 안)으로는 카드 사이를 날 수 없다. 여정도 칸↔알약이 아니라
      // 카드→카드이므로 부품을 따로 둔다. 도착하면 사라진다 — 부모가 그 값을 이름으로 가진
      // 것이 아니므로 남기면 없는 사실을 지어내는 것이다 (이름이 있으면 다음 샷에 알약이 뜬다)
      // 구간은 절대 초가 아니라 **샷 길이의 비율**이다 — 대본이 그 구간을 fast로 잡으면
      // 샷이 520ms 밑으로도 내려가는데(실측 510ms), 고정 0.75초짜리 비행은 다음 샷으로
      // 넘어가 같은 칩을 쓰는 다음 반환에 잘려나간다. 0.95d 안에 끝내면 겹칠 수가 없다.
      const returnTravel = (
        label: string,
        d: number,
        text: string,
        from: { x: number; y: number },
        to: { x: number; y: number },
      ) => {
        const chip = q('.film-return-chip')
        if (!chip) return
        tl.call(
          () => {
            const t = chip.querySelector('text')
            if (t) t.textContent = text
          },
          undefined,
          label,
        )
        tl.set(chip, { x: from.x, y: from.y, opacity: 0 }, label)
        tl.to(chip, { opacity: 1, duration: d * 0.15 }, label)
        tl.to(chip, { x: to.x, y: to.y, duration: d * 0.55, ease: 'power2.inOut' }, `${label}+=${d * 0.15}`)
        tl.to(chip, { opacity: 0, duration: d * 0.2 }, `${label}+=${d * 0.75}`)
      }

      // 라벨은 절대 위치 — useFilm의 샷 경계(durationMs 누적)와 타임라인이 초 단위로
      // 일치해야 스크럽·자막·인덱스가 화면과 같은 것을 가리킨다. 자동 이어붙이기는
      // 샷마다 꼬리가 붙어 경계가 뒤로 밀리고, 끝에서는 자막이 화면보다 여러 샷을 앞서 달렸다.
      let cum = 0
      shots.forEach((shot, si) => {
        const d = sec(shot.durationMs / 1000)
        const label = `s${shot.seq}`
        const labelPos = cum
        tl.addLabel(label, cum)
        cum += d
        const comp = comps[si] ?? new Map()

        // 카메라가 이야기를 따라간다 — 구성 경계가 유의미하게 바뀔 때만 (compose가 감쇠).
        // 선행 도착: 행동이 시작되기 camLead초 전에 출발한다 — 시선이 먼저 자리 잡게
        const camNow = cams[si]
        if (frameCam && camNow && camNow !== appliedCam) {
          camTo(
            frameCam,
            { k: camNow.k, x: camNow.x, y: camNow.y },
            sec(0.5),
            Math.max(0, labelPos - sec(GRAMMAR.camLead)),
          )
          appliedCam = camNow
        }

        // ── 구성 전환 — 배우 가시성·위치·배율의 단일 소유자 ──
        // 자리는 비운 뒤에 채운다. 퇴장과 등장이 같은 순간에 걸리면 두 배우가 반쯤 겹친 채
        // 둘 다 읽히는데, 알약 스트립처럼 자리를 물려주는 구조에서는 그게 곧 오독이다
        // (실측: 접히는 n = 10과 새로 서는 n = 9가 3,196px² 겹쳤다 — 재귀에서 "어느 n이
        // 지금인가"가 그대로 되살아난다). 비우는 시간은 짧은 샷에서도 등장할 몫이 남도록 잰다.
        const actorLeaves = [...prevComp.keys()].some(k => !comp.has(k))
        const clearD = actorLeaves ? Math.min(sec(0.24), d * 0.4) : 0
        const enterAt = labelPos + clearD
        for (const key of prevComp.keys()) {
          if (comp.has(key)) continue
          const el = actorEl(key)
          if (el) tl.to(el, { opacity: 0, duration: clearD, ease: 'power2.in' }, label)
        }
        for (const [key, p] of comp) {
          const el = actorEl(key)
          if (!el) continue
          const was = prevComp.get(key)
          // 시선 통제 — 지금 말하는 배우만 온전한 밝기, 나머지는 프리셋만큼 물러난다
          const op = p.focus ? 1 : GRAMMAR.dimIdle
          if (!was) {
            tl.fromTo(
              el,
              { opacity: 0, x: p.x, y: p.y + 18, scale: p.s * 0.9, transformOrigin: '0px 0px' },
              { opacity: op, y: p.y, scale: p.s, duration: Math.min(sec(0.4), d - clearD), ease: 'power2.out' },
              enterAt,
            )
          } else if (was.x !== p.x || was.y !== p.y || was.s !== p.s) {
            tl.to(
              el,
              { x: p.x, y: p.y, scale: p.s, duration: Math.min(sec(0.45), d), ease: 'power2.inOut', transformOrigin: '0px 0px' },
              label,
            )
          }
          if ((was?.focus ?? false) !== p.focus) {
            if (was) tl.to(el, { opacity: op, duration: sec(0.3), ease: 'power2.out' }, label)
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
        // 값 이동이 있는 샷 — 도착지의 갱신은 칩이 내려앉는 순간으로 늦춘다 (원인 → 결과).
        // 예고(출발지 들썩)만큼 출발·도착이 함께 밀린다
        const travelM = shot.motions.find(m => m.v === 'travel') as Extract<Motion, { v: 'travel' }> | undefined
        const travelAnt = sec(GRAMMAR.anticipation)
        const arriveAt = `${label}+=${travelAnt + sec(0.55)}`

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

        // 호출 스택 창 — 프레임이 앉을 슬롯은 compose가 정했다. 슬롯 0 자리에 그려둔
        // 카드를 그 슬롯으로 옮기고, 창 밖 프레임은 내린다. 폭은 슬롯마다 다르므로
        // rect의 width도 함께 트윈한다 (창 안 슬롯은 0..4라 폭이 음수가 될 수 없다)
        {
          const stack = stacks[si]
          const slot0 = layout.framePos.get(0)!
          // 창은 자리를 물려주는 구조라 3단으로 갈라야 한다: ① 밀려난 카드가 사라지고
          // ② 남은 카드가 그 자리로 내려온 다음 ③ 새 카드가 맨 위 슬롯에 들어온다.
          // 셋을 같이 걸면 사라지는 카드 위로 이동 카드가 미끄러져 둘 다 읽히는 순간이
          // 생긴다 (실측 3,902px² — 이름이 같은 fact 카드 둘이라 오독 그 자체다)
          const cOut = Math.min(sec(0.14), d * 0.22)
          const cMoveAt = labelPos + cOut
          const cMove = Math.min(sec(0.24), d * 0.3)
          const cEnterAt = cMoveAt + cMove
          for (const f of plan.frames) {
            const el = q(frameSel(f.frameId))
            if (!el) continue
            const slot = stack?.slots.get(f.frameId)
            const was = frameSlot.get(f.frameId)
            if (slot === undefined) {
              if (was !== undefined) {
                tl.to(el, { opacity: 0, duration: cOut, ease: 'power2.in' }, label)
                frameSlot.delete(f.frameId)
              }
              continue
            }
            if (was === slot) continue
            const r = layout.framePos.get(slot)!
            const rect = el.querySelector('rect')
            if (was === undefined) {
              // 창이 스크롤될 때 새 카드는 직전 점유자가 그 슬롯을 비운 뒤에 온다 —
              // 같이 걸면 카드끼리 2,910px², 사라지는 프로그램 카드와 "⋯ 앞선 호출 k개" 띠가
              // 2,838px² 겹쳤다 (실측). 배우 스트립과 같은 규율이다
              tl.fromTo(
                el,
                { opacity: 0, x: r.x - slot0.x - 26, y: r.y - slot0.y },
                { opacity: 1, x: r.x - slot0.x, y: r.y - slot0.y, duration: d - cOut - cMove, ease: 'power3.out' },
                cEnterAt,
              )
              if (rect) tl.set(rect, { attr: { width: r.w } }, cEnterAt)
            } else {
              tl.to(el, { x: r.x - slot0.x, y: r.y - slot0.y, duration: cMove, ease: 'power2.inOut' }, cMoveAt)
              if (rect) tl.to(rect, { attr: { width: r.w }, duration: cMove, ease: 'power2.inOut' }, cMoveAt)
            }
            frameSlot.set(f.frameId, slot)
          }
          // 접힌 얕은 호출 — 개수로 정직하게
          const more = q('.film-stack-more')
          const hidden = stack?.hidden ?? 0
          if (more && hidden !== prevHidden) {
            if (hidden > 0) {
              tl.call(
                () => {
                  const t = root.querySelector('.film-stack-more-text')
                  if (t) t.textContent = `⋯ 앞선 호출 ${hidden}개`
                },
                undefined,
                label,
              )
              tl.to(more, { opacity: 1, duration: d - cOut - cMove }, cEnterAt)
            } else {
              tl.to(more, { opacity: 0, duration: cOut }, label)
            }
            prevHidden = hidden
          }
        }

        // 강조 — decorate가 표시한 비트에서 대상이 화면 중앙으로 당겨진다. 좌표는 compose가
        // 배치에서 계산했다. 카메라는 camLead만큼 먼저 출발해 짧게 도착하고 그 샷 동안 머문다
        // (예전엔 샷 시작에 출발해 d×0.9 동안 표류해서, 도착하는 순간 비트가 끝났다)
        const autoNow = autos[si] ?? { k: 1, x: 0, y: 0 }
        const emphAt = Math.max(0, labelPos - sec(GRAMMAR.camLead))
        const autoMoved =
          autoNow.k !== appliedAuto.k || autoNow.x !== appliedAuto.x || autoNow.y !== appliedAuto.y
        if (autoEl && autoMoved) {
          camTo(autoEl, { k: autoNow.k, x: autoNow.x, y: autoNow.y }, sec(0.4), emphAt)
          appliedAuto = autoNow
        }

        // 저울이 비교 칸 위로 내려간다 — 자리는 compose(scales)가 소유한다. 등장 전이면
        // 즉시 그 자리에 서고, 떠 있으면 이동한다 (비교가 이어지면 저울이 다음 칸을 따라간다).
        // AI 줌(camera 모션)이 있는 샷은 줌 트윈과 같은 길이·ease로 움직인다 — 양끝이
        // 맞고 보간이 같으면 중간 프레임에서도 저울이 칸 위를 벗어나지 않는다
        const spot = scales[si]
        if (scaleEl && spot && (spot.x !== scalePos.x || spot.y !== scalePos.y)) {
          // 강조로 카메라가 움직이는 샷이면 저울도 같은 시각·같은 길이·같은 ease로 —
          // 양끝이 맞고 보간이 같으면 중간 프레임에서도 어긋나지 않는다
          if (scaleUp)
            tl.to(scaleEl, { x: spot.x, y: spot.y, duration: sec(0.4), ease: 'power2.inOut' }, autoMoved ? emphAt : label)
          else tl.set(scaleEl, { x: spot.x, y: spot.y }, autoMoved ? emphAt : label)
          scalePos = spot
        }

        for (const m of shot.motions) {
          switch (m.v) {
            case 'enterVar':
            case 'enterObj':
            case 'exitObj':
            case 'pointer':
              break // 배우 가시성은 구성이 소유한다 (포인터 등장은 첫 setVar가 담당)
            case 'exitVar': {
              // 포인터 화살표는 구성 밖(배열의 자식)이라 여기서 직접 내린다
              if (pointers.has(m.varKey)) {
                const el = q(ptrSel(m.varKey))
                if (el) tl.to(el, { opacity: 0, duration: sec(0.25) }, label)
              }
              break
            }
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
              if (from && to) {
                // 출발지가 먼저 꿈틀한다 — 떠나는 것은 칸이 아니라 값(토큰)이다
                const srcEl =
                  m.from.kind === 'cell' ? q(tokSel(m.from.objectId, m.from.index)) : inner(varSel(m.from.varKey))
                if (srcEl && travelAnt > 0.001) {
                  tl.fromTo(
                    srcEl,
                    { scale: 1 },
                    { scale: 1.08, duration: travelAnt, yoyo: true, repeat: 1, ease: 'power1.inOut', transformOrigin: 'center' },
                    label,
                  )
                }
                travel(label, m.text, from, to, travelAnt)
              }
              break
            }
            case 'setVar': {
              const key = m.varKey
              const text = m.text
              // 인덱스 포인터 변수 — 알약이 아니라 배열 아래 화살표가 그 칸 밑으로 걷는다
              const ptr = pointers.get(key)
              if (ptr) {
                const el = q(ptrSel(key))
                if (el) {
                  const idx = Number(text)
                  const cells = Math.max(plan.objects.find(o => o.objectId === ptr.objectId)?.maxItems ?? 1, 1)
                  const inRange = Number.isFinite(idx) && idx >= 0 && idx < cells
                  const clamped = Number.isFinite(idx) ? Math.min(Math.max(idx, -0.6), cells - 0.4) : 0
                  tl.to(
                    el,
                    {
                      x: 8 + clamped * layout.cellW + (layout.cellW - 6) / 2,
                      opacity: inRange ? 1 : 0.35,
                      duration: sec(0.35),
                      ease: 'power2.inOut',
                    },
                    label,
                  )
                }
                break
              }
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
                  { scale: 1, duration: d * 0.7, ease: GRAMMAR.settleEase, transformOrigin: 'center' },
                  at,
                )
              }
              break
            }
            case 'partial': {
              // 화면이 전부를 못 보여준다는 사실을 스스로 밝힌다 — 값의 신뢰성 축의 마지막 한 칸.
              // 중립색(4역할 색 아님)이라 읽기/쓰기/참/거짓 문법과 섞이지 않는다
              const id = m.objectId
              const text =
                m.total === undefined ? '안을 볼 수 없음'
                : m.total > m.shown ? `${m.shown} / ${m.total}`
                : ''
              tl.call(
                () => {
                  const el = root.querySelector(`${objSel(id)} .film-obj-partial`)
                  if (el) el.textContent = text
                },
                undefined,
                label,
              )
              const el = q(`${objSel(id)} .film-obj-partial`)
              if (el) tl.to(el, { opacity: text ? 1 : 0, duration: sec(0.25) }, label)
              break
            }
            case 'foldVars': {
              // 이름이 겹쳐 알약에서 물러난 변수들 — 그 값은 이 프레임의 카드가 든다.
              // 누가 물러나는지는 의미층이 정했고(varKeys는 compose가 쓴다) 여기서는 적기만 한다.
              // label·partial과 같은 tl.call 패턴이라 스크럽에 안전하다
              const fid = m.frameId
              const texts = m.texts
              const maxW = (layout.framePos.get(STACK_SLOTS - 1)?.w ?? 188) - 28
              tl.call(
                () => {
                  const el = root.querySelector(`${frameSel(fid)} .film-frame-vals`) as SVGTextElement | null
                  if (el) fitFrameVals(el, texts, maxW)
                },
                undefined,
                label,
              )
              // 값을 받으면 카드가 자리를 내준다 — 이름이 위로 올라가고 값 줄이 켜진다.
              // 값이 없는 카드는 이름이 세로 중앙에 그대로 있으므로 재귀 아닌 코드는 화면 변화 0.
              // 위치는 attr 트윈이라 스크럽에서 양방향으로 복원된다 (tl.call과 달리)
              const has = texts.length > 0
              const base = layout.framePos.get(0)!
              const nameEl = q(`${frameSel(fid)} .svg-name`)
              const valsEl = q(`${frameSel(fid)} .film-frame-vals`)
              if (nameEl)
                tl.to(nameEl, { attr: { y: base.y + (has ? 24 : 34) }, duration: sec(0.25), ease: 'power2.out' }, label)
              if (valsEl) tl.to(valsEl, { opacity: has ? 1 : 0, duration: sec(0.25) }, label)
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
              // 끈도 알약도 없다 — 상자가 쥔 변수명 이름표를 직접 다니까 (알약은 compose가 접는다).
              // 별칭이면 상자가 잠깐 부푼다
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
                  const el = root.querySelector(`${tokSel(id, idx)} .film-cell-text`)
                  if (el) el.textContent = fitCell(text)
                },
                undefined,
                at,
              )
              // origin은 셀 트윈 전체에서 'center'로 통일한다 — origin이 트윈마다 다르면
              // GSAP의 SVG origin 보정 translate가 잔여로 남아 칸이 상자를 이탈한다
              tl.fromTo(
                cellPair(id, idx),
                { opacity: 0, scale: 0.3 },
                { opacity: 1, scale: 1, duration: d, ease: GRAMMAR.settleEase, transformOrigin: 'center' },
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
                  const el = root.querySelector(`${tokSel(id, idx)} .film-cell-text`)
                  if (el) el.textContent = fitCell(text)
                },
                undefined,
                at,
              )
              // 새 값이 내려앉는 펄스는 토큰이 한다 — 슬롯은 제자리에서 가시성만 보전
              tl.set(cellPair(id, idx), { opacity: 1 }, at)
              tl.fromTo(
                q(tokSel(id, idx))!,
                { scale: 1.35 },
                { scale: 1, duration: d, ease: GRAMMAR.settleEase, transformOrigin: 'center' },
                at,
              )
              writeFlash(`${cellSel(id, idx)} .cell-flash`, at, d * 0.8)
              setBar(id, idx, text, at)
              break
            }
            case 'shrink': {
              const els = cellPair(m.objectId, m.index)
              if (els.length) tl.to(els, { opacity: 0, scale: 0.6, duration: d * 0.5, ease: 'power2.in', transformOrigin: 'center' }, label)
              break
            }
            case 'shiftLeft': {
              // 값이 떠나고 → 빈 칸이 생기고 → 뒤 토큰들이 한 몸으로 미끄러져 메운다.
              // 직선 당김(포물선 없음)이 교환의 서명과 이 동작을 구분한다. 슬롯은 붙박이.
              const id = m.objectId
              const k = m.index
              const landTexts = m.texts
              const n = k + landTexts.length // 새 크기 — 미끄러지는 토큰은 k+1..n, 접히는 슬롯은 n
              const tokAt = (ci: number) => q(tokSel(id, ci))
              const ant = sec(GRAMMAR.anticipation)
              // ① 빠지는 값의 퇴장 — 칩이 있으면 칩이 뜨는 순간 원본 토큰이 사라진다 (복제가 아니라 이동)
              const chipLeaves =
                travelM?.from.kind === 'cell' && travelM.from.objectId === id && travelM.from.index === k
              const departAt = chipLeaves ? ant + sec(0.1) : 0
              const kTok = tokAt(k)
              if (kTok) tl.to(kTok, { opacity: 0, duration: sec(0.12) }, `${label}+=${departAt}`)
              // ② 당겨짐 — 빈 칸을 향해 뒤 전원이 함께 미끄러진다
              const slideAt = departAt + sec(0.15)
              const fl = d * 0.45
              const sliders: Element[] = []
              for (let j = k + 1; j <= n; j++) {
                const el = tokAt(j)
                if (el) sliders.push(el)
              }
              if (sliders.length)
                tl.to(sliders, { x: -layout.cellW, duration: fl, ease: 'power2.inOut', transformOrigin: 'center' }, `${label}+=${slideAt}`)
              // ③ 착지 — 내용 교대(스냅백, swap과 같은 스크럽 계약), 값·막대·플래시, 끝 슬롯 접힘
              const land = slideAt + fl
              tl.call(
                () => {
                  for (let i = k; i < n; i++) {
                    const t = root.querySelector(`${tokSel(id, i)} .film-cell-text`)
                    if (t) t.textContent = fitCell(landTexts[i - k])
                  }
                },
                undefined,
                `${label}+=${land}`,
              )
              if (kTok) tl.set(kTok, { opacity: 1 }, `${label}+=${land}`)
              if (sliders.length) tl.set(sliders, { x: 0, transformOrigin: 'center' }, `${label}+=${land}`)
              for (let i = k; i < n; i++) {
                writeFlash(`${cellSel(id, i)} .cell-flash`, `${label}+=${land}`, d * 0.4)
                setBar(id, i, landTexts[i - k], `${label}+=${land}`)
                const tok = tokAt(i)
                if (tok)
                  tl.fromTo(
                    tok,
                    { scale: 1.05 },
                    { scale: 1, duration: d * 0.25, ease: GRAMMAR.settleEase, transformOrigin: 'center' },
                    `${label}+=${land + sec(0.02)}`,
                  )
              }
              const lastCell = cellPair(id, n)
              if (lastCell.length)
                tl.to(lastCell, { opacity: 0, scale: 0.6, duration: d * 0.3, ease: 'power2.in', transformOrigin: 'center' }, `${label}+=${land}`)
              break
            }
            case 'swap': {
              // 나는 것은 상자가 아니라 값이다 — 두 토큰(막대+글자)이 자리를 바꾸고,
              // 비행 동안 두 슬롯은 실제로 비어 보인다. 슬롯·번호는 붙박이.
              const a = q(tokSel(m.objectId, m.i))
              const b = q(tokSel(m.objectId, m.k))
              if (!a || !b) break
              const dx = (m.k - m.i) * layout.cellW
              const id = m.objectId
              const i = m.i
              const k = m.k
              const iText = m.iText
              const kText = m.kText
              // 레인 교차 — 토큰은 상자를 벗어나는 대신 몸을 낮춰 위·아래 레인으로 비껴간다.
              // 레인은 비대칭이다: 칸(8..56)은 상자(0..64) 안에서 위로 8, 아래로 8만 남기는데
              // 글자 디센더까지 real bbox가 아래로 더 넓어 대칭 ±11은 하단을 3.8px 넘겼다(실측).
              // 여유가 있는 위로 더 가고 아래로는 덜 내려간다 — 분리폭(21)은 그대로 지킨다.
              const LANE_UP = 14
              const LANE_DOWN = 7
              const LANE_S = 0.66
              // 예고 → 비행 → 여운: 들썩(질량 예고) → 레인 교차 → 펴지며 묵직한 착지
              const ant = sec(GRAMMAR.anticipation)
              if (ant > 0.001) {
                tl.fromTo([a, b], { y: 0 }, { y: -5, duration: ant, ease: 'power1.out', transformOrigin: 'center' }, label)
              }
              const fl = d * 0.5 // 비행 시간
              // 몸 낮추기는 출발 직후에 끝난다 — 먼저 자리를 만들고 나서 지나간다
              tl.to([a, b], { scale: LANE_S, duration: fl * 0.35, ease: 'power2.out', transformOrigin: 'center' }, `${label}+=${ant}`)
              tl.to(a, { x: dx, duration: fl, ease: 'power1.inOut', transformOrigin: 'center' }, `${label}+=${ant}`)
              tl.to(b, { x: -dx, duration: fl, ease: 'power1.inOut', transformOrigin: 'center' }, `${label}+=${ant}`)
              // 한 토큰은 위 레인, 다른 토큰은 아래 레인 — 최대 분리는 서로 스치는 중간 지점에서
              tl.to(a, { y: -LANE_UP, duration: fl / 2, ease: 'sine.out' }, `${label}+=${ant}`)
              tl.to(a, { y: 0, duration: fl / 2, ease: 'sine.in' }, `${label}+=${ant + fl / 2}`)
              tl.to(b, { y: LANE_DOWN, duration: fl / 2, ease: 'sine.out' }, `${label}+=${ant}`)
              tl.to(b, { y: 0, duration: fl / 2, ease: 'sine.in' }, `${label}+=${ant + fl / 2}`)
              // 착지 순간의 내용 교대(스냅백) — 날아온 토큰과 그 슬롯의 새 값이 같아
              // 화면상 연속이다. 스크럽 계약은 기존 스왑과 동일
              tl.call(
                () => {
                  const ta = root.querySelector(`${tokSel(id, i)} .film-cell-text`)
                  const tb = root.querySelector(`${tokSel(id, k)} .film-cell-text`)
                  if (ta) ta.textContent = fitCell(iText)
                  if (tb) tb.textContent = fitCell(kText)
                },
                undefined,
                `${label}+=${ant + fl}`,
              )
              tl.set([a, b], { x: 0, y: 0, transformOrigin: 'center' }, `${label}+=${ant + fl}`)
              // 낮췄던 몸이 새 자리에서 펴진다 — 축소분(0.66→1)이 곧 착지의 무게감이다
              tl.to(
                [a, b],
                { scale: 1, duration: d * 0.34, ease: GRAMMAR.settleEase, transformOrigin: 'center' },
                `${label}+=${ant + fl}`,
              )
              // 자리를 바꾼 두 슬롯이 값을 받으며 함께 번쩍인다 — "여기가 바뀌었다"의 마침표
              writeFlash(`${cellSel(id, i)} .cell-flash`, `${label}+=${ant + fl}`, d * 0.45)
              writeFlash(`${cellSel(id, k)} .cell-flash`, `${label}+=${ant + fl}`, d * 0.45)
              setBar(id, i, iText, `${label}+=${ant + fl}`)
              setBar(id, k, kText, `${label}+=${ant + fl}`)
              break
            }
            case 'returnValue': {
              // 카드는 HUD 좌표계에 산다 — 슬롯 사각형이 곧 좌표다 (카메라를 타지 않는다).
              // 도착지가 창 밖이면 띄우지 않는다: 반환하는 프레임은 늘 가장 깊고 부모는 그 바로
              // 위라 실제로는 걸리지 않지만, 갈 곳 없는 칩을 날리느니 침묵한다
              const stack = stacks[si]
              const a = layout.framePos.get(stack?.slots.get(m.frameId) ?? -1)
              const b = layout.framePos.get(stack?.slots.get(m.toFrameId) ?? -1)
              if (a && b)
                returnTravel(
                  label,
                  d,
                  m.text,
                  { x: a.x + a.w / 2, y: a.y + a.h / 2 },
                  { x: b.x + b.w / 2, y: b.y + b.h / 2 },
                )
              break
            }
            case 'pushFrame':
            case 'popFrame':
              // 카드의 등장·퇴장·자리는 스택 창(compose의 stacks)이 소유한다 —
              // 여기서 또 opacity/x를 건드리면 슬롯 이동과 싸운다
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
                if (scaleEl) tl.to(scaleEl, { opacity: 0, duration: d * 0.2 }, label)
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
                  cellPair(id, ci),
                  { scale: 1 },
                  { scale: GRAMMAR.sweepPop, duration: sec(0.12), yoyo: true, repeat: 1, ease: 'power1.inOut', transformOrigin: 'center' },
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
              const isEcho = shot.motions.some(mm => mm.v === 'swap')
              const skipAnim = isEcho && scaleUp // 교환 샷의 echo — 같은 판정의 재연은 껌뻑임일 뿐
              if (scaleEl && m.a !== undefined && m.b !== undefined && !skipAnim) {
                // 판단을 저울로 — 양팔에 값 카드, 무거운 쪽으로 기울고 도장이 찍힌다.
                // 저울은 판단의 흐름 동안 무대에 머문다: 비교가 이어지는 구간에서 샷마다
                // 떴다 사라지면 깜빡임이 된다. 교환 샷의 echo는 저울을 다시 흔들지 않고
                // (같은 판정의 재연은 껌뻑임일 뿐), 빔은 직전 기울기에서 이어 스윙하고,
                // 도장은 즉시 리셋 대신 부드럽게 물러난다.
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
                if (!scaleUp) {
                  tl.set(root.querySelectorAll('.film-scale-stamp'), { opacity: 0 }, label)
                  tl.fromTo(scaleEl, { opacity: 0 }, { opacity: 1, duration: d * 0.35, ease: 'power2.out' }, label)
                  prevRot = 0
                  prevStamp = null
                } else if (prevStamp) {
                  tl.to(prevStamp, { opacity: 0, duration: sec(0.2), ease: 'power2.in' }, label)
                }
                const beam = q('.film-scale-beam')
                const av = Number(a)
                const bv = Number(b)
                // 회전은 SVG 고유 rotate() 속성으로 — 항상 로컬 (0,0)=허브가 축이다.
                // GSAP rotation+transformOrigin(px)은 bbox 좌상단 기준, svgOrigin은 부모
                // transform을 무시해서 둘 다 축이 허브를 벗어난다 (실측으로 확인한 함정)
                if (beam && Number.isFinite(av) && Number.isFinite(bv) && av !== bv) {
                  const rot = av > bv ? -10 : 10
                  tl.fromTo(
                    beam,
                    { attr: { transform: `rotate(${prevRot})` } },
                    { attr: { transform: `rotate(${rot})` }, duration: d * 0.5, ease: 'power2.inOut' },
                    `${label}+=${d * 0.12}`,
                  )
                  prevRot = rot
                } else if (beam) {
                  tl.to(beam, { attr: { transform: 'rotate(0)' }, duration: d * 0.3 }, label)
                  prevRot = 0
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
                    prevStamp = stamp
                  }
                }
              }
              // 내려놓기 판정은 echo 샷에서도 — 여기서 안 내리면 마지막 교환 뒤 저울이 영원히 남는다
              if (scaleEl && m.a !== undefined && m.b !== undefined) {
                const streak = shots
                  .slice(si + 1, si + 3)
                  .some(s => s.motions.some(mm => mm.v === 'compare'))
                if (streak) {
                  scaleUp = true
                } else {
                  tl.to(scaleEl, { opacity: 0, duration: d * 0.45 }, `${label}+=${d * 1.05}`)
                  scaleUp = false
                  prevRot = 0
                  prevStamp = null
                }
              }
              for (const t of m.targets) {
                // 읽기 펄스는 값(토큰)이 한다 — 단 교환 샷에서는 비행이 곧 강조라 생략
                // (같은 transform을 펄스와 비행이 다투면 지터가 된다)
                const el = t.kind === 'cell' ? q(tokSel(t.objectId, t.index)) : inner(varSel(t.varKey))
                if (el && !isEcho) {
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
            const key = el.getAttribute('data-cell')
            const pair = [el, root.querySelector(`[data-token="${key}"]`)].filter(Boolean) as Element[]
            tl.fromTo(
              pair,
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
    // 헤드리스 검증 훅 — 패널이 가려져 rAF가 멎어도 __filmTl.time(t)은 동기 렌더된다 (개발 전용)
    if (import.meta.env.DEV) {
      const w = window as unknown as {
        __filmTl?: unknown; __filmScales?: unknown; __filmShots?: unknown
        __filmComps?: unknown; __filmCams?: unknown; __filmObjSize?: unknown; __filmLayout?: unknown; __filmAutos?: unknown
      }
      w.__filmTl = tl
      w.__filmScales = scales
      w.__filmShots = shots
      w.__filmComps = comps.map(c => Object.fromEntries(c))
      w.__filmCams = cams
      w.__filmObjSize = Object.fromEntries(plan.objects.map(o => [o.objectId, layout.objPos.get(o.objectId)]))
      w.__filmLayout = { width: layout.width, height: layout.height, cellW: layout.cellW }
      w.__filmAutos = autos
    }
    // 두 번째 인자 false = 이벤트 억제 해제 — 점프 경로의 tl.call(텍스트 세터)까지 전부 실행해야
    // 모션 감소 사용자도 값이 채워진 "완성된 마지막 프레임"을 본다
    if (still) tl.progress(1, false)

    return () => {
      register(null)
      if (import.meta.env.DEV) (window as unknown as { __filmTl?: unknown }).__filmTl = undefined
      tl.kill()
    }
  }, [shots, register, layout, plan, comps, cams, scales, autos, stacks, theme, pointers])

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
                <text className="film-obj-partial" x={r.w} y={-8} textAnchor="end" />
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
              <text className="film-obj-partial" x={r.w} y={-8} textAnchor="end" />
              {/* 칸 = 자리(슬롯) + 물건(값 토큰). 두 층을 따로 그린다 — SVG는 z-index가 없어
                  문서 순서가 곧 겹침 순서라, 토큰이 칸 안에 살면 오른쪽으로 나는 토큰이
                  이웃 칸의 불투명 배경 뒤로 숨는다. 토큰 층이 슬롯 층 전체 위에 뜬다. */}
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
                  <rect
                    className="cell-flash"
                    x={8 + i * layout.cellW}
                    y={8}
                    width={layout.cellW - 6}
                    height={r.h - 16}
                    rx={5}
                  />
                  <rect
                    className="cell-ring"
                    x={6 + i * layout.cellW}
                    y={6}
                    width={layout.cellW - 2}
                    height={r.h - 12}
                    rx={7}
                  />
                  {numberedObjs.has(o.objectId) && (
                    <text
                      className="svg-index"
                      x={8 + i * layout.cellW + (layout.cellW - 6) / 2}
                      y={r.h + 14}
                      textAnchor="middle"
                    >
                      {i}
                    </text>
                  )}
                </g>
              ))}
              {/* 토큰 층 — 좌표는 상자 로컬 절대값이라 슬롯과 정확히 같은 자리에 뜬다 */}
              {Array.from({ length: cells }, (_, i) => (
                <g key={`t${i}`} className="cell-token" data-token={`${o.objectId}-${i}`}>
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
                  <text
                    className="film-cell-text svg-value"
                    x={8 + i * layout.cellW + (layout.cellW - 6) / 2}
                    y={r.h / 2 + 5}
                    textAnchor="middle"
                  />
                </g>
              ))}
              {/* 인덱스 포인터 — 변수가 값이 아니라 "위치"로 산다. setVar마다 화살표가 칸 밑을 걷는다 */}
              {[...pointers.entries()]
                .filter(([, p]) => p.objectId === o.objectId)
                .map(([key, p]) => (
                  <g key={key} data-ptr={key} className="film-ptr">
                    <polygon points="0,0 -6,9 6,9" />
                    <text y={23} textAnchor="middle" className="svg-name">
                      {p.name.length > 6 ? p.name.slice(0, 5) + '…' : p.name}
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

      {/* 이동 칩 — 복제된 값 토큰이 나는 순간을 위한 풀(2개). 알약이 아니라 칸 크기의
          카드 모양이라 "값 하나가 복제되어 간다"로 읽힌다 */}
      {[0, 1].map(i => (
        <g key={`chip${i}`} data-chip={i} className="film-chip">
          <rect x={-32} y={-14} width={64} height={28} rx={8} fill="var(--accent-wash)" stroke="var(--accent)" strokeWidth={1.4} />
          <text textAnchor="middle" y={5} className="svg-name" />
        </g>
      ))}
      </g>{/* /film-cam-frame */}
      </g>{/* /film-cam-auto — 배우와 칩만 카메라를 탄다 */}

      {/* 하단 HUD — 프레임 카드·출력 바는 카메라 밖, 항상 화면 바닥에 */}
      <g transform={`translate(0 ${hudOffset})`}>
        {/* 호출 스택 — 카드는 슬롯 0 자리에 그려두고, 어느 슬롯에 앉을지는 compose가
            샷마다 정한 창(stacks)에 따라 GSAP이 옮긴다. 창은 늘 가장 깊은 쪽을 잡으므로
            실행 중인 프레임은 항상 화면 안이다 */}
        {plan.frames.map(f => {
          const r = layout.framePos.get(0)!
          return (
            <g key={`f${f.frameId}`} data-frame={f.frameId}>
              <rect x={r.x} y={r.y} width={r.w} height={r.h} rx={10} fill="var(--panel)" stroke="var(--line-strong)" strokeWidth={1.2} />
              <text x={r.x + 14} y={r.y + 34} className="svg-name">
                {f.func === '<module>' ? '프로그램' : f.func}
              </text>
              {/* 이 프레임이 든 값 — 이름이 겹쳐 알약에서 물러난 변수들 (foldVars).
                  값을 받기 전에는 꺼져 있고, 이름은 그때 위로 올라간다 */}
              <text className="film-frame-vals" x={r.x + 14} y={r.y + 44} />
            </g>
          )
        })}
        {/* 창 밖으로 접힌 얕은 호출 — 화면이 안 보여주는 것을 개수로 밝힌다 */}
        <g className="film-stack-more">
          {(() => {
            const r = layout.framePos.get(0)!
            return (
              <>
                <rect x={r.x} y={r.y + 18} width={r.w} height={r.h - 18} rx={10} />
                <text className="film-stack-more-text" x={r.x + 14} y={r.y + 44} />
              </>
            )
          })()}
        </g>
        {/* 반환 칩 — 닫히는 카드에서 값이 떠서 부모 카드로 내려앉는다. 카드보다 뒤에 그려야
            (SVG 문서 순서 = 겹침 순서) 카드 위를 지나간다 */}
        <g className="film-return-chip">
          <rect x={-56} y={-14} width={112} height={28} rx={8} fill="var(--accent-wash)" stroke="var(--accent)" strokeWidth={1.4} />
          <text textAnchor="middle" y={5} className="svg-name" />
        </g>
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
