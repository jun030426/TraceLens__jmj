/**
 * [랜딩 그림] 스크롤 스토리 '실습' 단계 — 학생용 실습 퀴즈 화면(pages/student/CodingPractice.tsx)과 같은 구성의 미리보기
 *   왼쪽: 문제 → 코드 입력 → 힌트 / 오른쪽: 시각화(그림 · 실행 흐름 · 시각화 설명) → 정답
 * - 스크롤(progress 0~1)에 따라: 코드가 한 글자씩 써지고 → 실행 → 회차가 하나씩 넘어가고 → 정답이 나와요.
 * - 로그인 없이 누구나 보는 예시라 실제로 코드를 돌리지는 않고, 미리 정해 둔 결과를 보여줘요.
 * - 스타일: styles/landing.css 의 .v-pd-*
 */

import DemoFit from './DemoFit'
import PracticeViz3D from './PracticeViz3D'
import { IconCheck, IconPause, IconPlay } from './Icons'

// [임시 데이터] 랜딩 소개용 — 실제로 코드를 실행하지 않고 아래에 적어 둔 값(TRACE)을 보여줘요
const NUMS = [3, 9, 2, 12]
const ANSWER_LINE = '    if (nums[i] > max) max = nums[i]'
const PLACEHOLDER = '    // 여기에 코드를 작성하세요'
const CODE_BEFORE = ['function findMax(nums) {', '  if (nums.length === 0) return null', '  let max = nums[0]', '  for (let i = 1; i < nums.length; i++) {']
const CODE_AFTER = ['  }', '  return max', '}']

// 반복문 회차별 변수 값 (실제 화면에서는 코드를 실행해서 얻어요)
// [임시 데이터] 미리 적어 둔 반복문 회차별 변수 값과 설명
const TRACE = [
  { i: 1, max: 9, changed: true, note: 'nums[1] 은 9 예요. 지금까지의 최댓값 3 보다 커서 max 가 9 로 바뀌어요.' },
  { i: 2, max: 9, changed: false, note: 'nums[2] 는 2 예요. max(9) 보다 작아서 그대로 둬요.' },
  { i: 3, max: 12, changed: true, note: 'nums[3] 은 12 예요. max(9) 보다 커서 max 가 12 로 바뀌어요.' },
]
// [임시 데이터] 랜딩 소개용 힌트 문구
const HINTS = ['반복문에서 지금까지의 최댓값과 nums[i] 를 비교하면 돼요.', 'nums[i] 가 max 보다 크면 max 를 바꿔요.']

const TYPE_END = 0.24
const RUN_AT = 0.3
const STEP_START = 0.36
const STEP_END = 0.84

