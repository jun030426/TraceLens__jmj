import { useEffect, useState, type ReactNode } from 'react'
import { Link, ROUTES } from '../router'
import { geminiApiKey } from '../director/gemini'
import { DEFAULTS, LIMITS, resetSettings, setSetting, useSettings, type CaptionSize, type Presentation } from '../settings/store'

function Switch({
  on,
  onChange,
  label,
  disabled = false,
}: {
  on: boolean
  onChange: (v: boolean) => void
  label: string
  disabled?: boolean
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      aria-label={label}
      disabled={disabled}
      className="tl-switch"
      onClick={() => onChange(!on)}
    >
      <span className="tl-switch__knob" />
    </button>
  )
}

/* 타이핑 도중에 잘라내면 1000을 칠 수 없다 — 편집 중에는 문자열로 두고
   포커스를 떠날 때(또는 Enter) 한 번만 확정한다. */
function NumberField({
  value,
  min,
  max,
  step,
  label,
  onCommit,
}: {
  value: number
  min: number
  max: number
  step: number
  label: string
  onCommit: (n: number) => void
}) {
  const [draft, setDraft] = useState(String(value))
  useEffect(() => setDraft(String(value)), [value])
  const commit = () => {
    const n = Number(draft)
    if (!Number.isFinite(n)) return setDraft(String(value))
    onCommit(n)
  }
  return (
    <input
      className="tl-number"
      type="number"
      inputMode="numeric"
      aria-label={label}
      min={min}
      max={max}
      step={step}
      value={draft}
      onChange={e => setDraft(e.target.value)}
      onBlur={commit}
      onKeyDown={e => {
        if (e.key === 'Enter') e.currentTarget.blur()
      }}
    />
  )
}

function Seg<T extends string | number>({
  value,
  options,
  onChange,
  label,
}: {
  value: T
  options: { v: T; l: string }[]
  onChange: (v: T) => void
  label: string
}) {
  return (
    <div className="tl-seg" role="group" aria-label={label}>
      {options.map(o => (
        <button key={String(o.v)} type="button" aria-pressed={value === o.v} onClick={() => onChange(o.v)}>
          {o.l}
        </button>
      ))}
    </div>
  )
}

function Group({ title, intro, children }: { title: string; intro?: ReactNode; children: ReactNode }) {
  return (
    <section className="tl-panel">
      <div className="tl-panel__bar">
        <h2 className="tl-h3">{title}</h2>
      </div>
      <div className="tl-panel__body">
        {intro && (
          <p className="tl-body" style={{ marginBottom: 14, fontSize: '0.9rem' }}>
            {intro}
          </p>
        )}
        {children}
      </div>
    </section>
  )
}

