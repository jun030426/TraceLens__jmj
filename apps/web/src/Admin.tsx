import { AdminWorkers, type WorkerStatus } from "./AdminWorkers";
import { useContext, useEffect, useState } from "react";
import { QRCodeSVG } from "qrcode.react";
import { Link, useSearchParams } from "react-router-dom";
import { Auth } from "./Auth";
import { api, post } from "./api";
import { ErrorNotice, Form, Input, Notice, field, useLoad } from "./components";
import { useConfirm } from "./ConfirmDialog";
import { isTestUser } from "./testAccess";
import "./admin.css";

type Security = {
  level: "owner" | "operator";
  enrolled: boolean;
  verified: boolean;
  configured: boolean;
  expires_at: string | null;
};
type Settings = {
  revision: number;
  maintenance: boolean;
  message: string;
  features: Record<string, boolean>;
  server_hold: boolean;
};
type Person = {
  id: string;
  login_id: string;
  display_name: string;
  role: string;
  active: boolean;
  admin_level: string | null;
  email: string | null;
};
type Work = {
  id: string;
  kind: string;
  title: string;
  owner: string;
  owner_name: string;
  course_title: string;
  group: string;
  locked: boolean;
  status: string;
  error_code: string | null;
  provider_error?: {
    http_status: number; provider_code: string | null; model: string | null;
    message: string | null; request_id: string | null; request_hash: string;
    service_failures: number; max_service_failures: number; recorded_at: string;
  } | null;
  created_at: string;
  provider_submitted: boolean;
};
type Command = {
  id: string;
  action: string;
  status: string;
  reason: string;
  error_code: string | null;
  created_at: string;
};
type Server = {
  state: string;
  instance_id?: string;
  region?: string;
  configured: boolean;
  scheduler_ready: boolean;
  scheduler_seen_at: string | null;
  server_hold: boolean;
  busy: Record<string, number>;
  commands: Command[];
  checked_at: string;
};
const features: Record<string, string> = {
  uploads: "자료 업로드·분석",
  rag: "RAG 질문",
  grading: "실습·이론 채점",
  content: "학습 콘텐츠 생성",
  videos: "새 영상 생성",
};
const statuses: Record<string, string> = {
  queued: "대기",
  waiting_ai: "AI 대기",
  running: "실행 중",
  succeeded: "완료",
  failed: "실패",
  cancelled: "취소",
  script_pending: "대본 준비",
  submitting: "외부 접수 중",
  processing: "영상 생성 중",
  storing: "저장 중",
  ready: "준비 완료",
  held: "보류",
  needs_attention: "확인 필요",
  revoked: "원본 변경",
  draining: "작업 완료 대기",
  starting: "서버 시작 중",
  stopping: "서버 중지 중",
  restarting: "재시작 중",
  uncertain: "접수 확인 중",
  stopped: "중지",
  pending: "시작 준비",
  unavailable: "연결 확인 필요",
  not_configured: "연결 설정 필요",
  online: "정상",
  stale: "응답 확인 필요",
};
const roles: Record<string, string> = {
  student: "학생",
  teacher: "교수자",
  operator: "운영 담당자",
  owner: "최고 관리자",
  revoked: "권한 회수",
};
const kinds: Record<string, string> = {
  extract: "자료 추출",
  embed: "자료 임베딩",
  auto_concepts: "개념 생성",
  chat: "RAG 답변",
  questions: "문항 생성",
  grade: "이론 채점",
  practice_prepare: "실습 생성",
  practice_grade: "실습 채점",
  narration_lesson: "영상 대본",
  daily_theory: "오늘의 이론",
  video: "영상 생성",
  code: "코드 실행",
};
const date = (value?: string | null) =>
  value
    ? new Date(value).toLocaleString("ko-KR", { timeZone: "Asia/Seoul" })
    : "확인 전";
function Badge({ value }: { value: string }) {
  return (
    <span className={`admin-badge state-${value}`}>
      {statuses[value] || value}
    </span>
  );
}
function Reason() {
  return (
    <label>
      변경 사유
      <input
        name="reason"
        required
        minLength={3}
        maxLength={500}
        placeholder="변경하는 이유를 적어 주세요"
      />
    </label>
  );
}
function Pager({
  offset,
  total,
  set,
}: {
  offset: number;
  total: number;
  set: (n: number) => void;
}) {
  return (
    <div className="admin-pager">
      <span>총 {total}개</span>
      <button disabled={!offset} onClick={() => set(Math.max(0, offset - 30))}>
        이전
      </button>
      <span>{Math.floor(offset / 30) + 1} 페이지</span>
      <button disabled={offset + 30 >= total} onClick={() => set(offset + 30)}>
        다음
      </button>
    </div>
  );
}
function usePoll(reload: () => void, seconds = 20) {
  useEffect(() => {
    const id = window.setInterval(() => {
      if (!document.hidden) reload();
    }, seconds * 1000);
    return () => clearInterval(id);
  }, [reload, seconds]);
}

export function AdminPage() {
  const { user } = useContext(Auth);
  if (user?.role !== "operator" || isTestUser(user))
    return (
      <Notice>
        관리자 계정으로 로그인해 주세요. <Link to="/home">내 홈으로</Link>
      </Notice>
    );
  return <AdminConsole />;
}

