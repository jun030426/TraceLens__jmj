import type { Job } from "./api";

const chatResumeTime = new Intl.DateTimeFormat("ko-KR", {
  timeZone: "Asia/Seoul", month: "long", day: "numeric", hour: "numeric", minute: "2-digit",
});

export function chatDailyWaitMessage(job: Pick<Job, "status" | "error" | "retry_at">): string | undefined {
  if (job.status !== "queued" || job.error?.code !== "GEMINI_DAILY_WAIT" || !job.retry_at) return;
  const resumeAt = Date.parse(job.retry_at);
  if (!Number.isFinite(resumeAt)) return;
  return `오늘 질문 처리 한도에 도달했어요. ${chatResumeTime.format(resumeAt)}(한국 시간)부터 대기 중인 질문을 다시 처리해요.`;
}
export function theoryChatBody(question: string, threadId?: string, conceptId?: string, context?: string) {
  const text = question.trim();
  const prefix = "\n\n[함께 보내는 퀴즈와 내 답안]\n";
  const remaining = 4000 - text.length - prefix.length;
  return {
    thread_id: threadId,
    mode: "theory" as const,
    concept_id: conceptId || undefined,
    message: context && remaining > 0 ? text + prefix + context.slice(0, remaining) : text,
  };
}

export function practiceChatBody(question: string, exerciseId: string, threadId?: string, context?: string) {
  return { thread_id: threadId, mode: "practice" as const, exercise_id: exerciseId,
    message: question.trim(), practice_context: context?.slice(0, 3000) || "" };
}

export const practiceSubmitBody = (exerciseId: string, source: string, editor?: { template: string; fills?: string[] }) =>
  ({ exercise_id: exerciseId, source, ...(editor && { editor }) });

export type TutorChoice = "understood" | "confused" | "stop";
export type Requester = (path: string, options: RequestInit) => Promise<unknown>;
export async function saveTutorChoice(request: Requester, sectionId: string, choice: TutorChoice, messageId?: string, jobId?: string) {
  if (choice === "stop" && jobId) {
    await request(`/jobs/${jobId}/cancel`, { method: "POST", body: "{}" });
    return;
  }
  if (!messageId) throw new Error("답변을 받은 뒤 피드백을 남길 수 있어요.");
  await request(`/sections/${sectionId}/chat/messages/${messageId}/feedback`, {
    method: "PUT", body: JSON.stringify({ value: choice === "stop" ? "aborted" : choice }),
  });
}
