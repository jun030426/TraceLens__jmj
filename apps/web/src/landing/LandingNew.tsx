/**
 * [랜딩 본문] 따뜻한 종이 위의 소개 — 앱 화면들과 같은 색(종이 · 자두색 · 모브)과 같은 글꼴(명조 제목 · 고딕 본문)을 써요.
 *   화면 순서 (위 → 아래)
 *   ① 첫 화면 — 누운 강의자료 15쪽이 일어서고, 하나로 모여 아래로 내려가요 (HeroParallax.tsx · 스타일은 lerny-hero-parallax.css)
 *   ② 하루의 학습 — 붙어 있는 화면. 스크롤에 따라 자료(숏폼 강의) → 이론 퀴즈 → 실습 → AI 질문 → 학습 기록 데모가 재생돼요
 *   ③ 학습 도구 — 짙은 자두색 띠 위에 종이 카드 여섯 장 (가운데 줄은 한 칸 내려앉아요)
 *   ④ 교수자 — 위에 제목 · 설명, 아래 한 줄 위에 1 → 2 → 3 → 4 좌표. 화면에 들어오면 진행선이 순서대로 다음 좌표까지 차오르며 강조돼요
 *   ⑤ 마지막 장식 — 점이 모여 네모를 그리고 맥북이 됨. 스크롤하면 맥북 화면 속으로 (MacScene.tsx · 스타일은 lerny-mac-scene.css)
 *   마무리 문장 · Lerny 바닥 띠는 Landing.tsx 에서 이어 붙여요.
 * - 문구와 데모(MaterialDemo · QuizDemo · PracticeDemo · ChatDemo · StatsDemo)는 개편 전 것 그대로, 색만 따뜻한 조합으로 바꿨어요.
 * - 스타일: landing/lerny-landing-new.css (색 · 글꼴 토큰은 lerny-design.css 의 --d-*)
 */

import { useEffect, useRef, useState, type CSSProperties } from 'react'
import { useInView } from './vizMotion'
import MaterialDemo from './MaterialDemo'
import QuizDemo from './QuizDemo'
import PracticeDemo from './PracticeDemo'
import ChatDemo from './ChatDemo'
import StatsDemo from './StatsDemo'
import { IconArrowUpRight } from './Icons'
import MacScene from './MacScene'
import HeroParallax from './HeroParallax'
import ConnectFlow from './ConnectFlow'
import StudentPreview from './StudentPreview'
import { IconCalendarCheck, IconFileSearch, IconMessageChatbot, IconFlame, IconClipboardCheck, IconChartBar, IconArrowUpRight as TbArrowUpRight, IconArrowRight as TbArrowRight } from '@tabler/icons-react'

interface LandingNewProps {
  /** 시작하기 버튼을 눌렀을 때 실행 */
  onStart: () => void
  /** 교수자로 시작하기 버튼을 눌렀을 때 실행 (교수자 로그인으로) */
  onProfessorStart: () => void
}

// 하루의 학습 다섯 단계 — 제목 · 설명은 기존 랜딩과 같아요
const STEPS = [
  { key: 'material', label: '자료', title: '교수님이 올린 강의 자료를', desc: 'AI 강사가 칠판의 도표와 예시로, 개념마다 짧은 강의로 설명해요.' },
  { key: 'quiz', label: '이론', title: '오늘의 이론 문제를 풀어요', desc: '헷갈릴 때는 강의 자료의 근거를 확인하고, 풀고 나면 결과와 해설로 복습해요.' },
  { key: 'code', label: '실습', title: '직접 구현하며 익혀요', desc: '배정된 실습 문제를 풀고, 내 코드의 실행 흐름을 시각화로 확인해요.' },
  { key: 'chat', label: 'AI 질문', title: '궁금한 건 AI에게 물어봐요', desc: '퀴즈 결과에서, AI 강의를 보다가 생긴 질문까지. 강의 자료의 근거와 함께 답해 줘요.' },
  { key: 'stats', label: '학습 기록', title: '다시 살펴볼 개념을 찾아요', desc: '개념별 · 날짜별 기록으로 나의 이해를 확인하고, 복습으로 이어가요.' },
]

// 학습 도구 — 문구는 기존 랜딩과 같아요
const TOOLS = [
  { title: '오늘의 학습', desc: '오늘의 이론과 실습으로 이어지는 하루 학습' },
  { title: '자료 근거', desc: '해설과 답변마다 강의 자료의 근거를 함께' },
  { title: 'AI 질문', desc: '“왜 이 답이 틀렸나요?” 수업 맥락 그대로' },
  { title: '연속 학습', desc: '오늘의 이론이나 실습을 마치면 한 칸씩' },
  { title: '시험 대비', desc: '공개된 시험 범위의 기출 · 연습 문제' },
  { title: '학습 기록', desc: '개념별 · 날짜별로 나의 이해를 확인' },
]

