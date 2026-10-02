/**
 * [학생 홈 · 로그인 직후 첫 화면] 주소: /student
 * - 첫 랜딩과 같은 소개 본문 + 버튼을 누르면 수강목록(/courses)으로 이동
 */

import StudentHeader from '../../components/layout/StudentHeader'
import LandingContent from '../../components/landing/LandingContent'

export default function StudentLanding() {
  const goCourses = () => {
    window.location.href = '/courses'
  }

  return (
    <div className="study-landing student-landing">
      <StudentHeader minimal />
      <LandingContent
        heroButtonLabel="수강목록"
        bottomButtonLabel="수강목록 보기"
        onStart={goCourses}
      />
    </div>
  )
}
