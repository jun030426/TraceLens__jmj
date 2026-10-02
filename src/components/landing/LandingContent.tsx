/**
 * [랜딩 공용 컴포넌트] 서비스 소개 본문 — 첫 랜딩(/)과 학생 홈(/student)이 같이 사용
 * - 히어로(제목 + 미리보기 화면) · 기능 소개 · 하단 시작 버튼 · 맨 위로 버튼
 * - 두 페이지는 버튼 글자와 눌렀을 때 이동할 곳만 달라서 props 로 받아요.
 * - 스타일: styles/landing.css
 */

import { useEffect, useState } from 'react'

interface LandingContentProps {
  /** 히어로 영역 버튼 글자 (예: 무료로 시작하기) */
  heroButtonLabel: string
  /** 맨 아래 버튼 글자 (예: 지금 시작하기) */
  bottomButtonLabel: string
  /** 두 버튼을 눌렀을 때 실행 */
  onStart: () => void
}

export default function LandingContent({
  heroButtonLabel,
  bottomButtonLabel,
  onStart,
}: LandingContentProps) {
  const [previewProgress, setPreviewProgress] = useState(68)
  const [showTopButton, setShowTopButton] = useState(false)

  // 미리보기 화면의 진도율 숫자가 2.4초마다 바뀌는 효과
  useEffect(() => {
    const interval = setInterval(() => {
      setPreviewProgress(Math.floor(Math.random() * 31) + 60)
    }, 2400)
    return () => clearInterval(interval)
  }, [])

  // 스크롤을 내리면 '맨 위로' 버튼 보이기
  useEffect(() => {
    const handleScroll = () => setShowTopButton(window.scrollY > 550)
    window.addEventListener('scroll', handleScroll)
    return () => window.removeEventListener('scroll', handleScroll)
  }, [])

  const scrollToTop = () => window.scrollTo({ top: 0, behavior: 'smooth' })

  return (
    <>
      <main className="study-landing-main">
        <section className="study-landing-hero">
          <div className="study-landing-glow study-landing-glow-left" />
          <div className="study-landing-glow study-landing-glow-right" />

          <div className="study-landing-hero-content">
            <div className="study-landing-badge">
              <span>✦</span>
              AI 기반 개인화 학습
            </div>

            <h1 className="study-landing-title">
              수업을 이해하고,
              <br />
              <span>나에게 맞게 공부하세요.</span>
            </h1>

            <p className="study-landing-description">
              교수자의 수업 특성을 이해하고 학습 내용을 분석해
              <br />
              나에게 필요한 학습과 퀴즈를 만들어주는 AI 학습 공간
            </p>

            <div className="study-landing-hero-actions">
              <button type="button" className="study-landing-primary-btn" onClick={onStart}>
                {heroButtonLabel}
                <span>→</span>
              </button>

              <a href="#features" className="study-landing-secondary-link">
                어떻게 학습하나요?
              </a>
            </div>
          </div>

          <div className="study-landing-preview">
            <div className="study-landing-preview-window">
              <div className="study-preview-header">
                <div className="study-preview-logo">
                  <div className="study-preview-logo-mark">A</div>
                  <span>AI STUDY</span>
                </div>

                <div className="study-preview-header-right">
                  <span className="study-preview-bell">♢</span>
                  <div className="study-preview-avatar">S</div>
                </div>
              </div>

              <div className="study-preview-body">
                <aside className="study-preview-sidebar">
                  <div className="study-preview-menu active">
                    <span>⌂</span>홈
                  </div>
                  <div className="study-preview-menu">
                    <span>▤</span>내 학습
                  </div>
                  <div className="study-preview-menu">
                    <span>✓</span>
                    퀴즈
                  </div>
                  <div className="study-preview-menu">
                    <span>✦</span>
                    AI 추천
                  </div>
                </aside>

                <div className="study-preview-content">
                  <div className="study-preview-welcome">
                    <div>
                      <span className="study-preview-small-label">GOOD AFTERNOON</span>
                      <h3>오늘도 학습을 시작해볼까요?</h3>
                      <p>학습 중인 수업을 이어서 공부해보세요.</p>
                    </div>

                    <button type="button">+ 학습 추가</button>
                  </div>

                  <div className="study-preview-grid">
                    <article className="study-preview-course">
                      <div className="study-preview-course-top">
                        <div className="study-preview-course-icon">C</div>
                        <span className="study-preview-course-status">학습 중</span>
                      </div>

                      <div className="study-preview-course-info">
                        <span>SOFTWARE</span>
                        <h4>컴퓨터 그래픽스</h4>
                        <p>최근 학습 · 오늘</p>
                      </div>

                      <div className="study-preview-progress">
                        <div className="study-preview-progress-track">
                          <div
                            className="study-preview-progress-value"
                            style={{ width: `${previewProgress}%` }}
                          />
                        </div>
                        <strong>{previewProgress}%</strong>
                      </div>
                    </article>

                    <article className="study-preview-ai">
                      <div className="study-preview-ai-icon">✦</div>
                      <span>AI RECOMMEND</span>
                      <h4>지금 복습하면 좋아요</h4>
                      <p>
                        최근 학습 내용을 바탕으로
                        <br />
                        복습할 내용을 찾았어요.
                      </p>
                      <button type="button">추천 학습 보기 →</button>
                    </article>

                    <article className="study-preview-quiz">
                      <div className="study-preview-quiz-header">
                        <span>오늘의 퀴즈</span>
                        <span>10문제</span>
                      </div>

                      <div className="study-preview-score">
                        <strong>8</strong>
                        <span>/ 10</span>
                      </div>

                      <p>지난 퀴즈보다 2문제 더 맞혔어요!</p>
                    </article>
                  </div>
                </div>
              </div>
            </div>

            <div className="study-floating-card study-floating-left">
              <div className="study-floating-icon study-floating-blue">▤</div>
              <div>
                <span>오늘의 학습</span>
                <strong>자료구조 3주차</strong>
              </div>
            </div>

            <div className="study-floating-card study-floating-right">
              <div className="study-floating-icon study-floating-green">✓</div>
              <div>
                <span>퀴즈 완료</span>
                <strong>8 / 10 정답</strong>
              </div>
            </div>
          </div>
        </section>

        <section className="study-landing-features" id="features">
          <div className="study-landing-section-heading">
            <span>HOW IT WORKS</span>
            <h2>
              공부의 모든 과정을
              <br />
              <strong>AI STUDY 하나로.</strong>
            </h2>
            <p>수업 자료부터 퀴즈까지, AI가 함께하는 새로운 학습 경험을 만나보세요.</p>
          </div>

          <div className="study-feature-grid">
            <article className="study-feature-card study-feature-blue">
              <span className="study-feature-number">01</span>
              <div className="study-feature-icon">▤</div>
              <h3>수업 특성 분석</h3>
              <p>강의 자료와 학습 내용을 바탕으로 교수자의 수업 특성을 분석해요.</p>
            </article>

            <article className="study-feature-card study-feature-purple">
              <span className="study-feature-number">02</span>
              <div className="study-feature-icon">✦</div>
              <h3>개인화 AI 학습</h3>
              <p>수업 특성과 학습 기록을 바탕으로 나에게 필요한 내용을 추천해요.</p>
            </article>

            <article className="study-feature-card study-feature-green">
              <span className="study-feature-number">03</span>
              <div className="study-feature-icon">✓</div>
              <h3>AI 퀴즈</h3>
              <p>학습한 내용으로 나만의 퀴즈를 만들고 바로 이해도를 확인해요.</p>
            </article>
          </div>
        </section>

        <section className="study-landing-bottom" id="learning">
          <div className="study-bottom-content">
            <span className="study-bottom-label">AI STUDY</span>

            <h2>
              더 효율적인 학습,
              <br />더 나은 성장을 위해.
            </h2>

            <p>
              AI가 만들어주는 맞춤형 학습 경험으로
              <br />
              새로운 공부의 방식을 시작해보세요.
            </p>

            <button type="button" onClick={onStart}>
              {bottomButtonLabel}
              <span>→</span>
            </button>
          </div>

          <div className="study-bottom-visual">
            <div className="study-bottom-circle" />

            <div className="study-bottom-stack">
              <div>
                <span>▤</span>
                강의자료 분석
              </div>
              <div>
                <span>✦</span>
                AI 맞춤 학습
              </div>
              <div>
                <span>✓</span>
                퀴즈 & 복습
              </div>
            </div>
          </div>
        </section>

        <section className="study-brand-footer">
          <div className="brand-divider">
            <span>LERNY</span>
          </div>

          {/* TODO: 하단 브랜드 문구 (지금은 '??' 자리표시) */}
          <h2>??</h2>
        </section>
      </main>

      {showTopButton && (
        <button
          type="button"
          className="scroll-top-button"
          onClick={scrollToTop}
          aria-label="맨 위로 이동"
        >
          ↑
        </button>
      )}
    </>
  )
}
