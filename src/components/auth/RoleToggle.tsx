/**
 * [회원가입 전용 컴포넌트] 아이디 칸 옆 [학번 | 교수자] 선택 버튼
 */

export type UserRole = 'student' | 'professor'

const ROLES: { value: UserRole; label: string }[] = [
  { value: 'student', label: '학번' },
  { value: 'professor', label: '교수자' },
]

interface RoleToggleProps {
  value: UserRole
  onChange: (role: UserRole) => void
}

export default function RoleToggle({ value, onChange }: RoleToggleProps) {
  return (
    <div className="role-toggle" role="radiogroup" aria-label="아이디 종류">
      {ROLES.map((r) => (
        <button
          key={r.value}
          type="button"
          role="radio"
          aria-checked={value === r.value}
          className={value === r.value ? 'active' : undefined}
          onClick={() => onChange(r.value)}
        >
          {r.label}
        </button>
      ))}
    </div>
  )
}
