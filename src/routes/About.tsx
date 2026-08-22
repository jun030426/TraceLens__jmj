import { ROUTES } from '../router'
import { Link } from '../ui/Link'

const STAGES: [string, string][] = [
  ['Tracer', '브라우저 안에서 코드를 실제로 실행하고, 줄 경계마다 상태를 비교해 사건으로 남깁니다.'],
  ['Digest', '수천 개 사건을 읽을 수 있는 분량으로 접습니다. 지루한 반복은 접고, 특별한 회차는 살립니다.'],
  ['Director', '무엇을 어떤 순서로 보여줄지 고릅니다. 값은 만들지 못하고, 이미 있는 구간을 고르기만 합니다.'],
  ['Player', '고른 대본을 타임라인으로 조립해 재생합니다. 멈추면 그 시점의 상태를 그대로 보여줍니다.'],
]

const MEASURED: [string, string, string][] = [
  ['파이프라인 완주율', '18 / 18', '유형별 층화 샘플 18개 전부 재생까지 도달'],
  ['Tracer 정확성', '18 / 18', '기록된 출력과 실제 실행 출력이 일치'],
  ['Digest 압축률', '평균 53%', '38~67% · 소형 샘플 기준'],
  ['대본 검증 통과율', '6 / 6', 'Gemini 2.5 Flash · 표본이 작습니다'],
]

const HONEST: [string, string][] = [
  ['지원하지 않는 것을 지원하는 척하지 않는다', '범위 밖 코드는 벤치마크 샘플에서도 뺍니다. 평균을 좋게 만들려고 어려운 걸 빼지 않습니다.'],
  ['“보안 문제를 없앴다”고 말하지 않는다', '코드를 서버에서 직접 실행하지 않으니 서버 측 위험과 비용이 크게 줍니다. 그 이상은 주장하지 않습니다.'],
  ['표본이 작으면 “증명했다”고 하지 않는다', '지금 수치는 소형 샘플 기준입니다. 경향을 관찰했다고 씁니다.'],
  ['근거 없는 숫자를 목표로 쓰지 않는다', '지연 시간 합격 기준은 실측 전까지 비워둡니다.'],
]

export default function About() {
  return (
    <main>
      <section className="tl-shell tl-lead">
        <h1 className="tl-h1">실행이 먼저다</h1>
        <p className="tl-lede" style={{ marginTop: 14 }}>
          무슨 일이 일어났는가는 실행이 결정하고, 그중 무엇을 어떻게 보여줄지는 AI가 결정합니다. 이 순서를 뒤집지
          않는 것이 TraceLens의 전부입니다.
        </p>
      </section>

      <section className="tl-shell tl-section">
        <div className="tl-head">
          <h2 className="tl-h2">네 단계를 지납니다</h2>
          <p className="tl-body">각 단계는 정해진 계약으로만 옆 단계와 이야기합니다. 내부를 바꿔도 옆이 깨지지 않습니다.</p>
        </div>
        <ol className="tl-pipeline">
          {STAGES.map(([key, body], i) => (
            <li key={key}>
              <div className="tl-pipeline__head">
                <span className="tl-num tl-pipeline__n">{i + 1}</span>
                <h3 className="tl-h3 tl-mono">{key}</h3>
              </div>
              <p className="tl-body">{body}</p>
            </li>
          ))}
        </ol>
        <p className="tl-note" style={{ marginTop: 20 }}>
          실행과 재생은 전부 브라우저 안에서 일어납니다. 연출을 만들 때만 코드와 요약본이 외부 모델로 전송되고, 그것도{' '}
          <Link to={ROUTES.settings} className="tl-link">
            설정에서 끌 수 있습니다
          </Link>
          .
        </p>
      </section>

      <section className="tl-shell tl-section">
        <div className="tl-split">
          <div className="tl-head">
            <h2 className="tl-h2">AI가 없어도 끝까지 갑니다</h2>
            <p className="tl-body">
              값을 만들고 순서를 정하는 일은 실행이 합니다. AI는 그중 무엇을 강조할지 고르는 층에만 있습니다. 모델
              호출이 실패하거나 검증을 통과하지 못하면 규칙 기반 대본으로 자동으로 넘어가고, 재생은 그대로
              이어집니다.
            </p>
            <p className="tl-body" style={{ marginTop: 12 }}>
              그래서 AI는 이 제품이 성립하기 위한 조건이 아니라, 설명의 품질을 올리는 층입니다.
            </p>
          </div>
          <div className="tl-panel">
            <div className="tl-panel__bar">
              <span className="tl-label">지금 상태</span>
            </div>
            <div className="tl-panel__body tl-stack">
              <div>
                <span className="tl-tag">Slice 1 완주</span>
                <p className="tl-note" style={{ marginTop: 8 }}>
                  실제 실행에서 자동 재생까지, AI 없이 통과
                </p>
              </div>
              <div>
                <span className="tl-tag">Slice 2 진행 중</span>
                <p className="tl-note" style={{ marginTop: 8 }}>
                  LLM 연출이 기본 경로이고, 실패하면 규칙 대본으로 폴백
                </p>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section className="tl-shell tl-section">
        <div className="tl-head">
          <h2 className="tl-h2">지금까지 잰 것</h2>
        </div>
        <div className="tl-scroll" style={{ marginTop: 20 }}>
          <table className="tl-table">
            <thead>
              <tr>
                <th>지표</th>
                <th>결과</th>
                <th>단서</th>
              </tr>
            </thead>
            <tbody>
              {MEASURED.map(([k, v, note]) => (
                <tr key={k}>
                  <td>{k}</td>
                  <td className="tl-num">{v}</td>
                  <td>{note}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="tl-note" style={{ marginTop: 14, maxWidth: '62ch' }}>
          전부 로컬 CPython 트레이스 기준입니다. 브라우저에서의 실제 지연 시간과, AI 연출이 규칙 연출보다 정말 더
          나은지를 비교하는 실험은 아직 하지 않았습니다.
        </p>
      </section>

      <section className="tl-shell tl-section">
        <div className="tl-head">
          <h2 className="tl-h2">지어내지 않기로 한 것들</h2>
        </div>
        <div className="tl-defs" style={{ marginTop: 24 }}>
          {HONEST.map(([rule, why]) => (
            <div className="tl-def" key={rule}>
              <h3 className="tl-h3">{rule}</h3>
              <p className="tl-body">{why}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="tl-shell tl-section tl-close">
        <div>
          <h2 className="tl-h2">직접 돌려보는 게 빠릅니다</h2>
          <p className="tl-body" style={{ marginTop: 8 }}>
            읽는 것보다 한 번 붙여넣어 보는 쪽이 이 도구를 더 정확히 설명합니다.
          </p>
        </div>
        <Link to={ROUTES.app} className="tl-btn tl-btn--lg">
          실행 화면으로
        </Link>
      </section>
    </main>
  )
}
