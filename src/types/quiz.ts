/**
 * [공용 타입] 퀴즈 데이터 모양
 * - 교수자 퀴즈 현황(ProfessorQuizStats)과 학생 퀴즈 목록(QuizList)에서 사용
 */

/* ---------- 교수자 퀴즈 현황용 ---------- */

export interface QuizQuestion {
  id: string
  /** 개념(단원) — 취약점 분석 기준 */
  concept: string
  text: string
  choices: string[]
  /** 정답 보기 번호 (0부터) */
  answer: number
}

export interface Quiz {
  id: number
  courseId: number
  title: string
  week: number
  questions: QuizQuestion[]
}

export interface QuizAttempt {
  quizId: number
  studentId: number
  /** 문항 순서대로 고른 보기 번호 (-1 = 응답 안 함) */
  choices: number[]
  submittedAt: string
}

/* ---------- 학생 퀴즈 목록용 ---------- */

export type StudentQuizStatus = '미응시' | '완료'

/** 학생 퀴즈 목록 카드 하나 */
export interface StudentQuiz {
  id: number
  title: string
  courseId: number
  courseName: string
  color: 'purple' | 'blue' | 'green' | 'orange'
  questionCount: number
  status: StudentQuizStatus
  isAI: boolean // AI가 만든 퀴즈인지
  lastScore?: number // 최근 맞힌 문제 수
  lastTakenAt?: string // 최근 응시일
  attempts: number // 응시 횟수
}
