/**
 * [교수자 공지·자료 페이지] 주소: /professor/notices  (헤더 메뉴 '강의 자료', ?course=ID 로 강의 지정 가능)
 * - 왼쪽: 새 게시물 작성 (공지/강의자료, 여러 강의에 한 번에 게시, 파일 첨부)
 * - 오른쪽: 게시물 목록 (강의·종류 필터, 펼쳐 보기, 상단 고정, 삭제)
 * - 서버 통신: api/noticeApi.ts (지금은 mock 모드라 새 글은 화면에만 저장되고 새로고침하면 사라져요)
 * - '강의자료'로 올린 파일은 백엔드가 우리 AI 서버에 넘겨 챗봇·AI 퀴즈 생성에 활용해요.
 */

import { useRef, useState, type DragEvent, type FormEvent } from 'react'
import { createNotice, deleteNotice, fetchNotices, setNoticePinned } from '../../api/noticeApi'
import { useApiData } from '../../hooks/useApiData'
import PageLayout from '../../components/layout/PageLayout'
import PageHeading from '../../components/common/PageHeading'
import EmptyState from '../../components/common/EmptyState'
import SegmentButtons from '../../components/common/SegmentButtons'
import CourseFilter from '../../components/professor/CourseFilter'
import { FileList, KindBadge } from '../../components/professor/NoticeParts'
import { courseById, useCourseStore } from '../../store/courseStore'
import { accentStyle, courseCode } from '../../utils/course'
import type { NoticeKind } from '../../types/course'

type KindFilter = '전체' | NoticeKind

const KINDS: NoticeKind[] = ['공지', '자료']
const KIND_FILTERS: KindFilter[] = ['전체', '공지', '자료']

