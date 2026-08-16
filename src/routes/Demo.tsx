import { useMemo, useState } from 'react'
import { Play, RotateCcw } from 'lucide-react'
import { buildStage } from '../film/buildStage'
import { layoutStage } from '../film/layout'
import { choreograph } from '../film/choreograph'
import WorldStage from '../film/WorldStage'
import { useFilm } from '../film/useFilm'
import { demos, PILOT_QUESTION, type Demo } from '../demo/demoSet'
import '../ui/app.css'
import './demo.css'

/* 파일럿 설문 화면.
   코드도 자막도 챕터명도 보여주지 않는다 — 영상만으로 메모리 진행 순서가
   읽히는지 확인하는 것이 목적이므로, 글자가 있으면 실험이 오염된다.
   코드는 답을 적은 뒤에만 펼쳐볼 수 있다. */
function Screening({ demo, onDone }: { demo: Demo; onDone: () => void }) {
  const { plan, layout, shots } = useMemo(() => {
    const p = buildStage(demo.fixture.events)
    return { plan: p, layout: layoutStage(p), shots: choreograph(demo.fixture.events, p, demo.fixture.code) }
  }, [demo])

  const film = useFilm(shots)
  const [revealed, setRevealed] = useState(false)
  const atEnd = film.index >= shots.length - 1

  return (
    <div className="dm-screening">
      <div className="dm-screen">
        <WorldStage plan={plan} layout={layout} shots={shots} film={film} />
      </div>

      <div className="dm-controls">
        {!film.playing && (
          <button type="button" className="dm-btn dm-btn--accent" onClick={film.play}>
            {atEnd ? <RotateCcw size={15} /> : <Play size={15} fill="currentColor" />}
            <span>{atEnd ? '다시 보기' : '재생'}</span>
          </button>
        )}
        {film.playing && (
          <button type="button" className="dm-btn" onClick={film.pause}>
            <span>일시정지</span>
          </button>
        )}
        <span className="dm-progress">{shots.length ? `${film.index + 1} / ${shots.length}` : '—'}</span>
      </div>

      <div className="dm-question">
        <p className="dm-question__text">{PILOT_QUESTION}</p>
        <p className="dm-question__hint">답을 적으신 뒤에 아래에서 코드를 확인해 주세요.</p>
      </div>

      <div className="dm-reveal">
        <button type="button" className="dm-btn" onClick={() => setRevealed(v => !v)}>
          <span>{revealed ? '코드 접기' : '코드 확인하기'}</span>
        </button>
        {revealed && <pre className="dm-code">{demo.fixture.code.trimEnd()}</pre>}
      </div>

      <button type="button" className="dm-btn dm-back" onClick={onDone}>
        <span>목록으로</span>
      </button>
    </div>
  )
}

export default function DemoRoute() {
  const [picked, setPicked] = useState<Demo | null>(null)

  if (picked) return <Screening key={picked.id} demo={picked} onDone={() => setPicked(null)} />

  return (
    <div className="dm">
      <header className="dm-head">
        <h1>영상 이해도 파일럿</h1>
        <p>
          각 영상은 파이썬 코드 한 편이 실행되면서 <strong>메모리에서 무엇이 어떤 순서로 일어났는지</strong>를
          기록한 것입니다. 설명 자막은 없습니다. 영상만 보고 순서를 읽어보세요.
        </p>
      </header>

      <ul className="dm-list">
        {demos.map(d => (
          <li key={d.id}>
            <button type="button" className="dm-card" onClick={() => setPicked(d)}>
              <span className="dm-card__label">{d.label}</span>
              <span className="dm-card__go">보기</span>
            </button>
          </li>
        ))}
      </ul>

      {demos.length === 0 && (
        <p className="dm-empty">
          데모 기록이 없습니다. <code>python scripts/gen_demo_fixtures.py</code>를 먼저 실행해 주세요.
        </p>
      )}
    </div>
  )
}
