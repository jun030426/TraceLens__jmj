import type { Material } from "./api";

export type MediaProgress = {
  stage: string; label: string; unit: string;
  completed: number; total: number | null; percent: number | null; updated_at: string | null;
};
export type ProcessingJob = {
  progress?: MediaProgress | null;
  id: string;
  kind: string;
  status: string;
  is_current: boolean;
  retryable: boolean;
  concept_id: string | null;
  error_code: string | null;
  result_status: string | null;
  retry_at: string | null;
};
export type Processing = {
  held_count?: number;
  extraction_pipeline?: string;
  material_id: string;
  version_id: string;
  source_status: string;
  jobs: ProcessingJob[];
};
export type Tone =
  "running" | "pending" | "held" | "failed" | "ready" | "neutral" | "unknown";
export type Stage = { name: string; tone: Tone; text: string; hint: string };
export type MaterialProgress = Stage & {
  stages: Stage[];
  jobs: ProcessingJob[];
  history: ProcessingJob[];
};

export const taskName: Record<string, string> = {
  extract: "원문 분석",
  embed: "AI 자료 검색 준비",
  auto_concepts: "개념 구성",
  weekly_content: "주차 자료 통합·개념 구성",
  questions: "이론 문항 생성",
  practice_prepare: "실습 준비",
  narration_lesson: "영상 대본 준비",
};
export function jobMessage(
  job: Pick<ProcessingJob, "error_code" | "status" | "result_status">,
) {
  if (job.status === "succeeded")
    return job.result_status === "no_verified_source_code"
      ? "검증 가능한 예제 코드가 없어 실습은 생성하지 않았어요. 코드가 포함된 자료를 추가해 주세요."
      : "처리가 완료됐어요.";
  const known: Record<string, string> = {
    MANUAL_GENERATION_REQUIRED: "주차별 콘텐츠 생성에서 자료를 모아 생성해 주세요.",
    CONTENT_GENERATION_REVOKED: "이 생성은 중단됐어요. 현재 주차의 생성 결과를 확인해 주세요.",
    CONTENT_SOURCES_CHANGED: "주차 자료가 변경됐어요. 현재 자료로 다시 생성해 주세요.",
    SHORTS_NARRATION_LENGTH: "영상 대본을 정해진 길이로 조정하지 못했어요. 주차 검토 화면에서 다시 시도해 주세요.",
    SCRIPT_VALIDATION_FAILED: "영상 대본의 내용을 강의 원문 근거로 확인하지 못해 영상 제작을 보류했어요. 생성 작업을 다시 시도하고, 반복되면 해당 개념의 설명 자료를 보완해 주세요.",
    INVALID_CITATION: "생성한 내용의 인용문이나 출처가 강의 원문과 맞지 않아 중단했어요. 생성 작업을 다시 시도해 주세요.",
    GEMINI_DEDICATED_WORKER_REQUIRED:
      "AI 전용 처리 서버로 작업을 연결하지 못했어요. ‘이 작업 다시 시도’를 눌러 주세요. 계속 실패하면 관리자에게 문의해 주세요.",
    INVALID_MP4: "영상 내용을 읽지 못했어요. 재생 가능한 MP4로 다시 저장해 올려 주세요.",
    MEDIA_WHISPER_NOT_READY: "영상 음성 분석 모델을 준비해야 해요. 관리자에게 문의해 주세요.",
    MEDIA_VIDEO_LIMIT: "영상은 2시간·4K 이하로 나누어 올려 주세요.",
    MEDIA_TASKS_INCOMPLETE: "영상의 일부 구간 분석을 완료하지 못했어요. 관리자에게 확인을 요청해 주세요.",
    MEDIA_PROCESSING_FAILED: "영상 분석을 완료하지 못했어요. 원본 재생 여부와 서버 처리 상태를 확인해 주세요.",
    MEDIA_MEMORY_LIMIT: "영상 처리 메모리 한도에 도달해 중단됐어요. 관리자에게 확인을 요청해 주세요.",
    MEDIA_WORKER_INTERRUPTED: "영상 처리가 반복 중단되어 자동 재시도를 멈췄어요. 관리자에게 처리 서버 확인을 요청해 주세요.",
    MEDIA_TIMEOUT: "영상 분석 시간이 한도를 넘었어요. 영상을 나누어 올려 주세요.",
    DOCUMENT_CHECKPOINT_PENDING: "완료한 문서 검증을 저장했어요. 잠시 후 남은 페이지를 이어서 처리해요.",
    DOCUMENT_TOOLS_NOT_READY: "문서 판독에 필요한 처리 도구를 준비해야 해요. 관리자에게 문의해 주세요.",
    DOCUMENT_RENDER_FAILED: "문서의 페이지 화면을 만들지 못했어요. 파일이 정상적으로 열리는지 확인해 주세요.",
    DOCUMENT_VALIDATION_INCOMPLETE: "문서의 일부 페이지 검증을 완료하지 못했어요. 저장된 결과는 유지돼요. 관리자에게 확인을 요청해 주세요.",
    DOCUMENT_MODEL_REVIEW_FAILED: "문서 판독 응답을 검증하지 못했어요. 저장된 결과는 유지돼요. 다시 시도해도 실패하면 관리자에게 문의해 주세요.",
    DOCUMENT_GEMINI_REQUIRED: "문서 검증에 필요한 Gemini 연결을 확인해야 해요. 관리자에게 문의해 주세요.",
    DOCUMENT_SOURCE_CHANGED: "문서 또는 공개 범위가 변경되어 처리를 중단했어요. 현재 자료를 확인해 주세요.",
    DOCUMENT_JOB_CANCELLED: "문서 처리 작업이 취소되거나 실행 권한이 만료됐어요. 현재 작업 상태를 확인해 주세요.",
    DOCUMENT_RECEIPT_INVALID: "저장된 문서 검증 근거가 일치하지 않아 사용을 보류했어요. 관리자에게 문의해 주세요.",
    DOCUMENT_SELECTION_INVALID: "문서 검증 결과가 기준을 충족하지 않아 사용을 보류했어요. 관리자에게 문의해 주세요.",
    GEMINI_INPUT_BUDGET_EXCEEDED: "AI 검토 요청의 입력량 한도에 걸려 중단됐어요. 원본과 저장된 분석 결과는 유지돼요. 관리자에게 처리 설정 확인을 요청해 주세요.",
    GEMINI_MEDIA_INPUT_INVALID: "AI 검토용 음성·이미지 구간을 읽지 못했어요. 원본은 유지돼요. 관리자에게 분석 결과 확인을 요청해 주세요.",
    GEMINI_MEDIA_INPUT_UNSUPPORTED: "AI 검토용 미디어 형식을 처리하지 못했어요. 관리자에게 확인을 요청해 주세요.",
    GEMINI_MEDIA_PAYLOAD_TOO_LARGE: "AI 검토용 구간 크기가 전송 한도를 넘었어요. 원본은 유지돼요. 관리자에게 구간 분할 확인을 요청해 주세요.",
    GEMINI_CALL_BUDGET_EXCEEDED: "자료 한 건의 AI 분석 한도에 도달했어요. 관리자가 처리 범위와 재시도를 확인해야 해요.",
    LEGACY_BACKFILL_DEFERRED:
      "이전 자료의 자동 생성을 보류했어요. 관리자에게 재개 여부를 확인해 주세요.",
    LOCAL_MODEL_MISSING:
      "생성에 필요한 모델 설정을 확인해야 해요. 관리자에게 문의해 주세요.",
    GEMINI_RATE_LIMITED:
      "AI 요청 한도로 잠시 기다리고 있어요. 같은 요청을 반복하지 않아도 돼요.",
    GEMINI_DAILY_WAIT:
      "AI의 일일 사용 한도로 대기 중이에요. 사용 가능해지면 이어서 처리해요.",
    GEMINI_PACING_WAIT: "AI 요청 간격에 맞춰 처리 순서를 기다리고 있어요.",
    MEDIA_CONTINUATION_WAIT: "완료한 분석을 저장했어요. 잠시 후 남은 구간을 이어서 처리해요.",
    MEDIA_REFERENCE_WAIT: "같은 주차 PPT를 먼저 준비하고 있어요. 완료되면 그림 분석 결과를 재사용해 영상을 이어서 처리해요.",
    GEMINI_TEMPORARILY_UNAVAILABLE: "AI 서비스의 일시적인 응답 지연으로 기다리고 있어요. 저장된 결과부터 자동으로 이어서 처리해요.",
    GEMINI_SERVICE_RETRY_EXHAUSTED: "AI 서비스 오류가 5회 반복되어 자동 재시도를 멈췄어요. 원본과 완료된 분석은 보존돼요. 잠시 후 ‘이 작업 다시 시도’를 누르면 저장된 결과부터 이어서 처리해요.",
    GEMINI_QUOTA_UNAVAILABLE:
      "AI 연결 상태를 확인해야 해요. 오래 지속되면 관리자에게 문의해 주세요.",
    SOURCE_REVOKED:
      "자료가 변경되거나 비공개로 전환되어 중단됐어요. 현재 자료의 공개 범위를 확인해 주세요.",
    INVALID_CONCEPT_EVIDENCE:
      "개념 보정 후에도 명칭·인용문·출처가 같은 원문과 일치하지 않아 중단했어요. 생성 작업을 다시 시도해 주세요.",
    CONCEPT_QUOTE_TOO_SHORT:
      "생성한 개념의 인용문이 5자보다 짧아 원문으로 보정을 요청했지만 기준을 충족하지 못했어요. 생성 작업을 다시 시도해 주세요.",
    CONCEPT_RESPONSE_INVALID:
      "개념 응답의 형식이나 인용문 길이가 보정 후에도 기준에 맞지 않아 중단했어요. 생성 작업을 다시 시도해 주세요.",
    SUBMISSION_UNCERTAIN_DO_NOT_RESUBMIT:
      "영상 요청의 접수 여부를 확인해야 해요. 중복 요청하지 말고 관리자에게 문의해 주세요.",
    VIDEO_STORAGE_SIZE_LIMIT:
      "영상 크기가 저장 한도를 넘었어요. 관리자에게 문의해 주세요.",
    HEYGEN_API_CREDITS_REQUIRED:
      "HeyGen API 크레딧이 부족해 영상 제작을 대기하고 있어요. API 크레딧 충전 후 실패한 영상에서 다시 시도해 주세요. 대본과 완료된 영상은 유지돼요.",
    PROVIDER_TERMINAL_FAILURE:
      "영상 제공 서비스가 제작 실패를 확정했어요. 관리자에게 상세 원인 확인을 요청해 주세요.",
    VIDEO_PREPARATION_FAILED:
      "영상에 넣을 자료 화면을 준비하지 못했어요. 대본은 보존돼요. 다시 시도하거나 관리자에게 문의해 주세요.",
    VIDEO_PROFILE_REVIEW_REQUIRED:
      "이전 영상 제작 설정을 확인해야 해요. 기존 영상은 보존되며 자동 재생성하지 않아요.",
    VIDEO_RENDER_PROFILE_MISMATCH:
      "완성 영상이 지정한 모델·화질·강사 설정과 달라 보류했어요. 관리자에게 문의해 주세요.",
    PROVIDER_REQUIRES_REVIEW:
      "영상 제공 서비스의 검토가 필요해요. 관리자에게 문의해 주세요.",
  };
  if (job.error_code && known[job.error_code]) return known[job.error_code];
  if (job.status === "failed")
    return "처리를 완료하지 못했어요. 다시 시도해도 실패하면 상세 오류 정보를 관리자에게 알려 주세요.";
  if (["held", "needs_attention"].includes(job.status))
    return "처리 결과를 확인해야 해요. 관리자에게 문의해 주세요.";
  if (["cancelled", "revoked"].includes(job.status))
    return "취소되거나 자료 변경으로 중단된 작업이에요. 현재 자료를 확인해 주세요.";
  if (job.status === "waiting_ai")
    return "AI 연결 또는 처리 차례를 기다리고 있어요.";
  return "처리 순서에 따라 자동으로 진행돼요.";
}
export type ConceptValidationIssue = { concept_index?: number | null; batch_number?: number; reason?: string;
  code?: string; target?: string; actual_characters?: number };
