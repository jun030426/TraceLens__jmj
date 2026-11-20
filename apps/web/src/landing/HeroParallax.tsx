/**
 * [랜딩 ① 첫 화면] 강의자료 패럴랙스 — Aceternity UI 의 Hero Parallax 를 Lerny 에 맞게 옮겼어요.
 * - 처음: 교수님의 강의자료 10쪽이 두 줄로 비스듬히 누워 있어요 (rotateX 15° 는 원본 그대로, rotateZ 는 원본과 반대로 -20° · 흐릿하게 0.2).
 * - 가만히 있을 때: 두 줄이 서로 반대 방향으로 천천히 좌우로 오가요 (DRIFT_S · DRIFT_PX).
 * - 스크롤 ①: 누운 자료가 일어서며 또렷해지고, 줄마다 반대 방향으로 미끄러지며 자료를 보여 줘요.
 * - 스크롤 ②: 10쪽이 가운데로 모여 한 묶음으로 겹쳐져요.
 * - 스크롤 ③: 묶음이 작아지며 아래로 내려가 다음 칸(하루의 학습)으로 이어져요.
 * - 원본과 다른 점 (이 프로젝트에 Tailwind 가 없고, 요청하신 '하나로 합쳐져 내려가는' 흐름 때문에):
 *   · Tailwind 클래스 대신 같은 값의 CSS 를 landing/lerny-hero-parallax.css 에 썼어요 (.hp-*).
 *   · 원본은 화면과 함께 흘러가지만, 여기선 장면이 화면에 붙어 있고(sticky) 그 안에서 움직여요 (모이는 모습을 끝까지 보여 주려고).
 *   · 원본은 줄이 양옆으로 1000px 씩 멀어지기만 하는데, 여기선 조금 미끄러진 뒤 가운데로 모여 겹치고 내려가요.
 *   · 카드 그림(썸네일 이미지) 대신 강의자료 한 쪽을 화면으로 그려요. 외부 사이트 링크도 없어서 <a> 대신 <div> 예요.
 *   · 움직임 줄이기 설정이면 기울기 · 스크롤 움직임 없이 자료를 반듯하게 펼쳐 둬요 (원본에는 이 처리가 없어요).
 *   · 스프링 값(stiffness 300 · damping 30 · bounce 100)과 hover 때 20px 떠오르는 것은 원본 그대로예요.
 */

import { useRef, type CSSProperties } from 'react'
import { motion, useAnimationFrame, useMotionValue, useMotionValueEvent, useReducedMotion, useScroll, useSpring, useTransform, type MotionValue } from 'motion/react'
import MacScene from './MacScene' // 맥북 장면 (원래 랜딩 맨 아래) — 여기선 embedded 로 넣어요
import './lerny-hero-parallax.css'

export type LectureSlide = {
  title: string // 카드 아래 hover 때 보이는 이름 (원본의 product.title)
  week: string
  heading: string
  lines: string[] // 본문 문장 (임시로 채운 강의 내용)
  code?: string
  chips?: string[]
  tone?: number // 0~3 자료마다 바탕 띠 색
}

