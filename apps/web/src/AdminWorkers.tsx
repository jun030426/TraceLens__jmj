import { useState } from "react";
import { ErrorNotice, Notice, useLoad } from "./components";
import { ListPager } from "./StudentLists";

export type WorkerStatus = {
  kind: string;
  status: string;
  last_seen_at: string | null;
  responding: number;
  ready: number;
};
const names: Record<string, string> = {
  material: "자료·학습",
  code: "코드 실행",
  video: "영상",
};
const labels: Record<string, string> = {
  online: "정상",
  not_ready: "준비 중",
  waiting_response: "응답 대기",
  stale: "응답 확인 필요",
};
const time = (value: string) =>
  new Date(value).toLocaleString("ko-KR", { timeZone: "Asia/Seoul" });

export function AdminWorkers({
  workers,
  historyCount,
  held,
}: {
  workers: WorkerStatus[];
  historyCount: number;
  held: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  return (
    <section
      className="admin-card admin-workers-card"
      aria-label="작업 처리기 상태"
    >
      <h3>작업 처리기</h3>
      <p className="admin-worker-description">
        연결된 작업 서버의 최근 응답을 종류별로 보여요.
      </p>
      {held && (
        <p className="admin-worker-hold">
          작업 접수가 보류되어 있어요. 최근 응답이 없으면 대기로 표시해요.
        </p>
      )}
      <div className="admin-worker-summary">
        {workers.map((worker) => (
          <div className="admin-worker" key={worker.kind}>
            <div>
              <strong>{names[worker.kind] || worker.kind}</strong>
              <small>
                {worker.responding > 0
                  ? `최근 90초 내 응답 ${worker.responding}개 · 준비 완료 ${worker.ready}개`
                  : worker.last_seen_at
                    ? "최근 90초 동안 응답 없음"
                    : "첫 응답을 기다리고 있어요"}
              </small>
            </div>
            <span className={`admin-badge state-${worker.status}`}>
              {labels[worker.status] || worker.status}
            </span>
          </div>
        ))}
      </div>
      <details
        className="admin-worker-details"
        onToggle={(event) => setExpanded(event.currentTarget.open)}
      >
        <summary>
          응답 기록 보기 <span>{historyCount}건</span>
        </summary>
        {expanded && <WorkerHistory />}
      </details>
    </section>
  );
}

function WorkerHistory() {
  const [kind, setKind] = useState("");
  const [page, setPage] = useState(0);
  const query = new URLSearchParams({ offset: String(page * 5), limit: "5" });
  if (kind) query.set("kind", kind);
  const result = useLoad<{
    items: {
      id: string;
      kind: string;
      last_seen_at: string;
      ready_at_response: boolean;
    }[];
    total: number;
  }>(`/admin/workers?${query}`);
  return (
    <div className="admin-worker-history">
      <p className="admin-worker-description">
        실행별 마지막 응답이에요. 강의·학습 데이터와 별도로 보관하며, 최신순으로
        5개씩 표시해요.
      </p>
      <div className="admin-worker-tools">
        <label>
          처리기 종류
          <select
            value={kind}
            onChange={(event) => {
              setKind(event.target.value);
              setPage(0);
            }}
          >
            <option value="">전체</option>
            {Object.entries(names).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <button
          type="button"
          onClick={() => {
            setPage(0);
            result.reload();
          }}
        >
          기록 새로고침
        </button>
      </div>
      <ErrorNotice text={result.error} />
      {!result.data && !result.error && (
        <Notice>응답 기록을 불러오는 중이에요…</Notice>
      )}
      {result.data && (
        <>
          <p className="admin-worker-count" role="status">
            총 {result.data.total}건
          </p>
          {result.data.items.length ? (
            <div
              className="admin-worker-scroll"
              role="region"
              aria-label="처리기 응답 기록 목록"
              tabIndex={0}
            >
              <ol>
                {result.data.items.map((row) => (
                  <li key={row.id}>
                    <strong>{names[row.kind] || row.kind}</strong>
                    <time dateTime={row.last_seen_at}>
                      {time(row.last_seen_at)}
                    </time>
                    <small>
                      응답 당시{" "}
                      {row.ready_at_response ? "준비 완료" : "준비 중"}
                    </small>
                  </li>
                ))}
              </ol>
            </div>
          ) : (
            <Notice>선택한 처리기의 응답 기록이 없어요.</Notice>
          )}
          <ListPager
            page={page}
            pages={Math.max(1, Math.ceil(result.data.total / 5))}
            onChange={setPage}
            label="처리기 응답 기록"
          />
        </>
      )}
    </div>
  );
}