export function conceptValidationMessage(issue: ConceptValidationIssue) {
  if (issue.code?.startsWith("NARRATION_") || issue.code === "SHORTS_NARRATION_LENGTH" || issue.code === "NO_PUBLIC_EVIDENCE") {
    if (issue.code === "SHORTS_NARRATION_LENGTH") return `대본 분량: ${Number.isFinite(issue.actual_characters) ? `${issue.actual_characters}자, ` : ""}50초 영상 기준인 360~400자를 충족하지 못했어요.`;
    const match = issue.target?.match(/^\/lesson\/(narration|key_facts)\/(\d+)$/);
    const position = match ? `${match[1] === "narration" ? "대본" : "핵심 내용"} ${Number(match[2]) + 1}` : "대본 검증";
    const detail = issue.code === "NARRATION_REFERENCE_CONFLICT" ? "교수자 검증 기준과의 일치 여부를 확인하지 못했어요."
      : issue.code === "NARRATION_REVIEW_INVALID" ? "근거 검증 응답 형식이 맞지 않아요."
      : "모든 주장을 공개 원문 근거로 확인하지 못했어요.";
    return `${position}: ${detail}`;
  }
  const reasons: Record<string, string> = {
    quote_too_short: "인용문이 5자 미만이에요.", quote_too_long: "인용문이 500자를 넘어요.",
    response_format: "개념 응답 형식이 맞지 않아요.", evidence_mismatch: "명칭·인용문·출처가 같은 원문과 일치하지 않아요.",
  };
  const position = [issue.batch_number ? `자료 묶음 ${issue.batch_number}` : "",
    issue.concept_index != null ? `개념 ${issue.concept_index + 1}` : "응답 전체"].filter(Boolean).join(" · ");
  return `${position}: ${reasons[issue.reason || ""] || "원문 근거와 응답을 확인해야 해요."}`;
}
export function jobTone(
  job: Pick<ProcessingJob, "status" | "error_code">,
): Tone {
  if (job.status === "succeeded" || job.status === "ready") return "ready";
  if (
    job.error_code === "LEGACY_BACKFILL_DEFERRED" ||
    job.error_code === "GEMINI_SERVICE_RETRY_EXHAUSTED" ||
    ["held", "needs_attention", "cancelled", "revoked"].includes(job.status)
  )
    return "held";
  if (job.status === "failed") return "failed";
  if (["running", "submitting", "processing", "storing"].includes(job.status))
    return "running";
  if (["queued", "waiting_ai", "script_pending"].includes(job.status))
    return "pending";
  return "unknown";
}
export const toneName: Record<Tone, string> = {
  running: "진행 중",
  pending: "대기",
  held: "보류·확인 필요",
  failed: "실패",
  ready: "완료",
  neutral: "생성 대상 아님",
  unknown: "상태 확인 필요",
};
function stage(name: string, tone: Tone, text: string, hint = ""): Stage {
  return { name, tone, text, hint };
}
function jobStage(
  name: string,
  jobs: ProcessingJob[],
  fallback: string,
  blocked: boolean,
): Stage {
  if (!jobs.length)
    return stage(
      name,
      blocked ? "held" : "pending",
      blocked ? "서버 재개 대기" : fallback,
      blocked
        ? "작업 접수가 중지되어 있어요. 관리자 재개 후 처리할 수 있어요."
        : "앞 단계가 완료되면 처리 상태를 다시 확인해 주세요.",
    );
  const rank: Record<Tone, number> = {
    failed: 0,
    held: 1,
    unknown: 2,
    running: 3,
    pending: 4,
    ready: 5,
    neutral: 6,
  };
  const chosen = [...jobs].sort(
    (a, b) => rank[jobTone(a)] - rank[jobTone(b)],
  )[0];
  const tone = jobTone(chosen);
  if (blocked && tone === "pending")
    return stage(
      name,
      "held",
      "서버 재개 대기",
      "접수가 재개될 때까지 대기해요. 중복 요청할 필요는 없어요.",
    );
  return stage(name, tone, toneName[tone], jobMessage(chosen));
}