// 학습 도구 목록형 디자인(11/18): 도구마다 아이콘. 순서는 TOOLS 와 같아요
const TOOL_ICONS = [IconCalendarCheck, IconFileSearch, IconMessageChatbot, IconFlame, IconClipboardCheck, IconChartBar]
// true = 왼쪽 큰 제목 + 오른쪽 번호 목록, false = 예전 흐르는 카드(marquee)
const USE_TOOL_LIST = true
// 학습 도구 칸 나눔 디자인(11/18): 위 가운데 제목, 아래 3 × 2 칸. 마우스를 대면 왼쪽 막대가 보라로 길어지고 연보라 그라데이션이 번져요.
// false 로 바꾸면 왼쪽 제목 + 오른쪽 01 ~ 06 목록으로 돌아가요
const USE_TOOL_GRID = true

// 교수자 도구 — 문구는 기존 랜딩과 같아요
const BRIDGE = [
  { title: '생성 문항 관리', desc: '강의 자료로 만든 이론 문항과 해설을 확인하고 관리' },
  { title: '서술형 검토', desc: '시험 대비 서술형 답안을 확인하고 피드백' },
  { title: '학생 학습 현황', desc: '분반별 참여, 개념별 이해도와 학생별 학습 기록' },
  { title: '수강 코드', desc: '코드로 신청하면 교수님 승인 후 수강' },
]

// 교수자 네 단계가 자동으로 넘어가는 간격 (ms). 마우스를 올리면 그 단계에서 멈춰요
const BRIDGE_MS = 2800

// 단계마다 차지하는 스크롤 길이 (1 = 화면 약 1장). 숏폼 강의 데모가 가장 길어요
const FLOW_MS = 2800 // 하루의 학습: 한 단계가 머무는 시간 (옆으로 넘어가는 0.7초를 포함해요)
const FLOW_MS_CODE = 3800 // 실습은 코드 입력 → 실행 → 입체 시각화 3회차까지 보여 주려고 조금 더 머물러요

// 하루의 학습 화면: true = 학생용 페이지 미리보기(StudentPreview.tsx), false = 예전 데모
const USE_STUDENT_PREVIEW = true
// 단계 배치: true = 왼쪽 세로 목록(지금 단계만 설명 · 진행 막대가 펼쳐짐) + 오른쪽 큰 화면, false = 제목 아래 가로 한 줄
const FLOW_SIDE_LIST = true
// 미리보기는 화면 속 마우스가 직접 눌러 보는 장면까지 보여 줘서 단계마다 머무는 시간이 달라요 (ms)
// 11/18 밤: 전체적으로 약 1.4배 느리게
const PREVIEW_MS: Record<string, number> = { material: 8500, quiz: 10000, code: 25000, chat: 10000, stats: 14000 }

const SLIDE_MS = 700 // 하루의 학습: 옆으로 넘어가는 시간 (CSS 의 lw-slide-in / lw-slide-out 과 같게)

const order = (i: number) => ({ ['--i' as string]: i }) as CSSProperties

