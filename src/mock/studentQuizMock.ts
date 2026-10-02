/**
 * [임시 데이터] 학생 퀴즈 목록 (mock) — 학생 퀴즈 페이지(QuizList)에서 사용
 * TODO(백엔드): GET /api/students/me/quizzes 로 교체 후 이 파일은 지워도 돼요.
 */

import type { StudentQuiz } from '../types/quiz'

export const MOCK_STUDENT_QUIZZES: StudentQuiz[] = [
  {
    id: 1,
    title: '3주차 · 변환 행렬 복습',
    courseId: 1,
    courseName: '컴퓨터 그래픽스',
    color: 'purple',
    questionCount: 10,
    status: '완료',
    isAI: true,
    lastScore: 8,
    lastTakenAt: '2026.09.25',
    attempts: 2,
  },
  {
    id: 2,
    title: '4주차 · 조명과 셰이딩',
    courseId: 1,
    courseName: '컴퓨터 그래픽스',
    color: 'purple',
    questionCount: 8,
    status: '미응시',
    isAI: true,
    attempts: 0,
  },
  {
    id: 3,
    title: '스택과 큐 개념 확인',
    courseId: 2,
    courseName: '자료구조',
    color: 'blue',
    questionCount: 12,
    status: '완료',
    isAI: false,
    lastScore: 7,
    lastTakenAt: '2026.09.22',
    attempts: 1,
  },
  {
    id: 4,
    title: '트리 순회 연습',
    courseId: 2,
    courseName: '자료구조',
    color: 'blue',
    questionCount: 10,
    status: '미응시',
    isAI: true,
    attempts: 0,
  },
  {
    id: 5,
    title: '탐색 알고리즘 총정리',
    courseId: 3,
    courseName: '인공지능 개론',
    color: 'green',
    questionCount: 15,
    status: '완료',
    isAI: false,
    lastScore: 14,
    lastTakenAt: '2026.09.18',
    attempts: 1,
  },
]
