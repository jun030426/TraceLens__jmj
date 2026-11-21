import { useId, useLayoutEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { Link } from "react-router-dom";
import type { Classroom } from "./api";
import { ErrorNotice, Notice, useLoad } from "./components";
import type { LearningConcept } from "./conceptProgress";
import { periodQuery, type Period } from "./learningPeriod";
import {
  BAND_LABEL,
  weaknessSummary,
  weaknessHeadline,
  type Band,
} from "./weakness";
import { ListPager } from "./StudentLists";

function reviewLink(c: LearningConcept | undefined, sectionId: string) {
  if (c?.review_session_id && c.review_question_id)
    return `/quiz/results/${c.review_session_id}#question-${c.review_question_id}`;
  if (c?.weeks.length)
    return `/classrooms/${sectionId}#material-week-${c.weeks[0]}`;
  return `/quiz?section=${sectionId}`;
}
function Ring({
  pct,
  band,
  size,
  stroke,
  label,
  children,
  className = "",
}: {
  pct: number | null;
  band: Band;
  size: number;
  stroke: number;
  label: string;
  children?: ReactNode;
  className?: string;
}) {
  const id = useId().replace(/:/g, "");
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const filled = pct == null ? 0 : Math.max(0, Math.min(100, pct));
  const style = {
    width: size,
    height: size,
    "--wk-c": `${c}`,
    "--wk-off": `${c * (1 - filled / 100)}`,
  } as CSSProperties;
  return (
    <div
      className={`wk-ring is-${band} ${className}`}
      style={style}
      role="img"
      aria-label={label}
    >
      <svg
        width={size}
        height={size}
        viewBox={`0 0 ${size} ${size}`}
        aria-hidden="true"
      >
        <defs>
          <linearGradient id={`g${id}`} x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" className="wk-stop-a" />
            <stop offset="100%" className="wk-stop-b" />
          </linearGradient>
        </defs>
        <circle
          className="wk-ring__track"
          cx={size / 2}
          cy={size / 2}
          r={r}
          strokeWidth={stroke}
          fill="none"
        />
        {filled > 0 && (
          <circle
            className="wk-ring__value"
            cx={size / 2}
            cy={size / 2}
            r={r}
            strokeWidth={stroke}
            fill="none"
            strokeLinecap="round"
            stroke={`url(#g${id})`}
            strokeDasharray={c}
            strokeDashoffset={c * (1 - filled / 100)}
            transform={`rotate(-90 ${size / 2} ${size / 2})`}
          />
        )}
      </svg>
      <div className="wk-ring__center">{children}</div>
    </div>
  );
}

export function WeaknessCard({
  items,
  sectionId,
}: {
  items: LearningConcept[];
  sectionId: string;
}) {
  const [page, setPage] = useState(0);
  const scoped = items.filter(
    (c) =>
      c.in_scope ||
      (c.learning && c.learning.state !== "no_data") ||
      c.valid_recent > 0,
  );
  const s = weaknessSummary(scoped);
  const byId = new Map(scoped.map((c) => [c.id, c]));
  const spot = s.rings.filter((r) => r.band === "weak").slice(0, 3);
  const pages = Math.max(1, Math.ceil(s.rings.length / 12));
  const currentPage = Math.min(page, pages - 1);
  const mapRef = useRef<HTMLUListElement>(null);

  useLayoutEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    const overviews = [...map.querySelectorAll<HTMLElement>(".wk-map__overview")];
    const alignEvidence = () => {
      const height = Math.max(0, ...overviews.map((overview) => overview.offsetHeight));
      map.style.setProperty("--wk-overview-height", `${height}px`);
    };

    alignEvidence();
    const observer = new ResizeObserver(alignEvidence);
    overviews.forEach((overview) => observer.observe(overview));
    return () => observer.disconnect();
  }, [items, currentPage]);

  return (
    <div className="wk">
      <section
        className="wk-hero student-weakness-summary"
        aria-label="나의 취약도 요약"
      >
        <div className="wk-hero__side">
          <Ring pct={scoped.length ? 100 * s.counts.weak / scoped.length : null}
            band={s.counts.weak ? "weak" : "none"} size={150} stroke={14}
            label={`개념 ${scoped.length}개 중 복습 필요 ${s.counts.weak}개`} className="wk-hero__ring">
            <strong>{s.counts.weak}<small>개</small></strong><span>복습 필요</span>
          </Ring>
        </div>
        <div className="wk-hero__text">
          <h3>{weaknessHeadline(s)}</h3>
          <p>
            이론 독립 풀이로 확인해요. 취약도는 0~100이며 높을수록 복습이
            필요해요.
          </p>
          <ul className="student-signal-counts">
            {(Object.keys(BAND_LABEL) as Band[]).map((b) => (
              <li key={b} className={s.counts[b] > 0 ? `has-count is-${b}` : undefined}>
                <b>{s.counts[b]}개</b> {BAND_LABEL[b]}
              </li>
            ))}
          </ul>
          <p className="muted">
            개념별 최근 5건 중 4건 이상 정답, 2일 이상 정답 기록이면 기준
            충족이에요. 5건 미만은 표본 부족으로 표시해요.
          </p>
          {spot[0] && (
            <Link
              className="wk-cta"
              to={reviewLink(byId.get(spot[0].id), sectionId)}
            >
              「{spot[0].concept}」 복습하기 →
            </Link>
          )}
        </div>
      </section>
      {spot.length > 0 && <section className="wk-section" aria-label="먼저 복습할 개념">
        <div className="wk-section__head"><h4>먼저 복습할 개념</h4></div>
        <ol className="wk-spots">{spot.map((ring, index) => (
          <li className="wk-spot is-weak" key={ring.id}>
            <div className="wk-spot__head"><span className="wk-spot__rank">{index + 1}</span>
              <span className="wk-spot__name"><strong>{ring.concept}</strong></span>
              <span className="wk-chip is-weak">{BAND_LABEL.weak}</span>
            </div>
            {ring.pct != null && <div className="wk-spot__score">
              <div className="wk-spot__bar" aria-hidden="true"><i style={{ width: `${ring.pct}%` }} /></div>
              <b aria-label={`취약도 ${ring.pct}점`}>{ring.pct}<small>점</small></b>
            </div>}
            <div className="wk-spot__foot"><span className="wk-spot__count">최근 독립 풀이 {ring.solved}건 중 {ring.correct}건 정답</span>
              <Link className="wk-spot__go" to={reviewLink(byId.get(ring.id), sectionId)} aria-label={`${ring.concept} 복습하기`}>복습하기 →</Link>
            </div>
          </li>
        ))}</ol>
      </section>}
      {!s.rings.length ? (
        <Notice>
          선택 기간에 확인할 개념이 없어요. 강의 자료와 개념 퀴즈를 확인해
          보세요.
        </Notice>
      ) : (
        <section className="wk-section" aria-labelledby="wk-map-title">
          <div className="wk-section__head">
            <h4 id="wk-map-title">개념별 취약도 지도</h4>
            <p>복습 필요 → 표본 부족 → 추가 확인 순으로 보여요.</p>
          </div>
          <ul ref={mapRef} className="wk-map student-weakness-map">
            {s.rings.slice(currentPage * 12, currentPage * 12 + 12).map((r) => (
              <li key={r.id} className={`wk-map__card is-${r.band}`}>
                <Link
                  to={reviewLink(byId.get(r.id), sectionId)}
                  className="wk-map__overview"
                  title={`${r.concept} 답안·자료 보기`}
                >
                  <Ring
                    pct={r.pct}
                    band={r.band}
                    size={86}
                    stroke={9}
                    label={`${r.concept}: ${r.pct == null ? "취약도 미산정" : `취약도 ${r.pct}/100`}, ${BAND_LABEL[r.band]}`}
                  >
                    <strong>{r.pct == null ? "—" : r.pct}</strong>
                  </Ring>
                  <span className="wk-map__name">{r.concept}</span>
                  <small>{BAND_LABEL[r.band]}</small>
                  <small>
                    {r.pct == null
                      ? `독립 풀이 ${r.solved}/5건`
                      : `취약도 ${r.pct}/100 · 정답 ${r.correct}/5건`}
                  </small>
                  {r.band === "learning" && (
                    <small>다른 날에도 정답을 확인해 보세요.</small>
                  )}
                </Link>
                <details className="wk-map-evidence"><summary>판단 근거</summary>
                  <p>최근 독립 풀이 {r.solved}건 중 정답 {r.correct}건.
                    {r.pct == null ? " 점수 산정에는 5건이 필요해요." : ` 오답 비율에 따른 취약도는 ${r.pct}점이에요.`}</p>
                  <Link to={reviewLink(byId.get(r.id), sectionId)}>답안·자료 보기 →</Link>
                </details>
              </li>
            ))}
          </ul>
          <ListPager
            page={currentPage}
            pages={pages}
            onChange={setPage}
            label="개념별 취약도"
          />
        </section>
      )}
    </div>
  );
}

export function WeaknessTab({
  room,
  period,
}: {
  room: Classroom;
  period: Period;
}) {
  const result = useLoad<{ items: LearningConcept[] }>(
    `/sections/${room.section.id}/my-learning?${periodQuery(period)}`,
  );
  if (result.error)
    return (
      <>
        <ErrorNotice text={result.error} />
        <button onClick={result.reload}>다시 불러오기</button>
      </>
    );
  if (!result.data) return <Notice>취약도를 불러오는 중이에요…</Notice>;
  return (
    <div className="weakness-tab">
      <p className="muted">
        도움받은 풀이·재학습·채점 대기는 취약도 계산에서 제외해요. 실습 결과는
        실습 탭에서 따로 확인해요.
      </p>
      <WeaknessCard
        key={`${period.from}:${period.to}`}
        items={result.data.items}
        sectionId={room.section.id}
      />
    </div>
  );
}