export const LECTURE_SLIDES: LectureSlide[] = [
  { title: '1주차 · 변수와 자료형', week: '1주차', heading: '변수와 자료형', lines: ['변수는 값을 담아 두는 이름표예요.', 'int · float · str · bool 네 가지 기본 자료형', 'type()으로 값의 자료형을 확인해요.'], code: 'age = 20\nname = "Lerny"', tone: 0 },
  { title: '2주차 · 조건문', week: '2주차', heading: '조건문 if · elif · else', lines: ['조건이 참일 때만 블록을 실행해요.', 'elif는 앞 조건이 거짓일 때 차례로 검사해요.'], code: 'if score >= 90:\n    grade = "A"', tone: 1 },
  { title: '3주차 · 반복문', week: '3주차', heading: '반복문 for · while', lines: ['for는 정해진 범위를, while은 조건이 참인 동안 반복해요.', 'break로 반복을 멈추고, continue로 건너뛰어요.', '무한 루프에 빠지지 않게 종료 조건을 확인해요.'], chips: ['range()', 'break'], tone: 2 },
  { title: '4주차 · 리스트', week: '4주차', heading: '리스트와 인덱스', lines: ['여러 값을 순서대로 담는 자료형이에요.', '인덱스는 0부터 시작하고, -1은 마지막 원소예요.'], code: 'nums = [3, 1, 4]\nnums.append(1)', tone: 3 },
  { title: '5주차 · 딕셔너리', week: '5주차', heading: '딕셔너리', lines: ['키와 값을 한 쌍으로 저장해요.', '키로 값을 바로 찾아서 탐색이 빨라요.', '같은 키를 다시 넣으면 값이 덮어써져요.'], chips: ['key', 'value'], tone: 0 },
  { title: '6주차 · 함수', week: '6주차', heading: '함수 만들기', lines: ['def로 함수를 정의하고, return으로 값을 돌려줘요.', '매개변수로 받은 값은 함수 안에서만 쓰여요.'], code: 'def add(a, b):\n    return a + b', tone: 1 },
  { title: '7주차 · 재귀', week: '7주차', heading: '재귀 함수', lines: ['함수가 자기 자신을 다시 호출해요.', '기저 조건이 없으면 호출이 끝나지 않아요.', '호출할 때마다 호출 스택이 한 칸씩 쌓여요.'], chips: ['기저 조건', '호출 스택'], tone: 2 },
  { title: '8주차 · 중간 정리', week: '8주차', heading: '중간고사 범위 정리', lines: ['1~7주차: 자료형, 조건문, 반복문, 함수, 재귀', '코드 실행 결과 예측 문제가 출제돼요.', '리스트 · 딕셔너리 메서드를 꼭 복습하세요.', '재귀 함수는 호출 순서를 직접 따라가 보세요.'], tone: 3 },
  { title: '9주차 · 연결 리스트', week: '9주차', heading: '연결 리스트', lines: ['노드가 값과 다음 노드의 주소를 가져요.', '중간 삽입 · 삭제가 빠르지만 탐색은 처음부터 해야 해요.'], chips: ['탐색 O(n)', '삽입 O(1)'], tone: 0 },
  { title: '10주차 · 스택과 큐', week: '10주차', heading: '스택과 큐', lines: ['스택은 나중에 넣은 것을 먼저 꺼내요 (LIFO).', '큐는 먼저 넣은 것을 먼저 꺼내요 (FIFO).', '괄호 검사는 스택, 대기열은 큐로 풀어요.'], code: 'stack.append(x)\nstack.pop()', tone: 1 },
  { title: '11주차 · 정렬', week: '11주차', heading: '정렬 알고리즘', lines: ['버블 정렬은 이웃한 두 값을 비교해 바꿔요.', '병합 · 퀵 정렬은 평균 O(n log n)이에요.'], chips: ['버블', '병합', '퀵'], tone: 2 },
  { title: '12주차 · 탐색', week: '12주차', heading: '이진 탐색', lines: ['정렬된 리스트에서 가운데 값과 비교해요.', '찾는 범위가 매번 절반으로 줄어요.', '시간 복잡도는 O(log n)이에요.'], code: 'mid = (lo + hi) // 2', tone: 3 },
  { title: '13주차 · 클래스', week: '13주차', heading: '클래스와 객체', lines: ['클래스는 설계도, 객체는 그 설계도로 만든 실체예요.', '__init__에서 객체의 속성을 정해요.'], code: 'class Student:\n    pass', tone: 0 },
  { title: '14주차 · 예외 처리', week: '14주차', heading: '예외 처리', lines: ['실행 중 오류가 나도 프로그램이 멈추지 않게 해요.', 'try 블록에서 난 오류를 except가 받아요.', 'finally는 오류와 상관없이 항상 실행돼요.'], chips: ['try', 'except'], tone: 1 },
  { title: '15주차 · 기말 정리', week: '15주차', heading: '기말고사 범위 정리', lines: ['9~14주차: 연결 리스트, 스택 · 큐, 정렬, 탐색', '알고리즘의 시간 복잡도를 비교하는 문제', '클래스로 자료구조를 직접 구현해 보세요.', '예외 처리 코드의 실행 순서를 확인하세요.'], tone: 2 },
]

