/**
 * [랜딩 그림] '자료' 단계 데모 — 강의 자료 → 과목 펼치기 → 1주차 자료 → 숏폼 영상 목록 → 영상 하나 고르기
 * - 스크롤(progress 0~1)을 12개 장면(phase)으로 나눠요. 가짜 마우스 커서가 장면마다 다음에 누를 곳으로 움직여요.
 * - 두 가지 모드가 있어요:
 *     · 자동(기본): 장면 번호(phase)만으로 무엇이 펼쳐져 있는지 정해요.
 *     · 직접 보기(manual): 방문자가 버튼을 직접 누르면 그때부터는 누른 대로 보여줘요. 다시 스크롤하면 자동으로 돌아와요.
 *   '움직임 줄이기' 설정(still)이면 처음부터 직접 보기처럼 동작해요.
 * - 교수님 사진: ProfessorPhoto.tsx (public/professor-images.png)
 * - 스타일: styles/landing.css 의 .v-material-* · .v-md-*
 */
import { type CSSProperties, useEffect, useLayoutEffect, useRef, useState } from 'react'
import ProfessorPhoto from './ProfessorPhoto'
import { IconPlay } from './Icons'

// [임시 데이터] 랜딩 소개용 숏폼 제목과 길이 (실제 강의 데이터와 연결되지 않아요)
const DEMO_PARTS = [
  { title: '버블 정렬', time: '1:12' },
  { title: '선택 정렬', time: '1:05' },
  { title: '삽입 정렬', time: '1:24' },
  { title: '병합 정렬', time: '1:48' },
  { title: '퀵 정렬', time: '1:40' },
  { title: '시간 복잡도 비교', time: '2:00' },
]

// [임시 데이터] 랜딩 소개용 과목 · 주차 목록
const COURSES = ['자료구조', '알고리즘'] as const
const WEEKS = [1, 2, 3, 4, 5]
const DEMO_PICK = 4
// 시작 → 자료 클릭 → 과목으로 → 과목 클릭 → 1주차로 → 클릭 → 영상 카드로 → 카드 클릭 → 숏폼 목록 → 숏폼으로 → 강조 → 선택
const PHASE_COUNT = 12
type Selection = { course: string; week: number }

