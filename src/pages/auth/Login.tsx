/**
 * [로그인 페이지] 주소: /login
 * - 아이디 하나로 로그인 (학생/교수자 선택 버튼 없음)
 * - 서버(api/authApi.ts 의 login)가 돌려준 role 로 학생이면 /student, 교수자면 /professor 로 이동
 *   (mock 모드에서는 숫자로만 된 아이디 = 학생으로 판단)
 */

import { useState } from 'react'
import type { ChangeEvent, FormEvent } from 'react'
import Logo from '../../components/common/Logo'
import { AuthBackButton, AuthBackground, AuthIllustration } from '../../components/auth/AuthDecor'
import { useAuth } from '../../hooks/useAuth'
import { login as loginRequest } from '../../api/authApi'
import { ApiError } from '../../api/client'

export default function Login() {
  const { login } = useAuth()
  const [userId, setUserId] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)

  const goSignup = () => {
    window.location.href = '/signup'
  }

  // 아이디: 띄어쓰기만 빼고 그대로 받음
  const handleIdChange = (e: ChangeEvent<HTMLInputElement>) => {
    setUserId(e.target.value.replace(/\s/g, ''))
    if (error) setError('')
  }

  const handlePasswordChange = (e: ChangeEvent<HTMLInputElement>) => {
    setPassword(e.target.value)
    if (error) setError('')
  }

  const handleSubmit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault()

    if (!userId) {
      setError('아이디를 입력해주세요.')
      return
    }
    if (!password) {
      setError('비밀번호를 입력해주세요.')
      return
    }

    setIsSubmitting(true)
    try {
      // 서버가 아이디·비밀번호를 확인하고 세션 쿠키를 내려줘요
      const user = await loginRequest(userId, password)
      login()
      window.location.href = user.role === 'student' ? '/student' : '/professor'
    } catch (err) {
      setError(
        err instanceof ApiError && err.status !== 401
          ? err.message
          : '아이디 또는 비밀번호가 올바르지 않습니다.',
      )
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <div className="login-page">
      <AuthBackground prefix="login" />
      <AuthBackButton prefix="login" />

      <main className="login-area">
        <div className="login-shell">
          {/* 왼쪽: 폼 */}
          <div className="login-panel-left">
            <div className="login-logo">
              <Logo />
            </div>

            <div className="login-heading">
              <h1>Login</h1>
              <p>계정에 로그인하여 학습을 시작해보세요.</p>
            </div>

            <form className="login-form" onSubmit={handleSubmit} noValidate>
              <div className="login-field">
                <label htmlFor="userId">아이디</label>
                <input
                  id="userId"
                  name="userId"
                  type="text"
                  autoComplete="username"
                  placeholder="아이디를 입력하세요"
                  value={userId}
                  onChange={handleIdChange}
                  aria-invalid={!!error}
                  aria-describedby={error ? 'login-error' : undefined}
                />
              </div>

              <div className="login-field">
                <label htmlFor="password">비밀번호</label>
                <input
                  id="password"
                  name="password"
                  type="password"
                  autoComplete="current-password"
                  placeholder="비밀번호를 입력하세요"
                  value={password}
                  onChange={handlePasswordChange}
                  aria-invalid={!!error}
                  aria-describedby={error ? 'login-error' : undefined}
                />
              </div>

              <div className="login-meta">
                {error ? (
                  <p id="login-error" className="login-error" role="alert">
                    {error}
                  </p>
                ) : (
                  <span />
                )}
                <button type="button" className="forgot-password">
                  아이디 / 비밀번호 찾기
                </button>
              </div>

              <button type="submit" className="login-button" disabled={isSubmitting}>
                {isSubmitting ? '로그인 중...' : '로그인'}
              </button>
            </form>

            <p className="signup-text">
              계정이 없으신가요?
              <button type="button" onClick={goSignup}>
                회원가입
              </button>
            </p>
          </div>

          {/* 오른쪽: 컬러 패널 + 일러스트 */}
          <AuthIllustration className="login-panel-right" />
        </div>
      </main>
    </div>
  )
}