// 카드 크기 (원본 h-96 w-[30rem]) 와 간격 (space-x-20 · mb-20) — 가운데로 모일 때 얼마나 움직일지 계산해요
const CARD_W = 480
const CARD_H = 384
const GAP = 80
const MAC_FROM = 0.46 // 첫 화면 스크롤 중 이 지점부터 맥북 장면이 움직여요 (자료가 네모 속으로 다 들어간 뒤)
// 맥북 장면은 화면 속 확대가 끝나는 지점 → 첫 화면 끝(1)에서 딱 끝나도록 맞춘 값 (빈 화면으로 스크롤하는 구간이 없게)
// 11/18: 확대가 첫 화면 끝(1)에서 딱 끝나요. 다음 칸(하루의 학습)은 이 장면 바로 밑에 겹쳐 있다가(CSS margin-bottom: -100vh)
//   확대가 끝나는 순간 장면이 사라지며 그 자리에 바로 나타나요 → 화면 속으로 들어간 뒤 스크롤이 더 필요 없어요
const MAC_TO = MAC_FROM + (1 - MAC_FROM) / 0.42
// 11/18 (2): 맥북 장면은 랜딩 아래 원래 자리로 돌려보내고, 첫 화면 끝에는 '학생의 배움과 교수자의 수업을 잇다'(ConnectFlow)가 와요.
//   모인 강의자료는 아래 가운데(Lerny 로고 자리)로 작아지며 내려가고, 장면이 걷히면 밑에 겹쳐 있던 연결 섹션이 나타나요.
//   true 로 바꾸면 예전처럼 맥북 화면 속으로 들어가요 (CSS 의 .hp-root 높이도 250vh 로)
const MAC_IN_HERO = false
const DRIFT_S = 18 // 좌우로 한 번 오가는 시간 (초) — 클수록 느려요
const DRIFT_PX = 120 // 좌우로 움직이는 폭 (px)

