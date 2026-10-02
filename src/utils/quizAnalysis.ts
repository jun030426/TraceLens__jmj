/**
 * [공용 유틸] 퀴즈 결과 분석 함수 — 교수자 퀴즈 현황 페이지(ProfessorQuizStats)에서 사용
 * - 받은 퀴즈/응시 데이터만으로 계산하므로 백엔드 연결 후에도 그대로 쓰면 돼요.
 */

import type { Quiz, QuizAttempt, QuizQuestion } from '../types/quiz'
import { average, percent as pct } from './format'

export const WEAK_RATE = 60 // 정답률 이 값 미만이면 '취약'

export interface QuestionStat {
  quiz: Quiz
  question: QuizQuestion
  index: number // 퀴즈 안에서 몇 번 문항인지 (0부터)
  responses: number
  correct: number
  correctRate: number
  /** 보기별 선택 수 */
  choiceCounts: number[]
  /** 가장 많이 고른 오답 (없으면 null) */
  topWrong: { choice: number; count: number } | null
  /** 틀린 학생 id */
  wrongStudentIds: number[]
}

export function analyzeQuestions(quizzes: Quiz[], attempts: QuizAttempt[]): QuestionStat[] {
  return quizzes.flatMap((quiz) => {
    const qa = attempts.filter((a) => a.quizId === quiz.id)
    return quiz.questions.map((question, index) => {
      const choiceCounts = question.choices.map(() => 0)
      const wrongStudentIds: number[] = []
      let responses = 0
      let correct = 0
      qa.forEach((a) => {
        const c = a.choices[index]
        responses += 1
        // 응답 안 한 문항은 오답으로 처리
        if (c === undefined || c < 0) {
          wrongStudentIds.push(a.studentId)
          return
        }
        choiceCounts[c] = (choiceCounts[c] ?? 0) + 1
        if (c === question.answer) correct += 1
        else wrongStudentIds.push(a.studentId)
      })
      let topWrong: QuestionStat['topWrong'] = null
      choiceCounts.forEach((count, choice) => {
        if (choice !== question.answer && count > 0 && (!topWrong || count > topWrong.count))
          topWrong = { choice, count }
      })
      return {
        quiz,
        question,
        index,
        responses,
        correct,
        correctRate: pct(correct, responses),
        choiceCounts,
        topWrong,
        wrongStudentIds,
      }
    })
  })
}

export interface ConceptStat {
  concept: string
  questions: number
  responses: number
  correctRate: number
}

export function analyzeConcepts(stats: QuestionStat[]): ConceptStat[] {
  const map = new Map<string, { questions: number; responses: number; correct: number }>()
  stats.forEach((s) => {
    const m = map.get(s.question.concept) ?? { questions: 0, responses: 0, correct: 0 }
    m.questions += 1
    m.responses += s.responses
    m.correct += s.correct
    map.set(s.question.concept, m)
  })
  return [...map.entries()]
    .map(([concept, m]) => ({
      concept,
      questions: m.questions,
      responses: m.responses,
      correctRate: pct(m.correct, m.responses),
    }))
    .sort((a, b) => a.correctRate - b.correctRate)
}

export interface QuizStat {
  quiz: Quiz
  attempted: number
  enrolled: number
  participation: number
  avgScore: number // 평균 점수(%)
}

export function analyzeQuizzes(
  quizzes: Quiz[],
  attempts: QuizAttempt[],
  enrolledIds: number[],
): QuizStat[] {
  return quizzes.map((quiz) => {
    const qa = attempts.filter((a) => a.quizId === quiz.id && enrolledIds.includes(a.studentId))
    const scores = qa.map((a) =>
      pct(quiz.questions.filter((q, i) => a.choices[i] === q.answer).length, quiz.questions.length),
    )
    return {
      quiz,
      attempted: qa.length,
      enrolled: enrolledIds.length,
      participation: pct(qa.length, enrolledIds.length),
      avgScore: average(scores),
    }
  })
}
