/**
 * [교수자 공지·자료 공용 조각] 공지/자료 종류 배지 · 첨부 파일 목록
 * - 공지·자료 페이지(ProfessorNotices), 강의 상세의 '최근 공지·자료'(ProfessorCourseDetail)에서 사용
 */

import type { NoticeKind } from '../../types/course'
import { formatBytes } from '../../utils/format'

/** 공지/자료 종류 배지 */
export function KindBadge({ kind }: { kind: NoticeKind }) {
  return <span className={`prof-kind ${kind === '공지' ? 'notice' : 'material'}`}>{kind}</span>
}

/** 첨부 파일 목록 (onRemove 를 주면 각 파일 옆에 ✕ 버튼) */
export function FileList({
  files,
  onRemove,
}: {
  files: { name: string; size: number }[]
  onRemove?: (index: number) => void
}) {
  return (
    <ul className="prof-file-list">
      {files.map((f, i) => (
        <li key={`${f.name}-${i}`}>
          <span>📎 {f.name}</span>
          <small>{formatBytes(f.size)}</small>
          {onRemove && (
            <button
              type="button"
              className="prof-icon-btn small"
              onClick={() => onRemove(i)}
              aria-label={`${f.name} 제거`}
            >
              ✕
            </button>
          )}
        </li>
      ))}
    </ul>
  )
}
