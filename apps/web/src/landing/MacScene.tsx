/**
 * [랜딩 첫 화면] 점 → 네모 → (스크롤) 맥북 → 화면 속
 * - 들어오면 저절로: 흩어진 점 네 개(강의자료 · 오늘의 퀴즈 · 질의응답 · 학습 분석)가 가운데로 모여
 *   돌면서 퍼지고, 선을 이어 맥북 화면과 같은 크기의 네모를 그려요. 그다음 네모는 '흩어진 배움이,'를 가운데 두고 계속 천천히 돌아요.
 * - 스크롤하면: 네모가 똑바로 서면서 맥북(테두리 · 노치 · 힌지 · 키보드 · 트랙패드)이 생기고,
 *   '흩어진 배움이,'가 맥북 화면 첫 줄로 들어가 나머지 문구('하나의 이해로.' · 부제목)와 이어져요.
 *   더 내리면 맥북 화면 속으로 들어가(테두리가 화면 밖으로 사라질 만큼 확대) 학생 강의실 '예고편' 화면이 창을 가득 채워요.
 *   예고편은 창에 보이는 칸 크기에 맞춰 다시 배치되므로 어떤 화면비에서도 잘리지 않아요.
 *   예고편은 실제 학생 페이지를 그대로 옮기지 않고, 핵심만 크게 간추린 미리보기예요 (스타일은 .lm-tz-*).
 * - 위로 다시 올리면 거꾸로 되돌아가고, 맨 위에서는 네모가 다시 돌아요. 움직임 줄이기 설정이면 돌지 않아요.
 * - 매 프레임 바뀌는 위치 · 크기는 React 상태 대신 ref 로 직접 바꿔요 (다시 그리기 없이 부드럽게).
 * - 스타일: landing/lerny-mac-scene.css 의 .lm-*  /  예전 책상 장면은 DeskScene.tsx 에 그대로 있어요.
 */

import { useEffect, useRef, useState, type Ref, type RefObject } from 'react'
import { createPortal } from 'react-dom'
import './lerny-mac-scene.css'
import { AuroraLayer } from './AuroraBackground'

// 맥북 장면 배경에 오로라 빛을 깔아요 (11/18)
const USE_AURORA = true

// 점 네 개 — 시계 방향으로 네모의 꼭짓점 (왼위 → 오른위 → 오른아래 → 왼아래). from = 처음 흩어져 있는 자리 (화면 가운데 기준 비율)
const DOTS = [
  { label: '강의자료', color: 'var(--lm-c1)', from: [-0.4, -0.32] },
  { label: '오늘의 퀴즈', color: 'var(--lm-c2)', from: [0.4, -0.28] },
  { label: '질의응답', color: 'var(--lm-c3)', from: [0.36, 0.34] },
  { label: '학습 분석', color: 'var(--lm-c4)', from: [-0.34, 0.3] },
] as const
const CORNERS = [[-0.5, -0.5], [0.5, -0.5], [0.5, 0.5], [-0.5, 0.5]] as const
const EDGE_PTS = [[0, 0], [100, 0], [100, 100], [0, 100]] as const

// 저절로 재생되는 구간 (초) — 이후 네모는 SPIN 속도로 계속 돌아요
const A = {
  gather: [0.3, 1.4], // 흩어진 점이 가운데로 모임
  draw: [1.3, 3.0], // 점이 돌면서 퍼져 네모를 그림
} as const
const INTRO_END = 3.0
const SPIN = 24 // 도/초

// 스크롤 구간 (이 섹션 안에서 0~1)
const S = {
  // 11/18: 화면 속으로 들어간 뒤 마무리까지 — 섹션 250vh (스크롤 150vh). 맥북 · 문구 구간은 예전과 같은 길이이고,
  // 확대를 조금 천천히 한 뒤 마무리 칸이 제자리에서 서서히 떠올라요 (올라오는 100vh 스크롤 없음)
  mac: [0.056, 0.345], // 네모가 똑바로 서며 맥북이 생김
  copy: [0.256, 0.416], // 맥북 화면에 나머지 문구
  zoom: [0.44, 0.88], // 맥북 화면 속으로
} as const
// 예전 값: 섹션 310vh · mac [0.04, 0.246] · copy [0.183, 0.297] · zoom [0.331, 0.663] (확대 뒤 마무리가 100vh 동안 올라옴)
// 섹션 마지막 100vh 는 다음 마무리 칸과 겹쳐요 (lerny-mac-scene.css 의 margin-bottom: -100vh)

