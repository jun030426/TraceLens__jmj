import { ROUTES } from '../router'
import { Link } from '../ui/Link'
import TraceDiagram from '../ui/TraceDiagram'

const DIFFS: [string, string][] = [
  [
    '값은 실행에서만 나옵니다',
    '코드를 읽고 추측하지 않습니다. 브라우저 안에서 실제로 실행한 뒤 줄 경계마다 관측된 상태 변화만 기록해서 그립니다. 설명은 틀릴 수 있어도 값이 실행과 다를 수는 없습니다.',
  ],
  [
    '스텝을 직접 밟지 않아도 됩니다',
    '어디를 봐야 하는지 고르고, 중요한 순간은 느리게, 반복 구간은 접어서 자동으로 재생합니다. 디버거를 다룰 줄 몰라도 흐름이 먼저 보입니다.',
  ],
  [
    '멈추면 그 순간을 열어볼 수 있습니다',
    '녹화된 영상이 아니라 실시간으로 그리는 화면입니다. 멈춘 시점의 변수와 객체를 인스펙터로 열어볼 수 있고, 화면과 값이 어긋나지 않습니다.',
  ],
]

export default function Landing({ still }: { still: boolean }) {
  return (
    <main>
      <section className="tl-shell tl-hero">
        <div className="tl-hero__say">
          <h1 className="tl-h1">
            붙여넣기 전에
            <br />
            돌아가는 걸 봅니다
          </h1>
          <p className="tl-lede">
            AI가 준 파이썬 코드를 브라우저 안에서 실제로 실행하고, 그 실행이 남긴 기록만으로 자동 재생되는 설명
            화면을 만듭니다. 설치도 로그인도 없습니다.
          </p>
          <div className="tl-actions">
            <Link to={ROUTES.app} className="tl-btn tl-btn--lg">
              코드 붙여넣고 실행
            </Link>
            <Link to={ROUTES.about} className="tl-btn tl-btn--quiet tl-btn--lg">
              어떻게 동작하나
            </Link>
          </div>
          <p className="tl-note tl-hero__scope">
            표준 라이브러리 중심 · 단일 파일 · 동기 파이썬.{' '}
            <Link to={ROUTES.help} className="tl-link">
              어떤 코드가 되고 안 되는지
            </Link>{' '}
            먼저 확인할 수 있습니다.
          </p>
        </div>

        <TraceDiagram still={still} />
      </section>

      <section className="tl-shell tl-section">
        <div className="tl-head">
          <h2 className="tl-h2">텍스트 설명이 못 하는 것</h2>
          <p className="tl-body">
            AI는 코드가 무엇을 하는지 말해줍니다. 하지만 <code className="tl-mono">team_b = team_a</code> 다음에 무슨
            일이 벌어지는지는, 실제로 돌려서 상태를 봐야 알 수 있습니다.
          </p>
        </div>
        <div className="tl-defs" style={{ marginTop: 28 }}>
          {DIFFS.map(([t, d]) => (
            <div className="tl-def" key={t}>
              <h3 className="tl-h3">{t}</h3>
              <p className="tl-body">{d}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="tl-shell tl-section">
        <div className="tl-head">
          <h2 className="tl-h2">못 하는 것부터 말합니다</h2>
          <p className="tl-body">
            <code className="tl-mono">input()</code>, generator, async, 네트워크와 파일 접근처럼 아직 다루지 못하는
            코드는 실행하기 전에 막고 이유를 알려줍니다. 되는 척하다 중간에 깨지는 것보다 낫습니다.
          </p>
        </div>
        <div className="tl-scopes">
          <span className="tl-tag tl-tag--ok">전용 그림으로 재생</span>
          <span className="tl-tag tl-tag--info">표로는 항상 표시</span>
          <span className="tl-tag tl-tag--warn">상한까지만 재생</span>
          <span className="tl-tag tl-tag--stop">실행 전 차단</span>
          <Link to={ROUTES.help} className="tl-link" style={{ fontSize: '0.875rem' }}>
            판정 기준 전체 보기
          </Link>
        </div>
      </section>

      <section className="tl-shell tl-section tl-close">
        <div>
          <h2 className="tl-h2">그 코드, 지금 붙여넣어 보세요</h2>
          <p className="tl-body" style={{ marginTop: 8 }}>
            파이썬 런타임은 페이지에 들어온 순간부터 백그라운드에서 준비됩니다.
          </p>
        </div>
        <Link to={ROUTES.app} className="tl-btn tl-btn--lg">
          실행 화면으로
        </Link>
      </section>
    </main>
  )
}
