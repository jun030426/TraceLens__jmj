/**
 * [랜딩 첫 화면] 교수님의 강의 자료(책) → 종이비행기 → 아래 기능 설명으로
 * - 들어오면 "단일 연결 리스트" 강의 자료 표지가 저절로 열려요. 책 속은 모두 강의 자료 쪽이에요.
 * - 아래로 스크롤하면 강의 자료가 한 장씩 넘어가고, 마지막 쪽(정리)이 책에서 떨어져 나와 종이비행기로 접혀요.
 * - 더 내리면 비행기가 곡선을 그리며 아래로 날아가 다음 칸(하루의 학습 · 기능 설명)으로 들어가요.
 * - 매 프레임 바뀌는 값은 React 상태 대신 ref 로 CSS 변수 · SVG 속성만 바꿔요.
 * - 스타일: landing/lerny-hero-book.css 의 .bk-*
 * - 책 속 글 · 그림 · 코드는 소개용 예시예요. [임시 데이터]
 */

import { useEffect, useRef, type CSSProperties } from 'react'
import './lerny-hero-book.css'

type Pt = [number, number]
type Quad = [Pt, Pt, Pt, Pt]

const clamp = (v: number, a = 0, b = 1) => Math.min(b, Math.max(a, v))
const seg = (v: number, [a, b]: readonly [number, number]) => clamp((v - a) / (b - a))
const ease = (t: number) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2)
const lerp = (a: number, b: number, t: number) => a + (b - a) * t
const lerpQuad = (a: Quad, b: Quad, t: number): Quad =>
  a.map((p, i) => [lerp(p[0], b[i][0], t), lerp(p[1], b[i][1], t)]) as Quad
