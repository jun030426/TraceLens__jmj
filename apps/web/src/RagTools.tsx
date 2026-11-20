import { useEffect, useState } from "react";
import { api, post } from "./api";
import { ErrorNotice, useLoad } from "./components";

type Status = { provider: string; eligible_chunks: number; indexed_chunks: number; index_ready: boolean; calls_enabled: boolean; key_configured: boolean };
type Progress = { status: string; result: { index_ready?: boolean } | null; error: { code: string } | null };

export function RagTools({ courseId, blockedReason = "" }: { courseId: string; blockedReason?: string }) {
  const status = useLoad<Status>(`/courses/${courseId}/rag/status`);
  const [job, setJob] = useState<string>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const reload = status.reload;
  useEffect(() => {
    if (!job) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const result = await api<Progress>(`/jobs/${job}`, { signal: controller.signal });
        if (controller.signal.aborted) return;
        if (result.status === "succeeded") {
          setMessage(result.result?.index_ready ? "자료 검색 준비가 완료됐어요." : "일부 자료를 준비했어요. 남은 자료의 준비를 이어갈 수 있어요.");
          setJob(undefined); setBusy(false); reload();
        } else if (["failed", "cancelled"].includes(result.status)) {
          setError("자료 준비를 완료하지 못했어요. 처리 상태를 확인한 뒤 다시 시도해 주세요.");
          setJob(undefined); setBusy(false);
        } else if (result.status === "waiting_ai") {
          setMessage("AI 연결을 기다리고 있어요.");
          timer = setTimeout(poll, 5000);
        } else timer = setTimeout(poll, 2000);
      } catch (e) {
        if (!controller.signal.aborted) { setError((e as Error).message); setJob(undefined); setBusy(false); }
      }
    };
    void poll();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [job, reload]);

  const prepare = async () => {
    if (blockedReason) return;
    setBusy(true); setError(""); setMessage("");
    try {
      const result = await api<{ job_id: string }>(`/courses/${courseId}/rag/reindex`, post({}));
      setJob(result.job_id);
    } catch (e) { setError((e as Error).message); setBusy(false); }
  };
  if (status.data?.provider !== "gemini") return status.error ? <ErrorNotice text={status.error} /> : null;
  const ready = status.data.index_ready;
  const enabled = status.data.calls_enabled && status.data.key_configured;
  return <section className="material-detail-state" aria-label="자료 검색 준비">
    <strong>{ready ? "자료 검색 준비 완료" : "자료 검색 준비"}</strong>
    <p>{status.data.eligible_chunks}개 검색 단위 중 {status.data.indexed_chunks}개가 준비됐어요.</p>
    {!enabled && <p>AI 연결 설정이 완료되면 자료 검색을 준비할 수 있어요. 파일 등록과 원문 확인은 계속 이용할 수 있어요.</p>}
    {blockedReason && <p>{blockedReason}</p>}
    <button disabled={!!blockedReason || !enabled || busy || ready || !status.data.eligible_chunks} onClick={() => void prepare()}>{busy ? "자료 준비 중…" : "자료 검색 준비하기"}</button>
    <button disabled={busy} onClick={reload}>상태 새로고침</button>
    {message && <p role="status">{message}</p>}
    <ErrorNotice text={error} />
  </section>;
}
