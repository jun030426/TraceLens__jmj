// Request bodies shared by the UI and contract tests. Server remains authoritative.
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

export const practiceSubmitBody = (exerciseId: string, source: string) => ({ exercise_id: exerciseId, source });

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
