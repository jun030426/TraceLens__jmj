/**
 * [랜딩 그림] 소개 데모(강의 영상 · AI 질문)에 쓰는 AI 교수님 프로필 — 실제 사진 대신 기본 프로필 그림이에요.
 * - 동그란 연한 배경에 사람 모양(머리 + 어깨)만 그려요. 사진 파일이 필요 없어요.
 * - 학생용 화면의 캐릭터(ProfessorAvatar)와는 따로예요.
 * - 스타일: landing/lerny-landing.css 의 .v-prof-photo (동그란 틀)
 */

export default function ProfessorPhoto({ size }: { size: number }) {
  return (
    <span className="v-prof-photo" style={{ width: size, height: size, background: '#ece3ea' }} aria-hidden="true">
      <svg viewBox="0 0 40 40" width="100%" height="100%" style={{ display: 'block' }}>
        <circle cx="20" cy="15.5" r="7" fill="#b8a3b4" />
        <path d="M6 40c0-8.3 6.3-14 14-14s14 5.7 14 14Z" fill="#b8a3b4" />
      </svg>
    </span>
  )
}