export default function Settings() {
  const s = useSettings()
  const aiPossible = Boolean(geminiApiKey)

  return (
    <main>
      <section className="tl-shell tl-lead">
        <h1 className="tl-h1">설정</h1>
        <p className="tl-lede" style={{ marginTop: 14 }}>
          이 브라우저에만 저장되며 계정도 서버도 쓰지 않습니다. 바꾸는 즉시 적용됩니다.
        </p>
      </section>

      <section className="tl-shell tl-section">
        <div className="tl-settings">
          <Group
            title="AI 연출"
            intro={
              <>
                실행과 재생은 전부 이 브라우저 안에서 끝납니다. 다만 <strong>연출 대본을 만들 때만</strong> 코드와 실행
                요약본이 외부 모델(Gemini)로 전송됩니다. 끄면 규칙 기반 대본만 사용하고, 아무것도 전송하지 않습니다.
              </>
            }
          >
            <div className="tl-field">
              <div>
                <div className="tl-field__name">AI 연출 사용</div>
                <p className="tl-field__help">
                  {aiPossible
                    ? '끄면 local-only 모드입니다. 재생 품질은 규칙 대본 수준이 되지만 기능은 그대로 동작합니다.'
                    : '이 빌드에는 API 키가 설정되어 있지 않아 지금은 항상 규칙 대본으로 재생됩니다.'}
                </p>
              </div>
              <Switch
                on={s.aiDirector && aiPossible}
                onChange={v => setSetting('aiDirector', v)}
                label="AI 연출 사용"
                disabled={!aiPossible}
              />
            </div>
          </Group>

          <Group
            title="표현 방식"
            intro="같은 실행 기록을 두 가지 스킨으로 볼 수 있습니다. 값과 순서는 어느 쪽이든 똑같이 트레이스에서 옵니다."
          >
            <div className="tl-field">
              <div>
                <div className="tl-field__name">실행 화면 스킨</div>
                <p className="tl-field__help">
                  입문: 값을 막대 높이로, 비교를 저울로 보여줍니다 — 코드를 몰라도 흐름이 보이게. 정밀: 구조
                  그대로(값·칸 번호 중심). 재생 화면에서도 바로 바꿀 수 있습니다.
                </p>
              </div>
              <Seg
                label="실행 화면 스킨"
                value={s.presentation}
                options={[
                  { v: 'intro' as Presentation, l: '입문(비유)' },
                  { v: 'precise' as Presentation, l: '정밀(구조)' },
                ]}
                onChange={v => setSetting('presentation', v)}
              />
            </div>
          </Group>

          <Group title="재생">
            <div className="tl-field">
              <div>
                <div className="tl-field__name">실행 후 자동 재생</div>
                <p className="tl-field__help">끄면 Run 이후 첫 장면에서 멈춘 채 기다립니다.</p>
              </div>
              <Switch on={s.autoplay} onChange={v => setSetting('autoplay', v)} label="실행 후 자동 재생" />
            </div>
            <div className="tl-field">
              <div>
                <div className="tl-field__name">기본 배속</div>
                <p className="tl-field__help">재생 중에도 바꿀 수 있습니다. 여기서 정하는 건 시작 값입니다.</p>
              </div>
              <Seg
                label="기본 배속"
                value={s.speed}
                options={LIMITS.speeds.map(v => ({ v, l: `${v}×` }))}
                onChange={v => setSetting('speed', v)}
              />
            </div>
          </Group>

          <Group title="모션·접근성">
            <div className="tl-field">
              <div>
                <div className="tl-field__name">모션 줄이기</div>
                <p className="tl-field__help">
                  장면 전환과 화면 전체의 애니메이션을 끕니다. 운영체제에서 이미 모션 감소를 켜두었다면 이 설정과
                  무관하게 적용됩니다. 값과 순서는 그대로 보입니다.
                </p>
              </div>
              <Switch on={s.reduceMotion} onChange={v => setSetting('reduceMotion', v)} label="모션 줄이기" />
            </div>
            <div className="tl-field">
              <div>
                <div className="tl-field__name">자막 크기</div>
                <p className="tl-field__help">실행 화면 아래 내레이션 자막의 크기입니다.</p>
              </div>
              <Seg
                label="자막 크기"
                value={s.captionSize}
                options={[
                  { v: 'sm' as CaptionSize, l: '작게' },
                  { v: 'md' as CaptionSize, l: '보통' },
                  { v: 'lg' as CaptionSize, l: '크게' },
                ]}
                onChange={v => setSetting('captionSize', v)}
              />
            </div>
          </Group>

          <Group
            title="실행 상한"
            intro="무한 루프와 아주 긴 실행을 위한 안전장치입니다. 상한에 걸리면 실패가 아니라 모아둔 데까지 재생합니다. 올릴수록 긴 코드를 볼 수 있지만 메모리와 대기 시간이 늘어납니다."
          >
            <div className="tl-field">
              <div>
                <div className="tl-field__name">최대 이벤트 수</div>
                <p className="tl-field__help">
                  {LIMITS.maxEvents.min.toLocaleString()}~{LIMITS.maxEvents.max.toLocaleString()} · 기본{' '}
                  {DEFAULTS.maxEvents.toLocaleString()}
                </p>
              </div>
              <NumberField
                label="최대 이벤트 수"
                min={LIMITS.maxEvents.min}
                max={LIMITS.maxEvents.max}
                step={LIMITS.maxEvents.step}
                value={s.maxEvents}
                onCommit={n => setSetting('maxEvents', n)}
              />
            </div>
            <div className="tl-field">
              <div>
                <div className="tl-field__name">실행 시간 제한</div>
                <p className="tl-field__help">
                  {LIMITS.timeoutSec.min}~{LIMITS.timeoutSec.max}초 · 기본 {DEFAULTS.timeoutMs / 1000}초
                </p>
              </div>
              <NumberField
                label="실행 시간 제한(초)"
                min={LIMITS.timeoutSec.min}
                max={LIMITS.timeoutSec.max}
                step={LIMITS.timeoutSec.step}
                value={Math.round(s.timeoutMs / 1000)}
                onCommit={n => setSetting('timeoutMs', n * 1000)}
              />
            </div>
          </Group>

          <div className="tl-close" style={{ paddingTop: 4 }}>
            <p className="tl-note">
              바꾼 설정은 이 브라우저에만 남습니다.{' '}
              <Link to={ROUTES.app} className="tl-link">
                실행 화면으로 돌아가기
              </Link>
            </p>
            <button type="button" className="tl-btn tl-btn--quiet" onClick={resetSettings}>
              기본값으로 되돌리기
            </button>
          </div>
        </div>
      </section>
    </main>
  )
}
