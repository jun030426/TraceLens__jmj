/**
 * [앱 시작점] React 를 #root 에 그리고, 전체 CSS 를 한 번에 불러와요.
 *
 * CSS 는 모두 여기서만 import 해요. (페이지/컴포넌트 파일에서는 import 하지 않음)
 * ⚠️ 아래 순서가 곧 CSS 적용 우선순위예요 — 뒤에 있는 파일이 같은 규칙을 덮어써요. 순서를 바꾸지 마세요.
 */

import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'

import './styles/landing.css' //            랜딩 페이지 + 모든 페이지 상단 헤더
import './styles/login.css' //              로그인
import './styles/role-toggle.css' //        회원가입 [학번|교수자] 버튼
import './styles/signup.css' //             회원가입
import './styles/header-profile.css' //     헤더 오른쪽 프로필 드롭다운
import './styles/page-common.css' //        로그인 후 페이지 공통 (제목·요약 카드·빈 화면·강의 색상)
import './styles/student-courses.css' //    학생 수강목록 표 · 탭 · 신청 확인 창 (출석 현황도 사용)
import './styles/quiz.css' //               학생 퀴즈 카드 · 필터 칩 · 공용 버튼
import './styles/professor.css' //          교수자 페이지 공용 (패널·표·폼·모달) — 내 정보 페이지도 사용
import './styles/mypage.css' //             내 정보
import './styles/chatbot.css' //            학생 AI 챗봇
import './styles/attendance-stairs.css' //  출석 스탬프 계단
import './styles/attendance.css' //         학생 출석 현황
import './styles/professor-quiz.css' //     교수자 퀴즈 현황
import './styles/global.css' //             전체 기본값 (글꼴·box-sizing·로고 크기)

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