function AdminConsole() {
  const security = useLoad<Security>("/admin/security", true);
  const [recovery, setRecovery] = useState<string[]>([]);
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") || "overview";
  usePoll(security.reload, 30);
  useEffect(() => {
    const refresh = () => security.reload();
    window.addEventListener("lerny-admin-auth", refresh);
    return () => window.removeEventListener("lerny-admin-auth", refresh);
  }, [security.reload]);
  if (security.error)
    return (
      <section className="admin-console">
        <ErrorNotice text={security.error} />
        <button onClick={security.reload}>다시 확인</button>
      </section>
    );
  if (!security.data) return <Notice>관리자 권한을 확인하고 있어요…</Notice>;
  if (!security.data.verified || recovery.length > 0)
    return (
      <SecurityGate
        security={security.data}
        reload={security.reload}
        recovery={recovery}
        setRecovery={setRecovery}
      />
    );
  const owner = security.data.level === "owner";
  return (
    <section className="admin-console">
      <div className="admin-heading">
        <div>
          <span className="admin-eyebrow">LERNY ADMIN</span>
          <h1>운영 관리</h1>
          <p>서비스 상태를 확인하고 필요한 작업을 관리하세요.</p>
        </div>
        <span className="admin-role">{roles[security.data.level]}</span>
      </div>
      <nav className="admin-nav" aria-label="관리자 메뉴">
        {[
          ["overview", "운영 현황"],
          ["users", "사용자 관리"],
          ["jobs", "작업 관리"],
          ["settings", "점검·기능 설정"],
          ["server", "서버 관리"],
          ["audit", "관리 이력"],
        ].map(([id, label]) => (
          <button
            key={id}
            aria-current={tab === id ? "page" : undefined}
            className={tab === id ? "selected" : ""}
            onClick={() => setParams({ tab: id })}
          >
            {label}
          </button>
        ))}
      </nav>
      <div className="admin-content" key={tab}>
        {tab === "overview" ? (
          <Overview />
        ) : tab === "users" ? (
          <Users owner={owner} />
        ) : tab === "jobs" ? (
          <Jobs />
        ) : tab === "settings" ? (
          <SettingsPanel owner={owner} />
        ) : tab === "server" ? (
          <ServerPanel owner={owner} />
        ) : tab === "audit" ? (
          <Audit />
        ) : (
          <Notice>메뉴를 선택해 주세요.</Notice>
        )}
      </div>
      <p className="admin-footer">
        관리자 인증 유효 시간 · {date(security.data.expires_at)}까지. 중요한
        변경은 관리 이력에 기록됩니다.
      </p>
    </section>
  );
}

function SecurityGate({
  security,
  reload,
  recovery,
  setRecovery,
}: {
  security: Security;
  reload: () => void;
  recovery: string[];
  setRecovery: (codes: string[]) => void;
}) {
  const [enrollment, setEnrollment] = useState<{
    secret: string;
    uri: string;
  }>();
  return (
    <section className="admin-console admin-security">
      <span className="admin-eyebrow">LERNY ADMIN</span>
      <h1>관리자 보안 인증</h1>
      <p>비밀번호와 인증 앱의 코드를 확인한 뒤 운영 화면으로 이동합니다.</p>
      {!security.configured ? (
        <Notice>
          관리자 보안 키 설정이 필요합니다. 배포 설정을 확인해 주세요.
        </Notice>
      ) : recovery.length ? (
        <>
          <h2>복구 코드 보관</h2>
          <p>
            인증 앱을 사용할 수 없을 때 코드 하나로 인증할 수 있어요. 각 코드는
            한 번만 사용할 수 있고, 이 화면에서만 표시됩니다.
          </p>
          <div className="admin-recovery">
            {recovery.map((code) => (
              <code key={code}>{code}</code>
            ))}
          </div>
          <button
            className="primary"
            onClick={() => {
              setRecovery([]);
              reload();
            }}
          >
            안전한 곳에 보관했어요
          </button>
        </>
      ) : (
        <>
          {!security.enrolled && !enrollment ? (
            <Form
              label="인증 앱 등록 준비"
              onSubmit={async (f) =>
                setEnrollment(
                  await api(
                    "/admin/security/enroll",
                    post({ password: field(f, "password") }),
                  ),
                )
              }
            >
              <Input
                label="현재 비밀번호"
                name="password"
                type="password"
                maxLength={128}
              />
            </Form>
          ) : null}
          {enrollment && (
            <div className="admin-enrollment">
              <h2>휴대폰으로 QR 코드 스캔</h2>
              <p>
                휴대폰의 Google Authenticator 등 인증 앱에서 + → QR 코드 스캔을
                선택하고 아래 코드를 비춰 주세요.
              </p>
              <div className="admin-enrollment-qr">
                <QRCodeSVG
                  value={enrollment.uri}
                  size={232}
                  level="M"
                  marginSize={4}
                  bgColor="#ffffff"
                  fgColor="#111111"
                  title="Lerny 관리자 인증 앱 등록용 QR 코드"
                  role="img"
                />
              </div>
              <p>
                앱에 계정이 추가되면 표시되는 6자리 번호를 아래에 입력해 주세요.
              </p>
              <details className="admin-enrollment-manual">
                <summary>
                  같은 휴대폰으로 접속했거나 QR 스캔이 어려운가요?
                </summary>
                <p>
                  설정 키를 복사한 뒤 인증 앱의 ‘설정 키 입력’을 선택해 붙여
                  넣고, 유형을 ‘시간 기반’으로 설정해 주세요.
                </p>
                <code>{enrollment.secret}</code>
                <button
                  type="button"
                  onClick={() =>
                    void navigator.clipboard.writeText(enrollment.secret)
                  }
                >
                  설정 키 복사
                </button>
              </details>
              <p>
                등록 시간은 10분입니다. QR 코드와 설정 키는 다른 사람에게
                공유하지 마세요.
              </p>
            </div>
          )}
          {(security.enrolled || enrollment) && (
            <Form
              label={enrollment ? "등록하고 인증하기" : "인증하기"}
              onSubmit={async (f) => {
                const result = await api<{ recovery_codes: string[] }>(
                  "/admin/security/verify",
                  post({
                    password: field(f, "password"),
                    code: field(f, "code").trim(),
                  }),
                );
                setEnrollment(undefined);
                if (result.recovery_codes.length)
                  setRecovery(result.recovery_codes);
                else reload();
              }}
            >
              <Input
                label="현재 비밀번호"
                name="password"
                type="password"
                maxLength={128}
              />
              <label>
                인증 코드 또는 복구 코드
                <input
                  name="code"
                  autoComplete="one-time-code"
                  required
                  maxLength={80}
                />
              </label>
            </Form>
          )}
        </>
      )}
    </section>
  );
}

