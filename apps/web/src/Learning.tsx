import { DropSelect } from "./DropSelect";
import { VanishPlaceholder } from "./VanishPlaceholder";
import { useAutosizeTextarea } from "./useAutosizeTextarea";
import { isComposingInput } from "./inputKeyboard";
import { MaterialUpload, MATERIAL_ACCEPT } from "./MaterialUpload";
import { WeeklyContent } from "./WeeklyContent";
import { HeldMaterialReview } from "./HeldMaterialReview";
import { theoryChatBody, saveTutorChoice, type TutorChoice } from "./learningRequests";
import type { FeedbackValue } from "./ChatFeedback";
import { MaterialProcessingDetails, MediaProcessingProgress, useCourseProcessing } from "./AutomaticLearning";
import { materialProgress, type Tone } from "./materialProcessing";
import { featureBlock, useServiceStatus } from "./ServiceStatus";
import "./teacher-processing.css";
import { PagedList } from "./StudentLists";
import { matchesSearch } from "./listNavigation";
import { QuestionArchive, isQuizQuestion, quizNameOf, type HistoryItem } from "./QuestionArchive";
import { TypedAnswer } from "./TypedAnswer";
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Link, useLocation } from "react-router-dom";
import { api, post, uploadMaterial, type Answer, type Job, type Material } from "./api";
import { RagTools } from "./RagTools";
import { ErrorNotice, Form, Notice, field, useLoad } from "./components";
import { materialWeeks } from "./studentOverview";
import { ChatCitation, useStudentHandouts } from "./ChatCitation";

const labels: Record<string, string> = {
  queued: "처리 대기",
  running: "처리 중",
  ready: "자료 원문 준비 완료",
  extracted: "원문 분석 완료 · 검색 준비 대기",
  failed: "원문 처리 실패",
  needs_review: "텍스트 확인 필요",
};
/* 한 학기 16주 — 숫자를 직접 적거나 목록에서 골라요 */

