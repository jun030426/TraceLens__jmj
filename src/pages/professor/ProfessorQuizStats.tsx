/**
 * [교수자 퀴즈 현황 페이지] 주소: /professor/courses/:id/quizzes  (강의 상세 → '퀴즈 현황')
 * - 퀴즈별 응시 현황 · 개념별 정답률(취약 개념) · 오답이 많은 문항(보기별 선택, 틀린 학생)
 * - 데이터: api/quizApi.ts 의 getCourseQuizData() (지금은 임시 데이터), 계산: utils/quizAnalysis.ts
 */

import { useState } from 'react'
import PageLayout from '../../components/layout/PageLayout'
import PageHeading from '../../components/common/PageHeading'
import SummaryCards from '../../components/common/SummaryCards'
import EmptyState from '../../components/common/EmptyState'
import CourseNotFound from '../../components/professor/CourseNotFound'
import { studentsOf, useCourseStore } from '../../store/courseStore'
import { getCourseQuizData } from '../../api/quizApi'
import { useApiData } from '../../hooks/useApiData'
import {
  analyzeConcepts,
  analyzeQuestions,
  analyzeQuizzes,
  WEAK_RATE,
} from '../../utils/quizAnalysis'
import { accentStyle } from '../../utils/course'
import { average, percent } from '../../utils/format'

const CHOICE_MARK = ['①', '②', '③', '④', '⑤', '⑥']

interface Props {
  courseId: number
}

