import type { User } from "./api";

// Demo data is opt-in for local design review. Production always uses real sessions.
const env = (import.meta as unknown as { env?: Record<string, string | boolean | undefined> }).env || {};
export const SHOW_TEST_ROLE_BUTTONS = env.DEV === true && env.VITE_ENABLE_DEMO === "true";

export type TestRole = User["role"];

const KEY = "lerny-test-role";

export const TEST_ROLES: { role: TestRole; label: string; hint: string }[] = [
  { role: "student", label: "학생용 화면", hint: "홈 · 내 강의" },
  { role: "teacher", label: "교수자용 화면", hint: "강의 목록 · 수강생" },
  { role: "operator", label: "운영자용 화면", hint: "운영 관리" },
];

// Never embed account passwords in VITE_* variables or browser bundles.
export function testAccount(_role: TestRole): { login_id: string; password: string } | null {
  return null;
}

export function getTestRole(): TestRole | null {
  if (!SHOW_TEST_ROLE_BUTTONS) return null;
  try {
    const value = sessionStorage.getItem(KEY);
    return value === "student" || value === "teacher" || value === "operator" ? value : null;
  } catch {
    return null;
  }
}

export function setTestRole(role: TestRole | null) {
  try {
    if (role) sessionStorage.setItem(KEY, role);
    else sessionStorage.removeItem(KEY);
  } catch {
    /* Storage may be disabled. */
  }
}

export function isTestUser(user: User | null) {
  return !!user?.id.startsWith("test-");
}

export function testUser(role: TestRole): User {
  const name = { student: "테스트 학생", teacher: "테스트 교수", operator: "테스트 운영자" }[role];
  return {
    id: `test-${role}`,
    login_id: `test_${role}`,
    display_name: name,
    role,
    must_change_password: false,
    major: null,
    student_number: null,
    email: null,
    avatar: null,
  };
}
