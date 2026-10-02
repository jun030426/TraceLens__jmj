/**
 * [첫 랜딩 페이지 · 로그인 전] 주소: / (다른 주소와 안 맞을 때도 이 화면)
 * - 서비스 소개 + 로그인 버튼. 본문은 components/landing/LandingContent 를 같이 써요.
 */

import Logo from '../components/common/Logo'
import LandingContent from '../components/landing/LandingContent'

export default function Landing() {
  const goLogin = () => {
    window.location.href = '/login'
  }

  return (
    <div className="study-landing">
      <header className="study-landing-header study-landing-header-bare">
        <div className="study-landing-header-inner">
          <div className="study-landing-logo">
            <Logo />
          </div>

          <div className="study-landing-header-right">
            <button type="button" className="study-landing-login-pill" onClick={goLogin}>
              로그인
            </button>
          </div>
        </div>
      </header>

      <LandingContent
        heroButtonLabel="무료로 시작하기"
        bottomButtonLabel="지금 시작하기"
        onStart={goLogin}
      />
    </div>
  )
}
