/**
 * [회원가입 페이지] 주소: /signup
 * - 학생(학번) / 교수자 아이디를 골라 가입 정보 입력 → api/authApi.ts 의 signup 으로 서버에 전송
 * - 가입 성공하면 로그인 화면으로 이동 (mock 모드에서는 서버 없이 바로 성공 처리)
 */

import { useState, type FormEvent } from 'react'
import { signup } from '../../api/authApi'
import { ApiError } from '../../api/client'
import Logo from '../../components/common/Logo'
import RoleToggle, { type UserRole } from '../../components/auth/RoleToggle'
import { AuthBackButton, AuthBackground, AuthIllustration } from '../../components/auth/AuthDecor'

export default function Signup() {
  const [role, setRole] = useState<UserRole>('student')
  const [userId, setUserId] = useState('')
  const [error, setError] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)
  const isStudent = role === 'student'

  const handleSubmit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    // 입력칸의 name 속성으로 값을 한 번에 읽어요
    const form = new FormData(e.currentTarget)
    const value = (key: string) => String(form.get(key) ?? '').trim()

    if (!value('name') || !userId || !value('password') || !value('email')) {
      setError('이름, 아이디, 비밀번호, 이메일은 꼭 입력해주세요.')
      return
    }
    if (value('password') !== value('confirmPassword')) {
      setError('비밀번호가 서로 일치하지 않아요.')
      return
    }

    setError('')
    setIsSubmitting(true)
    try {
      await signup({
        role,
        name: value('name'),
        userId,
        school: value('school'),
        major: value('major'),
        password: String(form.get('password') ?? ''), // 비밀번호는 공백도 그대로
        email: value('email'),
        phone: value('phone'),
      })
      window.location.href = '/login'
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : '회원가입에 실패했어요. 잠시 후 다시 시도해주세요.',
      )
    } finally {
      setIsSubmitting(false)
    }
  }

  const goLogin = () => {
    window.location.href = '/login'
  }

  return (
    <div className="signup-page">
      <AuthBackground prefix="signup" />
      <AuthBackButton prefix="signup" />

      <main className="signup-area">
        <div className="signup-shell">
          {/* 왼쪽: 컬러 패널 + 일러스트 */}
          <AuthIllustration className="signup-panel-left" />

          {/* 오른쪽: 폼 */}
          <div className="signup-panel-right">
            <div className="signup-logo">
              <Logo />
            </div>

            <div className="signup-heading">
              <h1>Sign up</h1>
              <p>계정을 만들고 학습을 시작해보세요.</p>
            </div>

            <form className="signup-form" onSubmit={handleSubmit} noValidate>
              <div className="signup-row">
                <div className="signup-field">
                  <label htmlFor="name">이름</label>
                  <input
                    id="name"
                    name="name"
                    type="text"
                    placeholder="홍길동"
                    autoComplete="name"
                  />
                </div>

                <div className="signup-field">
                  <div className="id-label-row">
                    <label htmlFor="userId">아이디</label>
                    <RoleToggle
                      value={role}
                      onChange={(next) => {
                        if (next === role) return
                        setRole(next)
                        setUserId('') // 학번 ↔ 교수자 아이디는 형식이 달라서 비워줌
                      }}
                    />
                  </div>
                  <input
                    id="userId"
                    type="text"
                    inputMode={isStudent ? 'numeric' : 'text'}
                    placeholder={isStudent ? '학번' : '교수자 아이디'}
                    autoComplete="username"
                    value={userId}
                    onChange={(e) =>
                      setUserId(
                        isStudent
                          ? e.target.value.replace(/\D/g, '')
                          : e.target.value.replace(/\s/g, ''),
                      )
                    }
                  />
                </div>
              </div>

              <div className="signup-row">
                <div className="signup-field">
                  <label htmlFor="school">학교</label>
                  <input id="school" name="school" type="text" autoComplete="organization" />
                </div>

                <div className="signup-field">
                  <label htmlFor="major">학과(전공)</label>
                  <input id="major" name="major" type="text" />
                </div>
              </div>

              <div className="signup-row">
                <div className="signup-field">
                  <label htmlFor="password">비밀번호</label>
                  <input
                    id="password"
                    name="password"
                    type="password"
                    placeholder="비밀번호"
                    autoComplete="new-password"
                  />
                </div>

                <div className="signup-field">
                  <label htmlFor="confirmPassword">비밀번호 확인</label>
                  <input
                    id="confirmPassword"
                    name="confirmPassword"
                    type="password"
                    placeholder="비밀번호 확인"
                    autoComplete="new-password"
                  />
                </div>
              </div>

              <div className="signup-field">
                <label htmlFor="email">이메일</label>
                <input
                  id="email"
                  name="email"
                  type="email"
                  placeholder="example@email.com"
                  autoComplete="email"
                />
              </div>

              <div className="signup-field">
                <label htmlFor="phone">전화번호</label>
                <input
                  id="phone"
                  name="phone"
                  type="tel"
                  placeholder="010-1234-5678"
                  autoComplete="tel"
                />
              </div>

              {error && (
                <p className="signup-error" role="alert">
                  {error}
                </p>
              )}

              <button type="submit" className="signup-button" disabled={isSubmitting}>
                {isSubmitting ? '가입 중...' : '회원가입'}
              </button>
            </form>

            <p className="login-text">
              이미 계정이 있으신가요?
              <button type="button" onClick={goLogin}>
                로그인
              </button>
            </p>
          </div>
        </div>
      </main>
    </div>
  )
}
