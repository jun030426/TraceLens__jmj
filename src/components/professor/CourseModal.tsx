/**
 * [교수자 강의 목록 전용 컴포넌트] '담당 강의 추가' 모달
 * - 교수자 첫 화면(ProfessorDashboard)의 '강의 추가' 버튼으로 열려요.
 * - 강의명·강의 번호·분반·수업 시간·학점·정원·주차·카드 색상·소개 입력
 */

import { useState, type FormEvent } from 'react'
import { useDismiss } from '../../hooks/useDismiss'
import { PRESET_COLORS } from '../../utils/course'
import type { AccentColor, NewCourseInput } from '../../types/course'

/** 수업 시간 선택용 요일 / 시간 (08:00 ~ 22:00, 30분 단위) */
const DAYS = ['월', '화', '수', '목', '금', '토']
const TIMES = Array.from({ length: 29 }, (_, i) => {
  const minutes = 8 * 60 + i * 30
  const h = String(Math.floor(minutes / 60)).padStart(2, '0')
  const m = String(minutes % 60).padStart(2, '0')
  return `${h}:${m}`
})

/** 선택할 수 있는 분반 */
const SECTIONS = ['01', '02', '03']

interface CourseModalProps {
  professorName: string
  onClose: () => void
  onSubmit: (input: NewCourseInput) => void
}

