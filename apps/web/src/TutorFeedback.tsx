import { useRef, useState } from "react";
import { api } from "./api";
import { saveTutorChoice, type TutorChoice } from "./learningRequests";

export function TutorFeedback({ sectionId, messageId, jobId, disabled, onStop, onConfused, onBusyChange }: {
  sectionId: string; messageId?: string; jobId?: string; disabled?: boolean;
  onStop: () => void; onConfused: () => Promise<void>; onBusyChange: (busy: boolean) => void;
}) {
  const [value, setValue] = useState<{ messageId: string; kind: TutorChoice }>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const inFlight = useRef(false);
  const choose = async (kind: TutorChoice) => {
    if (inFlight.current || disabled) return;
    inFlight.current = true; setBusy(true); onBusyChange(true); setError(""); setNote("");
    try {
      await saveTutorChoice(api, sectionId, kind, messageId, jobId);
      if (!jobId && messageId) setValue({ messageId, kind });
      if (kind === "stop" && jobId) {
        onStop();
        setNote("대화를 중단했어요. 다음 질문은 새 대화로 시작해요.");
      } else if (kind === "stop") {
        setNote("모르겠어요로 기록했어요. 이해가 안 된 부분을 이어서 물어보세요.");
      }
      else if (kind === "confused") await onConfused();
      else setNote("이해했어요! 궁금한 점이 생기면 다시 물어보세요.");
    } catch (e) { setError((e as Error).message); }
    finally { inFlight.current = false; setBusy(false); onBusyChange(false); }
  };
  return <>
    <div className="practice-chat__feedback chat-feedback" role="group" aria-label="지금 내 상태">
      {([["understood", "💡", "이해했어요"], ["confused", "❓", "헷갈려요"], ["stop", "🤯", "모르겠어요"]] as const).map(([kind, icon, label]) =>
        <button key={kind} type="button" className={`is-${kind}`} aria-pressed={value?.messageId === messageId && value?.kind === kind} disabled={busy || disabled || (kind === "stop" ? !jobId && !messageId : !!jobId || !messageId)} onClick={() => void choose(kind)}><span aria-hidden="true">{kind === "stop" && jobId ? "🛑" : icon}</span> {kind === "stop" && jobId ? "답변 멈추기" : label}</button>)}
    </div>
    {note && <p className="practice-chat__status chat-feedback-note" role="status">{note}</p>}
    {error && <p className="practice-chat__error" role="alert">{error}</p>}
  </>;
}
