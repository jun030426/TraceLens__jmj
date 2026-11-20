import { useCallback, useEffect, useState } from "react";
import { api, post } from "./api";
import { ErrorNotice } from "./components";
import { type ConceptVideo, videoState } from "./Instructor";
import { featureBlock, useServiceStatus } from "./ServiceStatus";
import {
  jobMessage,
  jobTone,
  taskName,
  toneName,
  type Processing,
  type MaterialProgress,
} from "./materialProcessing";

export function MediaProcessingProgress({ progress }: { progress: MaterialProgress }) {
  if (progress.tone === "unknown") return null;
  const job = progress.jobs.find(j => j.kind === "extract" && j.is_current !== false && j.progress && ["running", "queued", "failed"].includes(j.status));
  const value = job?.progress;
  if (!value || !job) return null;
  const paused = job.status !== "running";
  const stopped = job.status === "failed";
  return <div className={`media-stage-progress${paused ? " is-paused" : ""}`}>
    <div><strong>{value.label}{paused ? " · 마지막 진행" : ""}</strong><span>{stopped ? "처리 중단" : paused ? "재개 대기" : value.percent === null ? "진행 확인 중" : `${value.percent}%`}</span></div>
    {!stopped && <progress aria-label={`${value.label} 단계 진행률`} max={100} value={value.percent ?? (paused ? 0 : undefined)} />}
    <small>{stopped ? "현재 처리 중이 아니에요. 원본과 저장된 분석 결과는 유지돼요." : value.total === null ? (paused ? "처리를 재개하면 진행률이 갱신돼요." : "이 단계는 완료량을 계산하고 있어요.") : `${value.completed}/${value.total}${value.unit} 완료 · 현재 단계 기준`}</small>
    <small>{value.stage.startsWith('document_') ? '문서 페이지 준비 → 내용 판독·검증 → 근거 정리 → 검색 준비' : value.stage.startsWith('local_') ? '음성 인식 → 기초 검사 → 로컬 OCR → 정상·보류 분리' : '음성 인식 → 원음 검토 → 화면 분석 → 결과 검증'}</small>
  </div>;
}

export function useCourseProcessing(courseId: string, enabled: boolean) {
  const [revision, setRevision] = useState(0);
  const [snapshot, setSnapshot] = useState<{
    courseId: string;
    items?: Processing[];
    videos?: ConceptVideo[];
    error: string;
    videoError: string;
  }>();
  const reload = useCallback(() => setRevision((value) => value + 1), []);
  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    void Promise.allSettled([
      api<{ items: Processing[] }>(`/courses/${courseId}/processing`, {
        signal: controller.signal,
      }),
      api<{ items: ConceptVideo[] }>(`/courses/${courseId}/concept-videos`, {
        signal: controller.signal,
      }),
    ]).then(([progress, videos]) => {
      if (controller.signal.aborted) return;
      setSnapshot((old) => ({
        courseId,
        items:
          progress.status === "fulfilled"
            ? progress.value.items
            : old?.courseId === courseId
              ? old.items
              : undefined,
        videos:
          videos.status === "fulfilled"
            ? videos.value.items
            : old?.courseId === courseId
              ? old.videos
              : undefined,
        error:
          progress.status === "rejected"
            ? "자료 처리 상태를 불러오지 못했어요."
            : "",
        videoError:
          videos.status === "rejected" ? "영상 상태를 불러오지 못했어요." : "",
      }));
    });
    return () => controller.abort();
  }, [courseId, enabled, revision]);
  useEffect(() => {
    if (!enabled) return;
    const refresh = () => {
      if (!document.hidden) reload();
    };
    const timer = window.setInterval(refresh, 15000);
    document.addEventListener("visibilitychange", refresh);
    return () => {
      clearInterval(timer);
      document.removeEventListener("visibilitychange", refresh);
    };
  }, [enabled, reload]);
  const data =
    enabled && snapshot?.courseId === courseId ? snapshot : undefined;
  return {
    items: data?.items,
    videos: data?.videos || [],
    error: data?.error || "",
    videoError: data?.videoError || "",
    reload,
  };
}

