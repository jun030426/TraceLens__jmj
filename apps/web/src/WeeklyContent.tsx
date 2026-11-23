import { conceptVideoPoster } from "./conceptVideoPoster";
import { useEffect, useId, useRef, useState } from "react";
import { api, post } from "./api";
import { ErrorNotice, Notice, useLoad } from "./components";
import { featureBlock, useServiceStatus } from "./ServiceStatus";
import { conceptValidationMessage, emptyPracticeMessage, jobMessage, practiceReason, taskName, type ConceptValidationIssue } from "./materialProcessing";
import "./weekly-content.css";
import { GoogleSlidesConnection, TeachingSlides } from "./GoogleSlides";

type Source = { material_id: string; title: string; kind: string; version_id: string; ready: boolean; status: string };
type Work = { id: string; kind: string; status: string; required?: boolean; error_code: string | null; retry_at: string | null; result_status: string | null; held: { reason: string }[]; skipped?: { reason: string }[]; retryable_practice?: boolean; validation_issues?: ConceptValidationIssue[] };
type Generation = {
  id: string; week: number; status: string; state: string; stale: boolean; can_publish: boolean;
  published_at: string | null; sources: Source[]; blockers: string[]; jobs: Work[];
  video_mode?: "all" | "ready_only" | "none";
  counts: { concepts: number; questions: number; practice: number; videos: number; videos_ready: number; videos_deferred?: number };
};
type Week = { week: number; sources: Source[]; source_hash: string; sources_ready: boolean; draft: Generation | null; published: Generation | null };
type Question = { id: string; concept_id: string; kind: string; prompt: string; options: string[]; sources_current: boolean;
  solution: { answer_index: number; explanation: string; criteria: string[] }; sources: { chunk_id: string; quote: string }[] };
type Exercise = { id: string; title: string; kind: string; language: string; prompt: string; template: string; reference: string;
  tests: { input?: string; expected: string }[]; sources: { quote: string }[]; status: string };
type Video = { id: string; title: string; concept_id: string; included?: boolean; status: string; play_url: string | null; poster_url?: string | null; error_code?: string;
  script?: { lesson?: { narration: string[]; key_facts: string[] } } };
type Review = Generation & { review_token: string; concepts: { id: string; name: string; description: string; version_id: string }[];
  questions: Question[]; practice: Exercise[]; videos: (Video | null)[] };
const stateName: Record<string, string> = {
  generating: "콘텐츠 생성 중", ready: "검토 후 공개 가능", failed: "확인·재시도 필요", stale: "자료 변경됨 · 재생성 필요",
  published: "학생 공개 중", cancelled: "이전 생성", archived: "이전 공개 버전", draft: "교수자 검토용",
};
const jobState: Record<string, string> = { succeeded: "완료", queued: "대기", running: "처리 중", waiting_ai: "AI 연결 대기", failed: "실패", cancelled: "중단" };
const videoState: Record<string, string> = { ready: "재생 가능", script_pending: "대본 준비 중", queued: "영상 생성 대기", processing: "영상 생성 중", submitting: "영상 요청 중", failed: "실패", held: "검토 필요", waiting_ai: "AI 연결 대기", waiting_credits: "API 크레딧 충전 대기", cancelled: "중단" };

function PracticeReasons({ job }: { job: Work }) {
  const reasons = [...new Set([...job.held, ...(job.skipped ?? [])].map(item => practiceReason(item.reason)))];
  const message = emptyPracticeMessage(job.result_status);
  return <>{message && <p>{message}</p>}
    {reasons.length > 0 && <ul>{reasons.map(reason => <li key={reason}>{reason}</li>)}</ul>}
    {!reasons.length && message && <p>{practiceReason(job.result_status === "no_supported_language" ? "PRACTICE_FILE_LANGUAGE" : "PRACTICE_NO_PROPOSAL")}</p>}</>;
}