export default function LandingNew({ onStart, onProfessorStart }: LandingNewProps) {
  const toolRef = useRef<HTMLElement>(null)
  const toolIn = useInView(toolRef, 0.15)
  const bridgeRef = useRef<HTMLElement>(null)
  const bridgeIn = useInView(bridgeRef, 0.15)
  // 교수자 단계 자동 넘김 — 화면에 들어온 뒤부터 1 → 2 → 3 → 4 → 1 … (움직임 줄이기 설정이면 넘기지 않아요)
  const [bridgeStep, setBridgeStep] = useState(0)
  const [bridgeHold, setBridgeHold] = useState(false)
  const [reduceMotion] = useState(
    () => typeof window !== 'undefined' && !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches,
  )
  useEffect(() => {
    if (!bridgeIn || bridgeHold || reduceMotion) return
    const t = window.setTimeout(() => setBridgeStep((s) => (s + 1) % BRIDGE.length), BRIDGE_MS)
    return () => window.clearTimeout(t)
  }, [bridgeIn, bridgeHold, bridgeStep, reduceMotion])

  return (
    <main className="v-landing lw">
      {/* ① 첫 화면 — 누워 있던 교수님 강의자료 15쪽이 일어서고, 가운데로 모여 하나로 겹친 뒤 아래로 내려가요 (HeroParallax.tsx).
          예전 첫 화면(책 HeroBook · 종이비행기 HeroPlane · 보라 원 HeroOrb)은 파일로 남겨 두었어요 */}
      <HeroParallax />

      {/* ①-2 학생 · Lerny · 교수자 연결 (ConnectFlow.tsx) — 11/18 맥북 장면 자리(첫 화면 바로 밑)로 옮겼어요.
          첫 화면에서 모인 강의자료가 아래 가운데로 내려가면 이 칸이 나타나요 */}
      <ConnectFlow />

      <Flow />

      {/* ③ 학습 도구 — 왼쪽 큰 제목 · 설명, 오른쪽 01 ~ 06 번호 목록 (아이콘 · 이름 · 설명 · ↗) */}
      {USE_TOOL_LIST ? (
        <section ref={toolRef} className={`lw-tools lw-kit ${USE_TOOL_GRID ? 'is-grid' : ''} ${toolIn ? 'is-in' : ''}`} aria-labelledby="lw-tools-title">
          <div className="lw-kit-inner">
            <div className="lw-kit-head">
              <h2 id="lw-tools-title">
                나만의
                {USE_TOOL_GRID ? ' ' : <br />}
                {USE_TOOL_GRID ? '학습 도구' : '학습 도구.'}
              </h2>
              <p>강의 자료에서 시작해, 매일의 학습이 나의 이해로 쌓여요.</p>
              <button type="button" className={USE_TOOL_GRID ? 'lw-btn' : 'lw-btn on-dark'} onClick={onStart}>
                학습 시작하기 {USE_TOOL_GRID ? <TbArrowRight size={18} stroke={2} aria-hidden="true" /> : <IconArrowUpRight />}
              </button>
            </div>
            {USE_TOOL_GRID ? (
            <div className="lw-feat-grid" role="list">
              {TOOLS.map((t, i) => {
                const Icon = TOOL_ICONS[i]
                return (
                  <button type="button" role="listitem" key={t.title} className={`lw-feat ${i < 3 ? 'top' : 'bot'}`} style={order(i)} onClick={onStart}>
                    <span className="lw-feat-icon" aria-hidden="true">
                      <Icon size={26} stroke={1.6} />
                    </span>
                    <strong className="lw-feat-title">{t.title}</strong>
                    <span className="lw-feat-desc">{t.desc}</span>
                  </button>
                )
              })}
            </div>
            ) : (
            <div className="lw-kit-list" role="list">
              {TOOLS.map((t, i) => {
                const Icon = TOOL_ICONS[i]
                return (
                  <button type="button" role="listitem" key={t.title} className="lw-kit-row" style={order(i)} onClick={onStart}>
                    <span className="lw-kit-num">{String(i + 1).padStart(2, '0')}</span>
                    <span className="lw-kit-icon" aria-hidden="true">
                      <Icon size={30} stroke={1.6} />
                    </span>
                    <span className="lw-kit-text">
                      <strong>{t.title}</strong>
                      <span>{t.desc}</span>
                    </span>
                    <TbArrowUpRight className="lw-kit-go" size={22} stroke={1.6} aria-hidden="true" />
                  </button>
                )
              })}
            </div>
            )}
          </div>
        </section>
      ) : (
      <section ref={toolRef} className={`lw-tools ${toolIn ? 'is-in' : ''}`} aria-labelledby="lw-tools-title">
        <div className="lw-tools-head">
          <h2 id="lw-tools-title">나만의 학습 도구</h2>
          <button type="button" className="lw-btn on-dark" onClick={onStart}>
            학습 시작하기 <IconArrowUpRight />
          </button>
        </div>
        {/* 한 줄로 늘어선 카드가 왼쪽으로 천천히 흘러요 (끊김 없이 이어지도록 한 벌을 더 붙여요). 마우스를 대면 멈춰요 */}
        <div className="lw-marquee">
          <div className="lw-marquee-track">
            {[0, 1].map((copy) => (
              <ul key={copy} aria-hidden={copy === 1 ? true : undefined}>
                {TOOLS.map((t) => (
                  <li key={t.title}>
                    <strong>{t.title}</strong>
                    <span>{t.desc}</span>
                  </li>
                ))}
              </ul>
            ))}
          </div>
        </div>
      </section>
      )}

      {/* ④ 교수자 */}
      <section ref={bridgeRef} className={`lw-bridge is-line ${bridgeIn ? 'is-in' : ''}`} aria-labelledby="lw-bridge-title">
        <div className="lw-bridge-head">
          <h2 id="lw-bridge-title">강의실과 내 공부를 연결</h2>
          <p>
            교수자는 강의 자료를 올리고 분반 학습 범위를 정해요. 이론 문항은 자료에서 만들어지고, 학생들의 기록은 다음 수업에서 짚어볼 개념이 돼요.
          </p>
        </div>
        {/* 한 줄 위에 1 → 2 → 3 → 4 좌표가 찍히고, 진행선이 순서대로 다음 좌표까지 차올라요 */}
        <div
          className={`lw-bridge-track ${reduceMotion ? '' : 'is-auto'} ${bridgeHold ? 'is-hold' : ''}`}
          style={{ ['--lw-bridge-ms' as string]: `${BRIDGE_MS}ms`, ['--n' as string]: BRIDGE.length, ['--s' as string]: bridgeStep } as CSSProperties}
          onMouseLeave={() => setBridgeHold(false)}
        >
          <div className="lw-bridge-rail" aria-hidden="true">
            <i />
          </div>
          <ol>
            {BRIDGE.map((b, i) => (
              <li
                key={b.title}
                style={order(i)}
                className={i === bridgeStep ? 'on' : i < bridgeStep ? 'done' : undefined}
                aria-current={i === bridgeStep ? 'step' : undefined}
                onMouseEnter={() => {
                  setBridgeStep(i)
                  setBridgeHold(true)
                }}
              >
                <span className="lw-bridge-dot" aria-hidden="true">{i + 1}</span>
                <strong>{b.title}</strong>
                <span className="lw-bridge-desc">{b.desc}</span>
              </li>
            ))}
          </ol>
        </div>
        <div className="lw-bridge-cta">
          <button type="button" className="lw-btn" onClick={onProfessorStart}>
            교수자로 시작하기 <TbArrowRight size={18} stroke={2} aria-hidden="true" />
          </button>
        </div>
      </section>

      {/* ⑤ 마지막 장식 — 점 → 네모 → 맥북 → 화면 속으로 (MacScene.tsx). 11/18 첫 화면에서 다시 원래 자리로 돌려놨어요.
          바로 아래(Landing.tsx)에 '오늘의 물음표가' 마무리 문장이 이어져요 */}
      <MacScene />
    </main>
  )
}

