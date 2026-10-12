let csrf = "";
export const setCsrf = (value: string) => {
  csrf = value;
};
export async function api<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.body && !(options.body instanceof FormData))
    headers.set("Content-Type", "application/json");
  if (csrf) headers.set("X-CSRF-Token", csrf);
  const r = await fetch("/api/v1" + path, {
    ...options,
    headers,
    credentials: "same-origin",
  });
  if (r.status === 204) return undefined as T;
  const value = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(value.error?.message || `요청 실패 (${r.status})`);
  return value as T;
}
export const post = (body: unknown): RequestInit => ({
  method: "POST",
  body: JSON.stringify(body),
});
export interface User {
  major: string | null;
  student_number: string | null;
  email: string | null;
  avatar: string | null;
  id: string;
  login_id: string;
  display_name: string;
  role: "student" | "teacher" | "operator";
  must_change_password: boolean;
}
export interface Term {
  id: string;
  name: string;
  starts_on: string;
  ends_on: string;
}
export interface Course {
  id: string;
  title: string;
  term_id: string;
  teaching_language: string;
  revision: number;
  lead_teacher_id: string;
}
export interface Section {
  id: string;
  title: string;
  course_id: string;
  revision: number;
  progress: string[];
  progress_mode?: "auto" | "manual";
}
export interface Concept {
  id: string;
  name: string;
  description: string;
  revision: number;
}
export interface Material {
  learning_status?: string;
  id: string;
  title: string;
  kind: string;
  week: number;
  visibility: string;
  internal_use: string;
  revision: number;
  version: {
    id: string;
    status: string;
    filename: string;
    error_code: string | null;
  } | null;
}
export interface Classroom {
  teacher_name: string;
  current_week: number | null;
  enrollment_id: string;
  status: string;
  section: Section;
  course: Course;
  term: Term;
}
export interface Enrollment {
  id: string;
  student_id: string;
  display_name: string;
  status: string;
}
export interface Citation {
  material_id: string;
  version_id: string;
  title: string;
  locator: Record<string, unknown>;
  excerpt: string;
}
export interface Answer {
  answer: string;
  answer_kind: string;
  citations: Citation[];
}
export interface Job {
  id: string;
  status: string;
  result: Answer | null;
  error: { code: string; retryable: boolean } | null;
}