const progressFilters = [
  ["", "전체"], ["working", "진행·대기"], ["held", "보류·확인"],
  ["failed", "실패"], ["ready", "사용 가능"], ["neutral", "비공개·참고"],
] as const;
const progressGroup = (tone: Tone) => ["running", "pending"].includes(tone) ? "working" : tone === "unknown" ? "held" : tone;
export function Materials({
  courseId,
  teacher = false,
  currentWeek = null,
  totalWeeks = null,
}: {
  courseId: string;
  teacher?: boolean;
  currentWeek?: number | null;
  /* 학기 전체 주차 수 */
  totalWeeks?: number | null;
}) {
  const list = useLoad<{ items: Material[] }>(
    "/courses/" + courseId + "/materials", true,
  );
  const [error, setError] = useState("");
  const [editing, setEditing] = useState<{
    id: string;
    text: string;
    revision: number;
  } | null>(null);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [spinning, setSpinning] = useState(false);
  const [search, setSearch] = useState("");
  const [week, setWeek] = useState("");
  const [status, setStatus] = useState("");
  const service = useServiceStatus();
  const uploadBlock = featureBlock(service.data, "uploads", service.error);
  const contentBlock = featureBlock(service.data, "content", service.error);
  const processing = useCourseProcessing(courseId, teacher);
  const processingById = new Map((processing.items || []).map(item => [item.material_id, item]));
  const states = new Map((list.data?.items || []).map(material => [material.id, materialProgress(material, processingById.get(material.id), {
    error: processing.error, uploadsBlocked: !service.error && !!service.data && !!uploadBlock, contentBlocked: !service.error && !!service.data && !!contentBlock,
  })]));
  const searched = (list.data?.items || []).filter(m => matchesSearch(search, m.title) && (!week || m.week === Number(week)));
  const filtered = searched.filter(m => !status || progressGroup(states.get(m.id)!.tone) === status);
  const reload = () => { list.reload(); processing.reload(); service.reload(); };

  const weeks = [...new Set((list.data?.items || []).map(m => m.week))].sort((a,b) => a-b);
  const [uploadBusy, setUploadBusy] = useState(false);
  const needsPoll = teacher || !!list.data?.items.some(m => ["queued", "running", "extracted"].includes(m.version?.status || "") || ["generating", "waiting_ai"].includes(m.learning_status || ""));
  useEffect(() => {
    if (!needsPoll) return;
    const timer = window.setInterval(() => { if (!document.hidden) list.reload(); }, teacher ? 15000 : 5000);
    return () => clearInterval(timer);
  }, [needsPoll, teacher, list.reload]);
  useEffect(() => {
    if (uploadOpen) document.getElementById("material-upload")?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [uploadOpen]);
  const run = async (fn: () => Promise<void>) => {
    setError("");
    try {
      await fn();
      reload();
    } catch (e) {
      setError((e as Error).message);
    }
  };
  return (
    <div className={teacher ? "materials-manager teacher-materials" : "materials-manager"}>
      <div className="row materials-heading">
        <div><h2>강의 자료 {!teacher && <button type="button" className={`materials-refresh${spinning ? " is-spinning" : ""}`} aria-label="강의 자료 새로고침" title="새로고침" onClick={() => { setSpinning(true); list.reload(); }} onAnimationEnd={() => setSpinning(false)}><span aria-hidden="true">↻</span></button>}{list.data && <span className="materials-count">{list.data.items.length}</span>}</h2><p>{teacher ? "자료별 준비 단계와 필요한 조치를 확인하세요. 상태는 15초마다 갱신돼요." : "우리 수업의 자료를 확인하세요."}</p></div>
        {teacher ? <button className="materials-add" disabled={uploadBusy || (!!uploadBlock && !uploadOpen)} aria-describedby={uploadBlock ? "teacher-upload-block" : undefined} aria-expanded={uploadOpen} aria-controls="material-upload" onClick={() => setUploadOpen(!uploadOpen)}>{uploadOpen ? "업로드 닫기" : "+ 자료 올리기"}</button> : null}
      </div>
      <ErrorNotice text={error || list.error} />
      {teacher && uploadOpen && <MaterialUpload key={courseId} courseId={courseId} totalWeeks={totalWeeks ?? 16} blocked={uploadBlock} onChange={reload} onBusy={setUploadBusy} />}
      {teacher && <WeeklyContent courseId={courseId} refreshKey={JSON.stringify(list.data?.items.map(m => [m.id,m.revision,m.version?.id,m.version?.status])) || ""} />}
      {teacher && <>
        {uploadBlock && <div className="teacher-upload-block" id="teacher-upload-block" role="status"><strong>자료 업로드·새 버전 저장 일시중지</strong><p>{uploadBlock}</p><button type="button" onClick={service.reload}>상태 다시 확인</button></div>}
        <ErrorNotice text={processing.error || processing.videoError} />
        <div className="teacher-processing-toolbar"><span>상태를 누르면 해당 자료만 볼 수 있어요.</span><button type="button" onClick={reload}>상태 새로고침</button></div>
        <div className="teacher-processing-counts" role="group" aria-label="자료 처리 상태 필터">{progressFilters.map(([key, label]) => <button type="button" key={key} className={"material-status-card status-"+(key || "all")} aria-pressed={status === key} onClick={() => setStatus(key)}><span>{label}</span><strong>{list.data && processing.items ? searched.filter(m => !key || progressGroup(states.get(m.id)!.tone) === key).length : "—"}</strong></button>)}</div>
      </>}
      {teacher && !!list.data?.items.length && <div className="material-list-tools student-list-tools">
        <label>자료 검색<input type="search" value={search} onChange={e => setSearch(e.target.value)} placeholder="자료 이름" /></label>
        <DropSelect label="주차" value={week} onChange={setWeek}
          options={[{ value: "", label: "전체 주차" }, ...weeks.map(w => ({ value: String(w), label: w+"주차" }))]} />
        <DropSelect label="준비 상태" value={status} onChange={setStatus}
          options={progressFilters.map(([value, label]) => ({ value, label }))} />
        {(search || week || status) && <button onClick={() => { setSearch(""); setWeek(""); setStatus(""); }}>필터 초기화</button>}
        <p className="material-filter-count" role="status">전체 {list.data.items.length}개 중 {filtered.length}개</p>
      </div>}
      <div className="materials">
        {!list.data && !list.error && <Notice>자료를 불러오는 중이에요…</Notice>}
        {list.data?.items.length === 0 && (teacher || !totalWeeks) && <div className="materials-empty"><span aria-hidden="true">▤</span><h3>아직 등록된 자료가 없어요.</h3><p>{teacher ? "수업 자료를 올리면 이곳에서 공개 여부와 처리 상태를 확인할 수 있어요." : "공개된 수업 자료가 이곳에 표시돼요."}</p></div>}
        {!teacher && list.data && (list.data.items.length > 0 || !!totalWeeks) && <StudentMaterials items={list.data.items} currentWeek={currentWeek} totalWeeks={totalWeeks} />}
        {teacher && list.data && <PagedList key={`${courseId}:${search}:${week}:${status}`} items={filtered} label="강의 자료" size={8}>
          {visible => <>{!visible.length && !!list.data?.items.length && <p className="student-list-empty">조건에 맞는 자료가 없어요. 검색어나 필터를 바꿔보세요.</p>}{visible.map((m) => (
          <article className="material" key={m.id}>
            <div>
              <small className="material-meta">
                {m.week}주차 ·{" "}
                {m.visibility === "public" ? "수강생 공개" : "비공개"}
              </small>
              <h3>{m.title}</h3>
              {!teacher && <span className={`material-processing material-processing-${m.version?.status || "unknown"}`}>{labels[m.version?.status || ""] || "처리 중"}</span>}
            </div>
            <div className="material-state"><span className={`teacher-progress-badge tone-${states.get(m.id)!.tone}`}>{states.get(m.id)!.text}</span><p className="teacher-progress-reason">{states.get(m.id)!.hint}</p><MediaProcessingProgress progress={states.get(m.id)!} /></div>
            <details className={teacher ? "material-more" : "material-student-download"} open={teacher ? undefined : true}>
              {teacher && <summary aria-label={`${m.title} 상세·관리`}>처리·자료 관리 <span aria-hidden="true">⌄</span></summary>}
            <MaterialProcessingDetails courseId={courseId} progress={states.get(m.id)!} videos={processing.videos.filter(v => v.material_id === m.id)} videoError={processing.videoError} onChange={reload} />
            {m.version && <HeldMaterialReview materialId={m.id} versionId={m.version.id} heldCount={processingById.get(m.id)?.held_count} />}
            <div className="material-detail-state">
              <p>원문: {labels[m.version?.status || ""] || "자료 준비 중"}</p>
              {m.content_generation_mode !== "weekly" && m.learning_status === "failed" && m.version?.status === "ready" && m.visibility === "public" && ["lecture", "example", "assignment"].includes(m.kind) && <button disabled={!!contentBlock} title={contentBlock || undefined} onClick={() => void run(async () => { if (contentBlock) throw new Error(contentBlock); await api(`/materials/${m.id}/learning`, post({})); })}>개념·문항 생성 다시 시도</button>}
            </div>
            <div className="actions">
              {teacher && <label className="file-replace">
                수정본 업로드
                <input
                  type="file"
                  disabled={!!uploadBlock}
                  title={uploadBlock || undefined}
                  accept={MATERIAL_ACCEPT}
                  onChange={(e) => {
                    const file = e.target.files?.[0];
                    if (file)
                      void run(async () => {
                        if (uploadBlock) throw new Error(uploadBlock);
                        const f = new FormData();
                        f.append("file", file);
                        await uploadMaterial(courseId, f, { id: m.id, revision: m.revision });
                      });
                  }}
                />
              </label>}
              <a href={"/api/v1/materials/" + m.id + "/file"}>원본 받기</a>
              {teacher && (
                <>
                  <button
                    onClick={() =>
                      void run(async () => {
                        await api("/materials/" + m.id + "/access", {
                          method: "PATCH",
                          headers: { "If-Match": String(m.revision) },
                          body: JSON.stringify({
                            visibility:
                              m.visibility === "public" ? "private" : "public",
                          }),
                        });
                      })
                    }
                  >
                    {m.visibility === "public" ? "비공개로 전환" : "공개하기"}
                  </button>
                  <button
                    onClick={() =>
                      void run(async () => {
                        const r = await api<{ text: string; revision: number }>(
                          "/materials/" + m.id + "/transcript",
                        );
                        setEditing({ id: m.id, ...r });
                      })
                    }
                  >
                    추출 텍스트 확인
                  </button>
                </>
              )}
            </div>
            </details>
          </article>
        ))}</>}
        </PagedList>}
      </div>
      {teacher && <details className="teacher-search-tools"><summary>자료 검색 설정 · 필요할 때만</summary><p>자료별 준비 상태는 위 목록에서 확인하세요. 검색 준비를 다시 요청해야 할 때 사용해요.</p><RagTools key={courseId} courseId={courseId} blockedReason={uploadBlock} /></details>}
      {editing && (
        <section className="panel materials-editor">
          <h2>추출 텍스트 수정</h2>
          <Form
            label="새 버전으로 저장"
            disabled={!!uploadBlock}
            onSubmit={async (f) => {
              if (uploadBlock) throw new Error(uploadBlock);
              await api("/materials/" + editing.id + "/transcript", {
                method: "PUT",
                headers: { "If-Match": String(editing.revision) },
                body: JSON.stringify({ text: field(f, "text") }),
              });
              setEditing(null);
              reload();
            }}
          >
            <label>
              텍스트
              <textarea
                name="text"
                rows={12}
                defaultValue={editing.text}
                required
              />
            </label>
          </Form>
          <button onClick={() => setEditing(null)}>닫기</button>
        </section>
      )}
    </div>
  );
}
/* 주차 안에서는 이미 주차가 보이니까 자료 이름 앞의 'N주차 ·'는 빼고 보여줘요 */
function materialName(title: string) {
  return title.replace(/^\s*\d{1,2}\s*주차\s*[·:\-–]\s*/, "") || title;
}

function StudentMaterials({ items, currentWeek, totalWeeks }: { items: Material[]; currentWeek: number | null; totalWeeks?: number | null }) {
  const location = useLocation();
  const [search, setSearch] = useState("");
  /* 검색창에 '3', '3주차'처럼 주차를 적으면 그 주차로 바로 가요. 그 밖에는 자료 이름으로 찾아요. */
  const query = search.trim();
  const weekQuery = Number(query.match(/^(\d{1,2})\s*(주차|주)?$/)?.[1]) || null;
  const filtered = weekQuery ? items.filter(item => item.week === weekQuery) : items.filter(item => matchesSearch(search,item.title));
  /* 자료가 아직 없는 주차도 학기 전체 주차만큼 칸을 보여줘요 */
  const allWeeks = totalWeeks && totalWeeks > 0 ? Array.from({ length: totalWeeks }, (_, i) => i + 1) : [];
  const weeks = materialWeeks([...allWeeks, ...items.map(item => item.week)], currentWeek);
  const requestedWeek = Number(location.hash.match(/^#material-week-(\d+)$/)?.[1]);
  const targetWeek = weeks.includes(requestedWeek) ? requestedWeek : null;
  const [expanded, setExpanded] = useState(() => new Set([currentWeek && currentWeek > 0 ? currentWeek : weeks[0]]));
  /* 주차가 10주 이상이면 '전체 주차 / 1–9주차 / 10주차~마지막' 탭으로 나눠 보여줘요.
     처음에는 현재 진도가 있는 묶음을 열어요. 검색할 때는 전체 주차에서 찾아요. */
  const SPLIT = 9;
  const lastWeek = weeks.length ? weeks[weeks.length - 1] : 0;
  const splitWeeks = lastWeek > SPLIT;
  const [half, setHalf] = useState(() => (currentWeek && currentWeek > SPLIT ? 1 : 0));
  /* 검색하면 결과가 있는 주차 묶음으로 탭이 저절로 바뀌어요 (양쪽에 다 있으면 전체 주차) */
  const hitWeeks = weekQuery ? [weekQuery] : query ? [...new Set(filtered.map(item => item.week))] : [];
  const hitGroup = !hitWeeks.length ? null : hitWeeks.every(week => week <= SPLIT) ? 0 : hitWeeks.every(week => week > SPLIT) ? 1 : 2;
  useEffect(() => {
    if (hitGroup != null) setHalf(hitGroup);
  }, [hitGroup, query]);
  useEffect(() => {
    if (targetWeek == null) return;
    setHalf(previous => (previous === 2 ? 2 : targetWeek > SPLIT ? 1 : 0));
    setExpanded(previous => new Set([...previous, targetWeek]));
    const frame = requestAnimationFrame(() => document.getElementById(`material-week-${targetWeek}`)?.scrollIntoView({ block: "start" }));
    return () => cancelAnimationFrame(frame);
  }, [targetWeek]);
  return <div className="student-material-weeks">
    <div className="material-week-toolbar">
    {splitWeeks && <div className="material-week-split" role="tablist" aria-label="주차 묶음">
      {[[2, "전체 주차"], [0, `1–${SPLIT}주차`], [1, `${SPLIT + 1}–${lastWeek}주차`]].map(([id, label]) => <button key={id} type="button" role="tab" aria-selected={half === id} className={half === id ? "is-active" : ""} onClick={() => { setHalf(id as number); setSearch(""); }}>
        {label}{currentWeek != null && id !== 2 && (id === 0 ? currentWeek <= SPLIT : currentWeek > SPLIT) && currentWeek > 0 && <span className="material-week-split-dot" aria-label="현재 진도 포함" />}
      </button>)}
    </div>}
    <label className="material-week-search"><span aria-hidden="true">⌕</span><input type="search" aria-label="강의 자료 검색" value={search} onChange={e => setSearch(e.target.value)} placeholder="주차 또는 자료 이름 검색" /></label>
    </div>
    {!!query && !weekQuery && !filtered.length && <p className="student-list-empty">검색한 자료가 없어요. 다른 이름으로 찾아보세요.</p>}
    {!!weekQuery && !weeks.includes(weekQuery) && <p className="student-list-empty">{weekQuery}주차는 이 학기에 없어요.</p>}
    {weeks.filter(week => !query || (weekQuery ? week === weekQuery : filtered.some(item => item.week === week))).filter(week => search.trim() || !splitWeeks || half === 2 || (half === 0 ? week <= SPLIT : week > SPLIT)).map(week => {
      const materials = filtered.filter(item => item.week === week);
      const current = week === currentWeek;
      return <details id={`material-week-${week}`} key={week} className={`material-week ${current ? "is-current" : ""}`} open={!!search.trim() || expanded.has(week)} onToggle={event => {
        if (search.trim()) return;
        const open = event.currentTarget.open;
        setExpanded(previous => {
          if (previous.has(week) === open) return previous;
          const next = new Set(previous);
          if (open) next.add(week); else next.delete(week);
          return next;
        });
      }}>
        <summary><span><strong>{week}주차</strong>{current && <span className="material-week-current">현재 진도</span>}</span><span className="material-week-count">자료 {materials.length}개 <span className="material-week-chevron" aria-hidden="true">⌄</span></span></summary>
        <div className="material-week-content">{materials.length ? <PagedList items={materials} label={`${week}주차 자료`} resetKey={search} className="material-week-list">{visible => visible.map(item => <article className="student-material" key={item.id}>
          <span className="student-material-icon" aria-hidden="true">▤</span><div><h3>{materialName(item.title)}</h3></div>
          {item.view_url && <Link to={item.view_url} aria-label={`${item.title} 자료 열기`}>자료 열기 <span aria-hidden="true">↓</span></Link>}
        </article>)}</PagedList> : <p>이 주차에 공개된 자료가 아직 없어요. 다른 주차의 자료도 확인할 수 있어요.</p>}</div>
      </details>;
    })}
  </div>;
}

/* 문자 메시지처럼 내 질문은 오른쪽, AI 강사 답변은 왼쪽 말풍선으로 나뉘어요. */

/** 말풍선 아래 작은 날짜·시간 — 마우스를 올렸을 때만 보여요 (11-15) */
function ChatTime({ iso }: { iso?: string }) {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  const text = new Intl.DateTimeFormat("ko-KR", { timeZone: "Asia/Seoul", month: "long", day: "numeric", hour: "numeric", minute: "2-digit" }).format(d);
  return <time className="chat-time" dateTime={iso}>{text}</time>;
}
/** 개념 퀴즈 해설 아래 바로가기가 넘겨주는 문항 정보 (Flow.tsx QuizAskLink) */
export type QuizAsk = { title: string; question: string; context: string; /** 퀴즈 이름 (없으면 날짜) */ name?: string; /** 이 문항의 개념 — 대화와 상태 버튼 기록을 이 개념의 취약도에 연결해요 */ conceptId?: string };

export function Chat({ sectionId, courseId, speaker = "AI 강사" }: { sectionId: string; courseId: string; speaker?: string }) {
  const handouts = useStudentHandouts(courseId);
  const sendingRequest = useRef(false);
  const feedbackRequest = useRef(false);
  const [feedbackBusy, setFeedbackBusy] = useState(false);
  const messagesRef = useRef<HTMLDivElement>(null);
  // 개념 퀴즈 해설에서 넘어왔으면 그 문항을 함께 보낼 준비를 하고, 질문 칸에 질문 예시를 적어 둬요.
  // 새로고침해도 다시 채워지지 않게 넘겨받은 기록은 바로 지워요.
  const chatLocation = useLocation();
  const [quizAsk, setQuizAsk] = useState<QuizAsk | null>(() => (chatLocation.state as { quizAsk?: QuizAsk } | null)?.quizAsk || null);
  // 지금 대화가 어떤 개념 문항에서 시작됐는지 — 새 대화가 되면 비워요. 일반 질문은 개념 없이 남아요 (취약도 2단계, 11-16)
  const [quizConversation, setQuizConversation] = useState(false);
  const [threadConcept, setThreadConcept] = useState<string | undefined>();
  useEffect(() => {
    if (!quizAsk) return;
    try { window.history.replaceState({ ...window.history.state, usr: null }, ""); } catch { /* 기록을 못 바꿔도 동작에는 문제없어요 */ }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const [archiveSlot, setArchiveSlot] = useState<HTMLElement | null>(null);
  useEffect(() => { setArchiveSlot(document.getElementById("chat-archive-slot")); }, []);
  const [draft, setDraft] = useState(() => quizAsk?.question || "");
  // 질문 칸은 손으로 크기를 바꾸지 않고, 글이 길어지면 저절로 커져요 (최대 높이를 넘으면 칸 안에서 스크롤)
  const draftRef = useRef<HTMLTextAreaElement>(null);
  const [sent, setSent] = useState<{ text: string; key: number } | null>(null);
  useAutosizeTextarea(draftRef, draft);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [archiveRevision, setArchiveRevision] = useState(0);
  const [archiveOpen, setArchiveOpen] = useState(false);
  // 이전 질문에서 고른 대화를 보고 있을 때: 날짜 이름 · 눌렀던 질문 위치 (11-15)
  const [past, setPast] = useState<{ label: string; focus: number } | null>(null);
  const [pastLoading, setPastLoading] = useState(false);
  const [sending, setSending] = useState(false);
  const [formError, setFormError] = useState("");
  // 답변에 달린 이모티콘을 다시 누르면 고를 수 있게 열어 두는 답변 번호 (11-15)
  const [reEdit, setReEdit] = useState<number | null>(null);
  const [latestKey, setLatestKey] = useState(0);
  const [thread, setThread] = useState<string>(),
    [job, setJob] = useState<string>();
  const [items, setItems] = useState<
    {
      id?: string; pending?: string; question: string; answer?: Answer; error?: string; fresh?: boolean;
      /** 질문·답변 시각 — 말풍선에 마우스를 올리면 아래에 작게 보여요 (11-15) */
      at?: string; answeredAt?: string;
      /** 퀴즈에서 넘어온 질문이면 퀴즈 이름 — 내 질문 말풍선 위에 작게 보여요 (11-15) */
      quizName?: string;
      /** 원래 묻던 주제 — 상태 체크로 다시 물을 때 같은 주제의 자료를 찾게 해요 */
      topic?: string;
      /** 답변 뒤 상태 체크박스에서 보낸 상태 · 이해했어요일 때 보여 주는 짧은 안내 */
      note?: string;
      /** 답변 옆에서 고른 내 상태 — 답변 말풍선에 이모티콘으로 달려요 (11-15) */
      reaction?: "understood" | "confused" | "stop";
    }[]
  >([]);
  useEffect(() => {
    let active = true;
    setHistoryLoading(true);
    setQuizConversation(false);
    setItems([]);
    setPast(null);
    if (!latestKey) setArchiveOpen(false);
    setThread(undefined);
    setThreadConcept(undefined);
    setJob(undefined);
    api<{
      thread_id: string | null;
      job_id: string | null;
      items: (HistoryItem & {feedback?: FeedbackValue})[];
    }>(`/sections/${sectionId}/chat/history?mode=theory&limit=3`)
      .then((r) => {
        if (active) {
          setItems(r.items.map(x => ({
            ...x, question: x.question.split("\n\n[함께 보내는 퀴즈와 내 답안]")[0],
            at: x.created_at, quizName: quizNameOf(x),
            reaction: x.feedback === "aborted" ? "stop" : x.feedback,
          })));
          setThread(r.thread_id || undefined);
          setQuizConversation(!!r.thread_id && r.items.some(
            item => item.thread_id === r.thread_id && isQuizQuestion(item),
          ));
          setJob(r.job_id || undefined);
        }
      })
      .finally(() => {
        if (active) setHistoryLoading(false);
      })
      .catch((e) => {
        if (active)
          setItems([{ question: "대화 기록 불러오기", error: e.message }]);
      });
    return () => {
      active = false;
    };
  }, [sectionId, latestKey]);
  /* 이전 질문을 누르면 그 질문을 했던 대화를 불러와 그 자리로 이동해요 (11-15).
     서버가 질문마다 대화 번호(thread_id)를 주면 그 대화만 정확히 모으고,
     아직 주지 않으면 앞뒤 질문 사이 간격이 30분 이내인 것까지를 같은 대화로 봐요. */
  const openPast = async (target: HistoryItem) => {
    if (job || sendingRequest.current || feedbackRequest.current || pastLoading) return;
    setPastLoading(true);
    if (!archiveSlot) setArchiveOpen(false);
    try {
      const all: HistoryItem[] = [];
      for (let offset = 0; offset < 500; offset += 50) {
        const r = await api<{ total: number; items: HistoryItem[] }>(`/sections/${sectionId}/chat/history?mode=theory&limit=50&offset=${offset}&q=`);
        all.push(...r.items);
        if (all.some(x => x.id === target.id) || !r.items.length || offset + 50 >= r.total) break;
      }
      const list = (all.some(x => x.id === target.id) ? all : [...all, target])
        .filter((x, i, arr) => arr.findIndex(y => y.id === x.id) === i)
        .sort((a, b) => String(a.created_at).localeCompare(String(b.created_at)));
      const at = list.findIndex(x => x.id === target.id);
      const threadId = target.thread_id || list[at].thread_id;
      let conv: HistoryItem[];
      if (threadId) conv = list.filter(x => x.thread_id === threadId);
      else {
        const gap = (a?: HistoryItem, b?: HistoryItem) => !!a && !!b && Math.abs(Date.parse(b.created_at) - Date.parse(a.created_at)) <= 30 * 60e3;
        let from = at, to = at;
        while (from > 0 && at - from < 20 && gap(list[from - 1], list[from])) from--;
        while (to < list.length - 1 && to - at < 20 && gap(list[to], list[to + 1])) to++;
        conv = list.slice(from, to + 1);
      }
      setItems(conv.map(x => ({ id: x.id, question: x.question.split("\n\n[함께 보내는 퀴즈와 내 답안]")[0], answer: x.answer, error: x.answer ? undefined : x.error, at: x.created_at, quizName: quizNameOf(x) || undefined })));
      setThread(threadId || undefined);
      setQuizAsk(null);
      setQuizConversation(isQuizQuestion(target));
      const d = new Date(target.created_at);
      setPast({ label: Number.isNaN(d.getTime()) ? "이전" : new Intl.DateTimeFormat("ko-KR", { timeZone: "Asia/Seoul", month: "long", day: "numeric" }).format(d), focus: Math.max(0, conv.findIndex(x => x.id === target.id)) });
      setTutorNote("");
    } catch (e) {
      setTutorNote(`대화를 불러오지 못했어요. ${(e as Error).message}`);
    } finally {
      setPastLoading(false);
    }
  };
  useEffect(() => {
    if (!past) return;
    const el = messagesRef.current?.querySelector<HTMLElement>(".chat-pair.is-focus");
    if (el && messagesRef.current) messagesRef.current.scrollTop = el.offsetTop - messagesRef.current.offsetTop - 12;
    // 좁은 화면에서는 대화 창이 목록 아래에 있으니, 대화 창이 보이도록 내려가요
    const panel = messagesRef.current?.closest(".chat");
    if (panel && panel.getBoundingClientRect().top > window.innerHeight * 0.6) panel.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [past]);
  useEffect(() => {
    if (!job) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const r = await api<Job>("/jobs/" + job);
        if (stopped) return;
        if (["succeeded", "failed", "cancelled"].includes(r.status)) {
          setItems((old) =>
            old.map((x, i) =>
              i === old.length - 1
                ? {
                    ...x,
                    answeredAt: new Date().toISOString(),
                    fresh: !!r.result,
                    answer: r.result || undefined,
                    error: r.error
                      ? "답변 처리에 실패했어요. 다시 질문해 주세요."
                      : r.status === "cancelled"
                        ? "취소됐어요."
                        : undefined,
                  }
                : x,
            ),
          );
          setJob(undefined);
          setArchiveRevision(value => value + 1);
        } else {
          setItems(old => old.map((item, i) => i === old.length - 1 ? {
            ...item,
            pending: r.status === "waiting_ai"
              ? "AI 연결을 기다리고 있어요. 연결이 준비되면 답변을 이어서 처리해요."
              : undefined,
          } : item));
          timer = setTimeout(poll, 2000);
        }
      } catch (e) {
        if (!stopped) {
          setItems((old) =>
            old.map((x, i) =>
              i === old.length - 1 ? { ...x, error: (e as Error).message } : x,
            ),
          );
          setJob(undefined);
        }
      }
    };
    void poll();
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [job]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    const container = messagesRef.current;
    // 메신저처럼 아래로 쌓여요 — 새 질문·답변이 오면 맨 아래로 내려가요
    if (container && !past && !historyLoading) container.scrollTop = container.scrollHeight;
  }, [items, historyLoading, past]);
  // 퀴즈 해설에서 넘어왔으면 대화를 불러온 뒤 질문 칸에 커서를 놓아요 (적어 둔 질문을 고쳐 쓰거나 바로 보낼 수 있게)
  useEffect(() => {
    if (!quizAsk || historyLoading) return;
    const el = draftRef.current;
    if (el) { el.focus({ preventScroll: true }); el.setSelectionRange(el.value.length, el.value.length); el.scrollIntoView({ block: "center" }); }
  }, [historyLoading]); // eslint-disable-line react-hooks/exhaustive-deps
  // 질문 보내기 — 질문 칸과 상태 체크박스가 같이 써요
  const [tutorNote, setTutorNote] = useState("");
  const sendQuestion = async (question: string) => {
    if (job || historyLoading || pastLoading || sendingRequest.current) throw new Error("이전 답변을 기다려 주세요.");
    const conceptId = quizAsk?.conceptId || threadConcept;
    sendingRequest.current = true;
    try {
      const r = await api<{ job_id: string; thread_id: string; resource_id: string }>(
        `/sections/${sectionId}/chat/messages`, {
          ...post(theoryChatBody(question, thread, conceptId, quizAsk?.context)),
          headers: { "Idempotency-Key": crypto.randomUUID() },
        });
      setThread(r.thread_id);
      setThreadConcept(conceptId);
      setArchiveOpen(false);
      setPast(null);
      if (quizAsk) setQuizConversation(true);
      setQuizAsk(null);
      setTutorNote("");
      setItems(v => [...v, { id: r.resource_id, question, at: new Date().toISOString(), quizName: quizAsk ? quizAsk.name || "개념 퀴즈" : undefined }]);
      setJob(r.job_id);
      setArchiveRevision(v => v + 1);
    } finally { sendingRequest.current = false; }
  };
  const chatFeedback = async (kind: TutorChoice, index: number) => {
    if (feedbackRequest.current || sendingRequest.current || past) return;
    const item = items[index];
    if (!item) return;
    setReEdit(null);
    if (item.reaction === kind) return;
    feedbackRequest.current = true;
    setFeedbackBusy(true);
    try {
      await saveTutorChoice(api, sectionId, kind, item.id || item.answer?.message_id, job);
      setItems(old => old.map((x, i) => i === index ? { ...x, reaction: kind } : x));
      if (kind === "confused") {
        await sendQuestion("방금 설명이 헷갈려요. 더 쉬운 예로, 한 단계씩 다시 설명해 주세요.");
      } else if (kind === "stop") {
        if (job) setItems(old => old.map((x, i) => i === index ? { ...x, pending: undefined, error: "질문을 중단했어요." } : x));
        setJob(undefined);
        setThread(undefined);
        setThreadConcept(undefined);
        setQuizConversation(false);
        setTutorNote("대화를 중단했어요. 새로 질문하면 새 대화로 시작해요.");
      } else {
        setTutorNote("좋아요! 이해한 내용을 오늘의 퀴즈로 확인해 보세요.");
      }
      setArchiveRevision(v => v + 1);
    } catch (error) { setTutorNote((error as Error).message); }
    finally { feedbackRequest.current = false; setFeedbackBusy(false); }
  };
  // 이전 질문 내역 — AI 질문 화면에서는 왼쪽 '내 강의' 아래 자리(#chat-archive-slot)에 그려요. 자리가 없으면 대화 창 안에 그대로 둬요.
  const isQuizChat = !!quizAsk || quizConversation;
  const archive = <QuestionArchive sectionId={sectionId} revision={archiveRevision} open={archiveOpen} onOpenChange={setArchiveOpen}
    onOpenItem={(item) => void openPast(item)} />;
  return (
    <section className={`panel chat chat-messenger${isQuizChat ? " is-quiz-chat" : ""}`}>
      <div className="chat-heading">
      <h2 className="chat-title">{isQuizChat ? "퀴즈 챗봇" : "학습 챗봇"} <span>수업 자료에서 답변의 근거를 함께 확인하세요.</span></h2>
      <div className="chat-heading-actions">
        <button
          type="button"
          className="chat-new-conversation"
          disabled={!!job || feedbackBusy || sending || pastLoading || historyLoading}
          onClick={() => {
            setItems([]);
            setQuizAsk(null);
            setQuizConversation(false);
            setThread(undefined);
            setThreadConcept(undefined);
            setPast(null);
            setTutorNote("");
            setArchiveOpen(false);
            draftRef.current?.focus();
          }}
        >
          새 대화
        </button>
      </div>
      </div>
      {archiveSlot ? createPortal(archive, archiveSlot) : archive}
      <div className="chat-messages" ref={messagesRef} aria-live="polite" tabIndex={0} aria-label="최근 질문과 답변">
        {past ? <p className="chat-past-bar"><span>{past.label} 대화를 보고 있어요</span><button type="button" disabled={!!job || feedbackBusy || sending || pastLoading || historyLoading} onClick={() => { setLatestKey(k => k + 1); }}>최근 대화로 돌아가기</button></p> : null}
        {pastLoading && <p className="chat-loading" role="status">그 질문을 했던 대화를 불러오는 중이에요…</p>}
        {historyLoading && (
          <p className="chat-loading" role="status">
            이전 대화를 불러오는 중이에요…
          </p>
        )}
        {!historyLoading && items.length === 0 && (
          <div className="chat-welcome">
            <span className="chat-welcome-icon" aria-hidden="true">
              ?
            </span>
            <h3>이해는 질문에서 시작돼요.</h3>
            <p>
              궁금한 개념이나 이해되지 않는 부분을 적어 주세요.
              <br />
              공개된 강의 자료에서 답변의 근거를 찾아볼게요.
            </p>
            <span className="chat-source-note">
              강의 자료 기반 답변 · 출처 함께 확인
            </span>
          </div>
        )}
        {/* 메신저처럼 오래된 대화가 위, 가장 최근 질문과 답변이 맨 아래(질문 칸 바로 위)에 와요 */}
        {(past ? items : items.slice(-3)).map((item, n) => ({ item, i: past ? n : Math.max(0, items.length - 3) + n })).map(({ item, i }) => (
          <article key={i} className={`chat-pair ${past && i === past.focus ? "is-focus" : ""}`}>
            <div className="chat-row is-me">{item.quizName && <span className="chat-quiz-name">{item.quizName}</span>}<p className="chat-bubble">{item.question}</p><ChatTime iso={item.at} /></div>
            <div className="chat-row is-ai">
              <span className="chat-speaker">{speaker}</span>
              <div className="chat-bubble-col">
              <div className="chat-bubble">
                {item.reaction && <button type="button" className={`chat-reaction ${reEdit === i ? "is-editing" : ""}`} disabled={past !== null || !!job}
                  title="눌러서 바꾸기" aria-label={`내 상태: ${REACTIONS.find(r => r[0] === item.reaction)?.[2]} · 눌러서 바꾸기`} aria-expanded={reEdit === i}
                  onClick={() => setReEdit(reEdit === i ? null : i)}>{REACTIONS.find(r => r[0] === item.reaction)?.[1]}</button>}
                {item.answer ? <TypedAnswer text={item.answer.answer} animate={!!item.fresh}>
                  {item.answer.citations?.map((c, n) => <ChatCitation key={n} citation={c} handouts={handouts} />)}
                </TypedAnswer> : item.error ? <ErrorNotice text={item.error} /> : item.pending ? <p role="status">{item.pending}</p> : <p className="chat-typing" role="status"><span className="chat-dots" aria-hidden="true"><i /><i /><i /></span><span>{speaker}가 답변을 적고 있어요</span></p>}
                {item.answer?.follow_up && <p className="chat-followup"><b>🤔 생각해 볼 질문</b>{item.answer.follow_up}</p>}
              </div>
              {/* 답변 바로 아래 줄: 왼쪽은 시간, 오른쪽은 이해했어요·헷갈려요·중단. 하나 고르면 답변에 이모티콘이 달리고 선택지는 사라져요 (11-15) */}
              {(() => { const react = !past && ((i === items.length - 1 && !item.reaction && !item.error) || (reEdit === i && !!item.answer)); return <div className={`chat-ai-foot ${react ? "has-react" : ""}`}>
              {item.answer ? <ChatTime iso={item.answeredAt || item.at} /> : <span />}
              {react && (item.answer
                ? !job && <div className="chat-react" role="group" aria-label="지금 내 상태">
                    {REACTIONS.map(([kind, icon, label]) => <button key={kind} type="button" disabled={feedbackBusy || sending} className={`is-${kind} ${item.reaction === kind ? "is-picked" : ""}`} aria-pressed={item.reaction === kind} title={label} onClick={() => void chatFeedback(kind, i)}><span aria-hidden="true">{icon}</span><span className="chat-react-label">{label}</span></button>)}
                  </div>
                : !!job && <div className="chat-react" role="group" aria-label="답변 멈추기">
                    <button type="button" className="is-stop" title="중단" onClick={() => void chatFeedback("stop", i)}><span aria-hidden="true">⛔️</span><span className="chat-react-label">중단</span></button>
                  </div>)}
              </div>; })()}
              </div>
            </div>
            {item.note && <div className="chat-row is-ai"><p className="chat-bubble chat-state-note">{item.note}</p></div>}
          </article>
        ))}
      </div>
      {tutorNote && <p className="practice-chat__status chat-feedback-note" role="status">{tutorNote}</p>}
      <div className="chat-composer">
      {quizAsk && <div className="chat-quiz-context" role="note">
        <span className="chat-quiz-context__label">함께 보내는 퀴즈 문제</span>
        <strong>{quizAsk.name && <span className="chat-quiz-context__name">{quizAsk.name}</span>}{quizAsk.title}</strong>
        <button type="button" onClick={() => setQuizAsk(null)} aria-label="함께 보내는 퀴즈 문제 빼기">빼기 ✕</button>
      </div>}
      {/* 질문 칸 오른쪽에 보내기(화살표) 버튼, 음성 질문·음성 답변은 질문 칸 바깥 아래에 둬요 (11-15) */}
      <form className="form chat-form" onSubmit={async (e) => {
        e.preventDefault();
        if (sending || feedbackBusy) return;
        const f = new FormData(e.currentTarget);
        setSending(true);
        setFormError("");
        try {
          const sentText = field(f, "message");
          await sendQuestion(sentText);
          setSent({ text: sentText, key: Date.now() });
          setDraft("");
        } catch (err) {
          setFormError(err instanceof Error ? err.message : "질문을 보내지 못했어요.");
        } finally {
          setSending(false);
        }
      }}>
        <div className="chat-input-row">
          <label className="chat-input-label">
            <span className="chat-sr-only">질문</span>
            <textarea
              ref={draftRef}
              name="message"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              rows={1}
              maxLength={4000}
              required
              disabled={!!job || sending || pastLoading || feedbackBusy || historyLoading}
              onKeyDown={(e) => {
                if (
                  e.key === "Enter" &&
                  !e.shiftKey &&
                  !isComposingInput(e.nativeEvent)
                ) {
                  e.preventDefault();
                  e.currentTarget.form?.requestSubmit();
                }
              }}
            />
            <VanishPlaceholder textarea={draftRef} examples={QUESTION_EXAMPLES} hidden={draft.length > 0} sent={sent} />
          </label>
          <button type="submit" className="chat-send" aria-label="질문 보내기" title="질문 보내기 (Enter)" disabled={sending || pastLoading || feedbackBusy || !!job || historyLoading || !draft.trim()}>
            {sending
              ? <span className="chat-send-spin" aria-hidden="true" />
              : <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M19 5v7a3 3 0 0 1-3 3H6" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" /><path d="m10 10.5-4.5 4.5 4.5 4.5" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" /></svg>}
          </button>
        </div>
        <ErrorNotice text={formError} />
      </form></div>
    </section>
  );
}

/* 질문 칸에 돌아가며 보이는 예시 문구 (VanishPlaceholder) */
const QUESTION_EXAMPLES = [
  "궁금한 점을 적어 질문해보세요.",
  "예: 리스트와 튜플은 뭐가 다른가요?",
  "예: 재귀 함수는 언제 멈추나요?",
  "예: 이번 주 강의에서 꼭 알아야 할 개념은 뭐예요?",
];

const REACTIONS = [["understood", "💡", "이해했어요"], ["confused", "❓", "헷갈려요"], ["stop", "⛔️", "중단"]] as const;

/* 새로 도착한 답변은 한 글자씩 적히듯 보여 줘요. 예전 대화나 '동작 줄이기' 설정에서는 바로 다 보여요.
   글이 길어도 2.5초 안에 다 나오도록 한 번에 나오는 글자 수를 늘려요. 다 나온 뒤에 출처 링크가 붙어요. */
