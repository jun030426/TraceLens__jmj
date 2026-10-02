/**
 * [내 정보 페이지 · 학생/교수자 공용] 주소: /mypage (학생), /professor/mypage (교수자)
 * - 프로필 카드 · 기본 정보 수정 · 비밀번호 변경
 * TODO(백엔드): 저장 → PATCH /api/me, 비밀번호 변경 → POST /api/me/password
 */

import { useState, type FormEvent } from 'react'
import PageLayout from '../components/layout/PageLayout'
import PageHeading from '../components/common/PageHeading'
import { useAuth, useProfessorAuth } from '../hooks/useAuth'

type Role = 'student' | 'professor'

interface MyPageProps {
  role: Role
}

interface ProfileForm {
  name: string
  email: string
  phone: string
  affiliation: string // 학생: 전공, 교수: 소속 학과
}

type Notice = { type: 'success' | 'error'; text: string } | null

export default function MyPage({ role }: MyPageProps) {
  const studentAuth = useAuth()
  const professorAuth = useProfessorAuth()
  const isStudent = role === 'student'

  const student = studentAuth.user
  const professor = professorAuth.user

  // 화면에 보여줄 기본값 (mock 사용자 정보 기반)
  const initial: ProfileForm = isStudent
    ? {
        name: student?.name ?? '',
        email: student?.email ?? '',
        phone: '',
        affiliation: student?.major ?? '',
      }
    : {
        name: professor?.name ?? '',
        email: professor?.email ?? '',
        phone: '',
        affiliation: professor?.department ?? '',
      }

  const idLabel = isStudent ? '학번' : '아이디'
  const idValue = isStudent ? (student?.studentNo ?? '-') : (professor?.email ?? '-')
  const affiliationLabel = isStudent ? '전공' : '소속 학과'

  const [saved, setSaved] = useState<ProfileForm>(initial)
  const [form, setForm] = useState<ProfileForm>(initial)
  const [profileNotice, setProfileNotice] = useState<Notice>(null)

  const [pw, setPw] = useState({ current: '', next: '', confirm: '' })
  const [pwNotice, setPwNotice] = useState<Notice>(null)

  const isDirty = JSON.stringify(form) !== JSON.stringify(saved)

  const update = (key: keyof ProfileForm, value: string) => {
    setForm((prev) => ({ ...prev, [key]: value }))
    setProfileNotice(null)
  }

  const handleProfileSubmit = (e: FormEvent) => {
    e.preventDefault()

    if (!form.name.trim()) {
      setProfileNotice({ type: 'error', text: '이름을 입력해주세요.' })
      return
    }
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(form.email)) {
      setProfileNotice({ type: 'error', text: '올바른 이메일 주소를 입력해주세요.' })
      return
    }
    if (form.phone && !/^01[0-9]-?\d{3,4}-?\d{4}$/.test(form.phone)) {
      setProfileNotice({ type: 'error', text: '전화번호 형식을 확인해주세요. (예: 010-1234-5678)' })
      return
    }

    // TODO: PATCH /api/me  (백엔드 연결 시 교체)
    setSaved(form)
    setProfileNotice({ type: 'success', text: '내 정보가 저장되었어요.' })
  }

  const handleProfileReset = () => {
    setForm(saved)
    setProfileNotice(null)
  }

  const handlePasswordSubmit = (e: FormEvent) => {
    e.preventDefault()

    if (!pw.current || !pw.next || !pw.confirm) {
      setPwNotice({ type: 'error', text: '모든 항목을 입력해주세요.' })
      return
    }
    if (pw.next.length < 8) {
      setPwNotice({ type: 'error', text: '새 비밀번호는 8자 이상이어야 해요.' })
      return
    }
    if (pw.next !== pw.confirm) {
      setPwNotice({ type: 'error', text: '새 비밀번호가 서로 일치하지 않아요.' })
      return
    }
    if (pw.next === pw.current) {
      setPwNotice({ type: 'error', text: '현재 비밀번호와 다른 비밀번호를 입력해주세요.' })
      return
    }

    // TODO: POST /api/me/password  (백엔드 연결 시 교체)
    setPw({ current: '', next: '', confirm: '' })
    setPwNotice({ type: 'success', text: '비밀번호가 변경되었어요.' })
  }

  return (
    <PageLayout
      role={role}
      // 교수자 화면 스타일(prof-panel 등)을 학생 화면에서도 쓰기 때문에 professor-page 를 항상 붙여요
      className={`professor-page mypage ${isStudent ? '' : 'mypage-professor'}`}
    >
      <PageHeading
        label="MY PAGE"
        title="내 정보"
        description="계정 정보를 확인하고 수정할 수 있어요."
      />

      <div className="mypage-layout">
        {/* 왼쪽: 프로필 카드 */}
        <aside className="prof-panel mypage-profile-card">
          <div className="mypage-avatar">{saved.name.charAt(0) || '?'}</div>
          <strong className="mypage-name">{saved.name}</strong>
          <span className="mypage-role">{isStudent ? '학생' : '교수자'}</span>

          <dl className="mypage-summary">
            <div>
              <dt>{idLabel}</dt>
              <dd>{idValue}</dd>
            </div>
            <div>
              <dt>{affiliationLabel}</dt>
              <dd>{saved.affiliation || '-'}</dd>
            </div>
            <div>
              <dt>이메일</dt>
              <dd>{saved.email}</dd>
            </div>
            <div>
              <dt>전화번호</dt>
              <dd>{saved.phone || '-'}</dd>
            </div>
          </dl>
        </aside>

        <div className="mypage-forms">
          {/* 기본 정보 */}
          <form className="prof-panel" onSubmit={handleProfileSubmit} noValidate>
            <div className="prof-panel-head">
              <h2>기본 정보</h2>
            </div>

            <div className="prof-field-row">
              <label className="prof-field">
                <span>이름</span>
                <input
                  className="prof-input"
                  value={form.name}
                  onChange={(e) => update('name', e.target.value)}
                  autoComplete="name"
                />
              </label>
              <label className="prof-field">
                <span>{idLabel}</span>
                <input className="prof-input" value={idValue} disabled />
              </label>
            </div>

            <div className="prof-field-row">
              <label className="prof-field">
                <span>이메일</span>
                <input
                  className="prof-input"
                  type="email"
                  value={form.email}
                  onChange={(e) => update('email', e.target.value)}
                  autoComplete="email"
                />
              </label>
              <label className="prof-field">
                <span>전화번호</span>
                <input
                  className="prof-input"
                  type="tel"
                  placeholder="010-1234-5678"
                  value={form.phone}
                  onChange={(e) => update('phone', e.target.value)}
                  autoComplete="tel"
                />
              </label>
            </div>

            <label className="prof-field">
              <span>{affiliationLabel}</span>
              <input
                className="prof-input"
                value={form.affiliation}
                onChange={(e) => update('affiliation', e.target.value)}
              />
            </label>

            {profileNotice && (
              <p className={`mypage-notice ${profileNotice.type}`} role="status">
                {profileNotice.text}
              </p>
            )}

            <div className="mypage-actions">
              <button
                type="button"
                className="mypage-btn secondary"
                onClick={handleProfileReset}
                disabled={!isDirty}
              >
                되돌리기
              </button>
              <button type="submit" className="mypage-btn primary" disabled={!isDirty}>
                저장
              </button>
            </div>
          </form>

          {/* 비밀번호 변경 */}
          <form className="prof-panel" onSubmit={handlePasswordSubmit} noValidate>
            <div className="prof-panel-head">
              <h2>비밀번호 변경</h2>
            </div>

            <label className="prof-field">
              <span>현재 비밀번호</span>
              <input
                className="prof-input"
                type="password"
                value={pw.current}
                onChange={(e) => {
                  setPw((p) => ({ ...p, current: e.target.value }))
                  setPwNotice(null)
                }}
                autoComplete="current-password"
              />
            </label>

            <div className="prof-field-row">
              <label className="prof-field">
                <span>새 비밀번호</span>
                <input
                  className="prof-input"
                  type="password"
                  placeholder="8자 이상"
                  value={pw.next}
                  onChange={(e) => {
                    setPw((p) => ({ ...p, next: e.target.value }))
                    setPwNotice(null)
                  }}
                  autoComplete="new-password"
                />
              </label>
              <label className="prof-field">
                <span>새 비밀번호 확인</span>
                <input
                  className="prof-input"
                  type="password"
                  value={pw.confirm}
                  onChange={(e) => {
                    setPw((p) => ({ ...p, confirm: e.target.value }))
                    setPwNotice(null)
                  }}
                  autoComplete="new-password"
                />
              </label>
            </div>

            {pwNotice && (
              <p className={`mypage-notice ${pwNotice.type}`} role="status">
                {pwNotice.text}
              </p>
            )}

            <div className="mypage-actions">
              <button type="submit" className="mypage-btn primary">
                비밀번호 변경
              </button>
            </div>
          </form>
        </div>
      </div>
    </PageLayout>
  )
}