/** ② 하루의 학습 — 화면은 붙어 있고, 스크롤할수록 왼쪽 단계가 하나씩 펼쳐지며 오른쪽 데모가 그 단계를 실제처럼 재생해요.
 *   자료(숏폼 강의) → 이론 퀴즈 → 실습 → AI 질문(챗봇) → 학습 기록(분석). 데모는 개편 전 것 그대로예요. */
function Flow() {
  // 스크롤 대신 시간으로 넘어가요: 화면에 보이는 동안 한 단계씩 FLOW_MS 마다 자동으로 다음 단계로 (끝나면 처음부터)
  const ref = useRef<HTMLElement>(null)
  const [index, setIndex] = useState(0)
  const [local, setLocal] = useState(0)
  const [visible, setVisible] = useState(false)
  // 옆으로 넘기기: 방금 나간 단계(prev)는 잠깐 남아 반대쪽으로 빠지고, 새 단계는 dir 쪽(1 = 오른쪽)에서 밀려 들어와요
  const [prev, setPrev] = useState<number | null>(null)
  const [dir, setDir] = useState<1 | -1>(1)
  const go = (next: number, d: 1 | -1) => {
    setPrev(index)
    setDir(d)
    setIndex(next)
  }
  const [reduce] = useState(() => typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches)

  useEffect(() => {
    const el = ref.current
    if (!el || typeof IntersectionObserver === 'undefined') {
      setVisible(true)
      return
    }
    const io = new IntersectionObserver(([e]) => setVisible(e.isIntersecting), { threshold: 0.35 })
    io.observe(el)
    return () => io.disconnect()
  }, [])

  useEffect(() => {
    if (!visible) return
    if (reduce) {
      setLocal(1)
      const t = window.setTimeout(() => go((index + 1) % STEPS.length, 1), FLOW_MS + 600)
      return () => window.clearTimeout(t)
    }
    let raf = 0
    const start = performance.now()
    const ms = USE_STUDENT_PREVIEW ? PREVIEW_MS[STEPS[index].key] ?? FLOW_MS : STEPS[index].key === 'code' ? FLOW_MS_CODE : FLOW_MS
    const tick = (now: number) => {
      const e = now - start
      // 단계 안 애니메이션은 80% 시간 안에 끝내고, 남은 시간은 결과를 잠깐 보여줘요
      setLocal(Math.min(1, e / (ms * 0.8)))
      if (e >= ms) {
        go((index + 1) % STEPS.length, 1)
        return
      }
      raf = requestAnimationFrame(tick)
    }
    setLocal(0)
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
    // eslint-disable-next-line react-hooks/exhaustive-deps -- go 는 index 만 쓰고, index 가 바뀌면 다시 걸려요
  }, [visible, index, reduce])

  // 넘어가는 애니메이션(0.7초)이 끝나면 나간 단계를 치워요
  useEffect(() => {
    if (prev === null) return
    const t = window.setTimeout(() => setPrev(null), SLIDE_MS + 60)
    return () => window.clearTimeout(t)
  }, [prev, index])

  const step = STEPS[index]
  return (
    <section ref={ref} id="lw-flow" className={`lw-flow is-auto${FLOW_SIDE_LIST ? ' is-side' : ''}`} aria-labelledby="lw-flow-title" style={{ ['--dir' as string]: dir } as CSSProperties}>
      <div className="lw-flow-sticky">
        {/* 11/18: 제목은 왼쪽 목록 위가 아니라 맨 위 전체 폭으로 빼서, 오른쪽 화면이 더 크게 보여요 */}
        {FLOW_SIDE_LIST && <h2 id="lw-flow-title" className="lw-flow-top">하루의 학습</h2>}
        <div className="lw-flow-side">
          {!FLOW_SIDE_LIST && <h2 id="lw-flow-title">하루의 학습</h2>}
          <ol className="lw-flow-steps">
            {STEPS.map((s, i) => {
              const fill = i < index ? 1 : i === index ? local : 0
              return (
                <li key={s.key} className={i === index ? 'on' : i < index ? 'done' : undefined} aria-current={i === index ? 'step' : undefined} onClick={() => i !== index && go(i, i > index ? 1 : -1)}>
                  <span className="lw-flow-label">
                    <b className="lw-flow-num" aria-hidden="true">{FLOW_SIDE_LIST ? null : i + 1}</b>
                    {s.label}
                    <i style={{ transform: `scaleX(${fill})`, ['--fill' as string]: fill } as CSSProperties} />
                  </span>
                  <div className="lw-flow-copy">
                    <div>
                      <h3>{s.title}</h3>
                      <p>{s.desc}</p>
                    </div>
                  </div>
                </li>
              )
            })}
          </ol>
        </div>
        <div className="lw-flow-right">
        {/* 11/18: 단계 설명은 왼쪽 목록이 아니라 화면 바로 위에 — 넘어갈 때마다 같이 바뀌어요 */}
        {FLOW_SIDE_LIST && (
          <div className="lw-flow-cap" key={`cap-${step.key}`} aria-live="polite">
            <h3>{step.title}</h3>
            <p>{step.desc}</p>
          </div>
        )}
        <div className="lw-flow-slider">
          {prev !== null && prev !== index && (
            <div className={`lw-flow-stage is-leave is-${STEPS[prev].key} ${STEPS[prev].key === 'material' ? 'v-material-light' : ''}`} key={`out-${STEPS[prev].key}`} aria-hidden="true">
              <StoryCanvas step={STEPS[prev].key} progress={1} />
            </div>
          )}
          <div className={`lw-flow-stage is-${step.key} ${step.key === 'material' ? 'v-material-light' : ''} ${prev !== null ? 'is-enter' : ''}`} key={step.key}>
            <StoryCanvas step={step.key} progress={local} />
          </div>
        </div>
        </div>
      </div>
    </section>
  )
}

function StoryCanvas({ step, progress }: { step: string; progress: number }) {
  if (USE_STUDENT_PREVIEW) return <StudentPreview step={step} progress={progress} />
  if (step === 'material') return <MaterialDemo progress={progress} />
  if (step === 'quiz')
    return (
      <div className="v-app solo">
        <div className="v-app-canvas quiz-demo-canvas">
          <QuizDemo progress={progress} />
        </div>
      </div>
    )
  return (
    <div className="v-app solo big">
      <div className="v-app-canvas fit-canvas">
        {step === 'code' ? <PracticeDemo progress={progress} /> : step === 'chat' ? <ChatDemo progress={progress} /> : <StatsDemo />}
      </div>
    </div>
  )
}