// 디자인 입히기 전 원래 랜딩 문구 (DeskScene.tsx 와 같음)
const HERO_FIRST = '흩어진 배움이,'
const HERO_REST = '하나의 이해로.'
const HERO_SUB = '교수님의 자료로 질문하고, 퀴즈로 나의 이해를 완성해요.'
// 예고편을 그리는 기준 너비 — 실제 높이는 보이는 칸의 비율을 따라가요 (넓은 화면 1200 / 좁은 화면 640)
const PAGE_W = 1200
const PAGE_W_NARROW = 640

const clamp = (v: number, a = 0, b = 1) => Math.min(b, Math.max(a, v))
const lerp = (a: number, b: number, t: number) => a + (b - a) * t
const seg = (x: number, [a, b]: readonly [number, number]) => clamp((x - a) / (b - a))
const ease = (t: number) => (t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2)
const easeOut = (t: number) => 1 - (1 - t) ** 3

/**
 * embedded: 첫 화면(HeroParallax) 안에 넣어 쓸 때 (11/18)
 * - 점이 모여 네모를 그리는 소개 없이, 처음부터 네모(맥북 화면 크기)가 그려져 있고 돌지 않아요.
 * - 스크롤 진행은 이 장면이 아니라 trackRef(첫 화면 전체)를 기준으로, range 구간을 0~1 로 바꿔 써요.
 */
type MacSceneProps = { embedded?: boolean; trackRef?: RefObject<HTMLElement | null>; range?: [number, number] }