export const HeroParallax = ({ products = LECTURE_SLIDES }: { products?: LectureSlide[] }) => {
  // 11/18: 세 줄 → 두 줄 (한 줄에 5쪽, 카드는 더 크게)
  const firstRow = products.slice(0, 5)
  const secondRow = products.slice(5, 10)
  const ref = useRef<HTMLDivElement>(null)
  const reduce = useReducedMotion()
  const { scrollYProgress } = useScroll({ target: ref, offset: ['start start', 'end end'] })

  const springConfig = { stiffness: 300, damping: 30, bounce: 100 }
  // 11/18: 화면 약 0.5장 내리면 하나로 모이고 → 모인 묶음이 네모(맥북 화면 크기) 속으로 들어가요 →
  //   그 네모가 맥북이 되고 '흩어진 배움이, 하나의 이해로.' → 더 내리면 맥북 화면 속으로 확대돼 다음 칸으로 (높이 350vh)
  //   맥북 부분은 원래 랜딩 맨 아래에 있던 MacScene 을 그대로 써요 (MAC_FROM 부터).
  // 구간: 일어서기(stand) · 모이기(merge) · 네모 속으로(enter). 움직임 줄이기면 모두 '펼쳐진 상태'로 고정
  const still1 = useMotionValue(1)
  const still0 = useMotionValue(0)
  const standS = useSpring(useTransform(scrollYProgress, MAC_IN_HERO ? [0, 0.1] : [0, 0.14], [0, 1]), springConfig)
  const slideS = useSpring(useTransform(scrollYProgress, MAC_IN_HERO ? [0, 0.13] : [0, 0.18], [0, 1]), springConfig)
  const mergeS = useSpring(useTransform(scrollYProgress, [0.1, 0.33], [0, 1]), springConfig)
  const macInS = useSpring(useTransform(scrollYProgress, [0.33, 0.48], [0, 1]), springConfig)
  const enterS = useSpring(useTransform(scrollYProgress, [0.33, 0.48], [0, 1]), springConfig)
  // 맥북 없이 (첫 화면 높이 150vh → 스크롤 약 0.5장): 0.25장쯤에서 모이고(merge 0.06 → 0.48),
  //   이어서 위로 날아가 '학생의 배움과 교수자의 수업을 잇다.' 제목 속으로 빨려 들어가요(drop 0.48 → 0.92)
  const mergeLS = useSpring(useTransform(scrollYProgress, [0.06, 0.48], [0, 1]), springConfig)
  const dropS = useSpring(useTransform(scrollYProgress, [0.48, 0.92], [0, 1]), springConfig)
  // 11/18: 가만히 있을 때도 두 줄이 서로 반대로 천천히 좌우로 오가요 (한 번 오가는 데 DRIFT_S 초, 폭 DRIFT_PX).
  // 가운데로 모이기 시작하면 줄어들어 멈춰요. 움직임 줄이기 설정이면 움직이지 않아요
  const drift = useMotionValue(0)
  useAnimationFrame((t) => {
    if (!reduce) drift.set(Math.sin((t / 1000) * ((2 * Math.PI) / DRIFT_S)))
  })
  const stand = reduce ? still1 : standS
  const slide = reduce ? still0 : slideS
  const merge = reduce ? still0 : MAC_IN_HERO ? mergeS : mergeLS
  const drop = reduce ? still0 : dropS
  const macIn = reduce ? still1 : macInS
  const enter = reduce ? still0 : enterS

  // 원본 값: rotateX 15 → 0, rotateZ 20 → 0, opacity 0.2 → 1
  const rotateX = useTransform(stand, (v) => 15 * (1 - v))
  // 11/18: 원본(20°, 왼쪽 위 → 오른쪽 아래)과 반대로 -20° — 오른쪽 위에서 왼쪽 아래로 누워요
  const rotateZ = useTransform(stand, (v) => -20 * (1 - v))
  const opacity = useTransform([stand, enter, drop], ([s, e, d]: number[]) =>
    MAC_IN_HERO ? (0.2 + 0.8 * s) * (1 - Math.max(0, e - 0.45) / 0.55) : (0.2 + 0.8 * s) * (1 - Math.max(0, d - 0.78) / 0.22),
  )
  // 위아래: 처음엔 제목 아래 조금 내려가 있다가 → 가운데로 모임 → 화면 가운데(네모 속)로 올라가요
  const translateY = useTransform([stand, enter, drop], ([s, e, d]: number[]) =>
    MAC_IN_HERO ? `calc(${(1 - s) * 18}vh - ${e * 20}vh)` : `calc(${(1 - s) * 18}vh - ${d * 37}vh)`,
  )
  const scale = useTransform([merge, enter, drop], ([m, e, d]: number[]) => (1 - 0.42 * m) * (MAC_IN_HERO ? 1 - 0.75 * e : 1 - 0.88 * d))
  // 맥북 장면: 자료가 모일 무렵 바로 맥북으로 나타나요 (11/18 네모 단계 없앰)
  const macOpacity = useTransform(macIn, (v) => v)
  // 제목은 자료가 일어서는 동안 위로 사라져요. scrollYProgress 를 바로 쓰면 motion 이 브라우저 스크롤 타임라인으로 넘겨
  // 이 영역이 아닌 페이지 전체 기준으로 움직여서, 스프링 값(standS)에서 이끌어 와요
  const headOpacity = useTransform(standS, (v) => (reduce ? 1 : 1 - Math.min(1, v / 0.7)))
  const headY = useTransform(standS, (v) => (reduce ? 0 : -60 * Math.min(1, v / 0.7)))

  // 확대가 끝나면(첫 화면 맨 끝) 장면을 걷어 내서 밑에 있던 다음 칸이 바로 보여요.
  // (함수형 변환이라 브라우저 스크롤 타임라인으로 넘어가지 않아요)
  const stageOpacity = useTransform(scrollYProgress, (v) =>
    MAC_IN_HERO ? (v > 0.86 ? Math.max(0, (0.96 - v) / 0.1) : 1) : v > 0.72 ? Math.max(0, (0.94 - v) / 0.22) : 1,
  )
  const stageEvents = useTransform(stageOpacity, (o) => (o < 0.05 ? 'none' : 'auto'))
  // 바로 아래 칸(연결 섹션)에 --hp-in(0 → 1)을 넘겨요: 자료가 날아드는 동안 제목이 살짝 커지며 빛나요 (lerny-hero-parallax.css)
  useMotionValueEvent(scrollYProgress, 'change', (v) => {
    const next = ref.current?.nextElementSibling as HTMLElement | null
    if (!next || MAC_IN_HERO) return
    const t = Math.min(1, Math.max(0, (v - 0.7) / 0.28))
    next.style.setProperty('--hp-in', reduce ? '1' : t.toFixed(3))
  })

  return (
    <div ref={ref} className={`hp-root ${reduce ? 'is-still' : ''}`}>
      <motion.div className="hp-stage" style={{ opacity: stageOpacity, pointerEvents: stageEvents }}>
        <motion.div style={{ opacity: headOpacity, y: headY }}>
          <Header />
        </motion.div>
        {/* 네모 → 맥북 → 화면 속으로 (MacScene.tsx 를 embedded 로) — 모인 강의자료가 이 네모 속으로 들어가요 */}
        {MAC_IN_HERO && (
          <motion.div className="hp-mac" style={{ opacity: macOpacity }}>
            <MacScene embedded trackRef={ref} range={[MAC_FROM, MAC_TO]} />
          </motion.div>
        )}
        <div className="hp-fit">
          <motion.div className="hp-group" style={{ rotateX, rotateZ, y: translateY, opacity, scale }}>
            <div className="hp-row hp-reverse">
              {firstRow.map((p, i) => (
                <ProductCard key={p.title} product={p} row={0} col={i} reverse dir={1} slide={slide} merge={merge} drift={drift} />
              ))}
            </div>
            <div className="hp-row">
              {secondRow.map((p, i) => (
                <ProductCard key={p.title} product={p} row={1} col={i} dir={-1} slide={slide} merge={merge} drift={drift} />
              ))}
            </div>
          </motion.div>
        </div>
      </motion.div>
    </div>
  )
}

