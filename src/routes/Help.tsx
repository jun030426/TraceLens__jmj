import { Link, ROUTES } from '../router'

type Tone = 'ok' | 'info' | 'warn' | 'stop'

type Verdict = {
  id: string
  tag: string
  tone: Tone
  title: string
  blurb: string
  head: string
  rows: [string, string, string][]
}

const VERDICTS: Verdict[] = [
  {
    id: 'a',
    tag: '완전 지원',
    tone: 'ok',
    title: '전용 그림으로 재생됩니다',
    blurb: '아래 유형은 각자의 전용 시각화가 있습니다.',
    head: '화면',
    rows: [
      ['변수 할당·연산', 'x = a + b', '변수 패널에서 값이 바뀌는 순간을 강조'],
      ['조건문·반복문', 'if / for / while', '비교는 실제 값과 부등호로, 반복은 회차 배지와 빨리감기로 표시'],
      ['함수 호출·재귀', 'f(x), 재귀 호출', '호출 스택 카드가 쌓였다 줄어듦'],
      ['리스트·dict·set 조작', 'arr.append(3)', '번호 붙은 칸이 자라고, 자리 교환은 두 칸이 실제로 움직임'],
      ['별칭·얕은 복사', 'b = a, b = a[:]', '같은 객체를 가리키는 화살표'],
      ['예외 발생', 'arr[5] → IndexError', '터지는 지점까지 재생하고 그 순간을 강조'],
      ['클래스 인스턴스', 'p = Point(1, 2)', '필드가 보이는 객체 상자'],
      ['컴프리헨션·문자열·print', '[x*2 for x in arr]', '시퀀스와 콘솔 출력'],
    ],
  },
  {
    id: 'b',
    tag: '기본 지원',
    tone: 'info',
    title: '표 형태로는 항상 보입니다',
    blurb: '전용 그림은 아직 없지만 이름·타입·값·변경 여부는 언제나 표시됩니다.',
    head: '화면',
    rows: [
      ['트리·그래프 등 사용자 정의 구조', 'Node(1).children = [...]', '변수 표로 표시'],
      ['깊은 중첩 데이터', '{"a": {"b": [{...}]}}', '제한 깊이까지 표로 표시'],
    ],
  },
  {
    id: 'c',
    tag: '제한 재생',
    tone: 'warn',
    title: '상한까지만 보여줍니다',
    blurb: '끝까지 가지 못해도 모아둔 데까지는 재생합니다. 상한은 설정에서 올리고 내릴 수 있습니다.',
    head: '동작',
    rows: [
      ['매우 긴 실행', '10만 회 루프', '상한까지 모으고 “여기까지 시각화” 안내'],
      ['무한 루프', 'while True:', '시간 제한으로 종료하고 모은 만큼 재생'],
      ['대량 데이터', '원소 10만 개 리스트', '앞부분만 표시'],
    ],
  },
  {
    id: 'd',
    tag: '범위 밖',
    tone: 'stop',
    title: '실행하기 전에 막습니다',
    blurb: '되는 척하고 중간에 깨지는 대신, 실행 전에 이유를 알려줍니다.',
    head: '안내',
    rows: [
      ['사용자 입력', 'input()', '입력 대기 코드는 아직 지원하지 않습니다'],
      ['generator·async·thread', 'yield, async def', '이 실행 모델은 아직 지원하지 않습니다'],
      ['네트워크', 'requests.get(...)', '브라우저 실행 환경에서는 접근할 수 없습니다'],
      ['파일·DB', 'open("f.txt")', '같은 이유로 접근할 수 없습니다'],
      ['미지원 외부 라이브러리', 'import django', '표준 라이브러리 중심 코드를 지원합니다'],
      ['조각 코드', 'self.repository.find(...)', '독립 실행 가능한 형태로 잘라서 넣어주세요'],
      ['호출 없는 정의', '함수 정의만 있는 코드', '호출 예시를 한 줄 더해주세요'],
    ],
  },
]

const CONTROLS: [string, string][] = [
  ['일시정지', '멈추면 인스펙터가 열리고 그 시점의 변수와 객체를 볼 수 있습니다.'],
  ['장면 이동', '이전·다음 버튼으로 한 장면씩 오가고, 처음으로 버튼으로 되돌아갑니다.'],
  ['배속', '재생 중에 바꿀 수 있고, 시작 값은 설정에서 정합니다.'],
  ['챕터 점프', '진행바의 구분선을 눌러 장면 단위로 건너뜁니다.'],
  ['확대·축소', '무대 위에서 휠로 확대·축소하고, 확대 상태에서 드래그로 이동합니다. 우하단 버튼으로도 조절합니다.'],
]