export default function MacScene({ embedded = false, trackRef, range = [0, 1] }: MacSceneProps = {}) {
  const sectionRef = useRef<HTMLElement>(null)
  const deviceRef = useRef<HTMLDivElement>(null)
  const frameRef = useRef<HTMLDivElement>(null)
  const baseRef = useRef<HTMLDivElement>(null)
  const appRef = useRef<HTMLDivElement>(null)
  const firstRef = useRef<HTMLDivElement>(null)
  const copyRef = useRef<HTMLDivElement>(null)
  const ghostRef = useRef<HTMLDivElement>(null)
  const hintRef = useRef<HTMLDivElement>(null)
  const fadeRef = useRef<HTMLDivElement>(null)
  const dotRefs = useRef<(HTMLDivElement | null)[]>([])
  const edgeRefs = useRef<(SVGLineElement | null)[]>([])
  // 강의실 화면은 랜딩(.lerny-landing) 바깥, #root 바로 아래에 그려야 앱 스타일이 랜딩용 예외 없이 그대로 입혀져요
  const [portalRoot, setPortalRoot] = useState<HTMLElement | null>(null)
  useEffect(() => setPortalRoot(document.getElementById('root') ?? document.body), [])

  useEffect(() => {
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    let clock = reduce || embedded ? INTRO_END : 0 // 저절로 재생되는 소개 시간 (첫 화면에 넣으면 소개 없이 바로)
    let spin = 0 // 소개가 끝난 뒤 계속 도는 각도 (스크롤하는 동안은 멈춤)
    let start = performance.now()
    let started = reduce || embedded // 랜딩 끝에 있어서, 화면에 들어올 때 소개를 시작해요
    let last = start
    let raf = 0

    const render = () => {
      const section = sectionRef.current
      const frame = frameRef.current
      const device = deviceRef.current
      const base = baseRef.current
      const app = appRef.current
      const first = firstRef.current
      const copy = copyRef.current
      const ghost = ghostRef.current
      const hint = hintRef.current
      if (!section || !frame || !device || !base || !app || !first || !copy || !ghost || !hint) return

      const vw = window.innerWidth
      const vh = window.innerHeight
      const mobile = vw < 760
      const rect = (embedded && trackRef?.current ? trackRef.current : section).getBoundingClientRect()
      const total = rect.height - vh
      const raw = total <= 0 ? 0 : clamp(-rect.top / total)
      // 첫 화면에 넣었을 때는 range 구간만 이 장면의 0~1 로 써요
      const p = embedded ? clamp((raw - range[0]) / (range[1] - range[0])) : raw
      if (p > 0.005) clock = INTRO_END // 먼저 스크롤하면 소개를 건너뛰어요
      const t = clock

      const gather = easeOut(seg(t, A.gather))
      const draw = ease(seg(t, A.draw))
      // 첫 화면에 넣었을 때는 네모 단계 없이 처음부터 맥북이에요 (맥북이 생기는 구간을 건너뛴 지점부터 시작)
      const pm = embedded ? Math.min(1, S.mac[1] + p) : p
      const mac = embedded ? 1 : ease(seg(p, S.mac))
      const zoom = ease(seg(pm, S.zoom))

      // 맥북 화면 = 네모 크기 (16:10). 돌아도 화면 안에 들어오도록 대각선 기준으로 정해요
      // 11/25: 휴대폰에서는 맥북이 너무 작아 보여서, 네모가 맥북으로 바뀌는 동안 0.62 → 0.8 로 커져요
      //   (도는 네모는 모서리 이름표가 화면 밖으로 나가지 않게 0.62 그대로)
      const LW = mobile ? vw * lerp(0.62, 0.8, mac) : Math.min(vw * 0.68, vh * 0.84) // 11/18: 네모 · 맥북 화면 크게 (예전 0.56 / 0.6 · 0.74)
      const LH = LW / 1.6
      const cx = vw / 2
      const cySq = vh * 0.5
      const cyL = vh * 0.39 // 맥북은 아랫판이 보이도록 조금 위로
      const cy = lerp(cySq, cyL, mac)

      // 각도: 소개 때는 270도 돌며 펼쳐지고, 그다음 계속 돌다가, 스크롤하면 똑바로 서요.
      // 180도에서 멈추면 화면이 거꾸로 뒤집히므로 꼭 360도 단위(가장 가까운 쪽)로만 세워요
      const spinBase = -270 * (1 - draw) + spin
      const rot = lerp(spinBase, Math.round(spinBase / 360) * 360, clamp(mac / 0.7)) // 맥북이 나타나기 전에 먼저 똑바로
      const size = lerp(0.1, 1, draw)
      const W = LW * size
      const H = LH * size
      frame.style.width = `${W}px`
      frame.style.height = `${H}px`
      frame.style.transform = `translate(${cx - W / 2}px, ${cy - H / 2}px) rotate(${rot}deg)`

      // 선: 각 점이 다음 점 쪽으로 선을 끌고 가고, 맥북 테두리로 바뀌며 사라짐
      const reach = ease(seg(t, [A.draw[0] + 0.15, A.draw[1]]))
      edgeRefs.current.forEach((l, i) => {
        if (!l) return
        const a = EDGE_PTS[i]
        const b = EDGE_PTS[(i + 1) % 4]
        l.setAttribute('x1', String(a[0]))
        l.setAttribute('y1', String(a[1]))
        l.setAttribute('x2', String(lerp(a[0], b[0], reach)))
        l.setAttribute('y2', String(lerp(a[1], b[1], reach)))
        l.style.opacity = String((reach > 0 ? 1 : 0) * (1 - seg(mac, [0.4, 0.7])))
      })

      // 맥북 덮개 · 화면
      const bo = seg(mac, [0.45, 0.8])
      const bz = Math.max(6, LW * 0.028) * bo
      frame.style.setProperty('--lm-bo', String(bo))
      frame.style.setProperty('--lm-bz', `${bz}px`)
      frame.style.setProperty('--lm-so', String(seg(mac, [0.6, 0.9])))

      // 아랫판 (힌지 · 키보드 · 트랙패드 · 앞면) — 덮개 바로 아래에서 비스듬히 누운 판
      const baseIn = seg(mac, [0.7, 1])
      base.style.setProperty('--lm-bw', `${LW * 1.056}px`)
      base.style.setProperty('--lm-depth', `${LW * 0.7}px`)
      base.style.setProperty('--lm-th', `${Math.max(4, LW * 0.016)}px`)
      base.style.width = `${LW * 1.056}px`
      base.style.opacity = String(baseIn)
      base.style.transform = `translate(${cx - (LW * 1.056) / 2}px, ${cyL + LH / 2 + bz - 1}px) translateY(${(1 - baseIn) * 24}px)`

      // 점: 흩어진 자리 → 가운데로 모임 → 네모 꼭짓점과 함께 돎 → 맥북이 되면 사라짐
      const rad = (rot * Math.PI) / 180
      dotRefs.current.forEach((n, i) => {
        if (!n) return
        const [ux, uy] = CORNERS[i]
        const lx = ux * W
        const ly = uy * H
        const kx = cx + lx * Math.cos(rad) - ly * Math.sin(rad)
        const ky = cy + lx * Math.sin(rad) + ly * Math.cos(rad)
        const fx = cx + DOTS[i].from[0] * vw * (mobile ? 0.7 : 1)
        const fy = cySq + DOTS[i].from[1] * vh
        const x = lerp(fx, kx, gather)
        const y = lerp(fy, ky, gather)
        const left = x < cx
        n.style.transform = `translate(${x}px, ${y}px)`
        const inner = n.firstElementChild as HTMLElement
        inner.style.flexDirection = left ? 'row-reverse' : 'row'
        inner.style.transform = left ? 'translate(calc(-100% + 8px), -50%)' : 'translate(-8px, -50%)'
        // 가운데에 모여 펼쳐지는 동안은 글자를 숨기고 색 점만
        ;(inner.lastElementChild as HTMLElement).style.opacity = t > A.gather[1] - 0.4 && draw < 0.8 ? '0' : '1'
        n.style.opacity = embedded ? '0' : String(seg(t, [0, 0.4]) * (1 - seg(mac, [0, 0.4])))
      })

      // 문구: '흩어진 배움이,'는 네모 가운데 → 맥북 화면 첫 줄로. 나머지 문구는 맥북 화면에 나타남
      const fsMac = Math.min(LW / 11, mobile ? 26 : 56)
      const fsBig = Math.min(LW / 8, mobile ? 30 : 72)
      copy.style.fontSize = `${fsMac}px`
      const ghostY = cyL - copy.offsetHeight / 2 + ghost.offsetTop + ghost.offsetHeight / 2 // 화면 속 첫 줄 자리
      first.style.fontSize = `${lerp(fsBig, fsMac, mac)}px`
      const fw = first.offsetWidth
      const fh = first.offsetHeight
      const fy = lerp(cySq, ghostY, mac)
      const copyIn = seg(pm, S.copy)
      copy.style.setProperty('--lm-rest', String(copyIn))
      const copyOut = seg(zoom, [0.55, 0.95]) // 화면 속 문구를 따라 들어가다가 사라져요
      copy.style.opacity = String(1 - copyOut)
      first.style.opacity = String(seg(t, [A.draw[1] - 0.7, A.draw[1]]) * (1 - copyOut))

      hint.style.opacity = embedded ? '0' : String(seg(t, [INTRO_END - 0.4, INTRO_END]) * (1 - seg(p, [0.01, 0.05])))

      // 스크롤: 맥북 화면이 창을 다 덮을 때까지 확대해요 (테두리는 창 밖으로 사라져요 = 화면 속으로 들어감)
      const k = lerp(1, Math.max(vw / LW, vh / LH) * 1.04, zoom)
      const ty = lerp(cyL, vh / 2, zoom)
      const tf = `translate(${cx}px, ${ty}px) scale(${k}) translate(${-cx}px, ${-cyL}px)`
      device.style.transform = tf
      first.style.transform = `${tf} translate(${cx - fw / 2}px, ${fy - fh / 2}px)`

      // 강의실 화면: 맥북 화면이 있는 자리에 그대로 겹쳐요 (섹션이 끝나 위로 밀려 올라가면 같이 올라감)
      // 강의실 예고편은 띄우지 않아요 (화면 속으로 들어가면 바로 아래 마무리로 이어지게)
      const appIn = 0
      const fade = fadeRef.current
      if (fade) fade.style.opacity = String(seg(zoom, [0.8, 1]))
      // 마무리 칸(.ln-page)은 맥북 장면 마지막 100vh 와 겹쳐 있어요. 올라오지 않고 창 맨 위에 붙어 있다가
      // 확대가 끝나 갈 때 서서히 나타나요 → 화면 속으로 들어가자마자 마무리 + Lerny 가 한 화면에 보여요
      if (!embedded) {
        // 오로라 빛은 네모가 맥북으로 바뀌는 동안 사라져요 (맥북이 생기면 없음)
        const aurora = section.querySelector<HTMLElement>('.aur-clip')
        if (aurora) aurora.style.opacity = String(1 - seg(mac, [0.15, 0.75]))
        const page = document.querySelector<HTMLElement>('.lerny-landing .ln-page')
        if (page) {
          const show = ease(seg(p, [0.72, 1])) // 확대가 거의 끝날 때부터 장면 끝까지 서서히
          page.style.transform = `translateY(${-Math.max(0, rect.bottom - vh) + (1 - show) * 48}px)`
          page.style.opacity = String(show)
          page.style.pointerEvents = show > 0.5 ? '' : 'none'
        }
      }
      const sw = LW * k
      const sh = LH * k
      const lift = Math.min(0, rect.bottom - vh)
      // 예고편은 맥북 화면 중 창에 보이는 부분에만 그려요 → 화면이 창보다 커져도 내용이 잘리지 않아요
      const bl = Math.max(0, cx - sw / 2)
      const bt = Math.max(0, ty - sh / 2)
      const bw = Math.min(vw, cx + sw / 2) - bl
      const bh = Math.min(vh, ty + sh / 2) - bt
      app.style.opacity = String(appIn)
      app.style.visibility = appIn > 0 && rect.bottom > 0 ? 'visible' : 'hidden'
      app.style.width = `${bw}px`
      app.style.height = `${bh}px`
      app.style.transform = `translate(${bl}px, ${bt + lift}px)`
      app.style.borderRadius = bw < vw - 1 || bh < vh - 1 ? `${bz * 0.3 * k}px` : '0px'
      const narrow = bw < 760
      const ps = bw / (narrow ? PAGE_W_NARROW : PAGE_W)
      const pw = bw / ps
      const ph = bh / ps
      app.classList.toggle('is-narrow', narrow)
      app.style.setProperty('--lm-ps', String(ps))
      app.style.setProperty('--lm-pw', `${pw}px`)
      app.style.setProperty('--lm-ph', `${ph}px`)

      return p
    }

    const tick = (now: number) => {
      const dt = Math.min(0.05, (now - last) / 1000)
      last = now
      const section = sectionRef.current
      const visible = !!section && section.getBoundingClientRect().bottom > 0
      if (!started && section && section.getBoundingClientRect().top < window.innerHeight) {
        started = true
        start = now
      }
      if (started && clock < INTRO_END) clock = Math.min(INTRO_END, (now - start) / 1000)
      if (visible) {
        const p = render() ?? 0
        // 맨 위에 있을 때만 계속 돌아요 (처음 1초는 천천히 빨라짐)
        if (!reduce && !embedded && clock >= INTRO_END && p <= 0.005) {
          const ramp = Math.min(1, spin / 12 + 0.15)
          spin += SPIN * ramp * dt
        }
      }
      raf = requestAnimationFrame(tick)
    }

    render()
    raf = requestAnimationFrame(tick)
    const onResize = () => render()
    window.addEventListener('resize', onResize)
    document.fonts?.ready.then(render)
    return () => {
      cancelAnimationFrame(raf)
      window.removeEventListener('resize', onResize)
    }
  }, [])

  return (
    <section className={`lm-hero ${embedded ? 'is-embedded' : ''}`} ref={sectionRef} aria-label="Lerny 소개">
      <div className={`lm-sticky${USE_AURORA && !embedded ? ' has-aurora' : ''}`}>
        {/* 11/18: 배경에 오로라 빛 (AuroraBackground.tsx). USE_AURORA 를 false 로 바꾸면 예전 바탕으로 */}
        {USE_AURORA && !embedded && <AuroraLayer />}
        <div className="lm-device" ref={deviceRef}>
          <MacBase ref={baseRef} />
          <div className="lm-frame" ref={frameRef}>
            <div className="lm-lid" />
            <div className="lm-notch" />
            <div className="lm-screen">
              <div className="lm-copy" ref={copyRef}>
                <div className="lm-kick">
                  {/* 11/18: LERNY 글자 대신 로고 */}
                  <img className="lm-kick-logo" src="/lerny-logo.png" alt="Lerny" />
                </div>
                <div className="lm-ghost" ref={ghostRef} aria-hidden="true">
                  {HERO_FIRST}
                </div>
                <div className="lm-rest">{HERO_REST}</div>
                <p className="lm-sub">{HERO_SUB}</p>
              </div>
              <div className="lm-glare" />
            </div>
            <svg className="lm-edges" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
              {EDGE_PTS.map((_, i) => (
                <line key={i} ref={(el) => { edgeRefs.current[i] = el }} />
              ))}
            </svg>
          </div>
        </div>

        {DOTS.map((d, i) => (
          <div key={d.label} className="lm-dot" ref={(el) => { dotRefs.current[i] = el }} aria-hidden="true">
            <div className="lm-dot-in">
              <span className="lm-chip" style={{ background: d.color }} />
              <span className="lm-label">{d.label}</span>
            </div>
          </div>
        ))}

        <div className="lm-first" ref={firstRef}>
          <h2 aria-label={`${HERO_FIRST} ${HERO_REST}`}>{HERO_FIRST}</h2>
        </div>

        <div className="lm-hint" ref={hintRef} aria-hidden="true">
          SCROLL
        </div>
        {/* 화면 속으로 들어가면 아래 마무리와 같은 바탕색으로 덮여서 끊김 없이 이어져요 */}
        <div className="lm-fade" ref={fadeRef} aria-hidden="true" />
        {portalRoot &&
          createPortal(
            <div className="lm-app" ref={appRef} aria-hidden="true" inert>
              <ClassroomScreen />
            </div>,
            portalRoot,
          )}
      </div>
    </section>
  )
}