function Overview() {
  const { data, error, reload } = useLoad<{
    users: Record<string, number>;
    courses: number;
    jobs: Record<string, number>;
    workers: WorkerStatus[];
    worker_history_count: number;
    checked_at: string;
    database: string;
    operations: Settings;
  }>("/admin/overview", true);
  usePoll(reload);
  return (
    <>
      <div className="admin-section-heading">
        <h2>서비스 현황</h2>
        <button onClick={reload}>새로고침</button>
      </div>
      <ErrorNotice text={error} />
      {data ? (
        <>
          <div className="admin-stats">
            {[
              ["학생", data.users.student || 0],
              ["교수자", data.users.teacher || 0],
              ["강의", data.courses],
              [
                "대기 작업",
                (data.jobs.queued || 0) + (data.jobs.waiting_ai || 0),
              ],
              ["실행 작업", data.jobs.running || 0],
              ["실패 작업", data.jobs.failed || 0],
            ].map(([label, value]) => (
              <article key={label}>
                <span>{label}</span>
                <strong>{value}</strong>
              </article>
            ))}
          </div>
          <div className="admin-panels">
            <section className="admin-card">
              <h3>연결·운영 상태</h3>
              <div className="admin-status-line">
                <span>데이터베이스</span>
                <Badge value={data.database} />
              </div>
              <div className="admin-status-line">
                <span>사용자 점검 모드</span>
                <strong>{data.operations.maintenance ? "켜짐" : "꺼짐"}</strong>
              </div>
              <div className="admin-status-line">
                <span>서버 작업 접수</span>
                <strong>{data.operations.server_hold ? "보류" : "허용"}</strong>
              </div>
            </section>
            <AdminWorkers
              workers={data.workers}
              historyCount={data.worker_history_count}
              held={data.operations.server_hold || data.operations.maintenance}
            />
          </div>
          <p className="admin-meta">
            확인 시각 {date(data.checked_at)} · 과거 실패 작업도 포함됩니다.
          </p>
        </>
      ) : (
        !error && <Notice>상태를 불러오고 있어요…</Notice>
      )}
    </>
  );
}

function TokenNotice({ token, clear }: { token: string; clear: () => void }) {
  const url = new URL("/reset", location.origin).toString();
  return (
    <section className="admin-token" role="status">
      <h3>비밀번호 설정 안내</h3>
      <p>사용자에게 설정 화면과 아래 일회용 토큰을 안전하게 전달해 주세요.</p>
      <Link to="/reset">{url}</Link>
      <code>{token}</code>
      <button
        type="button"
        onClick={() => void navigator.clipboard.writeText(token)}
      >
        토큰 복사
      </button>
      <button type="button" onClick={clear}>
        안내 닫기
      </button>
    </section>
  );
}

