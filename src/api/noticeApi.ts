/**
 * [서버 연결] 공지 · 강의자료 API — 교수자 공지·자료 페이지(ProfessorNotices), 강의 상세에서 사용
 *
 * 강의자료(파일) 흐름: 프론트 → POST /api/notices (multipart/form-data, 파일 포함) → 우리 백엔드가 파일 저장
 *   → '자료'로 올라온 파일은 백엔드가 우리 AI 서버에 넘겨 분석(텍스트 추출·색인)해 두면
 *     학생 챗봇의 '강의 자료 기반 답변'과 AI 퀴즈 생성에 쓸 수 있어요.
 *   (프론트는 AI 서버를 직접 부르지 않아요 — api/client.ts 맨 위 설명 참고)
 *
 * 요청/응답 약속 (예시 — 백엔드와 맞춰서 바꾸세요)
 *   GET    /api/notices?courseId=3            → Notice[]   (courseId 없으면 내 강의 전체)
 *   POST   /api/notices  (multipart)          → Notice[]   (강의마다 하나씩 만들어진 게시물)
 *          - 'data'  : JSON { courseIds, kind, title, body, pinned }
 *          - 'files' : 첨부 파일 (여러 개)
 *   PATCH  /api/notices/:id { pinned }        → 204
 *   DELETE /api/notices/:id                   → 204
 *
 * 지금은 VITE_USE_MOCK 이 true 라서 mock/courseSeed.ts 의 임시 공지를 쓰고, 새 글은 화면에만 저장돼요.
 */

import { apiFetch, mockDelay, USE_MOCK } from './client'
import { initialNotices } from '../mock/courseSeed'
import { todayString } from '../utils/format'
import type { Notice, NoticeKind } from '../types/course'

export interface NewNoticeInput {
  /** 여러 강의를 고르면 강의마다 같은 게시물이 하나씩 만들어져요 */
  courseIds: number[]
  kind: NoticeKind
  title: string
  body: string
  pinned: boolean
  files: File[]
}

/** 공지·자료 목록 (courseId 를 주면 그 강의 것만) */
export async function fetchNotices(courseId?: number): Promise<Notice[]> {
  if (USE_MOCK) {
    return mockDelay(
      courseId === undefined
        ? initialNotices
        : initialNotices.filter((n) => n.courseId === courseId),
      150,
    )
  }
  return apiFetch<Notice[]>(courseId === undefined ? '/notices' : `/notices?courseId=${courseId}`)
}

/** 새 게시물 올리기 (파일 포함) */
export async function createNotice(input: NewNoticeInput): Promise<Notice[]> {
  if (USE_MOCK) {
    const now = Date.now()
    return mockDelay(
      input.courseIds.map((courseId, i) => ({
        id: now + i,
        courseId,
        kind: input.kind,
        title: input.title,
        body: input.body,
        createdAt: todayString(),
        pinned: input.pinned,
        files: input.files.map((f) => ({ name: f.name, size: f.size })),
        views: 0,
      })),
      300,
    )
  }

  const formData = new FormData()
  const { files, ...data } = input
  formData.append('data', new Blob([JSON.stringify(data)], { type: 'application/json' }))
  files.forEach((file) => formData.append('files', file))
  return apiFetch<Notice[]>('/notices', { method: 'POST', formData })
}

/** 상단 고정 켜기/끄기 */
export async function setNoticePinned(id: number, pinned: boolean): Promise<void> {
  if (USE_MOCK) return
  await apiFetch(`/notices/${id}`, { method: 'PATCH', body: { pinned } })
}

/** 게시물 삭제 */
export async function deleteNotice(id: number): Promise<void> {
  if (USE_MOCK) return
  await apiFetch(`/notices/${id}`, { method: 'DELETE' })
}
