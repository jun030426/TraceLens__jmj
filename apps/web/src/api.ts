import { getTestRole } from "./testAccess";
import { testResponse } from "./testData";
import { testChatAsk } from "./testChat";

let csrf = "";
export const setCsrf = (value: string) => {
  csrf = value;
};
export async function api<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  // 테스트용 화면: 서버 대신 샘플 데이터로 답하고, 저장 요청은 보내지 않아요.
  const testRole = getTestRole();
  if (testRole && !path.startsWith("/auth/") && path !== "/me") {
    // 질문하기(AI 질문 · 실습 질문 창)는 저장 대신 예시 답변을 만들어 흐름을 보여 줘요 — testChat.ts
    if (/^\/sections\/[^/]+\/chat\/messages$/.test(path) && (options.method || "GET").toUpperCase() === "POST")
      return testChatAsk(JSON.parse(String(options.body || "{}"))) as T;
    // 오늘의 이론 퀴즈 시작(POST)은 저장이 아니라 문항을 받아오는 요청이라 샘플 문항으로 답해요.
    if ((options.method || "GET").toUpperCase() !== "GET" && !/^\/sections\/[^/]+\/daily$/.test(path))
      throw new Error("테스트 화면에서는 답안을 저장하지 않아요. 문항 보기와 풀이 흐름만 확인할 수 있어요.");
    return testResponse(path, testRole) as T;
  }
  const headers = new Headers(options.headers);
  if (options.body && !(options.body instanceof FormData))
    headers.set("Content-Type", "application/json");
  if (csrf) headers.set("X-CSRF-Token", csrf);
  if ((options.method || "GET").toUpperCase() === "POST" && !headers.has("Idempotency-Key"))
    headers.set("Idempotency-Key", crypto.randomUUID());
  const r = await fetch("/api/v1" + path, {
    ...options,
    headers,
    credentials: "same-origin",
  });
  if (r.status === 204) return undefined as T;
  const value = await r.json().catch(() => ({}));
  if (r.status === 403 && path.startsWith("/admin/") && value.error?.message?.includes("보안 인증"))
    window.dispatchEvent(new Event("lerny-admin-auth"));
  if (!r.ok) throw new Error(value.error?.message || `요청 실패 (${r.status})`);
  return value as T;
}
export const post = (body: unknown): RequestInit => ({
  method: "POST",
  body: JSON.stringify(body),
});
export type UploadConfig = { direct: boolean; max_file_bytes: number; limits?: Record<string, number> };
export type UploadCheckpoint = { upload_id: string; url: string; method?: "PUT" | "MULTIPART"; uploaded: boolean; expires: number };
type UploadOptions = { checkpoint?: UploadCheckpoint; onCheckpoint?: (checkpoint: UploadCheckpoint) => void; onProgress?: (percent: number) => void };
function transfer(url: string, file: File, progress?: (percent: number) => void) {
  return new Promise<void>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("PUT", url); xhr.timeout = 15 * 60 * 1000;
    xhr.setRequestHeader("Content-Type", file.type || "application/octet-stream");
    xhr.setRequestHeader("x-upsert", "false");
    xhr.upload.onprogress = event => { if (event.lengthComputable) progress?.(Math.min(99, Math.round(event.loaded / event.total * 100))); };
    xhr.onload = () => {
      let duplicate = xhr.status === 409;
      try { duplicate ||= xhr.status === 400 && ["Duplicate", "ResourceAlreadyExists"].includes(JSON.parse(xhr.responseText).error); } catch {}
      if ((xhr.status >= 200 && xhr.status < 300) || duplicate) resolve();
      else reject(new Error("파일 전송을 완료하지 못했어요. 연결과 파일 크기를 확인하고 다시 시도해 주세요."));
    };
    xhr.onerror = xhr.ontimeout = () => reject(new Error("파일 전송이 중단됐어요. 미완료 파일만 다시 올려 주세요."));
    xhr.send(file);
  });
}
type MediaPart = { number: number; offset: number; size: number; url: string };
function transferPart(part: MediaPart, file: File, progress: (bytes: number) => void) {
  return new Promise<void>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("PUT", part.url); xhr.timeout = 5 * 60 * 1000;
    // The browser supplies the signed Content-Length for this exact Blob slice.
    xhr.upload.onprogress = event => progress(Math.min(event.loaded, part.size));
    xhr.onload = () => xhr.status >= 200 && xhr.status < 300 ? resolve()
      : reject(new Error("영상 일부의 전송을 완료하지 못했어요. 미완료 파일을 다시 올리면 이어서 전송해요."));
    xhr.onerror = xhr.ontimeout = () => reject(new Error("영상 전송이 중단됐어요. 미완료 파일을 다시 올리면 이어서 전송해요."));
    xhr.send(file.slice(part.offset, part.offset + part.size));
  });
}
async function transferMedia(ticket: UploadCheckpoint, file: File, progress?: (percent: number) => void) {
  const status = await api<{ complete: boolean; uploaded_bytes?: number; parts: MediaPart[] }>(`/uploads/${ticket.upload_id}/parts`, post({}));
  if (status.complete) return;
  let completed = status.uploaded_bytes || 0;
  progress?.(Math.min(99, Math.round(completed / file.size * 100)));
  for (const part of status.parts) {
    await transferPart(part, file, loaded => progress?.(Math.min(99, Math.round((completed + loaded) / file.size * 100))));
    completed += part.size;
  }
}
/** Session-authorized private uploads. Retain the completion ticket for safe retries. */
export async function uploadMaterial(courseId: string, form: FormData, replacement?: { id: string; revision: number }, options: UploadOptions = {}) {
  const kind = String(form.get("kind") || "");
  if (!replacement && !kind) throw new Error("자료 종류를 선택해 주세요.");
  if (kind === "answer") form.set("visibility", "private");
  const config = await api<UploadConfig>("/uploads/config");
  const file = form.get("file");
  if (!(file instanceof File) || !file.size) throw new Error("파일을 선택해 주세요.");
  const suffix = "." + file.name.split(".").pop()!.toLowerCase();
  const limit = config.limits?.[suffix] ?? config.max_file_bytes;
  if (file.size > limit) throw new Error(`이 형식은 파일당 ${limit / 1024 / 1024}MB까지 올릴 수 있어요.`);
  if (!config.direct) {
    options.onProgress?.(0);
    const result = await api(replacement ? `/materials/${replacement.id}/versions` : `/courses/${courseId}/materials`, {
      method: "POST", body: form,
      headers: replacement ? { "If-Match": String(replacement.revision) } : undefined,
    });
    options.onProgress?.(100); return result;
  }
  let ticket = options.checkpoint;
  if (!ticket || ticket.expires <= Date.now()) {
    const prepared = await api<{ upload_id: string; url: string; method?: "PUT" | "MULTIPART" }>(`/courses/${courseId}/uploads`, post({
      filename: file.name, size: file.size,
      kind: kind || undefined, week: Number(form.get("week") || 1),
      visibility: String(form.get("visibility") || "public"),
      material_id: replacement?.id, revision: replacement?.revision,
    }));
    ticket = { ...prepared, uploaded: false, expires: Date.now() + 110 * 60 * 1000 };
    options.onCheckpoint?.(ticket);
  }
  if (!ticket.uploaded) {
    if (ticket.method === "MULTIPART") await transferMedia(ticket, file, options.onProgress);
    else await transfer(ticket.url, file, options.onProgress);
    ticket = { ...ticket, uploaded: true }; options.onCheckpoint?.(ticket);
  }
  options.onProgress?.(100);
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
  view_url?: string;
  content_generation_mode?: "weekly";
  learning_status?: string;
  processing_job_id?: string | null;
  processing_status?: string | null;
  processing_stage?: string | null;
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
  /** 학생 프로필의 전공(학과)·학번 — 수강생 목록에 함께 보여요. */
  major?: string | null;
  student_number?: string | null;
}
export interface Citation {
  material_id: string;
  version_id: string;
  title: string;
  locator: Record<string, unknown>;
  excerpt: string;
}
export interface Answer {
  message_id?: string;
  answer: string;
  answer_kind: string;
  citations: Citation[];
  /** 서버가 반환한 추가 확인 질문 */
  follow_up?: string;
}
export interface Job {
  id: string;
  status: string;
  result: Answer | null;
  error: { code: string; retryable: boolean } | null;
  ai_status?: string | null;
}