function Users({ owner }: { owner: boolean }) {
  const [q, setQ] = useState("");
  const [role, setRole] = useState("");
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState<Person>();
  const [token, setToken] = useState("");
  const [message, setMessage] = useState("");
  const list = useLoad<{ items: Person[]; total: number }>(
    `/admin/users?q=${encodeURIComponent(q)}&role=${role}&offset=${offset}`,
  );
  const [confirm, dialog] = useConfirm();
  const names: Record<string, string> = {
    suspend: "계정 정지",
    activate: "계정 복구",
    logout: "모든 로그인 종료",
    reset: "비밀번호 재설정",
    grant_operator: "운영 담당자로 지정",
    grant_owner: "최고 관리자로 지정",
    revoke_admin: "관리자 권한 회수",
  };
  return (
    <>
      <h2>사용자 관리</h2>
      <p className="admin-description">
        계정을 검색하고 접근 권한을 관리하세요. 비밀번호는 조회하지 않습니다.
      </p>
      <form
        className="admin-filters"
        onSubmit={(e) => {
          e.preventDefault();
          setQ(field(new FormData(e.currentTarget), "q"));
          setOffset(0);
        }}
      >
        <label>
          이름·아이디
          <input name="q" maxLength={100} placeholder="사용자 검색" />
        </label>
        <label>
          역할
          <select
            value={role}
            onChange={(e) => {
              setRole(e.target.value);
              setOffset(0);
            }}
          >
            <option value="">전체</option>
            {["teacher", "student", "operator"].map((r) => (
              <option key={r} value={r}>
                {roles[r]}
              </option>
            ))}
          </select>
        </label>
        <button>검색</button>
      </form>
      <ErrorNotice text={list.error} />
      {message && <Notice>{message}</Notice>}
      {token && <TokenNotice token={token} clear={() => setToken("")} />}
      {list.data && (
        <>
          <div className="admin-table-scroll">
            <table className="admin-table">
              <thead>
                <tr>
                  <th>이름 / 아이디</th>
                  <th>권한</th>
                  <th>상태</th>
                  <th>관리</th>
                </tr>
              </thead>
              <tbody>
                {list.data.items.map((user) => (
                  <tr key={user.id}>
                    <td>
                      <strong>{user.display_name}</strong>
                      <small>{user.login_id}</small>
                    </td>
                    <td>{roles[user.admin_level || user.role] || user.role}</td>
                    <td>{user.active ? "활성" : "정지"}</td>
                    <td>
                      <button
                        onClick={() => {
                          setSelected(user);
                          setMessage("");
                        }}
                      >
                        관리
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {!list.data.items.length && <Notice>검색 결과가 없어요.</Notice>}
          </div>
          <Pager offset={offset} total={list.data.total} set={setOffset} />
        </>
      )}
      {selected && (
        <section className="admin-card" key={selected.id}>
          <h3>
            {selected.display_name} · {selected.login_id}
          </h3>
          <Form
            label="변경 적용"
            onCancel={() => setSelected(undefined)}
            onSubmit={async (f) => {
              const action = field(f, "action");
              if (
                !(await confirm({
                  title: names[action],
                  message: `${selected.login_id} 계정에 적용합니다. 기존 로그인은 종료됩니다.`,
                  tone: "warn",
                }))
              )
                return;
              const result = await api<{ one_time_token?: string }>(
                `/admin/users/${selected.id}/actions`,
                post({ action, reason: field(f, "reason") }),
              );
              setToken(result.one_time_token || "");
              setMessage("계정 변경을 적용했어요.");
              setSelected(undefined);
              list.reload();
            }}
          >
            <label>
              관리 작업
              <select name="action">
                {[
                  selected.active ? "suspend" : "activate",
                  "logout",
                  "reset",
                  ...(owner && selected.role === "operator"
                    ? ["grant_operator", "grant_owner", "revoke_admin"]
                    : []),
                ].map((action) => (
                  <option key={action} value={action}>
                    {names[action]}
                  </option>
                ))}
              </select>
            </label>
            <Reason />
          </Form>
        </section>
      )}
      <details className="admin-card">
        <summary>새 계정 발급</summary>
        <Form
          label="계정 발급"
          onSubmit={async (f) => {
            const result = await api<{ one_time_token: string }>(
              "/admin/users",
              post({
                login_id: field(f, "login_id").toLowerCase(),
                display_name: field(f, "name"),
                role: field(f, "role"),
                reason: field(f, "reason"),
              }),
            );
            setToken(result.one_time_token);
            setMessage(
              "계정을 발급했어요. 설정 토큰은 24시간 동안 유효합니다.",
            );
            list.reload();
          }}
        >
          <Input
            label="로그인 아이디"
            name="login_id"
            minLength={3}
            maxLength={100}
          />
          <Input label="이름" name="name" maxLength={100} />
          <label>
            역할
            <select name="role">
              {["teacher", "student", ...(owner ? ["operator"] : [])].map(
                (r) => (
                  <option key={r} value={r}>
                    {roles[r]}
                  </option>
                ),
              )}
            </select>
          </label>
          <Reason />
        </Form>
      </details>
      {dialog}
    </>
  );
}

const workGroups = [
  ["all", "전체"],
  ["running", "진행 중"],
  ["waiting", "대기·보류"],
  ["attention", "확인 필요"],
  ["done", "완료"],
  ["cancelled", "취소·중단"],
] as const;

function workHint(work: Work) {
  const errors: Record<string, string> = {
    GEMINI_SERVICE_RETRY_EXHAUSTED: "AI 서비스 오류가 5회 반복되어 자동 재시도를 멈췄어요. 다시 시도하면 완료된 결과부터 이어서 처리해요.",
    GEMINI_TEMPORARILY_UNAVAILABLE: "AI 서비스 응답 오류로 대기 중이에요. 요청 간격을 늘려 제한된 횟수만 다시 시도해요.",
    LEGACY_BACKFILL_DEFERRED: "이전 자료의 추가 생성을 보류한 작업이에요.",
    SUBMISSION_UNCERTAIN_DO_NOT_RESUBMIT:
      "영상 접수 여부를 확인해야 해요. 중복 요청하지 마세요.",
    VIDEO_STORAGE_SIZE_LIMIT: "영상 저장 용량을 확인해야 해요.",
    VIDEO_PREPARATION_FAILED: "영상 자료 화면 준비에 실패했어요. 폰트·이미지·HeyGen 업로드 연결을 확인해 주세요. 대본은 보존돼요.",
    VIDEO_PROFILE_REVIEW_REQUIRED: "이전 영상 제작 설정이에요. Avatar V·1080p 설정을 검토하기 전에는 새 렌더를 요청하지 않아요.",
    VIDEO_RENDER_PROFILE_MISMATCH: "완성 영상의 모델·해상도·강사·음성이 요청 설정과 달라 보류했어요. 기존 결과를 확인해 주세요.",
    PROVIDER_REQUIRES_REVIEW: "영상 제공 서비스의 확인이 필요해요.",
    SOURCE_REVOKED: "원본 자료가 변경되어 작업이 중단됐어요.",
    VIDEO_STATUS_OR_STORAGE_RETRY:
      "영상 상태 또는 저장 결과를 다시 확인하고 있어요.",
  };
  if (work.error_code && errors[work.error_code])
    return errors[work.error_code];
  const hints: Record<string, string> = {
    queued: "처리 순서를 기다리고 있어요.",
    waiting_ai: "AI 응답 또는 다음 처리 차례를 기다리고 있어요.",
    script_pending: "영상 대본을 준비하고 있어요.",
    running: "작업 처리기가 실행하고 있어요.",
    submitting: "영상 생성 요청을 접수하고 있어요.",
    processing: "영상 생성 서비스에서 처리하고 있어요.",
    storing: "완성된 영상을 저장하고 있어요.",
    held: "처리를 보류했어요. 상세 내용을 확인해 주세요.",
    failed: "처리에 실패했어요. 상세에서 원인을 확인해 주세요.",
    needs_attention: "처리 결과를 확인해야 해요.",
    succeeded: "처리가 완료됐어요.",
    ready: "생성이 완료되어 사용할 수 있어요.",
    cancelled: "취소된 작업이에요.",
    revoked: "원본 변경으로 중단된 작업이에요.",
  };
  return hints[work.status] || "상세 상태를 확인해 주세요.";
}

function Jobs() {
  const [category, setCategory] = useState("material");
  const [group, setGroup] = useState("all");
  const [order, setOrder] = useState("priority");
  const [days, setDays] = useState("0");
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [offset, setOffset] = useState(0);
  const [expanded, setExpanded] = useState("");
  const [selected, setSelected] = useState<{ work: Work; action: string }>();
  const [message, setMessage] = useState("");
  const list = useLoad<{
    items: Work[];
    total: number;
    summary: Record<string, number>;
    checked_at: string;
  }>(
    `/admin/jobs?category=${category}&group=${group}&order=${order}&days=${days}&q=${encodeURIComponent(query)}&offset=${offset}`,
    true,
  );
  usePoll(list.reload);
  useEffect(() => {
    setSelected(undefined);
    setExpanded("");
    setMessage("");
  }, [category, group, order, days, query, offset]);
  return (
    <section className="admin-jobs" aria-label="작업 처리 현황">
      <div className="admin-section-heading">
        <div>
          <h2>작업 관리</h2>
          <p className="admin-meta admin-job-updated">
            20초마다 자동 갱신 · 마지막 확인{" "}
            {list.data
              ? new Date(list.data.checked_at).toLocaleTimeString("ko-KR", {
                  timeZone: "Asia/Seoul",
                })
              : "확인 중"}
          </p>
        </div>
        <button onClick={list.reload}>새로고침</button>
      </div>
      <p className="admin-description">
        작업 종류를 고른 뒤 상태별로 확인하세요. 진행 중이거나 확인이 필요한
        작업을 먼저 보여드려요.
      </p>
      <div className="admin-job-categories" role="group" aria-label="작업 종류">
        {[
          ["material", "자료·학습·RAG"],
          ["code", "코드 실행"],
          ["video", "영상 생성"],
        ].map(([id, label]) => (
          <button
            key={id}
            aria-pressed={category === id}
            onClick={() => {
              setCategory(id);
              setOffset(0);
            }}
          >
            {label}
          </button>
        ))}
      </div>
      <div
        className="admin-job-summary"
        role="group"
        aria-label="작업 상태 필터"
      >
        {workGroups.map(([id, label]) => (
          <button
            key={id}
            className={`admin-job-count group-${id}`}
            aria-pressed={group === id}
            onClick={() => {
              setGroup(id);
              setOffset(0);
            }}
          >
            <span>{label}</span>
            <strong>{list.data ? list.data.summary[id] || 0 : "—"}</strong>
          </button>
        ))}
      </div>
      <form
        className="admin-job-filters"
        onSubmit={(event) => {
          event.preventDefault();
          setQuery(search.trim());
          setOffset(0);
        }}
      >
        <label className="admin-job-search">
          강의·사용자 검색
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            maxLength={100}
            placeholder="강의명, 이름 또는 아이디"
          />
        </label>
        <button type="submit">검색</button>
        <label>
          기간
          <select
            aria-label="기간"
            value={days}
            onChange={(e) => {
              setDays(e.target.value);
              setOffset(0);
            }}
          >
            <option value="0">전체 기간</option>
            <option value="1">최근 24시간</option>
            <option value="7">최근 7일</option>
            <option value="30">최근 30일</option>
          </select>
        </label>
        <label>
          정렬
          <select
            aria-label="정렬"
            value={order}
            onChange={(e) => {
              setOrder(e.target.value);
              setOffset(0);
            }}
          >
            <option value="priority">진행·확인 필요 우선</option>
            <option value="newest">최근 요청순</option>
            <option value="oldest">오래된 요청순</option>
          </select>
        </label>
        {(query || days !== "0" || group !== "all" || order !== "priority") && (
          <button
            type="button"
            onClick={() => {
              setSearch("");
              setQuery("");
              setDays("0");
              setGroup("all");
              setOrder("priority");
              setOffset(0);
            }}
          >
            필터 초기화
          </button>
        )}
      </form>
      <ErrorNotice text={list.error} />
      {message && <Notice>{message}</Notice>}
      {!list.data && !list.error && (
        <Notice>작업 상태를 확인하고 있어요…</Notice>
      )}
      {list.data && (
        <>
          <p className="admin-meta admin-job-results">
            {workGroups.find(([id]) => id === group)?.[1]} {list.data.total}건
            {query && ` · ‘${query}’ 검색 결과`}
            {" · 상태 카드를 누르면 해당 작업만 볼 수 있어요."}
          </p>
          <div className="admin-job-list" role="list">
            <div className="admin-job-columns" aria-hidden="true">
              <span>작업·강의</span>
              <span>현재 상태</span>
              <span>요청자</span>
              <span>요청 시각</span>
              <span>상세</span>
            </div>
            {list.data.items.map((work) => (
              <article
                key={work.id}
                role="listitem"
                className={`admin-job-item group-${work.group}`}
              >
                <div className="admin-job-row">
                  <div className="admin-job-title">
                    <strong>
                      {work.title || kinds[work.kind] || work.kind}
                    </strong>
                    <small>{work.course_title}</small>
                  </div>
                  <div className="admin-job-state">
                    <span
                      className={`admin-job-state-badge group-${work.group}`}
                    >
                      {work.error_code === "LEGACY_BACKFILL_DEFERRED"
                        ? "보류"
                        : statuses[work.status] || work.status}
                    </span>
                    <small>{workHint(work)}</small>
                  </div>
                  <div className="admin-job-owner">
                    <span>{work.owner_name}</span>
                    <small>{work.owner}</small>
                  </div>
                  <time className="admin-job-time" dateTime={work.created_at}>
                    {date(work.created_at)}
                  </time>
                  <button
                    className="admin-job-expand"
                    aria-expanded={expanded === work.id}
                    aria-controls={`job-detail-${work.id}`}
                    onClick={() =>
                      setExpanded(expanded === work.id ? "" : work.id)
                    }
                  >
                    {expanded === work.id ? "접기" : "상세"}
                  </button>
                </div>
                {expanded === work.id && (
                  <div
                    className="admin-job-detail"
                    id={`job-detail-${work.id}`}
                  >
                    <dl>
                      <div>
                        <dt>작업 ID</dt>
                        <dd>{work.id}</dd>
                      </div>
                      <div>
                        <dt>작업 유형</dt>
                        <dd>{kinds[work.kind] || work.kind}</dd>
                      </div>
                      <div>
                        <dt>오류 코드</dt>
                        <dd>{work.error_code || "없음"}</dd>
                      </div>
                      {work.provider_error && <>
                        <div><dt>최근 AI 오류</dt><dd>HTTP {work.provider_error.http_status} · {work.provider_error.provider_code || "상세 코드 없음"}</dd></div>
                        <div><dt>동일 요청 오류 횟수</dt><dd>{work.provider_error.service_failures}/{work.provider_error.max_service_failures}회</dd></div>
                        <div><dt>사용 모델</dt><dd>{work.provider_error.model || "확인 필요"}</dd></div>
                        <div><dt>기록 시각</dt><dd>{new Date(work.provider_error.recorded_at).toLocaleString("ko-KR")}</dd></div>
                        <div><dt>제공자 안내</dt><dd>{work.provider_error.message || "민감한 입력이 포함될 수 있어 원문 메시지는 기록하지 않았어요."}</dd></div>
                        <div><dt>요청 추적 ID</dt><dd>{work.provider_error.request_id || work.provider_error.request_hash}</dd></div>
                      </>}
                    </dl>
                    <div className="admin-row-actions">
                      {["queued", "waiting_ai", "script_pending"].includes(
                        work.status,
                      ) && (
                        <button
                          disabled={work.locked}
                          onClick={() =>
                            setSelected({ work, action: "cancel" })
                          }
                        >
                          작업 취소
                        </button>
                      )}
                      {category !== "code" &&
                        (work.status === "failed" ||
                          (category === "video" &&
                            work.provider_submitted &&
                            ["held", "needs_attention"].includes(
                              work.status,
                            ))) && (
                          <button
                            disabled={work.locked}
                            onClick={() =>
                              setSelected({ work, action: "retry" })
                            }
                          >
                            {category === "video" ? "결과 다시 확인" : "재시도"}
                          </button>
                        )}
                    </div>
                    {(work.group === "running" || work.locked) && (
                      <p className="admin-meta">
                        실행 중인 작업은 완료 후 관리할 수 있어요.
                      </p>
                    )}
                    {selected?.work.id === work.id && (
                      <div
                        className="admin-job-action"
                        aria-label="작업 상태 변경"
                      >
                        <h3>
                          {selected.action === "cancel"
                            ? "작업 취소"
                            : "작업 재시도"}
                        </h3>
                        <Form
                          label="적용"
                          onCancel={() => setSelected(undefined)}
                          onSubmit={async (f) => {
                            await api(
                              `/admin/jobs/${category}/${work.id}/actions`,
                              post({
                                action: selected.action,
                                reason: field(f, "reason"),
                              }),
                            );
                            setSelected(undefined);
                            setMessage("작업 상태를 변경했어요.");
                            list.reload();
                          }}
                        >
                          <Reason />
                        </Form>
                      </div>
                    )}
                  </div>
                )}
              </article>
            ))}
            {!list.data.items.length && (
              <div className="admin-job-empty">
                <strong>
                  {group === "running"
                    ? "현재 진행 중인 작업이 없어요."
                    : group === "attention"
                      ? "확인이 필요한 작업이 없어요."
                      : "조건에 맞는 작업이 없어요."}
                </strong>
                <p>다른 상태를 선택하거나 검색·기간 조건을 바꿔 보세요.</p>
              </div>
            )}
          </div>
          <Pager offset={offset} total={list.data.total} set={setOffset} />
        </>
      )}
    </section>
  );
}

function SettingsPanel({ owner }: { owner: boolean }) {
  const { data, error, reload } = useLoad<Settings>("/admin/settings");
  const [message, setMessage] = useState("");
  return (
    <>
      <h2>점검·기능 설정</h2>
      <p className="admin-description">
        점검 모드는 새 이용 요청과 작업 실행을 제한합니다. 서버는 계속 켜져
        있어요.
      </p>
      <ErrorNotice text={error} />
      {message && <Notice>{message}</Notice>}
      {data && (
        <section className="admin-card" key={data.revision}>
          <fieldset disabled={!owner}>
            <Form
              label="설정 저장"
              onSubmit={async (f) => {
                await api("/admin/settings", {
                  method: "PUT",
                  body: JSON.stringify({
                    revision: data.revision,
                    maintenance: f.has("maintenance"),
                    message: field(f, "message"),
                    features: Object.fromEntries(
                      Object.keys(features).map((key) => [key, f.has(key)]),
                    ),
                    reason: field(f, "reason"),
                  }),
                });
                setMessage("운영 설정을 저장했어요.");
                reload();
              }}
            >
              <fieldset disabled={!owner}>
                <label className="admin-check">
                  <input
                    name="maintenance"
                    type="checkbox"
                    defaultChecked={data.maintenance}
                  />
                  서비스 점검 모드
                </label>
                <label>
                  점검 안내
                  <textarea
                    name="message"
                    required
                    maxLength={500}
                    defaultValue={data.message}
                  />
                </label>
                <h3>개별 기능 허용</h3>
                {Object.entries(features).map(([key, label]) => (
                  <label className="admin-check" key={key}>
                    <input
                      type="checkbox"
                      name={key}
                      defaultChecked={data.features[key]}
                    />
                    {label}
                  </label>
                ))}
                <p>
                  영상 생성을 중지해도 외부에 접수된 영상의 결과 확인·저장은
                  계속됩니다.
                </p>
                <Reason />
              </fieldset>
              {!owner && (
                <Notice>설정 변경은 최고 관리자만 할 수 있어요.</Notice>
              )}
            </Form>
          </fieldset>
        </section>
      )}
    </>
  );
}

function ServerPanel({ owner }: { owner: boolean }) {
  const { data, error, reload } = useLoad<Server>("/admin/server", true);
  const [action, setAction] = useState("");
  const [message, setMessage] = useState("");
  const [key, setKey] = useState(() => crypto.randomUUID());
  const [confirm, dialog] = useConfirm();
  usePoll(reload, 15);
  const labels: Record<string, string> = {
    start: "서버 켜기",
    stop: "작업 종료 후 서버 중지",
    restart: "작업 종료 후 재시작",
    resume: "작업 접수 재개",
  };
  const pending = data?.commands.some((c) =>
    [
      "queued",
      "draining",
      "starting",
      "stopping",
      "restarting",
      "uncertain",
    ].includes(c.status),
  );
  return (
    <>
      <div className="admin-section-heading">
        <h2>AWS 작업 서버</h2>
        <button onClick={reload}>새로고침</button>
      </div>
      <p className="admin-description">
        자료·코드·영상 처리 서버를 관리합니다. 서버가 중지돼도 관리자 화면에서
        다시 켤 수 있어요.
      </p>
      <ErrorNotice text={error} />
      {message && <Notice>{message}</Notice>}
      {data && (
        <>
          <section className="admin-card">
            <div className="admin-status-line">
              <div>
                <h3>현재 서버 상태</h3>
                <small>
                  {data.instance_id || "서버 연결 설정 필요"} ·{" "}
                  {data.region || ""}
                </small>
              </div>
              <Badge value={data.state} />
            </div>
            <div className="admin-status-line">
              <span>독립 실행 스케줄러</span>
              <strong>
                {data.scheduler_ready ? "연결됨" : "응답 확인 필요"}
              </strong>
            </div>
            <p className="admin-meta">
              스케줄러 응답 {date(data.scheduler_seen_at)}
            </p>
            <div className="admin-status-line">
              <span>신규 작업 접수</span>
              <strong>{data.server_hold ? "보류 중" : "허용"}</strong>
            </div>
            <p>
              진행 중 · 자료/학습 {data.busy.jobs || 0}, 코드{" "}
              {data.busy.code || 0}, 외부 AI {data.busy.model || 0}, 영상 처리{" "}
              {data.busy.video || 0}
            </p>
            <div className="admin-row-actions">
              {[
                "start",
                "stop",
                "restart",
                ...(data.server_hold ? ["resume"] : []),
              ].map((value) => (
                <button
                  key={value}
                  disabled={
                    !owner ||
                    !data.configured ||
                    !data.scheduler_ready ||
                    pending ||
                    (value === "start"
                      ? !["stopped", "running"].includes(data.state)
                      : data.state !== "running")
                  }
                  onClick={() => {
                    setAction(value);
                    setKey(crypto.randomUUID());
                  }}
                >
                  {labels[value]}
                </button>
              ))}
            </div>
            {!owner && <p>서버 제어는 최고 관리자만 할 수 있어요.</p>}
          </section>
          {action && (
            <section className="admin-card admin-danger" key={key}>
              <h3>{labels[action]}</h3>
              <p>
                {action === "start"
                  ? "서버를 켜면 AWS 실행 요금이 다시 발생합니다. 처리기가 정상인지 확인한 뒤 작업을 재개합니다."
                  : "새 작업을 막고 진행 중인 작업이 끝난 뒤 실행합니다. 외부에서 이미 생성 중인 영상은 계속 처리될 수 있어요."}
              </p>
              <Form
                label="서버 작업 요청"
                onCancel={() => setAction("")}
                onSubmit={async (f) => {
                  if (
                    !(await confirm({
                      title: labels[action],
                      message:
                        "이 작업은 실제 AWS 서버 상태에 영향을 줍니다. 계속할까요?",
                      tone: "warn",
                    }))
                  )
                    return;
                  await api("/admin/server/commands", {
                    ...post({
                      action,
                      reason: field(f, "reason"),
                      confirmation: field(f, "confirmation"),
                    }),
                    headers: { "Idempotency-Key": key },
                  });
                  setAction("");
                  setMessage(
                    "요청을 접수했어요. 화면을 닫아도 처리 상태는 저장됩니다.",
                  );
                  reload();
                }}
              >
                <Reason />
                <label>
                  확인을 위해 Lerny 입력
                  <input
                    name="confirmation"
                    required
                    pattern="Lerny"
                    autoComplete="off"
                  />
                </label>
              </Form>
            </section>
          )}
          <h3>최근 서버 작업</h3>
          <div className="admin-table-scroll">
            <table className="admin-table">
              <thead>
                <tr>
                  <th>작업</th>
                  <th>상태</th>
                  <th>사유</th>
                  <th>요청 시각</th>
                </tr>
              </thead>
              <tbody>
                {data.commands.map((c) => (
                  <tr key={c.id}>
                    <td>{labels[c.action] || c.action}</td>
                    <td>
                      <Badge value={c.status} />
                      {c.error_code && <small>{c.error_code}</small>}
                    </td>
                    <td>{c.reason}</td>
                    <td>{date(c.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {!data.commands.length && (
              <Notice>아직 서버 제어 이력이 없어요.</Notice>
            )}
          </div>
        </>
      )}
      {dialog}
    </>
  );
}

function Audit() {
  const [offset, setOffset] = useState(0);
  const { data, error, reload } = useLoad<{
    items: {
      id: string;
      actor: string;
      action: string;
      target_id: string;
      detail: Record<string, unknown>;
      created_at: string;
    }[];
    total: number;
  }>(`/admin/audit?offset=${offset}`);
  return (
    <>
      <div className="admin-section-heading">
        <h2>관리 이력</h2>
        <button onClick={reload}>새로고침</button>
      </div>
      <p className="admin-description">
        관리자 변경 요청과 보안 인증의 결과를 확인하세요.
      </p>
      <ErrorNotice text={error} />
      {data && (
        <>
          <div className="admin-table-scroll">
            <table className="admin-table">
              <thead>
                <tr>
                  <th>시각</th>
                  <th>관리자</th>
                  <th>동작</th>
                  <th>결과·사유</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((item) => (
                  <tr key={item.id}>
                    <td>{date(item.created_at)}</td>
                    <td>{item.actor}</td>
                    <td>
                      {item.action}
                      <small>{item.target_id}</small>
                    </td>
                    <td>
                      {String(item.detail.outcome || "")}
                      <small>{String(item.detail.reason || "")}</small>
                      <details>
                        <summary>변경 내용</summary>
                        <pre>{JSON.stringify(item.detail, null, 2)}</pre>
                      </details>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Pager offset={offset} total={data.total} set={setOffset} />
        </>
      )}
    </>
  );
}
