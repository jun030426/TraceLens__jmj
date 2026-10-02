/**
 * [학생 퀴즈 목록 페이지] 주소: /quiz  (헤더 메뉴 '퀴즈')
 * - 강의별 필터 · 요약 · 퀴즈 카드(풀기 / 해설 보기 / 다시 풀기)
 * - 'AI 퀴즈 만들기': 필터에서 고른 강의의 자료로 우리 AI 서버가 퀴즈를 만들어요 (백엔드 경유)
 * - 데이터: api/quizApi.ts 의 getMyQuizzes / generateQuiz (지금은 임시 데이터)
 * TODO: 퀴즈 풀기(/quiz/:id) · 해설(/quiz/:id/review) 화면은 아직 없어요.
 */

import { useState } from 'react'
import PageLayout from '../../components/layout/PageLayout'
import PageHeading from '../../components/common/PageHeading'
import SummaryCards from '../../components/common/SummaryCards'
import EmptyState from '../../components/common/EmptyState'
import FilterChips from '../../components/common/FilterChips'
import { generateQuiz, getMyQuizzes } from '../../api/quizApi'
import { useApiData } from '../../hooks/useApiData'
import { average, percent } from '../../utils/format'

// AI 퀴즈 한 번에 만들 문제 수
const GENERATE_COUNT = 10

export default function QuizList() {
  const { data, setData, loading, error } = useApiData(getMyQuizzes, [])
  const quizzes = data ?? []

  // null = 전체
  const [selectedCourseId, setSelectedCourseId] = useState<number | null>(null)
  const [generating, setGenerating] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)

  // 필터 버튼용 강의 목록 (중복 제거)
  const courseOptions = Array.from(
    new Map(quizzes.map((q) => [q.courseId, q.courseName])).entries(),
  ).map(([value, label]) => ({ value, label }))

  const visibleQuizzes =
    selectedCourseId === null ? quizzes : quizzes.filter((q) => q.courseId === selectedCourseId)

  // 요약 (선택한 강의 기준)
  const completed = visibleQuizzes.filter((q) => q.status === '완료')
  const avgScore = average(completed.map((q) => percent(q.lastScore ?? 0, q.questionCount)))

  // AI 퀴즈 만들기 → 서버가 AI 로 퀴즈를 만들어 돌려주면 목록 맨 앞에 추가
  const handleGenerateQuiz = async () => {
    if (selectedCourseId === null) {
      setNotice('AI 퀴즈를 만들 강의를 아래 필터에서 먼저 골라 주세요.')
      return
    }
    setGenerating(true)
    setNotice(null)
    try {
      const quiz = await generateQuiz({ courseId: selectedCourseId, questionCount: GENERATE_COUNT })
      setData((prev) => [quiz, ...(prev ?? [])])
      setNotice(`‘${quiz.title}’ 퀴즈를 만들었어요.`)
    } catch (err) {
      setNotice(err instanceof Error ? err.message : 'AI 퀴즈를 만들지 못했어요.')
    } finally {
      setGenerating(false)
    }
  }

  return (
    <PageLayout role="student" active="quiz">
      <PageHeading
        label="MY QUIZ"
        title="퀴즈"
        description="수업 내용으로 만든 퀴즈를 풀고 이해도를 확인해보세요."
      >
        <button
          type="button"
          className="quiz-generate-btn"
          onClick={handleGenerateQuiz}
          disabled={generating}
        >
          <span>✦</span>
          {generating ? 'AI가 만드는 중…' : 'AI 퀴즈 만들기'}
        </button>
      </PageHeading>

      <SummaryCards
        ariaLabel="퀴즈 요약"
        items={[
          { label: '전체 퀴즈', value: visibleQuizzes.length, unit: '개' },
          { label: '완료', value: completed.length, unit: '개' },
          { label: '안 푼 퀴즈', value: visibleQuizzes.length - completed.length, unit: '개' },
          { label: '평균 정답률', value: avgScore, unit: '%' },
        ]}
      />

      <FilterChips
        ariaLabel="강의별 필터"
        options={courseOptions}
        value={selectedCourseId}
        onChange={setSelectedCourseId}
      />

      {notice && (
        <div className="s-notice" role="status">
          <span>{notice}</span>
          <button type="button" onClick={() => setNotice(null)} aria-label="알림 닫기">
            ✕
          </button>
        </div>
      )}

      {loading ? (
        <EmptyState icon="…" title="퀴즈를 불러오는 중이에요" />
      ) : error ? (
        <EmptyState icon="!" title="퀴즈를 불러오지 못했어요" description={error} />
      ) : visibleQuizzes.length === 0 ? (
        <EmptyState
          icon="✓"
          title="아직 퀴즈가 없어요"
          description="AI 퀴즈 만들기로 첫 퀴즈를 만들어보세요."
        />
      ) : (
        <section className="quiz-grid">
          {visibleQuizzes.map((quiz) => {
            const done = quiz.status === '완료'
            const rate = percent(quiz.lastScore ?? 0, quiz.questionCount)

            return (
              <article key={quiz.id} className={`quiz-card quiz-card-${quiz.color}`}>
                <div className="quiz-card-top">
                  <span className="quiz-card-course">{quiz.courseName}</span>
                  <div className="quiz-card-badges">
                    {quiz.isAI && <span className="quiz-badge ai">✦ AI</span>}
                    <span className={`quiz-badge ${done ? 'done' : 'todo'}`}>{quiz.status}</span>
                  </div>
                </div>

                <div className="quiz-card-info">
                  <h2>{quiz.title}</h2>
                  <p>총 {quiz.questionCount}문제</p>
                </div>

                {done ? (
                  <div className="quiz-card-score">
                    <div className="quiz-card-score-main">
                      <strong>{quiz.lastScore}</strong>
                      <span>/ {quiz.questionCount}</span>
                      <em>{rate}%</em>
                    </div>
                    <div className="course-progress-track">
                      <div className="course-progress-value" style={{ width: `${rate}%` }} />
                    </div>
                    <p>
                      최근 응시 {quiz.lastTakenAt} · {quiz.attempts}회 응시
                    </p>
                  </div>
                ) : (
                  <div className="quiz-card-score empty">
                    <p>아직 풀지 않은 퀴즈예요.</p>
                  </div>
                )}

                <div className="quiz-card-actions">
                  {done ? (
                    <>
                      <a href={`/quiz/${quiz.id}/review`} className="quiz-btn secondary">
                        해설 보기
                      </a>
                      <a href={`/quiz/${quiz.id}`} className="quiz-btn primary">
                        다시 풀기
                      </a>
                    </>
                  ) : (
                    <a href={`/quiz/${quiz.id}`} className="quiz-btn primary full">
                      풀기 시작 →
                    </a>
                  )}
                </div>
              </article>
            )
          })}
        </section>
      )}
    </PageLayout>
  )
}