export default function CourseModal({ professorName, onClose, onSubmit }: CourseModalProps) {
  const [title, setTitle] = useState('')
  // 강의 번호 입력칸 값 (형식: 000000-00, 뒤 2자리는 분반)
  const [courseNoInput, setCourseNoInput] = useState('')
  const [courseNoError, setCourseNoError] = useState('')
  const [section, setSection] = useState<string>(SECTIONS[0])
  const [credits, setCredits] = useState('3')
  const [capacity, setCapacity] = useState('40')
  const [schedule, setSchedule] = useState('')
  const [pickDays, setPickDays] = useState<string[]>([]) // 여러 요일 선택 가능
  const [startTime, setStartTime] = useState('09:00')
  const [endTime, setEndTime] = useState('10:30')
  const [scheduleError, setScheduleError] = useState('')
  const [totalWeeks, setTotalWeeks] = useState('15')
  const [color, setColor] = useState<AccentColor>('purple')
  const [customColor, setCustomColor] = useState<string | null>(null)
  const [description, setDescription] = useState('')

  // ESC 로 닫기
  useDismiss(true, onClose)

  /** 요일 버튼 켜기/끄기 — 화면 순서(월~토)대로 정렬해서 저장 */
  const toggleDay = (day: string) => {
    setScheduleError('')
    setPickDays((prev) =>
      prev.includes(day)
        ? prev.filter((d) => d !== day)
        : DAYS.filter((d) => d === day || prev.includes(d)),
    )
  }

  /** 시작 시간을 바꿨는데 끝 시간이 더 이르면, 끝 시간을 1시간 30분 뒤로 맞춰줌 */
  const handleStartChange = (value: string) => {
    setStartTime(value)
    setScheduleError('')
    if (endTime <= value) {
      const next = TIMES[Math.min(TIMES.indexOf(value) + 3, TIMES.length - 1)]
      setEndTime(next)
    }
  }

  /** 고른 요일·시간을 수업 시간 칸에 이어 붙여요 (예: '월·수 10:30~12:00, 금 13:00~15:00') */
  const addScheduleSlot = () => {
    if (pickDays.length === 0) {
      setScheduleError('요일을 하나 이상 선택해주세요.')
      return
    }
    if (endTime <= startTime) {
      setScheduleError('끝나는 시간은 시작 시간보다 늦어야 해요.')
      return
    }

    const slot = `${pickDays.join('·')} ${startTime}~${endTime}`
    setSchedule((prev) => {
      const parts = prev
        .split(',')
        .map((p) => p.trim())
        .filter(Boolean)
      if (parts.includes(slot)) return prev // 같은 시간은 중복 추가 안 함
      return [...parts, slot].join(', ')
    })
    setPickDays([])
    setScheduleError('')
  }

  /** 숫자만 받아서 앞 6자리 뒤에 '-' 를 자동으로 붙여요 */
  const handleCourseNoChange = (raw: string) => {
    const digits = raw.replace(/\D/g, '').slice(0, 8)
    // 지우는 중일 때는 6자리에서 '-' 를 다시 붙이지 않아야 백스페이스가 막히지 않아요
    const deleting = raw.length < courseNoInput.length
    const withDash =
      digits.length > 6 || (digits.length === 6 && !deleting)
        ? `${digits.slice(0, 6)}-${digits.slice(6)}`
        : digits

    setCourseNoInput(withDash)
    setCourseNoError('')

    // 분반 2자리를 다 적었으면 분반 선택도 맞춰줌
    const suffix = digits.slice(6)
    if (SECTIONS.includes(suffix)) setSection(suffix)
  }

  /** 분반을 고르면 강의 번호 뒤 2자리도 같이 바뀌어요 */
  const handleSectionChange = (value: string) => {
    setSection(value)
    const digits = courseNoInput.replace(/\D/g, '')
    if (digits.length >= 6) setCourseNoInput(`${digits.slice(0, 6)}-${value}`)
  }

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault()

    const digits = courseNoInput.replace(/\D/g, '')
    const number = digits.slice(0, 6)
    const suffix = digits.slice(6)

    if (number.length !== 6) {
      setCourseNoError('강의 번호 앞 6자리 숫자를 입력해주세요.')
      return
    }
    if (suffix && !SECTIONS.includes(suffix)) {
      setCourseNoError('분반은 01, 02, 03 중 하나만 가능해요.')
      return
    }

    onSubmit({
      title: title.trim(),
      courseNo: number,
      section,
      professor: professorName,
      description: description.trim() || undefined,
      credits: Number(credits),
      capacity: Math.max(1, Number(capacity) || 1),
      schedule: schedule.trim() || '시간 미정',
      color,
      customColor: color === 'custom' && customColor ? customColor : undefined,
      totalWeeks: Math.max(1, Number(totalWeeks) || 15),
    })
  }

  return (
    <div
      className="prof-modal-backdrop"
      onMouseDown={(e) => e.target === e.currentTarget && onClose()}
    >
      <form
        className="prof-modal"
        onSubmit={handleSubmit}
        role="dialog"
        aria-modal="true"
        aria-labelledby="course-modal-title"
      >
        <div className="prof-panel-head">
          <div>
            <h2 id="course-modal-title">담당 강의 추가</h2>
            <p className="prof-muted">추가한 강의는 학생 화면에 수강 신청 가능한 강의로 보여요.</p>
          </div>
          <button type="button" className="prof-icon-btn" onClick={onClose} aria-label="닫기">
            ✕
          </button>
        </div>

        <label className="prof-field">
          <span>강의명 *</span>
          <input
            className="prof-input"
            required
            autoFocus
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="예: 컴퓨터 비전"
          />
        </label>

        <div className="prof-field-row">
          <label className="prof-field">
            <span>강의 번호 *</span>
            <input
              className="prof-input"
              required
              inputMode="numeric"
              value={courseNoInput}
              onChange={(e) => handleCourseNoChange(e.target.value)}
              placeholder="000000-00"
              aria-invalid={courseNoError ? true : undefined}
            />
            {courseNoError && <small className="prof-field-error">{courseNoError}</small>}
          </label>
          <label className="prof-field">
            <span>분반</span>
            <select
              className="prof-input"
              value={section}
              onChange={(e) => handleSectionChange(e.target.value)}
            >
              {SECTIONS.map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          </label>
        </div>

        <div className="prof-field">
          <label htmlFor="course-schedule">
            <span className="prof-field-label">수업 시간</span>
          </label>
          <div className="prof-schedule-box">
            <input
              id="course-schedule"
              className="prof-input"
              value={schedule}
              onChange={(e) => setSchedule(e.target.value)}
              placeholder="직접 적거나 아래에서 골라 추가하세요 (예: 월·수 10:30~12:00)"
            />

            <div className="prof-schedule-picker">
              <div className="prof-day-chips" role="group" aria-label="요일 (여러 개 선택 가능)">
                {DAYS.map((d) => (
                  <button
                    key={d}
                    type="button"
                    className={`prof-day-chip ${pickDays.includes(d) ? 'active' : ''}`}
                    aria-pressed={pickDays.includes(d)}
                    onClick={() => toggleDay(d)}
                  >
                    {d}
                  </button>
                ))}
              </div>

              <div className="prof-time-range">
                <select
                  className="prof-input"
                  aria-label="시작 시간"
                  value={startTime}
                  onChange={(e) => handleStartChange(e.target.value)}
                >
                  {TIMES.slice(0, -1).map((t) => (
                    <option key={t} value={t}>
                      {t}
                    </option>
                  ))}
                </select>
                <span aria-hidden="true">~</span>
                <select
                  className="prof-input"
                  aria-label="끝나는 시간"
                  value={endTime}
                  onChange={(e) => {
                    setEndTime(e.target.value)
                    setScheduleError('')
                  }}
                >
                  {TIMES.filter((t) => t > startTime).map((t) => (
                    <option key={t} value={t}>
                      {t}
                    </option>
                  ))}
                </select>
              </div>

              <button
                type="button"
                className="prof-schedule-add"
                onClick={addScheduleSlot}
                aria-label="선택한 요일과 시간을 수업 시간에 추가"
              >
                추가
              </button>
            </div>
          </div>
          {scheduleError && <small className="prof-field-error">{scheduleError}</small>}
        </div>

        <div className="prof-field-row prof-field-row-3">
          <label className="prof-field">
            <span>학점</span>
            <select
              className="prof-input"
              value={credits}
              onChange={(e) => setCredits(e.target.value)}
            >
              {[1, 2, 3].map((n) => (
                <option key={n} value={n}>
                  {n}학점
                </option>
              ))}
            </select>
          </label>
          <label className="prof-field">
            <span>정원</span>
            <input
              className="prof-input"
              type="number"
              min={1}
              value={capacity}
              onChange={(e) => setCapacity(e.target.value)}
            />
          </label>
          <label className="prof-field">
            <span>총 주차</span>
            <input
              className="prof-input"
              type="number"
              min={1}
              max={20}
              value={totalWeeks}
              onChange={(e) => setTotalWeeks(e.target.value)}
            />
          </label>
        </div>

        <div className="prof-field">
          <span>카드 색상</span>
          <div className="prof-swatches" role="radiogroup" aria-label="카드 색상">
            {PRESET_COLORS.map((c) => (
              <button
                key={c.value}
                type="button"
                role="radio"
                aria-checked={color === c.value}
                aria-label={c.label}
                title={c.label}
                className={`prof-swatch ${color === c.value ? 'active' : ''}`}
                style={{ background: c.hex }}
                onClick={() => setColor(c.value)}
              />
            ))}

            {/* 직접 고른 색 — 한 번 고르면 스와치로 남아서 다시 선택할 수 있어요 */}
            {customColor && (
              <button
                type="button"
                role="radio"
                aria-checked={color === 'custom'}
                aria-label={`직접 고른 색 ${customColor}`}
                title={customColor}
                className={`prof-swatch ${color === 'custom' ? 'active' : ''}`}
                style={{ background: customColor }}
                onClick={() => setColor('custom')}
              />
            )}

            {/* + 버튼: 누르면 색상 선택 창이 열려요 */}
            <label className="prof-swatch prof-swatch-add" title="색상 직접 선택">
              <span aria-hidden="true">+</span>
              <input
                type="color"
                aria-label="색상 직접 선택"
                value={customColor ?? '#5145f5'}
                onChange={(e) => {
                  setCustomColor(e.target.value)
                  setColor('custom')
                }}
              />
            </label>
          </div>
        </div>

        <label className="prof-field">
          <span>강의 소개</span>
          <textarea
            className="prof-input"
            rows={3}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="학생들이 수강 신청할 때 보게 될 소개 문구예요."
          />
        </label>

        <div className="prof-modal-actions">
          <button type="button" className="quiz-btn secondary prof-btn-reset" onClick={onClose}>
            취소
          </button>
          <button type="submit" className="quiz-btn primary prof-btn-reset prof-btn-brand">
            강의 추가
          </button>
        </div>
      </form>
    </div>
  )
}