export default function MaterialDemo({ progress }: { progress: number }) {
  const timeline = Math.min(PHASE_COUNT, Math.max(0, progress * PHASE_COUNT))
  const phase = Math.min(PHASE_COUNT - 1, Math.floor(timeline))
  const waveProgress = Math.min(1, Math.max(0, timeline - 8))
  // 커서가 찾아갈 버튼들 (장면마다 이 중 하나의 실제 위치를 재서 커서를 옮겨요)
  const rootRef = useRef<HTMLDivElement>(null)
  const materialsRef = useRef<HTMLButtonElement>(null)
  const courseRef = useRef<HTMLButtonElement>(null)
  const weekRef = useRef<HTMLButtonElement>(null)
  const playRef = useRef<HTMLSpanElement>(null)
  const pickPlayRef = useRef<HTMLSpanElement>(null)
  const cursorRef = useRef<HTMLSpanElement>(null)
  const [manual, setManual] = useState(false)
  const [materialsOpen, setMaterialsOpen] = useState(true)
  const [openCourses, setOpenCourses] = useState<string[]>(['자료구조'])
  const [shortsOpen, setShortsOpen] = useState(false)
  const [selection, setSelection] = useState<Selection | null>(null)
  const [still] = useState(() => window.matchMedia('(prefers-reduced-motion: reduce)').matches)
  const browsing = manual || still
  // 아래 네 값이 화면에 그려지는 상태예요 — 직접 보기면 방문자가 누른 값, 자동이면 장면 번호로 계산한 값
  const expanded = browsing ? materialsOpen : phase >= 2
  const opened = browsing ? openCourses : phase >= 4 ? ['자료구조'] : []
  const selected = browsing ? selection : phase >= 6 ? { course: '자료구조', week: 1 } : null
  const grid = !!selected && (browsing ? shortsOpen : phase >= 8)
  const hover = !browsing && phase >= 10

  // 직접 눌러 살펴본 뒤 다시 스크롤하면 스크롤 위치에 맞는 장면으로 복귀해요.
  useEffect(() => {
    if (!manual) return
    const resume = () => setManual(false)
    window.addEventListener('scroll', resume, { passive: true })
    return () => window.removeEventListener('scroll', resume)
  }, [manual])

  useLayoutEffect(() => {
    if (browsing) return
    const root = rootRef.current
    const cursor = cursorRef.current
    if (!root || !cursor) return
    const place = () => {
      const target = phase < 2 ? materialsRef.current : phase < 4 ? courseRef.current : phase < 6 ? weekRef.current : phase <= 8 ? playRef.current : pickPlayRef.current
      if (!target) return
      const box = root.getBoundingClientRect()
      const rect = target.getBoundingClientRect()
      // 화면 전체가 축소된 경우에도 패널 안 좌표로 환산해요.
      const scaleX = root.offsetWidth / box.width
      const scaleY = root.offsetHeight / box.height
      const dx = 0.5
      const dy = 0.5
      cursor.style.transform = `translate(${(rect.left - box.left + rect.width * dx) * scaleX}px, ${(rect.top - box.top + rect.height * dy) * scaleY}px)`
    }
    // CSS 이동/축소 중에도 실제 버튼 위치를 추적해요. ResizeObserver는 위치 이동을 감지하지 못해요.
    let frame = 0
    const track = () => {
      place()
      frame = requestAnimationFrame(track)
    }
    track()
    return () => cancelAnimationFrame(frame)
  }, [phase, browsing])

  // 방문자가 처음 누르는 순간: 지금 자동으로 보이던 상태를 그대로 넘겨받아 직접 보기로 바꿔요 (화면이 튀지 않게)
  const takeControl = () => {
    if (!browsing) {
      setMaterialsOpen(expanded)
      setOpenCourses(opened)
      setSelection(selected)
      setShortsOpen(grid)
    }
    setManual(true)
  }

  return (
    <div ref={rootRef} className={`v-app v-material-demo ${grid ? 'shorts-open' : ''}`}>
      {!grid && <aside className="v-app-panel v-material-panel" aria-label="강의 자료 탐색">
        <button ref={materialsRef} className="v-material-heading" aria-expanded={expanded}
          onClick={() => { takeControl(); setMaterialsOpen(!expanded) }}>
          <span>강의 자료</span><span aria-hidden="true">{expanded ? '−' : '+'}</span>
        </button>
        {expanded && COURSES.map((course, index) => {
          const open = opened.includes(course)
          return <div className="v-material-course" key={course}>
            <button ref={index === 0 ? courseRef : undefined} className="v-material-toggle" aria-expanded={open}
              onClick={() => { takeControl(); setOpenCourses(open ? opened.filter(c => c !== course) : [...opened, course]) }}>
              <span aria-hidden="true" className={open ? 'expanded' : ''}>›</span>{course}
            </button>
            {open && <div className="v-material-weeks">
              {WEEKS.map(week => <button key={week} ref={index === 0 && week === 1 ? weekRef : undefined}
                className={`v-material-week ${selected?.course === course && selected.week === week ? 'selected' : ''}`}
                aria-pressed={selected?.course === course && selected.week === week}
                onClick={() => { takeControl(); setSelection({ course, week }); setShortsOpen(false) }}>
                <span aria-hidden="true">▤</span>{week}주차 강의 자료
              </button>)}
              <span className="v-material-more" role="img" aria-label="다음 주차 강의 자료가 더 있어요"><span className="v-material-more-width" aria-hidden="true">5주차 강의 자료</span><span aria-hidden="true">⋮</span></span>
            </div>}
          </div>
        })}
        {browsing && !still && <button className="v-material-replay" onClick={() => { setManual(false) }}>스크롤 흐름으로 돌아가기 ↕</button>}
      </aside>}
      <div className="v-app-canvas wide">
        <div className={`v-md ${grid ? 'grid' : ''} ${hover ? 'hover' : ''} ${!browsing && phase >= 11 ? 'picked' : ''} ${still ? 'still' : ''}`}>
          {!selected ? <div className="v-material-empty"><span aria-hidden="true">▤</span><strong>강의 자료로 시작하는 학습</strong><p>과목을 펼치고 주차별 강의 자료를 선택하세요.</p></div> : <>
            <button className={`v-md-card ${!browsing && phase === 7 ? 'press' : ''}`}
              aria-label={`${selected.week}주차 AI 강의 열기`} tabIndex={grid ? -1 : 0}
              aria-hidden={grid} disabled={grid}
              onClick={() => { takeControl(); setShortsOpen(true) }}>
              <span className="v-md-card-tag">{selected.course} · {selected.week}주차</span>
              <strong>{selected.week}주차 AI 강의</strong>
              <span className="v-md-card-board">
                <i className="w80" /><i className="w60 hl" /><i className="w90" /><i className="w70 hl" />
                <span ref={playRef} className="v-md-card-play" aria-hidden="true"><IconPlay /></span>
                <span className="v-md-card-prof"><ProfessorPhoto size={88} /></span>
              </span>
              <span className="v-md-card-foot"><b><IconPlay /></b> 파트별 영상 {DEMO_PARTS.length}개 · 예시 영상</span>
            </button>
            <div className="v-md-grid" aria-label={`${selected.course} ${selected.week}주차 AI 강의 예시`}>
              {DEMO_PARTS.map((part, index) => <div key={part.title}
                className={`v-md-cell ${index === DEMO_PICK ? 'pick' : ''}`}
                style={{ '--wave-delay': `${index * 110}ms`, ...(!browsing ? { animationPlayState: 'paused', animationDelay: `${index * 110 - waveProgress * 1900}ms` } : {}) } as CSSProperties}>
                <span className="v-md-cell-no">{index + 1}</span><span className="v-md-cell-title">{part.title}</span>
                <span className="v-md-cell-prof"><ProfessorPhoto size={44} /></span>
                <span className="v-md-cell-time">{part.time}</span>
                {index === DEMO_PICK && <span ref={pickPlayRef} className="v-md-cell-play"><IconPlay /></span>}
              </div>)}
            </div>
          </>}
        </div>
      </div>
      {grid && <button className="v-material-back" onClick={() => {
        takeControl(); setShortsOpen(false)
      }}>← 강의 자료 목록</button>}
      {!browsing && <span ref={cursorRef} aria-hidden="true" className={`v-md-cursor ${[1, 3, 5, 7, 11].includes(phase) ? 'press' : ''}`}>
        <svg width="33" height="33" viewBox="0 0 44 44"><path d="M40 4 L4 19 L19 25 L25 40 Z" fill="none" stroke="#fff" strokeWidth="3.2" strokeLinejoin="round" /></svg><i />
      </span>}
    </div>
  )
}