const TERMS: [string, string][] = [
  ['트레이스', '코드를 실행하면서 무슨 일이 일어났는지 순서대로 적은 기록. 화면의 모든 값이 여기서 나옵니다.'],
  ['챕터', '재생을 나눈 큰 단위. 진행바의 구분선이 챕터 경계이고, 눌러서 건너뛸 수 있습니다.'],
  ['인스펙터', '일시정지했을 때 그 순간의 변수와 객체를 펼쳐 보는 패널.'],
  ['별칭(aliasing)', 'b = a 처럼 두 이름이 같은 객체를 가리키는 상태. 한쪽을 바꾸면 다른 쪽도 바뀝니다.'],
  ['루프 접기', '같은 구간이 계속 반복되면 “×N회”로 접어 빨리감기합니다. 특별한 회차는 접지 않고 살립니다.'],
  ['폴백', 'AI 연출이 실패하면 규칙 기반 대본으로 자동 전환하는 것. 빈 화면은 나오지 않습니다.'],
]

export default function Help() {
  return (
    <main>
      <section className="tl-shell tl-lead">
        <h1 className="tl-h1">어떤 코드가 되나</h1>
        <p className="tl-lede" style={{ marginTop: 14 }}>
          네 가지 판정이 있습니다. 전용 그림으로 재생되는 코드, 표로만 보이는 코드, 상한까지만 보이는 코드, 그리고
          아예 실행하지 않고 막는 코드.
        </p>
        <nav className="tl-scopes" aria-label="판정 바로가기">
          {VERDICTS.map(v => (
            <a key={v.id} href={`#v-${v.id}`} className={`tl-tag tl-tag--${v.tone}`}>
              {v.tag}
            </a>
          ))}
        </nav>
      </section>

      {VERDICTS.map(v => (
        <section key={v.id} id={`v-${v.id}`} className="tl-shell tl-section">
          <div className="tl-head">
            <div className="tl-verdict-head">
              <span className={`tl-tag tl-tag--${v.tone}`}>{v.tag}</span>
              <h2 className="tl-h2">{v.title}</h2>
            </div>
            <p className="tl-body">{v.blurb}</p>
          </div>
          <div className="tl-scroll" style={{ marginTop: 20 }}>
            <table className="tl-table">
              <thead>
                <tr>
                  <th>코드 유형</th>
                  <th>예시</th>
                  <th>{v.head}</th>
                </tr>
              </thead>
              <tbody>
                {v.rows.map(([kind, example, screen]) => (
                  <tr key={kind}>
                    <td>{kind}</td>
                    <td>
                      <code className="tl-mono">{example}</code>
                    </td>
                    <td>{screen}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {v.id === 'd' && (
            <p className="tl-note" style={{ marginTop: 14, maxWidth: '62ch' }}>
              이 검사는 완벽하지 않습니다. 놓치고 실행에 들어가더라도 런타임 오류로 안전하게 내려오고, 거기까지는
              재생합니다.
            </p>
          )}
          {v.id === 'c' && (
            <p className="tl-note" style={{ marginTop: 14, maxWidth: '62ch' }}>
              최대 이벤트 수와 실행 시간 제한은{' '}
              <Link to={ROUTES.settings} className="tl-link">
                설정
              </Link>
              에서 바꿀 수 있습니다.
            </p>
          )}
        </section>
      ))}

      <section className="tl-shell tl-section">
        <div className="tl-head">
          <h2 className="tl-h2">재생 중에 할 수 있는 일</h2>
        </div>
        <div className="tl-defs" style={{ marginTop: 24 }}>
          {CONTROLS.map(([k, d]) => (
            <div className="tl-def" key={k}>
              <h3 className="tl-h3">{k}</h3>
              <p className="tl-body">{d}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="tl-shell tl-section">
        <div className="tl-head">
          <h2 className="tl-h2">말 정리</h2>
        </div>
        <div className="tl-defs" style={{ marginTop: 24 }}>
          {TERMS.map(([term, def]) => (
            <div className="tl-def" key={term}>
              <h3 className="tl-h3">{term}</h3>
              <p className="tl-body">{def}</p>
            </div>
          ))}
        </div>
      </section>
    </main>
  )
}
