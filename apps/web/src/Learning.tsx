import { PagedList } from "./StudentLists";
import { matchesSearch } from "./listNavigation";
import { QuestionArchive } from "./QuestionArchive";
import { useEffect, useRef, useState } from "react";
import { useLocation } from "react-router-dom";
import { api, post, uploadMaterial, type Answer, type Job, type Material } from "./api";
import { AIAvailability, ErrorNotice, Form, Notice, field, useLoad } from "./components";
import { materialWeeks, weekLabel } from "./studentOverview";
import { sourceLabel } from "./sourceLabels";

const labels: Record<string, string> = {
  queued: "처리 대기",
  running: "처리 중",
  extracted: "원문 추출 완료 · AI 처리 대기",
  ready: "자료 원문 준비 완료",
  failed: "원문 처리 실패",
  needs_review: "텍스트 확인 필요",
};
function materialState(m: Material) {
  if (m.version?.status === "failed") return { text: "자료 처리 실패", tone: "failed", hint: "원문 또는 AI 처리 중 문제가 발생했어요. 원본은 보관되어 있으며 다시 시도하거나 텍스트를 확인할 수 있어요." };
  if (m.version?.status === "needs_review") return { text: "텍스트 확인 필요", tone: "failed", hint: "추출한 내용을 확인해야 준비를 이어갈 수 있어요." };
  if (m.version?.status === "extracted") return { text: "원문 추출 완료 · AI 대기", tone: "pending", hint: "파일 저장과 텍스트 추출은 완료됐어요. AI 연결 후 임베딩과 학습 준비가 이어집니다." };
  if (m.version?.status !== "ready") return { text: "자료 준비 중", tone: "pending", hint: "" };
  if (m.visibility !== "public") return { text: "비공개 보관", tone: "neutral", hint: "" };
  if (["past_exam", "answer", "transcript"].includes(m.kind)) return { text: "참고 자료", tone: "neutral", hint: "" };
  if (m.learning_status === "ready") return { text: "개념·문항 준비 완료", tone: "ready", hint: "자료 원문과 자동 생성 작업이 준비됐어요." };
  if (m.learning_status === "failed") return { text: "개념·문항 생성 실패", tone: "failed", hint: "자료 원문은 준비됐지만 개념 추출 또는 문항 생성 중 실패한 작업이 있어요. 다시 시도할 수 있어요." };
  if (m.learning_status === "waiting_ai") return { text: "AI 처리 대기", tone: "pending", hint: "요청이 보관되어 있어요. AI 연결 후 개념·문항 생성을 이어갑니다." };
  return { text: "개념·문항 준비 중", tone: "pending", hint: "자료 원문은 준비됐어요. 개념 추출과 문항 생성 상태를 확인하고 있어요." };
}
export function Materials({
  courseId,
  teacher = false,
  currentWeek = null,
}: {
  courseId: string;
  teacher?: boolean;
  currentWeek?: number | null;
}) {
  const list = useLoad<{ items: Material[] }>(
    "/courses/" + courseId + "/materials",
  );
  const [message, setMessage] = useState(""),
    [error, setError] = useState("");
  const [editing, setEditing] = useState<{
    id: string;
    text: string;
    revision: number;
  } | null>(null);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [week, setWeek] = useState("");
  const [status, setStatus] = useState("");
  const filtered = (list.data?.items || []).filter(m => matchesSearch(search, m.title) && (!week || m.week === Number(week)) && (!status || materialState(m).tone === status));
  const weeks = [...new Set((list.data?.items || []).map(m => m.week))].sort((a,b) => a-b);
  const [kind, setKind] = useState("lecture"),
    [visibility, setVisibility] = useState("public");
  useEffect(() => {
    if (!list.data?.items.some(m => ["queued","running","extracted"].includes(m.version?.status || "") || ["generating", "waiting_ai"].includes(m.learning_status || ""))) return;
    const timer = setInterval(list.reload, 5000);
    return () => clearInterval(timer);
  }, [list.data]);
  const run = async (fn: () => Promise<void>) => {
    setError("");
    try {
      await fn();
      list.reload();
    } catch (e) {
      setError((e as Error).message);
    }
  };
  return (
    <div className={teacher ? "materials-manager teacher-materials" : "materials-manager"}>
      <div className="row materials-heading">
        <div><h2>강의 자료 {list.data && <span className="materials-count">{list.data.items.length}</span>}</h2><p>{teacher ? "자료를 올리면 개념과 이론 문항을 자동으로 준비해요." : "우리 수업의 자료를 확인하세요."}</p></div>
        {teacher ? <button className="materials-add" aria-expanded={uploadOpen} aria-controls="material-upload" onClick={() => setUploadOpen(!uploadOpen)}>{uploadOpen ? "업로드 닫기" : "+ 자료 올리기"}</button> : <button onClick={list.reload}>상태 새로고침</button>}
      </div>
      <ErrorNotice text={error || list.error} />
      {teacher && <AIAvailability />}
      {message && <Notice>{message}</Notice>}
      {teacher && !!list.data?.items.length && <div className="material-list-tools student-list-tools">
        <label>자료 검색<input type="search" value={search} onChange={e => setSearch(e.target.value)} placeholder="자료 이름" /></label>
        <label>주차<select value={week} onChange={e => setWeek(e.target.value)}><option value="">전체 주차</option>{weeks.map(w => <option key={w} value={w}>{w}주차</option>)}</select></label>
        <label>준비 상태<select value={status} onChange={e => setStatus(e.target.value)}><option value="">전체 상태</option><option value="failed">확인·재시도 필요</option><option value="pending">준비 중</option><option value="ready">개념·문항 준비 완료</option><option value="neutral">비공개·참고 자료</option></select></label>
        {(search || week || status) && <button onClick={() => { setSearch(""); setWeek(""); setStatus(""); }}>필터 초기화</button>}
        <p className="material-filter-count" role="status">전체 {list.data.items.length}개 중 {filtered.length}개</p>
      </div>}
      <div className="materials">
        {!list.data && !list.error && <Notice>자료를 불러오는 중이에요…</Notice>}
        {list.data?.items.length === 0 && <div className="materials-empty"><span aria-hidden="true">▤</span><h3>아직 등록된 자료가 없어요.</h3><p>{teacher ? "수업 자료를 올리면 이곳에서 공개 여부와 처리 상태를 확인할 수 있어요." : "공개된 수업 자료가 이곳에 표시돼요."}</p></div>}
        {!teacher && list.data && list.data.items.length > 0 && <StudentMaterials items={list.data.items} currentWeek={currentWeek} />}
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
            <div className="material-state"><span className={`material-processing material-state-${materialState(m).tone}`}>{materialState(m).text}</span></div>
            <details className={teacher ? "material-more" : "material-student-download"} open={teacher ? undefined : true}>
              {teacher && <summary aria-label={`${m.title} 상세·관리`}>상세·관리 <span aria-hidden="true">⌄</span></summary>}
            <div className="material-detail-state">
              <p>원문: {labels[m.version?.status || ""] || "자료 준비 중"}</p>
              {materialState(m).hint && <p>{materialState(m).hint}</p>}
              {m.version?.status === "failed" && m.processing_job_id && <button onClick={() => void run(async () => { await api(`/jobs/${m.processing_job_id}/retry`, post({})); })}>자료 처리 다시 시도</button>}
              {m.learning_status === "failed" && m.version?.status === "ready" && m.visibility === "public" && ["lecture", "example", "assignment"].includes(m.kind) && <button onClick={() => void run(async () => { await api(`/materials/${m.id}/learning`, post({})); })}>개념·문항 생성 다시 시도</button>}
            </div>
            <div className="actions">
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
                            internal_use: m.internal_use,
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
                  <label className="file-replace">
                    수정본 업로드
                    <input
                      type="file"
                      accept=".pdf,.pptx,.docx,.txt,.md,.c,.java,.py"
                      onChange={(e) => {
                        const file = e.target.files?.[0];
                        if (file)
                          void run(async () => {
                            const f = new FormData();
                            f.append("file", file);
                            await uploadMaterial(courseId, f, { id: m.id, revision: m.revision });
                          });
                      }}
                    />
                  </label>
                </>
              )}
            </div>
            </details>
          </article>
        ))}</>}
        </PagedList>}
      </div>
      {editing && (
        <section className="panel materials-editor">
          <h2>추출 텍스트 수정</h2>
          <Form
            label="새 버전으로 저장"
            onSubmit={async (f) => {
              await api("/materials/" + editing.id + "/transcript", {
                method: "PUT",
                headers: { "If-Match": String(editing.revision) },
                body: JSON.stringify({ text: field(f, "text") }),
              });
              setEditing(null);
              list.reload();
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
      {teacher && uploadOpen && (
        <section id="material-upload" className="panel materials-upload">
          <h2>강의 자료 올리기</h2><p className="materials-upload-intro">파일과 주차만 확인하세요. 기본 설정은 수강생 공개입니다.</p>
          <Form
            label="자료 올리기"
            onSubmit={async (f) => {
              await uploadMaterial(courseId, f);
              setMessage(
                "자료를 저장했어요. 공개된 강의 자료는 개념 추출과 학습 문항 생성이 자동으로 이어집니다.",
              );
              setUploadOpen(false);
              list.reload();
            }}
          >
            <label>
              파일
              <input
                type="file"
                name="file"
                accept=".pdf,.pptx,.docx,.txt,.md,.c,.java,.py"
                required
              />
            </label>
              <label>
                주차
                <input
                  type="number"
                  name="week"
                  min="1"
                  max="52"
                  defaultValue="1"
                  required
                />
              </label>
            <details className="material-upload-options"><summary>자료 종류·공개 범위 설정</summary>
            <div className="columns">
              <label>
                자료 종류
                <select
                  name="kind"
                  value={kind}
                  onChange={(e) => {
                    const v = e.target.value;
                    setKind(v);
                    setVisibility(
                      ["answer", "transcript", "past_exam"].includes(v)
                        ? "private"
                        : "public",
                    );
                  }}
                >
                  {[
                    ["lecture", "강의 자료"],
                    ["example", "예제 코드"],
                    ["assignment", "과제 안내"],
                    ["transcript", "녹취록"],
                    ["past_exam", "기출"],
                    ["answer", "정답·해설"],
                  ].map(([id, t]) => (
                    <option key={id} value={id}>
                      {t}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                학생 공개
                <select
                  name="visibility"
                  value={visibility}
                  onChange={(e) => setVisibility(e.target.value)}
                >
                  <option value="public">수강생에게 공개</option>
                  <option value="private">비공개</option>
                </select>
              </label>
              <label>
                내부 AI 활용
                <select name="internal_use">
                  <option value="none">사용하지 않음</option>
                  <option value="validation_grading">
                    검증·채점 기준 전용
                  </option>
                </select>
              </label>
            </div>
            </details>
            <p className="muted">
              음성·스캔 문서는 전사/OCR 연결 전입니다. 텍스트 문서로 변환해
              주세요. 정답·해설은 공개 범위를 확인해 주세요.
            </p>
          </Form>
        </section>
      )}
    </div>
  );
}
function StudentMaterials({ items, currentWeek }: { items: Material[]; currentWeek: number | null }) {
  const location = useLocation();
  const [search, setSearch] = useState("");
  const filtered = items.filter(item => matchesSearch(search,item.title));
  const weeks = materialWeeks(items.map(item => item.week), currentWeek);
  const requestedWeek = Number(location.hash.match(/^#material-week-(\d+)$/)?.[1]);
  const targetWeek = weeks.includes(requestedWeek) ? requestedWeek : null;
  const [expanded, setExpanded] = useState(() => new Set([currentWeek && currentWeek > 0 ? currentWeek : weeks[0]]));
  useEffect(() => {
    if (targetWeek == null) return;
    setExpanded(previous => new Set([...previous, targetWeek]));
    const frame = requestAnimationFrame(() => document.getElementById(`material-week-${targetWeek}`)?.scrollIntoView({ block: "start" }));
    return () => cancelAnimationFrame(frame);
  }, [targetWeek]);
  return <div className="student-material-weeks">
    <p className="material-week-guide">{weekLabel(currentWeek)} · 주차를 열어 자료를 확인하세요.</p>
    <div className="student-list-tools"><label>강의 자료 검색<input type="search" value={search} onChange={e => setSearch(e.target.value)} placeholder="전체 주차에서 자료 이름 검색" /></label></div>
    {!!search.trim() && !filtered.length && <p className="student-list-empty">검색한 자료가 없어요. 다른 이름으로 찾아보세요.</p>}
    {weeks.filter(week => !search.trim() || filtered.some(item => item.week === week)).map(week => {
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
        <div className="material-week-content">{materials.length ? <PagedList items={materials} label={`${week}주차 자료`} resetKey={search}>{visible => visible.map(item => <article className="student-material" key={item.id}>
          <span className="student-material-icon" aria-hidden="true">▤</span><div><h3>{item.title}</h3><span className={`material-processing material-processing-${item.version?.status || "unknown"}`}>{labels[item.version?.status || ""] || "자료 준비 중"}</span></div>
          {item.version && <a href={`/api/v1/materials/${item.id}/file`} aria-label={`${item.title} 원본 받기`}>원본 받기 <span aria-hidden="true">↓</span></a>}
        </article>)}</PagedList> : <p>이 주차에 공개된 자료가 아직 없어요. 다른 주차의 자료도 확인할 수 있어요.</p>}</div>
      </details>;
    })}
  </div>;
}

export function Chat({ sectionId }: { sectionId: string }) {
  const messagesRef = useRef<HTMLDivElement>(null);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [archiveRevision, setArchiveRevision] = useState(0);
  const [archiveOpen, setArchiveOpen] = useState(false);
  const [thread, setThread] = useState<string>(),
    [job, setJob] = useState<string>();
  const [items, setItems] = useState<
    { question: string; answer?: Answer; error?: string }[]
  >([]);
  useEffect(() => {
    let active = true;
    setHistoryLoading(true);
    setItems([]);
    setArchiveOpen(false);
    setThread(undefined);
    setJob(undefined);
    api<{
      thread_id: string | null;
      job_id: string | null;
      items: { question: string; answer?: Answer; error?: string }[];
    }>(`/sections/${sectionId}/chat/history?limit=3`)
      .then((r) => {
        if (active) {
          setItems(r.items);
          setThread(r.thread_id || undefined);
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
  }, [sectionId]);
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
        } else timer = setTimeout(poll, 2000);
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
  }, [job]);
  useEffect(() => {
    const container = messagesRef.current;
    if (container && !historyLoading) container.scrollTop = container.scrollHeight;
  }, [items, historyLoading]);
  return (
    <section className="panel chat">
      <AIAvailability />
      <div className="chat-heading">
      <h2>어떤 부분이 궁금한가요?</h2>
      <button
        type="button"
        disabled={!!job}
        onClick={() => {
          setItems([]);
          setThread(undefined);
          setArchiveOpen(false);
        }}
      >
        새 대화
      </button>
      </div>
      <p className="muted">
        공개된 수업 자료의 원문에서 답변과 출처를 찾아요.
      </p>
      <QuestionArchive sectionId={sectionId} revision={archiveRevision} open={archiveOpen} onOpenChange={setArchiveOpen} />
      <div className="chat-messages" ref={messagesRef} aria-live="polite" tabIndex={0} aria-label="최근 질문과 답변">
        {items.length > 0 && <p className="student-list-count">최근 대화 {Math.min(3,items.length)}개 · 전체 대화는 이전 질문에서 확인하세요.</p>}
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
        {items.slice(-3).map((item, i) => (
          <article key={i} className="conversation">
            <strong>나 · {item.question}</strong>
            {item.answer ? (
              <>
                <p className="answer">{item.answer.answer}</p>
                {item.answer.citations?.map((c, n) => (
                  <a
                    key={n}
                    href={
                      "/api/v1/materials/" +
                      c.material_id +
                      "/file?version_id=" +
                      c.version_id
                    }
                  >
                    {c.title} ·{" "}
                    {sourceLabel(c.locator)} ↗
                  </a>
                ))}
              </>
            ) : item.error ? (
              <ErrorNotice text={item.error} />
            ) : (
              <p>공개 자료에서 근거를 확인하고 있어요…</p>
            )}
          </article>
        ))}
      </div>
      <div className="chat-composer"><Form
        label="질문하기"
        onSubmit={async (f) => {
          if (job) throw new Error("이전 답변을 기다려 주세요.");
          const question = field(f, "message");
          const r = await api<{ job_id: string; thread_id: string }>(
            "/sections/" + sectionId + "/chat/messages",
            {
              ...post({ thread_id: thread, message: question }),
              headers: { "Idempotency-Key": crypto.randomUUID() },
            },
          );
          setThread(r.thread_id);
          setArchiveOpen(false);
          setItems((v) => [...v, { question }]);
          setJob(r.job_id);
          setArchiveRevision(value => value + 1);
        }}
      >
        <label>
          질문
          <textarea
            name="message"
            placeholder="수업에서 어떤 부분이 궁금했나요?"
            rows={2}
            maxLength={4000}
            required
            disabled={!!job || historyLoading}
            onKeyDown={(e) => {
              if (
                e.key === "Enter" &&
                !e.shiftKey &&
                !e.nativeEvent.isComposing
              ) {
                e.preventDefault();
                e.currentTarget.form?.requestSubmit();
              }
            }}
          />
        </label>
      </Form></div>
    </section>
  );
}