/** 맥북 아랫판 — 힌지, 비스듬히 누운 윗판(키보드 · 트랙패드), 앞면(엄지 홈), 바닥 그림자 */
function MacBase({ ref }: { ref: Ref<HTMLDivElement> }) {
  return (
    <div className="lm-base" ref={ref} aria-hidden="true">
      <div className="lm-hinge" />
      <div className="lm-deck-wrap">
        <div className="lm-deck">
          <div className="lm-kbd" />
          <div className="lm-pad" />
          <div className="lm-front" />
        </div>
      </div>
      <div className="lm-floor" />
    </div>
  )
}

/**
 * 맥북 화면 속 '예고편' — 학생 강의실과 AI 강의 화면을 그대로 옮기지 않고, 핵심만 크게 간추려 보여 줘요.
 * 색 · 글꼴 · 구성(상단 메뉴, AI 강의 카드, 바로가기 3개 / 강의 화면, 주차별 자료)은 실제 페이지와 비슷하게 맞췄어요.
 * 너비 1200(좁은 화면 640) 기준으로 그리고, 높이는 보이는 칸의 비율을 따라가요(--lm-pw · --lm-ph · --lm-ps).
 * 앱 전체 CSS 와 섞이지 않게 div · span 과 .lm-tz-* 만 써요.
 */
