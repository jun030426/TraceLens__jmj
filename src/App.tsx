/**
 * [주소(URL) → 페이지 연결] 브라우저 주소를 보고 어떤 페이지를 보여줄지 정해요.
 * - 라우터 라이브러리 없이 window.location.pathname 으로 직접 비교해요.
 * - 새 페이지를 추가하면 여기에 주소를 한 줄 추가하세요.
 */

import type { ReactElement } from 'react'
import Landing from './pages/Landing'
import MyPage from './pages/MyPage'
import Login from './pages/auth/Login'
import Signup from './pages/auth/Signup'
import StudentLanding from './pages/student/StudentLanding'
import CourseList from './pages/student/CourseList'
import QuizList from './pages/student/QuizList'
import Chatbot from './pages/student/Chatbot'
import Attendance from './pages/student/Attendance'
import ProfessorDashboard from './pages/professor/ProfessorDashboard'
import ProfessorCourseDetail from './pages/professor/ProfessorCourseDetail'
import ProfessorQuizStats from './pages/professor/ProfessorQuizStats'
import ProfessorStudents from './pages/professor/ProfessorStudents'
import ProfessorNotices from './pages/professor/ProfessorNotices'

/** 고정 주소 → 페이지 */
const PAGES: Record<string, () => ReactElement> = {
  // 로그인 전
  '/login': () => <Login />,
  '/signup': () => <Signup />,

  // 학생
  '/student': () => <StudentLanding />,
  '/courses': () => <CourseList />,
  '/quiz': () => <QuizList />,
  '/ai': () => <Chatbot />,
  '/attendance': () => <Attendance />,
  '/mypage': () => <MyPage role="student" />,

  // 교수자
  '/professor': () => <ProfessorDashboard />,
  '/professor/students': () => <ProfessorStudents />,
  '/professor/notices': () => <ProfessorNotices />,
  '/professor/mypage': () => <MyPage role="professor" />,
}

function App() {
  // 끝에 붙은 / 는 떼고 비교 (예: '/professor/' → '/professor')
  const path = window.location.pathname.replace(/\/+$/, '') || '/'

  const page = PAGES[path]
  if (page) return page()

  // 강의 퀴즈 현황: /professor/courses/3/quizzes
  const quizMatch = path.match(/^\/professor\/courses\/(\d+)\/quizzes$/)
  if (quizMatch) return <ProfessorQuizStats courseId={Number(quizMatch[1])} />

  // 강의 상세: /professor/courses/3
  const courseMatch = path.match(/^\/professor\/courses\/(\d+)$/)
  if (courseMatch) return <ProfessorCourseDetail courseId={Number(courseMatch[1])} />

  // 여기까지 해당하는 주소가 없으면 비로그인 랜딩 페이지가 보임
  return <Landing />
}

export default App