const pts = (q: Quad) => q.map((p) => `${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(' ')

// 종이 한 장(300×396, 가운데가 0,0) → 위 모서리 접기 → 종이비행기(오른쪽을 향해요)
const TL: Pt = [-150, -198], TR: Pt = [150, -198], BR: Pt = [150, 198], BL: Pt = [-150, 198]
const MT: Pt = [0, -198], MB: Pt = [0, 198]
const LF: Pt = [-150, -48], RF: Pt = [150, -48], CF: Pt = [0, -48]
const N: Pt = [200, -24], W1: Pt = [-170, -132], C: Pt = [-112, 2], W2: Pt = [-150, 96], K: Pt = [-100, 52]
const FACETS: Record<'keel' | 'left' | 'right' | 'flapL' | 'flapR', [Quad, Quad, Quad]> = {
  keel: [[MT, MT, MB, MB], [MT, MT, MB, MB], [N, N, K, C]],
  left: [[TL, MT, MB, BL], [LF, MT, MB, BL], [W1, N, C, C]],
  right: [[MT, TR, BR, MB], [MT, RF, BR, MB], [N, N, W2, C]],
  flapL: [[MT, LF, TL, TL], [MT, LF, CF, CF], [N, W1, C, C]],
  flapR: [[MT, RF, TR, TR], [MT, RF, CF, CF], [N, N, W2, C]],
}

// 스크롤 구간 (이 섹션 안에서 0~1)
const FLIPS = [
  [0.05, 0.19],
  [0.2, 0.34],
] as const
const FLAT = [0.34, 0.4] as const // 책이 반듯하게 놓여요
const FOLD = [0.4, 0.58] as const // 마지막 쪽이 떨어져 나와 비행기로 접혀요
const FLY = [0.58, 0.98] as const // 아래로 날아가요
const COPY_OUT = [0.34, 0.44] as const
const OPEN_MS = 1500
const OPEN_DELAY = 900

const v = (o: Record<string, string | number>) => o as CSSProperties

export default function HeroBook() {
  const sectionRef = useRef<HTMLElement>(null)
  const bookRef = useRef<HTMLDivElement>(null)
  const sheetSlotRef = useRef<HTMLDivElement>(null)
  const copyRef = useRef<HTMLDivElement>(null)
  const hintRef = useRef<HTMLDivElement>(null)
  const leafRefs = useRef<(HTMLDivElement | null)[]>([])
  const svgRef = useRef<SVGSVGElement>(null)
  const pathRef = useRef<SVGPathElement>(null)
  const trailRef = useRef<SVGPathElement>(null)
  const planeRef = useRef<SVGGElement>(null)
  const facetRefs = useRef<Record<string, SVGPolygonElement | null>>({})
  const docRef = useRef<SVGGElement>(null)

  useEffect(() => {
    const section = sectionRef.current
    const book = bookRef.current
    const slot = sheetSlotRef.current
    const svg = svgRef.current
    const path = pathRef.current
    const trail = trailRef.current
    const plane = planeRef.current
    if (!section || !book || !slot || !svg || !path || !trail || !plane) return
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    const t0 = performance.now()
    let raf = 0
    let w = 0
    let h = 0
    let len = 1
    let pathKey = ''
    // 마지막 쪽의 화면 위치(책이 반듯해진 뒤에 재요)
    let sheet = { x: 0, y: 0, s: 1 }

    const measure = () => {
      w = window.innerWidth
      h = window.innerHeight
      svg.setAttribute('viewBox', `${-w / 2} ${-h / 2} ${w} ${h}`)
      const r = slot.getBoundingClientRect()
      sheet = { x: r.left + r.width / 2 - w / 2, y: r.top + r.height / 2 - h / 2, s: r.width / 300 }
      const { x, y } = sheet
      // 떠올라 오른쪽으로 한 번 휘었다가, 아래로 내려가 화면 밖(다음 칸)으로
      const d =
        `M ${x} ${y} C ${x + w * 0.22} ${y - h * 0.12} ${w * 0.38} ${h * 0.02} ${w * 0.18} ${h * 0.22} ` +
        `C ${w * 0.02} ${h * 0.38} ${-w * 0.12} ${h * 0.36} ${-w * 0.04} ${h * 0.75}`
      if (d !== pathKey) {
        pathKey = d
        path.setAttribute('d', d)
        trail.setAttribute('d', d)
        len = path.getTotalLength()
        trail.style.strokeDasharray = `${len} ${len}`
      }
    }

    const tick = (now: number) => {
      const r = section.getBoundingClientRect()
      const vh = window.innerHeight
      if (r.bottom > 0 && r.top < vh) {
        const total = r.height - vh
        const p = total <= 0 ? 0 : clamp(-r.top / total)
        const t = now - t0

        // 표지는 저절로 열려요 (먼저 스크롤해도 바로 열려요)
        const open = reduce ? 1 : Math.max(ease(seg(t, [OPEN_DELAY, OPEN_DELAY + OPEN_MS])), seg(p, [0, 0.04]))
        const flips = FLIPS.map((f) => ease(seg(p, f)))
        ;[open, ...flips].forEach((f, i) => {
          const el = leafRefs.current[i]
          if (!el) return
          el.style.setProperty('--f', f.toFixed(4))
          // 넘기는 중인 장이 맨 위, 넘어간 장은 왼쪽에서 마지막 장이 위, 안 넘어간 장은 앞 장이 위
          el.style.zIndex = String(f > 0.001 && f < 0.999 ? 50 : f >= 0.999 ? 20 + i : 20 - i)
          el.dataset.side = f >= 0.5 ? 'back' : 'front'
        })
        const flat = ease(seg(p, FLAT))
        const fold = ease(seg(p, FOLD))
        const fl = seg(p, FLY)
        const ft = ease(fl)
        book.style.setProperty('--open', open.toFixed(4))
        book.style.setProperty('--flat', flat.toFixed(4))
        // 비행기가 떠나면 책은 살짝 위로 물러나며 옅어져요
        book.style.setProperty('--leave', ease(seg(p, [0.6, 0.85])).toFixed(4))
        const bob = !reduce && p < 0.01 ? Math.sin(t * 0.0015) * 6 : 0
        book.style.setProperty('--bob', `${bob.toFixed(2)}px`)

        // 마지막 쪽: 접기 전까지는 책 속 쪽이 보이고, 접기 시작하면 SVG 종이로 바뀌어요
        if (p < FOLD[0]) measure()
        const lifted = p >= FOLD[0]
        book.classList.toggle('is-lifted', lifted)
        svg.style.opacity = lifted ? '1' : '0'

        const stage = fold < 0.5 ? 0 : 1
        const k = ease(stage === 0 ? fold / 0.5 : (fold - 0.5) / 0.5)
        for (const [name, keys] of Object.entries(FACETS)) {
          facetRefs.current[name]?.setAttribute('points', pts(lerpQuad(keys[stage], keys[stage + 1], k)))
        }
        const flaps = seg(fold, [0.02, 0.3]) * (1 - seg(fold, [0.75, 1]))
        facetRefs.current.flapL?.style.setProperty('opacity', String(flaps))
        facetRefs.current.flapR?.style.setProperty('opacity', String(flaps))
        facetRefs.current.keel?.style.setProperty('opacity', String(seg(fold, [0.55, 0.9])))
        facetRefs.current.right?.style.setProperty('--shade', String(seg(fold, [0.5, 1])))
        if (docRef.current) docRef.current.style.opacity = String(1 - seg(fold, [0, 0.2]))

        // 접히면서 책에서 떠올라요 → 날아가요
        const lift = seg(fold, [0, 0.4])
        let x = sheet.x + lift * 20
        let y = sheet.y - lift * 50
        let rot = -8 * fold
        if (fl > 0) {
          const pt = path.getPointAtLength(len * ft)
          const ahead = path.getPointAtLength(Math.min(len, len * ft + 2))
          const blend = seg(fl, [0, 0.08])
          x = lerp(x, pt.x, blend)
          y = lerp(y, pt.y, blend)
          rot = lerp(rot, (Math.atan2(ahead.y - pt.y, ahead.x - pt.x) * 180) / Math.PI, blend)
        }
        const sc = sheet.s * lerp(1, 0.72, seg(fold, [0.5, 1]))
        plane.setAttribute('transform', `translate(${x.toFixed(1)} ${y.toFixed(1)}) rotate(${rot.toFixed(2)}) scale(${sc.toFixed(3)})`)
        trail.style.strokeDashoffset = String(len * (1 - ft))
        trail.style.opacity = String(fl > 0 ? 1 : 0)

        if (copyRef.current) {
          const o = seg(p, COPY_OUT)
          copyRef.current.style.opacity = String(1 - o)
          copyRef.current.style.transform = `translateY(${(-o * 60).toFixed(1)}px)`
        }
        if (hintRef.current) hintRef.current.style.opacity = String(seg(t, [2600, 3400]) * (1 - seg(p, [0.01, 0.05])))
      }
      raf = requestAnimationFrame(tick)
    }

    const onResize = () => {
      pathKey = ''
    }
    window.addEventListener('resize', onResize)
    raf = requestAnimationFrame(tick)
    return () => {
      cancelAnimationFrame(raf)
      window.removeEventListener('resize', onResize)
    }
  }, [])

  const leaf = (i: number, front: React.ReactNode, back: React.ReactNode, cls = '') => (
    <div
      className={`bk-leaf ${cls}`}
      ref={(el) => {
        leafRefs.current[i] = el
      }}
    >
      <div className="bk-face bk-front">{front}</div>
      <div className="bk-face bk-back">{back}</div>
    </div>
  )

  const facet = (name: keyof typeof FACETS, cls: string) => (
    <polygon
      ref={(el) => {
        facetRefs.current[name] = el
      }}
      className={cls}
      points={pts(FACETS[name][0])}
    />
  )

  const lines = (ws: number[], mark = -1) =>
    ws.map((wd, i) => <p key={i} className={`bk-line-t ${i === mark ? 'mark' : ''}`} style={{ width: `${wd}%` }} />)

  return (
    <section className="bk-hero" ref={sectionRef} aria-labelledby="bk-title">
      <div className="bk-sticky">
        <div className="bk-copy" ref={copyRef}>
          <span className="bk-eyebrow"><b>AI</b>교수님 강의 자료로 만드는 복습</span>
          <h1 id="bk-title">
            <span className="bk-line"><span style={v({ animationDelay: '.2s' })}>교수님의 강의 자료에서</span></span>
            <span className="bk-line"><span className="bk-g" style={v({ animationDelay: '.35s' })}>나의 복습이 날아올라요</span></span>
          </h1>
        </div>

        <div className="bk-scene" aria-hidden="true">
          <div className="bk-glow" />
          <div className="bk-book" ref={bookRef}>
            <div className="bk-base bk-base-l" />
            {/* 오른쪽 바탕: 마지막 쪽(p.18 정리). 접기 시작하면 이 자리의 종이가 비행기로 바뀌고, 아래 빈 쪽(p.19)이 드러나요 */}
            <div className="bk-base bk-base-r">
              <div className="bk-slot" ref={sheetSlotRef} />
              <div className="bk-page bk-last">
                <small>9주차 · 정리</small>
                <h4>오늘 꼭 기억할 것</h4>
                {lines([94, 80, 88], 1)}
                <div className="bk-sum">
                  <span>탐색 O(n)</span>
                  <span>삽입 O(1)</span>
                </div>
                {lines([90, 62])}
                <span className="bk-pg">p.18</span>
              </div>
              <div className="bk-page bk-under">
                {lines([70, 92, 84, 60, 88, 76, 50])}
                <span className="bk-pg">p.19</span>
              </div>
            </div>

            {/* 2장: p.16 코드 / p.17 시간 복잡도 */}
            {leaf(
              2,
              <div className="bk-page">
                <small>9주차 · 예제 코드</small>
                <h4>리스트 뒤집기</h4>
                <pre className="bk-code">
                  <span className="k">function</span> reverse(head) {'{\n'}
                  {'  '}<span className="k">let</span> prev = <span className="n">null</span>{'\n'}
                  {'  '}<span className="k">while</span> (head) {'{\n'}
                  {'    '}<span className="h">const next = head.next</span>{'\n'}
                  {'    '}head.next = prev{'\n'}
                  {'    '}prev = head; head = next{'\n'}
                  {'  }\n'}
                  {'  '}<span className="k">return</span> prev{'\n'}
                  {'}'}
                </pre>
                {lines([86, 58])}
                <span className="bk-pg">p.16</span>
              </div>,
              <div className="bk-page">
                <small>9주차 · 비교</small>
                <h4>배열과 연결 리스트</h4>
                <table className="bk-table">
                  <tbody>
                    <tr><th /><th>배열</th><th>연결 리스트</th></tr>
                    <tr><td>접근</td><td>O(1)</td><td>O(n)</td></tr>
                    <tr><td>앞에 삽입</td><td>O(n)</td><td className="hl">O(1)</td></tr>
                    <tr><td>메모리</td><td>연속</td><td>흩어짐</td></tr>
                  </tbody>
                </table>
                {lines([92, 74, 84], 2)}
                <span className="bk-pg">p.17</span>
              </div>,
            )}

            {/* 1장: p.14 노드 구조 / p.15 뒤집기 순서 */}
            {leaf(
              1,
              <div className="bk-page">
                <small>9주차 · 노드</small>
                <h4>노드는 값과 다음 주소</h4>
                <div className="bk-nodes">
                  {['12', '7', '30'].map((n, i) => (
                    <span key={n}>
                      <b>{n}</b>
                      {i < 2 && <i />}
                    </span>
                  ))}
                </div>
                {lines([96, 82, 90, 66], 1)}
                <span className="bk-pg">p.14</span>
              </div>,
              <div className="bk-page">
                <small>9주차 · 뒤집기</small>
                <h4>화살표 방향 바꾸기</h4>
                <div className="bk-nodes rev">
                  {['30', '7', '12'].map((n, i) => (
                    <span key={n}>
                      <b>{n}</b>
                      {i < 2 && <i />}
                    </span>
                  ))}
                </div>
                {lines([92, 70, 86, 78, 54], 2)}
                <span className="bk-pg">p.15</span>
              </div>,
            )}

            {/* 표지 / p.13 학습 목표 */}
            {leaf(
              0,
              <div className="bk-cover">
                <span className="bk-cover-k">자료구조 · 9주차 강의 자료</span>
                <strong>단일 연결<br />리스트</strong>
                <span className="bk-cover-m">2026 1학기</span>
              </div>,
              <div className="bk-page">
                <small>9주차 · 교수님 강의 자료</small>
                <h4 className="big">학습 목표</h4>
                <ol className="bk-goals">
                  <li>노드와 포인터의 구조를 이해한다</li>
                  <li>삽입 · 삭제의 순서를 설명한다</li>
                  <li>리스트를 제자리에서 뒤집는다</li>
                </ol>
                {lines([88, 72, 94, 60])}
                <span className="bk-pg">p.13</span>
              </div>,
              'bk-cover-leaf',
            )}
          </div>
        </div>

        {/* 책에서 떨어져 나온 마지막 쪽 → 종이비행기 → 아래로 */}
        <svg className="bk-fly" ref={svgRef} aria-hidden="true" preserveAspectRatio="xMidYMid meet">
          <defs>
            <linearGradient id="bk-trail" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="var(--d-lilac, #d0bcfc)" />
              <stop offset="100%" stopColor="var(--d-accent, #6631db)" />
            </linearGradient>
          </defs>
          <path ref={pathRef} fill="none" stroke="none" />
          <path ref={trailRef} className="bk-trail" fill="none" />
          <g ref={planeRef}>
            {facet('keel', 'bk-keel')}
            {facet('left', 'bk-sheet')}
            {facet('right', 'bk-sheet bk-right')}
            <g ref={docRef} className="bk-doc">
              <text x="-120" y="-150" className="k">9주차 · 정리</text>
              <text x="-120" y="-116" className="h">오늘 꼭 기억할 것</text>
              <rect x="-120" y="-92" width="226" height="7" rx="3.5" />
              <rect x="-120" y="-74" width="192" height="7" rx="3.5" className="m" />
              <rect x="-120" y="-56" width="212" height="7" rx="3.5" />
              <rect x="-120" y="-30" width="110" height="34" rx="9" className="b" />
              <rect x="-2" y="-30" width="110" height="34" rx="9" className="b" />
              <rect x="-120" y="22" width="216" height="7" rx="3.5" />
              <rect x="-120" y="40" width="150" height="7" rx="3.5" />
              <text x="120" y="176" className="k" textAnchor="end">p.18</text>
            </g>
            {facet('flapL', 'bk-flap')}
            {facet('flapR', 'bk-flap')}
          </g>
        </svg>

        <div className="bk-hint" ref={hintRef} aria-hidden="true">
          <span>스크롤하면 강의 자료가 넘어가요</span>
          <i />
        </div>
      </div>
    </section>
  )
}
