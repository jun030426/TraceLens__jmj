/**
 * [서버 연결] 퀴즈 API — 학생 퀴즈 목록, AI 퀴즈 만들기, 교수자 퀴즈 현황에서 사용
 *
 * AI 퀴즈 만들기 흐름: 프론트 → POST /api/quizzes/generate (우리 백엔드)
 *   → 백엔드가 그 강의의 강의자료를 모아 우리 AI 서버(직접 띄운 모델)에 문제 생성을 요청
 *   → 만들어진 퀴즈를 DB 에 저장하고 프론트에 돌려줌
 *   (프론트는 AI 서버를 직접 부르지 않아요 — api/client.ts 맨 위 설명 참고)
 *
 * 지금은 VITE_USE_MOCK 이 true 라서 mock/ 폴더의 임시 데이터를 돌려줘요.
 * 주소·응답 모양은 예시예요. 응답 데이터 모양은 types/quiz.ts 에 맞춰 주세요.
 */

import { apiFetch, mockDelay, USE_MOCK } from './client'
import { mockAttempts, MOCK_QUIZZES } from '../mock/quizMock'
import { MOCK_STUDENT_QUIZZES } from '../mock/studentQuizMock'
import type { Quiz, QuizAttempt, StudentQuiz } from '../types/quiz'

/* ---------- 학생 ---------- */

/** 내 퀴즈 목록 — GET /api/students/me/quizzes */
export async function getMyQuizzes(): Promise<StudentQuiz[]> {
  if (USE_MOCK) return mockDelay(MOCK_STUDENT_QUIZZES, 200)
  return apiFetch<StudentQuiz[]>('/students/me/quizzes')
}

export interface GenerateQuizInput {
  /** 어떤 강의의 자료로 만들지 */
  courseId: number
  /** 문제 수 */
  questionCount: number
}

/**
 * AI 퀴즈 만들기 — POST /api/quizzes/generate { courseId, questionCount } → StudentQuiz
 * AI 생성은 시간이 걸릴 수 있어요. 너무 오래 걸리면 백엔드에서 '생성 중' 상태로 먼저 응답하고
 * 나중에 목록을 다시 불러오는 방식(폴링)으로 바꿔도 돼요.
 */
export async function generateQuiz(input: GenerateQuizInput): Promise<StudentQuiz> {
  if (USE_MOCK) {
    const base = MOCK_STUDENT_QUIZZES.find((q) => q.courseId === input.courseId)
    return mockDelay(
      {
        id: Date.now(),
        title: '(임시) AI가 만든 복습 퀴즈',
        courseId: input.courseId,
        courseName: base?.courseName ?? '강의',
        color: base?.color ?? 'purple',
        questionCount: input.questionCount,
        status: '미응시',
        isAI: true,
        attempts: 0,
      },
      1200,
    )
  }
  return apiFetch<StudentQuiz>('/quizzes/generate', { method: 'POST', body: input })
}

/* ---------- 교수자 ---------- */

/**
 * 강의의 퀴즈 + 수강생 응시 기록 — 교수자 퀴즈 현황(ProfessorQuizStats)에서 사용
 *   GET /api/courses/:courseId/quizzes        → Quiz[]
 *   GET /api/courses/:courseId/quiz-attempts  → QuizAttempt[]
 * 통계 계산은 프론트(utils/quizAnalysis.ts)에서 해요. 서버에서 계산해 주고 싶으면 그 결과를 받아도 돼요.
 */
export async function getCourseQuizData(
  courseId: number,
  studentIds: number[],
): Promise<{ quizzes: Quiz[]; attempts: QuizAttempt[] }> {
  if (USE_MOCK) {
    const quizzes = MOCK_QUIZZES.filter((q) => q.courseId === courseId)
    return mockDelay({ quizzes, attempts: mockAttempts(quizzes, studentIds) }, 200)
  }
  const [quizzes, attempts] = await Promise.all([
    apiFetch<Quiz[]>(`/courses/${courseId}/quizzes`),
    apiFetch<QuizAttempt[]>(`/courses/${courseId}/quiz-attempts`),
  ])
  return { quizzes, attempts }
}
