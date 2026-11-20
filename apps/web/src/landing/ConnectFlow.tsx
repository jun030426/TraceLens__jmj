/**
 * [랜딩 · 교수자 아래] 학생 · Lerny · 교수자 연결 영역
 * - 왼쪽 학생, 가운데 Lerny 글씨(상단바 로고의 글씨 부분, public/lerny-wordmark.png), 오른쪽 교수자.
 * - 점선 곡선 두 줄(양 끝은 가로로 눕고 가운데가 솟는 대칭 곡선)이 계속 흐르고, 말풍선(박스) 자체가 선을 따라 하나씩 이동해요. 끝나면 처음부터 계속.
 *   위 곡선: 교수자 → 학생 (교수자 문구)
 *   아래 곡선: 학생 → 교수자 (학생 문구)
 *   한 줄에서 박스는 반 바퀴 간격으로 출발해서, 동시에 두 개까지만 보여요. 양 끝에서는 흐려지며 나타나고 사라져요.
 * - 화면 밖이면 멈추고, 움직임 줄이기 설정이면 박스를 선 위 제자리에 멈춰 둬요.
 * - 좁은 화면(980px 이하)에서는 학생 → 교수자 문구 → Lerny → 학생 문구 → 교수자 순서로 세로로 쌓여요 (움직이지 않아요).
 * - 스타일: landing/lerny-connect.css (.cn-*)
 */

import { useEffect, useRef } from 'react'
import './lerny-connect.css'

// 위 곡선 (교수자 → 학생)
const PROF_LINES = ['AI 강의로 개념을 쉽게 익혀보세요.', '이번 주 배운 내용을 퀴즈로 확인해요.', '어려운 개념은 함께 다시 살펴봐요.']
// 아래 곡선 (학생 → 교수자)
const STU_LINES = ['질문을 학습 기록으로 전해요.', '문제와 질문으로 어려워하는 개념을 알려드려요.', '헷갈린 개념을 다음 수업에서 짚어주세요.']

// 두 선은 양 끝에서 가로로 누운 채 출발해 가운데에서 크게 솟는(내려가는) 매끈한 종 모양 곡선이에요.
// 위·아래가 거울처럼 대칭이라 합쳐서 길쭉한 눈(렌즈) 모양이 돼요. 가운데 (501, 200)
// 11/18: 위아래 볼록함을 줄이고(52 → 92) 양 끝을 좌우로 더 길게(182 · 820 → 150 · 850), 끝에서 수평으로 길게 빠져나가요
const PATH_TOP = 'M850 192 C 740 192, 690 92, 500 92 C 310 92, 260 192, 150 192'
const PATH_BOT = 'M150 208 C 260 208, 310 308, 500 308 C 690 308, 740 208, 850 208'
const VB_W = 1000
const VB_H = 400
const TRAVEL = 9000 // 박스 하나가 선 끝에서 끝까지 가는 시간 (ms)
const LAUNCH = TRAVEL / 2 // 다음 박스가 출발하는 간격
const FADE = 0.16 // 양 끝에서 흐려지는 구간 (선 길이 비율)
const REST = [0.25, 0.5, 0.75] // 움직임 줄이기: 박스를 멈춰 둘 자리

const STU = { title: '궁금한 순간부터, 이해하는 순간까지.', desc: '질문하고 실습하며, 부족한 개념을 채워가세요.' }
const PROF = { title: '준비한 수업에서, 학생의 이해까지.', desc: '자료를 공유하고, 학생이 어려워하는 지점을 확인하세요.' }
const HUB = '자료에서 이해로, 배움에서 수업으로.'

function BubbleIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M4 5h16v11H10l-5 4v-4H4z" fill="none" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" />
      <circle cx="9" cy="10.5" r="1.2" fill="currentColor" />
      <circle cx="12" cy="10.5" r="1.2" fill="currentColor" />
      <circle cx="15" cy="10.5" r="1.2" fill="currentColor" />
    </svg>
  )
}
function PaperIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M5 4h11l3 3v13H5z" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
      <path d="M8.5 13 11 15.5 16 10" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

function Wordmark({ className }: { className: string }) {
  return <img className={className} src="/lerny-wordmark.png" alt="Lerny" />
}