export const Header = () => {
  return (
    <div className="hp-header">
      <span className="hp-eyebrow">
        교수님 강의 자료로 만드는 복습
      </span>
      <h1>
        교수님의 강의 자료가
        <br />
        <span className="hp-g">하나의 복습으로 모여요</span>
      </h1>
      <p>흩어진 주차별 자료를 Lerny가 한데 모아, 오늘 풀 문제와 AI 강의로 이어 드려요.</p>
    </div>
  )
}

export const ProductCard = ({
  product,
  row,
  col,
  reverse = false,
  dir,
  slide,
  merge,
  drift,
}: {
  product: LectureSlide
  row: number
  col: number
  reverse?: boolean
  dir: 1 | -1
  slide: MotionValue<number>
  merge: MotionValue<number>
  drift: MotionValue<number>
}) => {
  // 이 카드가 줄 가운데에서 떨어진 거리 (flex-row-reverse 줄은 순서가 뒤집혀요)
  const pos = reverse ? 2 - col : col - 2
  const offsetX = pos * (CARD_W + GAP)
  const offsetY = (row - 0.5) * (CARD_H + GAP) // 두 줄: 가운데에서 반 줄씩 위아래
  // 겹친 묶음이 조금씩 어긋나 보이도록 카드마다 다른 작은 기울기
  const tilt = (((row * 5 + col) * 7) % 11) - 5
  const x = useTransform([slide, merge, drift], ([s, m, d]: number[]) => dir * (260 * s + DRIFT_PX * d) * (1 - m) - offsetX * m)
  const y = useTransform(merge, (m) => -offsetY * m)
  const rotate = useTransform(merge, (m) => tilt * 1.2 * m)

  return (
    <motion.div style={{ x, y, rotate }} className="hp-card-slot">
      <motion.div whileHover={{ y: -20 }} className="hp-card" style={{ zIndex: row * 5 + col } as CSSProperties}>
        <div className={`hp-page tone-${product.tone ?? 0}`}>
          <div className="hp-page-top">
            <span>자료구조와 파이썬</span>
            <span>{product.week}</span>
          </div>
          <h3>{product.heading}</h3>
          <div className="hp-page-body">
            {product.lines.map((t) => (
              <p key={t}>{t}</p>
            ))}
          </div>
          {product.code && <pre>{product.code}</pre>}
          {product.chips && (
            <div className="hp-chips">
              {product.chips.map((c) => (
                <span key={c}>{c}</span>
              ))}
            </div>
          )}
          <span className="hp-page-no">교수자 강의자료</span>
        </div>
        <div className="hp-shade" />
        <h2 className="hp-card-title">{product.title}</h2>
      </motion.div>
    </motion.div>
  )
}

export default HeroParallax