function TeaserBar({ active }: { active: string }) {
  return (
    <div className="lm-tz-bar">
      <img className="lm-tz-logo" src="/lerny-logo.png" alt="" />
      <div className="lm-tz-nav">
        {['강의실', 'AI 강의', '퀴즈', '학습 기록'].map((label) => (
          <span key={label} className={label === active ? 'is-active' : undefined}>
            {label}
          </span>
        ))}
      </div>
    </div>
  )
}

const TEASER_TILES = [
  { label: '질의응답', desc: '자료에 근거한 답', color: '#6fa592' },
  { label: '오늘의 퀴즈', desc: '3문항 · 5분', color: '#d39aa9' },
  { label: '학습 분석', desc: '이해도 72%', color: '#d8ac4c' },
]

function ClassroomScreen() {
  return (
    <div className="lm-app-page lm-page-class">
      <TeaserBar active="강의실" />
      <div className="lm-tz-body">
        <div className="lm-tz-meta">1주차 학습 시작</div>
        <div className="lm-tz-title">오늘 배울 내용을 시작해요.</div>
        <div className="lm-tz-hero">
          <div>
            <div className="lm-tz-hero-title">개념 하나씩, AI 강사와 함께.</div>
            <div className="lm-tz-hero-sub">1주차</div>
          </div>
          <span className="lm-tz-cta">AI 강의 보기 ↗</span>
        </div>
        <div className="lm-tz-tiles">
          {TEASER_TILES.map((t) => (
            <div key={t.label} className="lm-tz-tile">
              <span className="lm-tz-chip" style={{ background: t.color }} />
              <span className="lm-tz-tile-label">{t.label}</span>
              <span className="lm-tz-tile-desc">{t.desc}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