export default function PracticeDemo({ progress }: { progress: number }) {
  const p = Math.min(1, Math.max(0, progress))
  const typed = Math.round(Math.min(1, p / TYPE_END) * (ANSWER_LINE.length - 4))
  const line = typed === 0 ? PLACEHOLDER : ANSWER_LINE.slice(0, 4 + typed)
  const typing = p < TYPE_END
  const hintLevel = p < 0.1 ? 0 : p < 0.18 ? 1 : 2
  const pressing = p >= RUN_AT - 0.03 && p < RUN_AT + 0.03
  const ran = p >= RUN_AT
  const stepping = p >= STEP_START
  const step = stepping
    ? Math.min(TRACE.length - 1, Math.floor(((p - STEP_START) / (STEP_END - STEP_START)) * TRACE.length))
    : -1
  const done = p >= STEP_END
  const now = step >= 0 ? TRACE[step] : null

  return (
    <DemoFit width={1040}>
      <div className="v-pd" aria-hidden="true">
        {/* 왼쪽 — 문제 · 코드 입력 · 힌트 */}
        <div className="v-pd-col left">
          <div className="v-pd-box">
            <span className="v-pd-tag">오늘의 실습 · 1주차 배열과 복잡도</span>
            <strong>배열의 최댓값 찾기</strong>
            <p>정수 배열 nums 가 주어져요. 가장 큰 값을 돌려주세요.</p>
            <code>findMax([3, 9, 2, 12]) → 12</code>
          </div>

          <div className="v-pd-editor">
            <div className="v-pd-editor-bar">
              <span>코드 입력 · JavaScript</span>
              <span className={`v-pd-run ${pressing ? 'press' : ''}`}>실행 <IconPlay /></span>
            </div>
            <pre>
              {[...CODE_BEFORE, line, ...CODE_AFTER].map((text, n) => (
                <span key={n} className={`v-pd-line ${n === 4 ? (typed === 0 ? 'todo' : 'mine') : ''}`}>
                  <i>{n + 1}</i>
                  {text}
                  {n === 4 && typing && typed > 0 && <b className="v-pd-caret" />}
                </span>
              ))}
            </pre>
          </div>

          <div className="v-pd-box hints">
            <div className="v-pd-hints-head">
              <strong>힌트</strong>
              <span>
                {[1, 2, 3].map((n) => (
                  <em key={n} className={n <= hintLevel ? 'on' : ''}>
                    힌트 {n}
                  </em>
                ))}
              </span>
            </div>
            {hintLevel === 0 ? (
              <p className="v-pd-muted">막히면 힌트를 1단계부터 차례로 볼 수 있어요.</p>
            ) : (
              HINTS.slice(0, hintLevel).map((h, n) => (
                <p key={h} className="v-pd-hint">
                  <b>힌트 {n + 1}</b>
                  {h}
                </p>
              ))
            )}
          </div>
        </div>

        {/* 오른쪽 — 시각화 · 정답 */}
        <div className="v-pd-col right">
          <div className="v-pd-box viz">
            <div className="v-pd-viz-head">
              <strong>시각화</strong>
              <span className="v-pd-controls">
                <em><IconPlay back /></em>
                <em className={stepping && !done ? 'on' : ''}>{stepping && !done ? <><IconPause /> 재생 중</> : <><IconPlay /> 재생</>}</em>
                <em><IconPlay /></em>
              </span>
            </div>

            {/* 실행 전에는 그림 · 표 없이 안내만 */}
            {ran ? (
              <div className="v-pd-viz-body">
              <div className="v-pd-pic">
                <span className="v-pd-pic-step">{now ? `${step + 1} / ${TRACE.length} 회차` : '시작'}</span>
                {/* 입체 시각화 — 값이 기둥 높이가 되고, 캐릭터가 i 번째 기둥으로 폴짝 뛰어요 (PracticeViz3D.tsx) */}
                <PracticeViz3D nums={NUMS} at={now ? now.i : 0} maxAt={NUMS.indexOf(now ? now.max : NUMS[0])} hop={step} />
                <div className="v-pd-vars">
                  <div className="v-pd-var">
                    <span>i</span>
                    <b>{now ? now.i : '–'}</b>
                  </div>
                  <div className={`v-pd-var ${now?.changed ? 'changed' : ''}`} key={`max-${step}`}>
                    <span>max</span>
                    <b>{now ? now.max : 3}</b>
                  </div>
                </div>
              </div>

              <h4>실행 흐름</h4>
              <table className="v-pd-table">
                <thead>
                  <tr>
                    <th>회차</th>
                    <th>i</th>
                    <th>nums[i]</th>
                    <th>max</th>
                  </tr>
                </thead>
                <tbody>
                  {TRACE.map((t, n) => (
                    <tr key={t.i} className={n > step ? 'wait' : n === step ? 'now' : ''}>
                      <td>{n + 1}</td>
                      <td>{n <= step ? t.i : ''}</td>
                      <td>{n <= step ? NUMS[t.i] : ''}</td>
                      <td className={n <= step && t.changed ? 'chg' : ''}>{n <= step ? t.max : ''}</td>
                    </tr>
                  ))}
                </tbody>
              </table>

              </div>
            ) : (
              <div className="v-pd-viz-body empty">코드를 실행해 주세요</div>
            )}

            {/* 시각화 설명 — 닫혀 있다가 실행되면 펼쳐져요 */}
            <div className={`v-pd-explain ${now ? 'open' : ''}`}>
              <b>
                <i>›</i> 시각화 설명
                {!now && <span>코드를 실행하면 반복문이 돌 때마다 변수가 어떻게 바뀌는지 설명해줘요</span>}
              </b>
              {now && <p key={step}>{now.note}</p>}
            </div>
          </div>

          <div className={`v-pd-box answer ${done ? 'ok' : ''}`}>
            <strong>정답</strong>
            {done ? (
              <p>
                <b><IconCheck /> 정답이에요</b> 테스트 3개를 모두 통과했어요 · findMax([3, 9, 2, 12]) = 12
              </p>
            ) : (
              <p className="v-pd-muted">실행이 끝나면 테스트 결과와 정답 여부가 여기에 나와요.</p>
            )}
          </div>
        </div>
      </div>
    </DemoFit>
  )
}