export default function ConnectFlow() {
  const rootRef = useRef<HTMLElement>(null)
  const topRef = useRef<SVGPathElement>(null)
  const botRef = useRef<SVGPathElement>(null)

  useEffect(() => {
    const root = rootRef.current
    const top = topRef.current
    const bot = botRef.current
    if (!root || !top || !bot) return
    const lanes = [
      { path: top, len: top.getTotalLength(), els: Array.from(root.querySelectorAll<HTMLElement>('.cn-stage .cn-bub.top')) },
      { path: bot, len: bot.getTotalLength(), els: Array.from(root.querySelectorAll<HTMLElement>('.cn-stage .cn-bub.bot')) },
    ]
    const place = (el: HTMLElement, path: SVGPathElement, len: number, u: number, opacity: number) => {
      const p = path.getPointAtLength(len * u)
      el.style.left = `${(p.x / VB_W) * 100}%`
      el.style.top = `${(p.y / VB_H) * 100}%`
      el.style.opacity = opacity.toFixed(3)
    }

    if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) {
      lanes.forEach((l) => l.els.forEach((el, i) => place(el, l.path, l.len, REST[i], 1)))
      return
    }

    let raf = 0
    let visible = false
    const t0 = performance.now()
    const period = LAUNCH * PROF_LINES.length // 한 박스가 다시 출발하기까지
    const tick = (now: number) => {
      const t = now - t0
      lanes.forEach((l, lane) =>
        l.els.forEach((el, i) => {
          // 아래 줄은 위 줄과 엇갈려 출발해요
          const local = (((t - i * LAUNCH - lane * (LAUNCH / 2)) % period) + period) % period
          const u = local / TRAVEL
          if (u > 1) {
            el.style.opacity = '0'
            return
          }
          const fade = Math.min(1, u / FADE, (1 - u) / FADE)
          place(el, l.path, l.len, u, fade)
        }),
      )
      if (visible) raf = requestAnimationFrame(tick)
    }
    const io = new IntersectionObserver(([en]) => {
      visible = en.isIntersecting
      cancelAnimationFrame(raf)
      if (visible) raf = requestAnimationFrame(tick)
    })
    io.observe(root)
    raf = requestAnimationFrame(tick)
    return () => {
      io.disconnect()
      cancelAnimationFrame(raf)
    }
  }, [])

  const bub = (kind: 'top' | 'bot', text: string) => (
    <div key={text} className={`cn-bub ${kind}`}>
      <span className="cn-ic">{kind === 'top' ? <BubbleIcon /> : <PaperIcon />}</span>
      {text}
    </div>
  )

  return (
    <section ref={rootRef} className="cn-connect" aria-labelledby="cn-title">
      <div className="cn-specks" aria-hidden="true">
        {[[6, 10], [22, 30], [40, 14], [63, 42], [80, 12], [93, 36], [15, 88], [47, 93], [72, 86]].map(([l, t]) => (
          <i key={`${l}-${t}`} style={{ left: `${l}%`, top: `${t}%` }} />
        ))}
      </div>
      <div className="cn-inner">
        <div className="cn-head">
          <h2 id="cn-title">
            학생의 <em className="cn-key">배움</em>과 교수자의 수업을 <em className="cn-key">잇다</em>.
          </h2>
          <p>
            강의 자료는 학생의 이해로, 학습 기록은 다음 수업의 단서로.
            <br />
            Lerny가 학생과 교수자를 연결합니다.
          </p>
        </div>

        <div className="cn-stage">
          <svg viewBox={`0 0 ${VB_W} ${VB_H}`} preserveAspectRatio="none" aria-hidden="true">
            <path className="cn-glow" d={PATH_TOP} />
            <path ref={topRef} className="cn-dots" d={PATH_TOP} />
            <path className="cn-glow" d={PATH_BOT} />
            <path className="cn-dots b" ref={botRef} d={PATH_BOT} />
            {/* 11/18: 양 끝 동그라미 대신 아래 '학생' · '교수자' 키워드 박스가 그 자리에 놓여요 */}
          </svg>
          <span className="cn-endbox stu">학생</span>
          <span className="cn-endbox prof">교수자</span>
          <div className="cn-side stu">
            <h3>{STU.title}</h3>
            <p>{STU.desc}</p>
          </div>
          <div className="cn-hub">
            <Wordmark className="cn-wordmark" />
            <p>{HUB}</p>
          </div>
          <div className="cn-side prof">
            <h3>{PROF.title}</h3>
            <p>{PROF.desc}</p>
          </div>
          <div className="cn-moving" aria-hidden="true">
            {PROF_LINES.map((t) => bub('top', t))}
            {STU_LINES.map((t) => bub('bot', t))}
          </div>
          {/* 화면 읽기 프로그램용: 움직이는 박스 대신 순서대로 읽어요 */}
          <div className="cn-sr">
            <p>교수자에서 학생으로: {PROF_LINES.join(' ')}</p>
            <p>학생에서 교수자로: {STU_LINES.join(' ')}</p>
          </div>
        </div>

        <div className="cn-mobile">
          <div className="cn-card">
            <span className="cn-role">학생</span>
            <h3>{STU.title}</h3>
            <p>{STU.desc}</p>
          </div>
          <div className="cn-mflow">
            <h4>교수자 → 학생</h4>
            {PROF_LINES.map((t) => bub('top', t))}
          </div>
          <div className="cn-mhub">
            <Wordmark className="cn-wordmark" />
            <p>{HUB}</p>
          </div>
          <div className="cn-mflow">
            <h4>학생 → 교수자</h4>
            {STU_LINES.map((t) => bub('bot', t))}
          </div>
          <div className="cn-card">
            <span className="cn-role">교수자</span>
            <h3>{PROF.title}</h3>
            <p>{PROF.desc}</p>
          </div>
        </div>
      </div>
    </section>
  )
}
