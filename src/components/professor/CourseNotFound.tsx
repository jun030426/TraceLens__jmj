/**
 * [교수자 공용 화면] 주소의 강의 id 가 없을 때 보여주는 '강의를 찾을 수 없어요' 페이지
 * - 강의 상세(ProfessorCourseDetail), 퀴즈 현황(ProfessorQuizStats)에서 사용
 */

import PageLayout from '../layout/PageLayout'
import EmptyState from '../common/EmptyState'

export default function CourseNotFound() {
  return (
    <PageLayout role="professor">
      <a href="/professor" className="prof-back-link">
        ← 강의 목록
      </a>
      <EmptyState title="강의를 찾을 수 없어요" description="삭제되었거나 잘못된 주소예요." />
    </PageLayout>
  )
}