export function MaterialProcessingDetails({
  courseId,
  progress,
  videos,
  videoError,
  onChange,
}: {
  courseId: string;
  progress: MaterialProgress;
  videos: ConceptVideo[];
  videoError: string;
  onChange: () => void;
}) {
  const service = useServiceStatus();
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const block = (feature: string) =>
    featureBlock(service.data, feature, service.error);
  const retry = async (path: string, feature: string) => {
    if (busy || block(feature)) return;
    setBusy(path);
    setError("");
    setMessage("");
    try {
      await api(path, post({}));
      setMessage("재시도를 요청했어요. 처리 상태가 자동으로 갱신돼요.");
      onChange();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy("");
    }
  };
  return (
    <section
      className="teacher-processing-detail"
      aria-label="자료별 처리 단계"
    >
      <ol className="teacher-processing-steps">
        {progress.stages.map((step, i) => (
          <li key={step.name} className={`tone-${step.tone}`}>
            <span>
              {i + 1}. {step.name}
            </span>
            <strong>{step.text}</strong>
            {step.hint && <p>{step.hint}</p>}
          </li>
        ))}
      </ol>
      <ErrorNotice text={error} />
      {message && <p role="status">{message}</p>}
      {!!progress.jobs.length && (
        <details className="teacher-processing-jobs">
          <summary>세부 작업 · {progress.jobs.length}개</summary>
          <ul>
            {progress.jobs.map((job) => {
              const feature = ["extract", "embed"].includes(job.kind)
                ? "uploads"
                : job.kind === "narration_lesson"
                  ? "videos"
                  : "content";
              const disabledReason = block(feature);
              return (
                <li key={job.id}>
                  <div>
                    <strong>{taskName[job.kind] || "자료 처리"}</strong>
                    <span
                      className={`teacher-progress-badge tone-${jobTone(job)}`}
                    >
                      {toneName[jobTone(job)]}
                    </span>
                  </div>
                  <p>{jobMessage(job)}</p>
                  {job.retry_at && (
                    <p className="muted">
                      다음 재시도 예정:{" "}
                      {new Date(job.retry_at).toLocaleString("ko-KR", {
                        timeZone: "Asia/Seoul",
                      })}
                      {disabledReason ? " · 서비스 재개 후 처리" : ""}
                    </p>
                  )}
                  {job.retryable && (
                    <>
                      <button
                        type="button"
                        disabled={!!busy || !!disabledReason}
                        onClick={() =>
                          void retry(`/jobs/${job.id}/retry`, feature)
                        }
                      >
                        {busy ? "요청 중…" : "이 작업 다시 시도"}
                      </button>
                      {disabledReason && <small>{disabledReason}</small>}
                    </>
                  )}
                  {job.error_code && (
                    <details>
                      <summary>오류 정보</summary>
                      <code>{job.error_code}</code>
                    </details>
                  )}
                </li>
              );
            })}
          </ul>
        </details>
      )}
      <details className="teacher-processing-videos">
        <summary>
          개념 영상 · {videos.filter((v) => v.status === "ready").length}/
          {videos.length}개 준비
        </summary>
        <ErrorNotice text={videoError} />
        {!videos.length && !videoError && (
          <p>
            생성된 영상 작업이 없어요. 영상은 자료와 서비스 설정에 따라 별도로
            준비돼요.
          </p>
        )}
        <ul>
          {[...videos]
            .sort((a, b) => a.position - b.position)
            .map((video) => (
              <li key={video.id}>
                <strong>{video.title}</strong>
                <span>{videoState(video.status)}</span>
                {["failed", "held", "needs_attention"].includes(
                  video.status,
                ) && (
                  <p>
                    {jobMessage({
                      status: video.status,
                      error_code: video.error_code || null,
                      result_status: null,
                    })}
                  </p>
                )}
                {["failed", "held"].includes(video.status) && (
                  <button
                    type="button"
                    disabled={!!busy || !!block("videos")}
                    onClick={() =>
                      void retry(
                        `/courses/${courseId}/concept-videos/${video.id}/retry`,
                        "videos",
                      )
                    }
                  >
                    영상 상태 확인·재시도
                  </button>
                )}
                {video.play_url && (
                  <a href={video.play_url} target="_blank" rel="noreferrer">
                    영상 확인
                  </a>
                )}
              </li>
            ))}
        </ul>
      </details>
      {!!progress.history.length && (
        <details className="teacher-processing-history">
          <summary>이전 처리 이력 · {progress.history.length}개</summary>
          <p>새 작업으로 대체된 기록이에요. 현재 상태에는 반영하지 않아요.</p>
          <ul>
            {progress.history.map((job) => (
              <li key={job.id}>
                {taskName[job.kind] || job.kind} · {toneName[jobTone(job)]}
                {job.error_code && <code>{job.error_code}</code>}
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}