function GenerationFailures({ jobs }: { jobs: Work[] }) {
  const failed = jobs.filter(job => job.required !== false && job.status === "failed");
  if (!failed.length) return null;
  return <div className="weekly-content-blockers" role="status" aria-label="콘텐츠 생성 실패 이유">
    {failed.map(job => <div key={job.id}><strong>{taskName[job.kind] || job.kind}</strong><p>{jobMessage(job)}</p>
      {!!job.validation_issues?.length && <ul>{job.validation_issues.map((issue, index) => <li key={index}>{conceptValidationMessage(issue)}</li>)}</ul>}
    </div>)}
    <p>원본·전사·검색 준비 결과는 유지돼요. 생성 결과 검토에서 실패한 작업을 다시 시도할 수 있어요.</p>
  </div>;
}

export function WeeklyContent({ courseId, refreshKey }: { courseId: string; refreshKey: string }) {
  const weeks = useLoad<{ items: Week[]; default_video_mode: "all" | "none" }>(`/courses/${courseId}/weekly-content`, true);
  const publishCheckId = useId();
  const generationHelpId = useId();
  const [weekSearch, setWeekSearch] = useState("");
  const [displayState, setDisplayState] = useState("");
  const [reviewTarget, setReviewTarget] = useState<{ id: string; week: number; trigger: HTMLButtonElement } | null>(null);
  const selected = reviewTarget?.id || "";
  const reviewHeading = useRef<HTMLHeadingElement>(null);
  const weekFilter = useRef<HTMLInputElement>(null);
  const review = useLoad<Review>(`/courses/${courseId}/content-generations/${selected}`, true, !!selected);
  const [tab, setTab] = useState("concepts");
  const [checked, setChecked] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const service = useServiceStatus();
  const block = featureBlock(service.data, "content", service.error);
  const reload = () => { weeks.reload(); if (selected) review.reload(); };
  useEffect(() => { weeks.reload(); }, [refreshKey, weeks.reload]);
  useEffect(() => { setChecked(false); }, [selected, review.data?.review_token]);
  useEffect(() => {
    if (!reviewTarget || !reviewHeading.current) return;
    reviewHeading.current.focus({ preventScroll: true });
    reviewHeading.current.scrollIntoView({ block: "start", behavior: "instant" });
  }, [reviewTarget]);
  useEffect(() => { setReviewTarget(null); setWeekSearch(""); setDisplayState(""); setError(""); setMessage(""); }, [courseId]);
  useEffect(() => {
    const timer = window.setInterval(() => {
      if (!document.hidden) { weeks.reload(); if (selected) review.reload(); }
    }, 15000);
    return () => window.clearInterval(timer);
  }, [weeks.reload, review.reload, selected]);
  const run = async (action: () => Promise<void>) => {
    if (busy || block) return;
    setBusy(true); setError(""); setMessage("");
    try { await action(); reload(); } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };
  const open = (id: string, week: number, trigger: HTMLButtonElement) => {
    setReviewTarget({ id, week, trigger });
    setTab("concepts");
    setChecked(false);
  };
  const close = () => {
    const trigger = reviewTarget?.trigger;
    setReviewTarget(null);
    const returnTo = trigger?.isConnected && !trigger.disabled
      ? trigger
      : trigger?.closest("article")?.querySelector<HTMLElement>("h3");
    (returnTo?.isConnected ? returnTo : weekFilter.current)?.focus();
  };
  const allWeeks = weeks.data?.items || [];
  const labelFor = (week: Week) => week.draft ? stateName[week.draft.state] || week.draft.state
    : week.published ? "학생 공개 중" : week.sources_ready ? "생성 준비 완료" : "자료 준비 중";
  const term = weekSearch.trim().toLocaleLowerCase();
  const visibleWeeks = allWeeks.filter(week =>
    (!displayState || labelFor(week) === displayState) &&
    (!term || String(week.week) === term || (String(week.week) + "주차").includes(term) ||
      week.sources.some(source => source.title.toLocaleLowerCase().includes(term))));
  const detail = review.data?.id === selected ? review.data : undefined;
  const includedVideos = detail?.videos.filter((video): video is Video => !!video && video.included !== false) || [];
  const deferredVideos = detail?.videos.filter((video): video is Video => !!video && video.included === false) || [];
  return <section className="weekly-content weekly-content-panel" aria-label="주차별 콘텐츠 생성·공개">
    <div className="weekly-content-heading"><div><h2>주차별 콘텐츠</h2>
      <p>자료를 모두 올린 뒤 생성하세요. 생성 결과를 검토하고 공개해야 학생이 학습할 수 있어요.</p></div>
      <button type="button" onClick={reload}>상태 새로고침</button></div>
    <ol className="weekly-content-steps" aria-label="진행 순서">{["자료 준비", "콘텐츠 생성", "결과 검토", "학생에게 공개"].map((label, i) =>
      <li key={label}><span>{i + 1}</span>{label}</li>)}</ol>
    <p id={generationHelpId}>{weeks.data?.default_video_mode === "none"
      ? "현재 새 영상 제작은 제외해요. 개념·문항·실습을 자동으로 생성하고, 영상 없이도 검토 후 공개할 수 있어요."
      : "준비된 주차별 자료로 개념·문항·실습과 영상을 생성해요."} 실습은 자료에 실행 검증이 가능한 예제 코드가 있을 때 만들어요.</p>
    <GoogleSlidesConnection />
    <ErrorNotice text={error || weeks.error} />
    {block && <Notice>{block}</Notice>}
    {message && <p role="status" className="weekly-content-notice">{message}</p>}
    {!weeks.data && !weeks.error && <p>주차별 준비 상태를 불러오고 있어요.</p>}
    {weeks.data?.items.length === 0 && <p>먼저 강의 자료를 올려 주세요. 업로드는 원문 분석과 AI 검색 준비까지만 진행돼요.</p>}
    {!!allWeeks.length && <div className="weekly-content-filters">
      <label>상태<select value={displayState} onChange={e => setDisplayState(e.target.value)}>
        <option value="">전체 상태</option>{Array.from(new Set(allWeeks.map(labelFor).concat(displayState ? [displayState] : []))).map(label => <option key={label}>{label}</option>)}
      </select></label>
      <label>주차·자료 검색<input ref={weekFilter} type="search" value={weekSearch} onChange={e => setWeekSearch(e.target.value)} placeholder="주차 또는 자료 이름" /></label>
      {(weekSearch || displayState) && <button onClick={() => { setWeekSearch(""); setDisplayState(""); }}>초기화</button>}
    </div>}
    {!!allWeeks.length && !visibleWeeks.length && <p role="status">조건에 맞는 주차가 없어요.</p>}
    <div className="weekly-content-weeks">{visibleWeeks.map(week => {
      const draft = week.draft;
      const creating = draft?.state === "generating";
      const canStart = week.sources_ready && (!draft || draft.stale);
      return <article className="weekly-content-week" key={week.week}>
        <div className="weekly-content-week-title"><h3 tabIndex={-1}>{week.week}주차</h3>
          <span className={`weekly-content-status state-${draft?.state || (week.published ? "published" : "preparing")}`}>
            {labelFor(week)}</span></div>
        {!!week.sources.length && <p>{week.sources.filter(s => s.ready).length}/{week.sources.length}개 학습 자료 준비</p>}
        <ul className="weekly-content-sources">{week.sources.map(source => <li key={source.material_id}>
          <span>{source.title}</span><strong>{source.ready ? "준비 완료" : "분석·검색 준비 중"}</strong></li>)}</ul>
        {!week.sources.length && <p>이 주차에 생성에 사용할 공개 학습 자료가 없어요. 비공개·정답 자료는 생성 대상에 포함되지 않아요.</p>}
        {draft && <p className="weekly-content-counts">개념 {draft.counts.concepts} · 문항 {draft.counts.questions} · 실습 {draft.counts.practice} · 영상 {draft.counts.videos_ready}/{draft.counts.videos}</p>}
        {draft?.video_mode === "ready_only" && <p>완성된 영상만 포함 · 나머지 {draft.counts.videos_deferred || 0}개 제작 대기</p>}
        {draft?.video_mode === "none" && <p>영상 제외 · 개념·문항·실습 검토 후 공개</p>}
        {week.published && draft && <p>이전 공개 콘텐츠로 학생 학습을 유지해요. 새 결과를 공개하면 교체돼요.</p>}
        {week.published?.stale && !draft && <p className="weekly-content-notice">공개 후 자료가 변경됐어요. 현재 자료로 새 콘텐츠를 생성해 주세요.</p>}
        {draft && <GenerationFailures jobs={draft.jobs} />}
        <div className="weekly-content-actions">
          <button type="button" className="primary" aria-describedby={generationHelpId} disabled={busy || !!block || !canStart || creating}
            onClick={event => {
              const trigger = event.currentTarget;
              void run(async () => {
                const result = await api<{ generation_id: string }>(`/courses/${courseId}/weeks/${week.week}/content`, post({ source_hash: week.source_hash }));
                open(result.generation_id, week.week, trigger);
                setMessage(`${week.week}주차 콘텐츠 생성을 요청했어요. 학생 공개 전 검토용으로 저장돼요.`);
              });
            }}>{creating ? "콘텐츠 생성 중…" : draft?.stale || week.published ? "현재 자료로 새 버전 생성" : "이번 주차 콘텐츠 생성"}</button>
          {draft && <button type="button" onClick={event => open(draft.id, week.week, event.currentTarget)}>생성 결과 검토</button>}
          {week.published && <button type="button" onClick={event => open(week.published!.id, week.week, event.currentTarget)}>공개 콘텐츠 보기</button>}
        </div>
      </article>;
    })}</div>
    {reviewTarget && <section className="weekly-content-review" aria-label="생성 결과 검토">
      <div className="weekly-content-heading"><div><h3 ref={reviewHeading} tabIndex={-1}>{reviewTarget.week}주차 생성 결과 검토</h3>
        <p>정답·해설과 출처, 실습 검증 결과를 확인해 주세요.{detail?.video_mode !== "none" && " 영상 내용도 함께 확인해 주세요."}</p></div>
        <button type="button" onClick={close}>검토 닫기</button></div>
      <ErrorNotice text={review.error} />
      {!detail && !review.error && <p>생성 결과를 불러오고 있어요.</p>}
      {detail && <>
        <span className={`weekly-content-status state-${detail.state}`}>{stateName[detail.state]}</span>
        {detail.video_mode === "none" && <p className="weekly-content-notice">영상과 영상 대본은 생성 대상에서 제외했어요. 기존 영상·대본 기록은 보존하며, 영상 준비를 기다리지 않고 아래 콘텐츠를 검토·공개할 수 있어요.</p>}
        {detail.video_mode === "ready_only" && <p className="weekly-content-notice">완성된 영상 {includedVideos.length}개만 해당 개념에 포함했어요. 나머지 {deferredVideos.length}개는 대본과 제작 기록을 보존하고 제작을 대기해요. 학생 공개는 아래에서 검토 후 별도로 결정해 주세요.</p>}
        <GenerationFailures jobs={detail.jobs} />
        {!!detail.blockers.length && <ul className="weekly-content-blockers">{detail.blockers.map(reason => <li key={reason}>{reason}</li>)}</ul>}
        <details className="weekly-content-jobs"><summary>필수 작업 상태 · {detail.jobs.filter(j => j.required !== false && j.status === "succeeded").length}/{detail.jobs.filter(j => j.required !== false).length}개 완료</summary>
          <div className="weekly-content-scroll">{detail.jobs.map(job => <article key={job.id}>
            <strong>{taskName[job.kind] || job.kind} · {jobState[job.status] || job.status}{job.required === false && " · 이번 공개에서 제외"}</strong>
            {job.error_code && <p>{jobMessage(job)}</p>}
            {job.retry_at && job.error_code && <small>다시 처리할 시각: {new Date(job.retry_at).toLocaleString("ko-KR")}</small>}
            {job.kind === "practice_prepare" && <PracticeReasons job={job} />}
          </article>)}</div>
          {detail.status === "draft" && !detail.stale && detail.jobs.some(j => j.required !== false && (j.status === "failed" || j.held.length > 0 || j.retryable_practice)) && <button disabled={busy || !!block} onClick={() => void run(async () => {
            await api(`/courses/${courseId}/content-generations/${detail.id}/retry`, post({})); setMessage("생성 작업의 재시도를 요청했어요.");
          })}>{detail.jobs.some(j => j.retryable_practice && emptyPracticeMessage(j.result_status)) ? "실습을 포함해 생성 작업 다시 시도" : "실패한 생성 작업 다시 시도"}</button>}
        </details>
        <div className="weekly-content-tabs" role="group" aria-label="검토 항목">{[
          ["concepts", `개념 ${detail.concepts.length}`], ["questions", `문항 ${detail.questions.length}`],
          ["practice", `실습 ${detail.practice.length}`], ["videos", detail.video_mode === "none" ? "영상 제외" : `영상 ${includedVideos.length}`],
        ].map(([key, label]) => <button type="button" key={key} aria-pressed={tab === key} onClick={() => setTab(key)}>{label}</button>)}</div>
        <div className="weekly-content-results">
          {tab === "videos" && detail.video_mode !== "none" && <TeachingSlides key={detail.id} courseId={courseId} generationId={detail.id} />}
          {tab === "concepts" && (detail.concepts.length ? detail.concepts.map(concept => <article key={concept.id}>
            <h4>{concept.name}</h4><p>{concept.description}</p><small>출처: {detail.sources.find(s => s.version_id === concept.version_id)?.title || "주차 강의 자료"}</small>
            {includedVideos.filter(video => video.concept_id === concept.id && video.status === "ready" && video.play_url).map(video =>
              <video key={video.id} poster={conceptVideoPoster(video.id, video.poster_url)} controls preload="none" src={video.play_url!} aria-label={`${concept.name} 개념 영상`} />)}
          </article>) : <p>{detail.jobs.some(j => j.kind === "weekly_content" && j.status === "failed") ? "개념 생성이 중단됐어요. 위의 실패 이유를 확인해 주세요." : "개념을 준비하고 있어요."}</p>)}
          {tab === "questions" && (detail.questions.length ? detail.questions.map((question, index) => <article key={question.id}>
            <h4>{index + 1}. {question.prompt}</h4><small>{detail.concepts.find(c => c.id === question.concept_id)?.name} · {question.kind === "mcq" ? "객관식" : "서술형"}</small>
            {question.options.length > 0 && <ol>{question.options.map((option, i) => <li key={i} className={i === question.solution.answer_index ? "weekly-content-answer" : ""}>{option}{i === question.solution.answer_index && <strong> · 정답</strong>}</li>)}</ol>}
            <p><strong>해설</strong> {question.solution.explanation}</p>
            {!!question.solution.criteria.length && <div><strong>채점 기준</strong><ul>{question.solution.criteria.map((criterion, i) => <li key={i}>{criterion}</li>)}</ul></div>}
            <details><summary>자료 근거 확인 {question.sources_current ? "· 확인됨" : "· 확인 필요"}</summary>{question.sources.map((source, i) => <blockquote key={i}>{source.quote}</blockquote>)}</details>
          </article>) : <p>검증을 통과한 문항부터 표시돼요.</p>)}
          {tab === "practice" && (detail.practice.length ? detail.practice.map(exercise => <article key={exercise.id}>
            <h4>{exercise.title} · {exercise.kind === "blank" ? "빈칸 채우기" : "전체 구현"}</h4><p>{exercise.prompt}</p>
            <details><summary>학생용 코드</summary><pre>{exercise.template}</pre></details>
            <details><summary>기준 코드와 실행 검증 {exercise.tests.length}건</summary><pre>{exercise.reference}</pre>
              {exercise.tests.map((test, i) => <div key={i}><strong>검증 {i + 1}</strong>{test.input && <pre>{test.input}</pre>}<p>기대 출력</p><pre>{test.expected}</pre></div>)}</details>
          </article>) : detail.jobs.some(j => emptyPracticeMessage(j.result_status))
            ? detail.jobs.filter(j => emptyPracticeMessage(j.result_status)).map(job => <PracticeReasons key={job.id} job={job} />)
            : <p>실습 코드와 실행 결과를 준비하고 있어요.</p>)}
          {tab === "videos" && detail.status === "draft" && !detail.stale && <div className="weekly-content-actions">
            {detail.video_mode !== "none" && <button type="button" disabled={busy || !!block} onClick={() => void run(async () => {
              await api(`/courses/${courseId}/content-generations/${detail.id}/video-selection`, post({ mode: "none", review_token: detail.review_token }));
              setMessage("영상과 대본을 제외하고 기존 콘텐츠의 생성·검토를 이어가요. 완료된 결과는 유지해요.");
            })}>영상 제외하고 계속</button>}
            {detail.video_mode !== "ready_only" && detail.videos.some(video => video?.status === "ready" && video.play_url) && <button disabled={busy || !!block} onClick={() => void run(async () => {
              await api(`/courses/${courseId}/content-generations/${detail.id}/video-selection`, post({ mode: "ready_only", review_token: detail.review_token }));
              setMessage("완성된 영상만 개념에 포함했어요. 나머지 영상 제작은 대기해요.");
            })}>완성된 영상만 포함</button>}
            {detail.video_mode !== "all" && weeks.data?.default_video_mode === "all" && <button disabled={busy || !!block} onClick={() => void run(async () => {
              await api(`/courses/${courseId}/content-generations/${detail.id}/video-selection`, post({ mode: "all", review_token: detail.review_token }));
              setMessage("전체 영상을 준비하는 상태로 전환했어요. 크레딧 부족으로 접수에 실패한 영상은 충전 후 다시 시도해 주세요.");
            })}>전체 영상 준비로 전환</button>}
          </div>}
          {tab === "videos" && (includedVideos.length ? includedVideos.map(video => <article key={video.id}>
            <h4>{video.title} · {video.error_code === "HEYGEN_API_CREDITS_REQUIRED" ? "API 크레딧 충전 대기" : videoState[video.status] || video.status}</h4>
            {video.error_code && <p>{jobMessage({ status: video.status, error_code: video.error_code, result_status: null })}</p>}
            {video.play_url && <video poster={conceptVideoPoster(video.id, video.poster_url)} controls preload="metadata" src={video.play_url} aria-label={`${video.title} 검토용 영상`} />}
            {video.script?.lesson && <details><summary>대본과 핵심 내용</summary>{video.script.lesson.narration.map((part, i) => <p key={i}>{part}</p>)}<ul>{video.script.lesson.key_facts.map((fact, i) => <li key={i}>{fact}</li>)}</ul></details>}
            {detail.status === "draft" && detail.video_mode !== "ready_only" && !detail.stale && ["failed", "held"].includes(video.status) && <button disabled={busy || !!block} onClick={() => void run(async () => {
              await api(`/courses/${courseId}/concept-videos/${video.id}/retry`, post({})); setMessage("영상 재시도를 요청했어요.");
            })}>영상 다시 시도</button>}
          </article>) : <p>{detail.video_mode === "none" ? "이번 주차는 영상 없이 학습할 수 있도록 구성해요." : "개념 생성 후 영상 준비가 시작돼요."}</p>)}
          {tab === "videos" && deferredVideos.length > 0 && <details><summary>제작 대기 영상 {deferredVideos.length}개 · 저장된 대본 보기</summary>
            {deferredVideos.map(video => <article key={video.id}><h4>{video.title} · 이번 구성에서 제외</h4>
              <p>{video.error_code === "HEYGEN_API_CREDITS_REQUIRED" ? "HeyGen API 크레딧 충전 대기" : "추가 영상 제작 대기"}</p>
              {video.script?.lesson && <details><summary>저장된 대본과 핵심 내용</summary>{video.script.lesson.narration.map((part, i) => <p key={i}>{part}</p>)}<ul>{video.script.lesson.key_facts.map((fact, i) => <li key={i}>{fact}</li>)}</ul></details>}
            </article>)}
          </details>}
        </div>
        {detail.status === "draft" && <div className="weekly-content-publish">
          <label htmlFor={publishCheckId}><input id={publishCheckId} type="checkbox" checked={checked} disabled={!detail.can_publish || busy} onChange={e => setChecked(e.target.checked)} />개념·문항·실습{detail.video_mode !== "none" && "·영상"}과 자료 근거를 확인했으며 학생에게 공개합니다.</label>
          <button className="primary" disabled={!detail.can_publish || !checked || busy || !!block} onClick={() => void run(async () => {
            await api(`/courses/${courseId}/content-generations/${detail.id}/publish`, post({ review_token: detail.review_token, reviewed: checked }));
            setChecked(false); setMessage(`${detail.week}주차 콘텐츠를 학생에게 공개했어요.`);
          })}>학생에게 공개</button>
          {!detail.can_publish && <p>모든 필수 작업이 완료되고 자료 변경이 없어야 공개할 수 있어요.</p>}
        </div>}
      </>}
    </section>}
  </section>;
}
