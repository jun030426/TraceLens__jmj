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

/** Authorize with the app session; upload bytes directly to private Storage. */
export async function uploadMaterial(courseId: string, form: FormData, replacement?: { id: string; revision: number }) {
  const config = await api<{ direct: boolean; max_file_bytes: number }>("/uploads/config");
  if (!config.direct) {
    return api(replacement ? `/materials/${replacement.id}/versions` : `/courses/${courseId}/materials`, {
      method: "POST", body: form,
      headers: replacement ? { "If-Match": String(replacement.revision) } : undefined,
    });
  }
  const file = form.get("file");
  if (!(file instanceof File) || !file.size) throw new Error("파일을 선택해 주세요.");
  if (file.size > config.max_file_bytes) throw new Error(`현재 파일 크기 제한은 ${config.max_file_bytes / 1024 / 1024}MB입니다.`);
  const ticket = await api<{ upload_id: string; url: string }>(`/courses/${courseId}/uploads`, post({
    filename: file.name, size: file.size,
    kind: String(form.get("kind") || "lecture"), week: Number(form.get("week") || 1),
    visibility: String(form.get("visibility") || "public"),
    internal_use: String(form.get("internal_use") || "none"),
    material_id: replacement?.id, revision: replacement?.revision,
  }));
  const uploaded = await fetch(ticket.url, {
    method: "PUT", credentials: "omit",
    headers: { "Content-Type": file.type || "application/octet-stream", "x-upsert": "false" },
    body: file,
  });
  if (!uploaded.ok) throw new Error("파일 업로드를 완료하지 못했어요. 연결과 파일 크기를 확인해 주세요.");
  return api(`/uploads/${ticket.upload_id}/complete`, post({}));
}
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
  processing_job_id?: string | null;
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
  ai_status?: string | null;
}