export default function ProfessorNotices() {
  const { courses } = useCourseStore()
  // 내 강의 전체의 공지·자료를 서버에서 받아와요
  const { data, setData: setNotices, loading, error } = useApiData(() => fetchNotices(), [])
  const notices = data ?? []
  // 강의 목록에서 카드를 눌러 들어오면 (?course=ID) 그 강의로 바로 걸러서 보여줌
  const [courseId, setCourseId] = useState<number | null>(() => {
    const id = Number(new URLSearchParams(window.location.search).get('course'))
    return courses.some((c) => c.id === id) ? id : null
  })
  const [kindFilter, setKindFilter] = useState<KindFilter>('전체')
  const [openId, setOpenId] = useState<number | null>(null)

  // 작성 폼
  const [kind, setKind] = useState<NoticeKind>('공지')
  // 올릴 강의 — 여러 개 고르면 강의마다 같은 게시물이 한 번에 올라가요
  const [formCourseIds, setFormCourseIds] = useState<number[]>(() => {
    const first = courseId ?? courses[0]?.id
    return first === undefined ? [] : [first]
  })
  const [courseError, setCourseError] = useState('')
  const [title, setTitle] = useState('')
  const [body, setBody] = useState('')
  const [pinned, setPinned] = useState(false)
  const [files, setFiles] = useState<File[]>([])
  const [dragging, setDragging] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState('')
  const fileInputRef = useRef<HTMLInputElement>(null)

  const visible = notices
    .filter(
      (n) =>
        (courseId === null || n.courseId === courseId) &&
        (kindFilter === '전체' || n.kind === kindFilter),
    )
    .sort((a, b) => Number(b.pinned) - Number(a.pinned) || b.id - a.id)

  const addFiles = (list: FileList | null) => {
    if (!list) return
    setFiles((prev) => [...prev, ...Array.from(list)])
  }

  const handleDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    setDragging(false)
    addFiles(e.dataTransfer.files)
  }

  const resetForm = () => {
    setTitle('')
    setBody('')
    setPinned(false)
    setFiles([])
    if (fileInputRef.current) fileInputRef.current.value = ''
  }

  const toggleFormCourse = (id: number) => {
    setCourseError('')
    setFormCourseIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]))
  }

  const allSelected = courses.length > 0 && formCourseIds.length === courses.length
  const toggleAllCourses = () => {
    setCourseError('')
    setFormCourseIds(allSelected ? [] : courses.map((c) => c.id))
  }

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    if (formCourseIds.length === 0) {
      setCourseError('게시물을 올릴 강의를 하나 이상 선택해 주세요.')
      return
    }
    if (kind === '자료' && files.length === 0) {
      alert('강의자료는 파일을 1개 이상 첨부해 주세요.')
      return
    }

    setSubmitting(true)
    setSubmitError('')
    try {
      // 서버에 파일과 함께 업로드 → 강의마다 하나씩 만들어진 게시물을 돌려받아요
      const created = await createNotice({
        // 강의 목록 순서대로 정렬해서 보냄
        courseIds: courses.filter((c) => formCourseIds.includes(c.id)).map((c) => c.id),
        kind,
        title: title.trim(),
        body: body.trim(),
        pinned,
        files,
      })
      setNotices((prev) => [...[...created].reverse(), ...(prev ?? [])])
      setOpenId(created.length === 1 ? created[0].id : null)
      resetForm()
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : '게시물을 올리지 못했어요.')
    } finally {
      setSubmitting(false)
    }
  }

  const togglePin = async (id: number) => {
    const target = notices.find((n) => n.id === id)
    if (!target) return
    try {
      await setNoticePinned(id, !target.pinned)
      setNotices((prev) => (prev ?? []).map((n) => (n.id === id ? { ...n, pinned: !n.pinned } : n)))
    } catch (err) {
      alert(err instanceof Error ? err.message : '변경하지 못했어요.')
    }
  }

  const remove = async (id: number) => {
    if (!confirm('이 게시물을 삭제할까요?')) return
    try {
      await deleteNotice(id)
      setNotices((prev) => (prev ?? []).filter((n) => n.id !== id))
    } catch (err) {
      alert(err instanceof Error ? err.message : '삭제하지 못했어요.')
    }
  }

  return (
    <PageLayout role="professor" active="materials">
      <PageHeading
        label="NOTICE & MATERIALS"
        title="공지·자료"
        description="수강생에게 공지를 보내고 강의자료를 올려주세요. 올린 자료는 AI 학습에도 활용돼요."
      />

      <div className="prof-notice-layout">
        {/* 작성 폼 */}
        <form className="prof-panel prof-compose" onSubmit={handleSubmit}>
          <div className="prof-panel-head">
            <h2>새 게시물</h2>
          </div>

          <SegmentButtons
            className="prof-segment-full"
            ariaLabel="게시물 종류"
            options={KINDS}
            value={kind}
            onChange={setKind}
            renderLabel={(k) => (k === '공지' ? '📢 공지' : '📁 강의자료')}
          />

          <div className="prof-field">
            <div className="prof-course-pick-head">
              <span className="prof-field-label">
                강의 <small>여러 개 선택 가능</small>
              </span>
              {courses.length > 1 && (
                <button type="button" className="prof-text-btn" onClick={toggleAllCourses}>
                  {allSelected ? '전체 해제' : '전체 선택'}
                </button>
              )}
            </div>
            <div className="prof-course-pick" role="group" aria-label="게시물을 올릴 강의">
              {courses.map((c) => {
                const on = formCourseIds.includes(c.id)
                return (
                  <button
                    key={c.id}
                    type="button"
                    aria-pressed={on}
                    className={`prof-course-pick-item course-card-${c.color} ${on ? 'active' : ''}`}
                    style={accentStyle(c)}
                    onClick={() => toggleFormCourse(c.id)}
                  >
                    <span className="prof-course-pick-check" aria-hidden="true">
                      {on ? '✓' : ''}
                    </span>
                    <span className="prof-course-pick-name">{c.title}</span>
                    <small>{courseCode(c)}</small>
                  </button>
                )
              })}
            </div>
            {courseError && <small className="prof-field-error">{courseError}</small>}
          </div>

          <label className="prof-field">
            <span>제목</span>
            <input
              className="prof-input"
              required
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder={
                kind === '공지' ? '예: 중간고사 일정 안내' : '예: 6주차 강의자료 · 텍스처 매핑'
              }
            />
          </label>

          <label className="prof-field">
            <span>내용</span>
            <textarea
              className="prof-input"
              rows={5}
              value={body}
              onChange={(e) => setBody(e.target.value)}
              placeholder="수강생에게 전할 내용을 적어주세요."
            />
          </label>

          <div
            className={`prof-dropzone ${dragging ? 'dragging' : ''}`}
            onDragOver={(e) => {
              e.preventDefault()
              setDragging(true)
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={handleDrop}
            onClick={() => fileInputRef.current?.click()}
            role="button"
            tabIndex={0}
            onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && fileInputRef.current?.click()}
          >
            <input
              ref={fileInputRef}
              type="file"
              multiple
              hidden
              accept=".pdf,.ppt,.pptx,.doc,.docx,.hwp,.zip,.png,.jpg"
              onChange={(e) => addFiles(e.target.files)}
            />
            <strong>파일을 끌어다 놓거나 클릭해서 선택</strong>
            <span>PDF, PPT, DOC, HWP, ZIP, 이미지</span>
          </div>

          {files.length > 0 && (
            <FileList
              files={files}
              onRemove={(i) => setFiles((prev) => prev.filter((_, j) => j !== i))}
            />
          )}

          <label className="prof-check">
            <input type="checkbox" checked={pinned} onChange={(e) => setPinned(e.target.checked)} />
            상단에 고정
          </label>

          {submitError && <small className="prof-field-error">{submitError}</small>}

          <button type="submit" className="quiz-generate-btn prof-submit" disabled={submitting}>
            {submitting
              ? '올리는 중…'
              : formCourseIds.length > 1
                ? `${formCourseIds.length}개 강의에 게시하기`
                : '게시하기'}
          </button>
        </form>

        {/* 목록 */}
        <section className="prof-notice-list">
          <CourseFilter value={courseId} onChange={setCourseId} />

          <SegmentButtons
            className="prof-list-tabs"
            ariaLabel="종류 필터"
            options={KIND_FILTERS}
            value={kindFilter}
            onChange={setKindFilter}
          />

          {loading ? (
            <EmptyState icon="…" title="게시물을 불러오는 중이에요" />
          ) : error ? (
            <EmptyState icon="!" title="게시물을 불러오지 못했어요" description={error} />
          ) : visible.length === 0 ? (
            <EmptyState
              icon="✎"
              title="게시물이 없어요"
              description="왼쪽에서 첫 공지나 자료를 올려보세요."
            />
          ) : (
            <ul className="prof-notice-items">
              {visible.map((n) => {
                const course = courseById(n.courseId)
                const open = openId === n.id
                return (
                  <li key={n.id} className={`prof-notice-item ${n.pinned ? 'pinned' : ''}`}>
                    <button
                      type="button"
                      className="prof-notice-summary"
                      onClick={() => setOpenId(open ? null : n.id)}
                      aria-expanded={open}
                    >
                      <KindBadge kind={n.kind} />
                      <div className="prof-list-main">
                        <strong>
                          {n.pinned && <span className="prof-pin">📌</span>}
                          {n.title}
                        </strong>
                        <span>
                          {course?.title} · {n.createdAt} · 조회 {n.views}
                          {n.files.length > 0 && ` · 첨부 ${n.files.length}`}
                        </span>
                      </div>
                      <span className={`student-profile-caret ${open ? 'open' : ''}`}>▾</span>
                    </button>

                    {open && (
                      <div className="prof-notice-body">
                        {n.body && <p>{n.body}</p>}
                        {n.files.length > 0 && <FileList files={n.files} />}
                        <div className="prof-notice-actions">
                          <button
                            type="button"
                            className="prof-small-btn ghost"
                            onClick={() => togglePin(n.id)}
                          >
                            {n.pinned ? '고정 해제' : '상단 고정'}
                          </button>
                          <button
                            type="button"
                            className="prof-small-btn danger"
                            onClick={() => remove(n.id)}
                          >
                            삭제
                          </button>
                        </div>
                      </div>
                    )}
                  </li>
                )
              })}
            </ul>
          )}
        </section>
      </div>
    </PageLayout>
  )
}
