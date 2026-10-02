/**
 * [로그인·회원가입 공용 컴포넌트] 두 페이지에 똑같이 들어가는 꾸밈 요소
 * - AuthBackground   : 뒤에 떠 있는 배경 도형
 * - AuthBackButton   : 왼쪽 위 '← 시작화면' 버튼
 * - AuthIllustration : 학생 일러스트 + 'Lerny와 함께 시작해요' 패널
 * - 스타일: styles/login.css, styles/signup.css (prefix 로 login- / signup- 클래스 선택)
 */

import studentImage from '../../assets/eximages.png'

type Prefix = 'login' | 'signup'

export function AuthBackground({ prefix }: { prefix: Prefix }) {
  return (
    <div className={`${prefix}-bg`} aria-hidden="true">
      <div className="shape shape-1" />
      <div className="shape shape-2" />
      <div className="shape shape-3" />
      <div className="shape shape-4" />
    </div>
  )
}

export function AuthBackButton({ prefix }: { prefix: Prefix }) {
  return (
    <button
      type="button"
      className={`${prefix}-back`}
      onClick={() => {
        window.location.href = '/'
      }}
      aria-label="시작화면으로 돌아가기"
    >
      <span className="back-arrow" aria-hidden="true">
        ←
      </span>
      <span>시작화면</span>
    </button>
  )
}

/** @param className 패널 위치 클래스 (로그인: login-panel-right, 회원가입: signup-panel-left) */
export function AuthIllustration({ className }: { className: string }) {
  return (
    <div className={className}>
      <div className="panel-illustration">
        <img
          src={studentImage}
          alt="책상에 앉아 공부하는 학생 캐릭터"
          className="student-illustration"
        />
      </div>
      <div className="panel-text">
        <h2>Lerny와 함께 시작해요</h2>
        <p>즐겁게 배우는 가장 쉬운 방법</p>
      </div>
    </div>
  )
}
