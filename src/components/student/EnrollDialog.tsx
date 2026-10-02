/**
 * [학생 수강목록 전용 컴포넌트] 수강 신청 확인 창
 * - confirm(신청할까요?) → done(완료 안내) / error(신청 불가 이유) 3단계
 * - 스타일: styles/student-courses.css 의 .s-modal
 */

import { useDismiss } from '../../hooks/useDismiss'
import { accentStyle, courseCode } from '../../utils/course'
import type { ProfessorCourse } from '../../types/course'

export interface EnrollDialogState {
  course: ProfessorCourse
  step: 'confirm' | 'done' | 'error'
  message?: string
}

interface EnrollDialogProps {
  dialog: EnrollDialogState
  onConfirm: () => void
  onClose: () => void
}

export default function EnrollDialog({ dialog, onConfirm, onClose }: EnrollDialogProps) {
  const { course, step } = dialog

  // ESC 로 창 닫기
  useDismiss(true, onClose)

  // 완료/오류 단계의 공통 '닫기' 버튼
  const closeButton = (
    <div className="s-modal-actions">
      <button type="button" className="s-btn primary wide" onClick={onClose} autoFocus>
        닫기
      </button>
    </div>
  )

  return (
    <div
      className="s-modal-backdrop"
      onMouseDown={(e) => e.target === e.currentTarget && onClose()}
    >
      <div
        className={`s-modal course-card-${course.color}`}
        style={accentStyle(course)}
        role="dialog"
        aria-modal="true"
        aria-labelledby="enroll-dialog-title"
      >
        {step === 'confirm' && (
          <>
            <div className="s-modal-icon" aria-hidden="true">
              {course.title.charAt(0)}
            </div>
            <h2 id="enroll-dialog-title">수강 신청하시겠습니까?</h2>
            <div className="s-modal-course">
              <strong>{course.title}</strong>
              <span>
                {courseCode(course)} · {course.professor} · {course.credits}학점
              </span>
              <span>{course.schedule}</span>
            </div>
            <div className="s-modal-actions">
              <button type="button" className="s-btn ghost" onClick={onClose}>
                취소
              </button>
              <button type="button" className="s-btn primary" onClick={onConfirm} autoFocus>
                신청
              </button>
            </div>
          </>
        )}

        {step === 'done' && (
          <>
            <div className="s-modal-icon done" aria-hidden="true">
              ✓
            </div>
            <h2 id="enroll-dialog-title">수강 신청이 완료되었어요</h2>
            <p className="s-modal-text">
              ‘{course.title}’은(는) <b>교수자의 승인 후 수강 가능합니다.</b>
              <br />
              승인되면 ‘내 강의’에 추가돼요.
            </p>
            {closeButton}
          </>
        )}

        {step === 'error' && (
          <>
            <div className="s-modal-icon error" aria-hidden="true">
              !
            </div>
            <h2 id="enroll-dialog-title">신청할 수 없어요</h2>
            <p className="s-modal-text">{dialog.message}</p>
            {closeButton}
          </>
        )}
      </div>
    </div>
  )
}