// Current work is grouped by version AND concept by the API. History never decides readiness.
export function materialProgress(
  material: Material,
  processing: Processing | undefined,
  options: {
    error?: string;
    uploadsBlocked?: boolean;
    contentBlocked?: boolean;
  } = {},
): MaterialProgress {
  const version = material.version;
  const valid = !!processing && processing.version_id === version?.id;
  const jobs = valid
    ? processing.jobs.filter((j) => j.is_current !== false && (material.content_generation_mode !== "weekly" || ["extract", "embed"].includes(j.kind)))
    : [];
  const history = valid
    ? processing.jobs.filter((j) => j.is_current === false || (material.content_generation_mode === "weekly" && !["extract", "embed"].includes(j.kind)))
    : [];
  const make = (state: Stage, stages: Stage[] = []): MaterialProgress => ({
    ...state,
    stages,
    jobs,
    history,
  });
  if (options.error)
    return make(
      stage(
        "전체",
        "unknown",
        "상태 확인 실패",
        "상태를 불러오지 못했어요. 새로고침 후 다시 확인해 주세요.",
      ),
    );
  if (!valid)
    return make(
      stage(
        "전체",
        "unknown",
        "상태 확인 중",
        "현재 자료 버전의 처리 상태를 확인하고 있어요.",
      ),
    );
  const source = version?.status;
  let analysis: Stage;
  if (["extracted", "ready"].includes(source || ""))
    analysis = stage("원문 분석", "ready", processing?.held_count ? `부분 완료 · ${processing.held_count}건 보류` : "완료",
      processing?.held_count ? "보류 내용을 제외한 정상 구간은 검색 준비를 진행해요. ‘보류 내용 보기’에서 이유와 원문을 확인하세요."
      : processing?.extraction_pipeline?.startsWith('local-media-') ? "로컬 추출·기초 검사를 완료했어요. AI 대조 검증은 하지 않아요." : "파일의 원문을 읽었어요.");
  else if (source === "needs_review")
    analysis = stage(
      "원문 분석",
      "held",
      "텍스트 확인 필요",
      "상세·관리에서 추출 텍스트를 확인하고 수정해 주세요.",
    );
  else if (source === "failed")
    analysis = stage(
      "원문 분석",
      version?.error_code === "GEMINI_SERVICE_RETRY_EXHAUSTED" ? "held" : "failed",
      version?.error_code === "GEMINI_SERVICE_RETRY_EXHAUSTED" ? "자동 재시도 중단" : "원문 분석 실패",
      jobMessage({
        status: "failed",
        error_code: version?.error_code || null,
        result_status: null,
      }),
    );
  else
    analysis = jobStage(
      "원문 분석",
      jobs.filter((j) => j.kind === "extract"),
      "분석 대기",
      !!options.uploadsBlocked,
    );
  const eligible =
    material.visibility === "public" &&
    ["lecture", "example", "assignment"].includes(material.kind) &&
    material.internal_use === "none";
  if (!eligible) {
    const state =
      analysis.tone !== "ready"
        ? analysis
        : stage(
            "전체",
            "neutral",
            material.visibility === "private" ? "비공개 보관" : "참고 자료",
            "자동 학습 생성 대상이 아니에요. 원본과 공개 범위를 관리할 수 있어요.",
          );
    return make(state, [
      analysis,
      stage("AI 자료 검색", "neutral", "대상 아님"),
      stage("개념·문항", "neutral", "대상 아님"),
    ]);
  }
  const search =
    source === "ready"
      ? stage(
          "AI 자료 검색",
          "ready",
          "완료",
          "이 자료를 바탕으로 검색할 수 있어요.",
        )
      : jobStage(
          "AI 자료 검색",
          jobs.filter((j) => j.kind === "embed"),
          "원문 분석 후 대기",
          !!options.uploadsBlocked,
        );
  if (material.content_generation_mode === "weekly") {
    const stages = [analysis, search];
    const pending = stages.find(s => s.tone !== "ready");
    return make(pending ? { ...pending, text: `${pending.name} · ${pending.text}` } : stage(
      "전체", processing?.held_count ? "held" : "ready", processing?.held_count ? `정상 구간 준비 · ${processing.held_count}건 보류` : "자료 준비 완료",
      processing?.held_count ? "정상 구간은 검색·콘텐츠 생성에 사용할 수 있어요. 보류된 내용은 따로 확인해 주세요." : "이 주차 자료를 모두 올린 뒤 ‘이번 주차 콘텐츠 생성’을 눌러 주세요."
    ), stages);
  }
  const coreJobs = jobs.filter((j) =>
    ["auto_concepts", "questions", "practice_prepare"].includes(j.kind),
  );
  let content = jobStage(
    "개념·문항",
    coreJobs,
    "자료 검색 준비 후 대기",
    !!options.contentBlocked,
  );
  if (
    content.tone === "ready" &&
    (!coreJobs.some((j) => j.kind === "auto_concepts") ||
      !coreJobs.some((j) => j.kind === "questions"))
  ) {
    content = stage(
      "개념·문항",
      options.contentBlocked ? "held" : "pending",
      options.contentBlocked ? "서버 재개 대기" : "문항 생성 대기",
      "개념과 이론 문항이 모두 준비됐는지 확인하고 있어요.",
    );
  }
  const stages = [analysis, search, content];
  const selected = stages.find((s) => s.tone !== "ready");
  if (selected)
    return make(
      {
        ...selected,
        text:
          selected.text === "완료"
            ? selected.name
            : `${selected.name} · ${selected.text}`,
      },
      stages,
    );
  const noPractice = coreJobs.some(
    (j) => j.result_status === "no_verified_source_code",
  );
  return make(
    stage(
      "전체",
      "ready",
      "개념·문항 사용 가능",
      noPractice
        ? "개념·이론 문항은 준비됐어요. 예제 코드가 없어 실습은 생성하지 않았어요."
        : "개념·이론 문항이 준비됐어요. 학생에게 적용되는 범위는 분반 진도를 따라요. 영상 상태는 상세에서 확인하세요.",
    ),
    stages,
  );
}