export default function ProfessorQuizStats({ courseId }: Props) {
  const db = useCourseStore()
  const course = db.courses.find((c) => c.id === courseId)
  const students = studentsOf(db, courseId)
  const studentIds = students.map((s) => s.id)
  const nameOf = (id: number) => students.find((s) => s.id === id)?.name ?? '(수강 취소)'

  // 퀴즈 + 응시 기록을 서버에서 받아와요 (mock 모드에서는 임시 데이터) — api/quizApi.ts
  const { data, loading, error } = useApiData(
    () => getCourseQuizData(courseId, studentIds),
    [courseId, studentIds.join(',')],
  )
  const quizzes = data?.quizzes ?? []
  const attempts = data?.attempts ?? []

  const [quizFilter, setQuizFilter] = useState<number | 'all'>('all')
  const [openQ, setOpenQ] = useState<string | null>(null)
  const [hoverConcept, setHoverConcept] = useState<string | null>(null)

  const shownQuizzes = quizFilter === 'all' ? quizzes : quizzes.filter((q) => q.id === quizFilter)
  const enrolledAttempts = attempts.filter((a) => studentIds.includes(a.studentId))

  const questionStats = analyzeQuestions(shownQuizzes, enrolledAttempts)
  const conceptStats = analyzeConcepts(questionStats)
  const quizStats = analyzeQuizzes(quizzes, attempts, studentIds)
  const hardest = [...questionStats].sort((a, b) => a.correctRate - b.correctRate)

  const totalResponses = questionStats.reduce((s, q) => s + q.responses, 0)
  const totalCorrect = questionStats.reduce((s, q) => s + q.correct, 0)
  const avgRate = percent(totalCorrect, totalResponses)
  const shownQuizStats = quizStats.filter((q) => shownQuizzes.includes(q.quiz))
  const participation = average(shownQuizStats.map((q) => q.participation))
  const weakest = conceptStats[0]
  const weakCount = conceptStats.filter((c) => c.correctRate < WEAK_RATE).length

  if (!course) return <CourseNotFound />

  return (
    <PageLayout
      role="professor"
      className={`course-card-${course.color}`}
      style={accentStyle(course)}
    >
      <a href={`/professor/courses/${course.id}`} className="prof-back-link">
        ← {course.title} 현황
      </a>

      <PageHeading
        label="QUIZ REPORT"
        title="퀴즈 진행 현황"
        description="학생들이 푼 퀴즈 결과로 많이 틀리는 개념과 문항을 확인해 보세요."
      />

      {loading ? (
        <EmptyState icon="…" title="퀴즈 결과를 불러오는 중이에요" />
      ) : error ? (
        <EmptyState icon="!" title="퀴즈 결과를 불러오지 못했어요" description={error} />
      ) : quizzes.length === 0 ? (
        <EmptyState
          icon="?"
          title="아직 출제된 퀴즈가 없어요"
          description="퀴즈가 생기고 학생들이 응시하면 이곳에서 결과를 볼 수 있어요."
        />
      ) : (
        <>
          {/* 퀴즈 선택 */}
          <div className="pq-filter" role="group" aria-label="퀴즈 선택">
            <button
              type="button"
              aria-pressed={quizFilter === 'all'}
              className={quizFilter === 'all' ? 'active' : undefined}
              onClick={() => setQuizFilter('all')}
            >
              전체 퀴즈
            </button>
            {quizzes.map((q) => (
              <button
                key={q.id}
                type="button"
                aria-pressed={quizFilter === q.id}
                className={quizFilter === q.id ? 'active' : undefined}
                onClick={() => setQuizFilter(q.id)}
              >
                {q.title}
              </button>
            ))}
          </div>

          {/* 요약 */}
          <SummaryCards
            ariaLabel="퀴즈 요약"
            items={[
              quizFilter === 'all'
                ? {
                    label: '퀴즈 / 문항',
                    value: quizzes.length,
                    unit: `개 · ${questionStats.length}문항`,
                  }
                : { label: '문항 수', value: questionStats.length, unit: '문항' },
              {
                label: '평균 정답률',
                value: avgRate,
                unit: '%',
                valueClassName: avgRate < WEAK_RATE ? 'prof-text-danger' : undefined,
              },
              { label: '평균 응시율', value: participation, unit: '%' },
              {
                label: '가장 취약한 개념',
                value: weakest ? weakest.concept : '-',
                unit: weakest ? `${weakest.correctRate}%` : undefined,
                valueClassName: 'pq-summary-text',
              },
            ]}
          />

          <div className="prof-dashboard-grid">
            {/* 개념별 정답률 */}
            <section className="prof-panel">
              <div className="prof-panel-head">
                <div>
                  <h2>개념별 정답률</h2>
                  <p className="prof-muted">낮은 순 · 정답률 {WEAK_RATE}% 미만은 취약 개념</p>
                </div>
                {weakCount > 0 && <span className="pq-weak-count">⚠ 취약 {weakCount}개</span>}
              </div>

              <ul className="pq-bars">
                {conceptStats.map((c) => {
                  const weak = c.correctRate < WEAK_RATE
                  return (
                    <li
                      key={c.concept}
                      className={`pq-bar-row ${weak ? 'weak' : ''}`}
                      tabIndex={0}
                      onMouseEnter={() => setHoverConcept(c.concept)}
                      onMouseLeave={() => setHoverConcept(null)}
                      onFocus={() => setHoverConcept(c.concept)}
                      onBlur={() => setHoverConcept(null)}
                    >
                      <span className="pq-bar-label">
                        {c.concept}
                        {weak && <em className="pq-weak-tag">⚠ 취약</em>}
                      </span>
                      <span className="pq-bar-track">
                        <i style={{ width: `${Math.max(c.correctRate, 1)}%` }} />
                        <b
                          className="pq-threshold"
                          style={{ left: `${WEAK_RATE}%` }}
                          aria-hidden="true"
                        />
                      </span>
                      <span className="pq-bar-value">{c.correctRate}%</span>

                      {hoverConcept === c.concept && (
                        <span className="pq-tip" role="tooltip">
                          <strong>{c.concept}</strong>
                          <span>
                            정답률 <b>{c.correctRate}%</b>
                          </span>
                          <span>
                            문항 {c.questions}개 · 응답 {c.responses}건
                          </span>
                        </span>
                      )}
                    </li>
                  )
                })}
              </ul>
            </section>

            {/* 퀴즈별 응시 현황 */}
            <section className="prof-panel">
              <div className="prof-panel-head">
                <h2>퀴즈별 응시 현황</h2>
              </div>
              <ul className="pq-quiz-list">
                {quizStats.map((q) => (
                  <li key={q.quiz.id} className={quizFilter === q.quiz.id ? 'active' : undefined}>
                    <button type="button" onClick={() => setQuizFilter(q.quiz.id)}>
                      <span className="pq-quiz-title">
                        <strong>{q.quiz.title}</strong>
                        <small>
                          {q.quiz.week}주차 · {q.quiz.questions.length}문항
                        </small>
                      </span>
                      <span className="pq-quiz-stats">
                        <span>
                          응시 <b>{q.attempted}</b>/{q.enrolled}명
                        </span>
                        <span>
                          평균{' '}
                          <b className={q.avgScore < WEAK_RATE ? 'prof-text-danger' : undefined}>
                            {q.avgScore}점
                          </b>
                        </span>
                      </span>
                      <span className="pq-mini-track" aria-hidden="true">
                        <i style={{ width: `${q.participation}%` }} />
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            </section>
          </div>

          {/* 오답이 많은 문항 */}
          <section className="prof-panel prof-section-gap">
            <div className="prof-panel-head">
              <div>
                <h2>오답이 많은 문항</h2>
                <p className="prof-muted">
                  정답률 낮은 순 · 누르면 보기별 선택과 틀린 학생을 볼 수 있어요
                </p>
              </div>
            </div>

            <ol className="pq-questions">
              {hardest.map((s, rank) => {
                const open = openQ === s.question.id
                const weak = s.correctRate < WEAK_RATE
                return (
                  <li key={s.question.id} className={open ? 'open' : undefined}>
                    <button
                      type="button"
                      className="pq-q-row"
                      aria-expanded={open}
                      onClick={() => setOpenQ(open ? null : s.question.id)}
                    >
                      <span className="pq-rank">{rank + 1}</span>
                      <span className="pq-q-main">
                        <strong>{s.question.text}</strong>
                        <small>
                          {s.quiz.title} · {s.index + 1}번 · <em>{s.question.concept}</em>
                        </small>
                      </span>
                      <span className="pq-q-rate">
                        <span className={`pq-rate ${weak ? 'weak' : ''}`}>
                          {weak && '⚠ '}
                          {s.correctRate}%
                        </span>
                        <small>
                          오답 {s.wrongStudentIds.length}/{s.responses}명
                        </small>
                      </span>
                      <span className="pq-q-wrong">
                        {s.topWrong ? (
                          <>
                            <small>많이 고른 오답</small>
                            <span>
                              {CHOICE_MARK[s.topWrong.choice]}{' '}
                              {s.question.choices[s.topWrong.choice]}
                            </span>
                          </>
                        ) : (
                          <small>-</small>
                        )}
                      </span>
                      <span className="pq-chevron" aria-hidden="true">
                        {open ? '▴' : '▾'}
                      </span>
                    </button>

                    {open && (
                      <div className="pq-q-detail">
                        <div>
                          <p className="pq-detail-title">보기별 선택</p>
                          <ul className="pq-choices">
                            {s.question.choices.map((choice, k) => {
                              const count = s.choiceCounts[k] ?? 0
                              const rate = percent(count, s.responses)
                              const isAnswer = k === s.question.answer
                              return (
                                <li key={k} className={isAnswer ? 'answer' : undefined}>
                                  <span className="pq-choice-label">
                                    {CHOICE_MARK[k]} {choice}
                                    {isAnswer && <em>✓ 정답</em>}
                                  </span>
                                  <span className="pq-choice-track">
                                    <i style={{ width: `${rate}%` }} />
                                  </span>
                                  <span className="pq-choice-value">
                                    {count}명 · {rate}%
                                  </span>
                                </li>
                              )
                            })}
                          </ul>
                        </div>
                        <div>
                          <p className="pq-detail-title">
                            틀린 학생 ({s.wrongStudentIds.length}명)
                          </p>
                          {s.wrongStudentIds.length === 0 ? (
                            <p className="prof-muted">모두 맞혔어요 🎉</p>
                          ) : (
                            <ul className="pq-students">
                              {s.wrongStudentIds.map((id) => (
                                <li key={id}>{nameOf(id)}</li>
                              ))}
                            </ul>
                          )}
                        </div>
                      </div>
                    )}
                  </li>
                )
              })}
            </ol>
          </section>
        </>
      )}
    </PageLayout>
  )
}
