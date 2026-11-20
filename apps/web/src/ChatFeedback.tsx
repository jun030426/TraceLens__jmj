import { useState } from "react";
import { api } from "./api";

export type FeedbackValue = "understood" | "confused" | "aborted";

export function ChatFeedback({ sectionId, messageId, initial }: {
  sectionId: string; messageId?: string; initial?: FeedbackValue;
}) {
  const [value, setValue] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  if (!messageId) return null;
  const save = async (next: FeedbackValue) => {
    setBusy(true); setError("");
    try {
      await api(`/sections/${sectionId}/chat/messages/${messageId}/feedback`, { method: "PUT", body: JSON.stringify({ value: next }) });
      setValue(next);
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  };
  return <div className="chat-feedback" aria-label="답변 이해도">
    <p>이 설명은 어땠나요?</p>
    {([["understood", "이해했어요"], ["confused", "아직 헷갈려요"], ["aborted", "나중에 다시 볼게요"]] as const).map(([id, label]) =>
      <button key={id} type="button" aria-pressed={value === id} disabled={busy} onClick={() => void save(id)}>{label}</button>)}
    {value && <small role="status">피드백이 저장됐어요.</small>}
    {error && <p role="alert">{error}</p>}
  </div>;
}
