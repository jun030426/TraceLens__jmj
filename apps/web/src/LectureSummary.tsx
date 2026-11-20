import { Link } from "react-router-dom";
import { useLoad } from "./components";

/** 선택한 공개 자료에서 개념 이름이 일치하는 검색 단위와 원문을 보여 줘요.
 *  비중은 일치한 텍스트 길이의 비율이며 영상 제작 여부를 뜻하지 않아요.
 *  서버 응답: GET /materials/{id}/lecture-summary → { items: LectureSummaryItem[] } */
export type LectureSummaryItem = {
  concept_id: string;
  concept: string;
  /** 강의 자료에서 이 개념이 차지하는 비중 (0~1) */
  share: number;
  /** 자료 안 위치 (예: "p.3–7") */
  pages?: string;
  /** 그 부분의 요약 문장 */
  points: string[];
  video_status?: "ready" | "making" | "planned";
};

export const LECTURE_SHARE_MIN = 0.15;

const pct = (n: number) => `${Math.round(n * 100)}%`;

export function LectureSummary({ materialId, title, conceptId, viewUrl }: { materialId: string; title: string; conceptId?: string; viewUrl?: string | null }) {
  const query = conceptId ? `?concept_id=${encodeURIComponent(conceptId)}` : "";
  const summary = useLoad<{ items: LectureSummaryItem[] }>(`/materials/${materialId}/lecture-summary${query}`);
  const items = summary.data?.items || [];
  const cur = conceptId ? items.find(item => item.concept_id === conceptId)
    : items.filter(item => item.share >= LECTURE_SHARE_MIN).sort((a, b) => b.share - a.share)[0];
  if (!summary.data && !summary.error) return <div className="instructor-info-content lecture-summary"><p className="lecture-summary-empty">요약을 불러오는 중이에요…</p></div>;
  if (summary.error) return <div className="instructor-info-content lecture-summary"><p role="alert">자료의 개념을 불러오지 못했어요. 잠시 후 다시 확인해 주세요.</p></div>;
  if (!cur) return <div className="instructor-info-content lecture-summary"><p className="lecture-summary-empty">자료 처리가 끝나고 연결된 개념이 준비되면, 이곳에서 해당 원문과 출처를 확인할 수 있어요.</p></div>;
  return <div className="instructor-info-content lecture-summary">
    <div className="lecture-summary-current">
      <div className="lecture-summary-title">
        <span className="lecture-summary-kicker">{conceptId ? "선택한 영상의 핵심 개념" : "선택한 자료의 핵심 개념"}</span>
        <strong>{cur.concept}</strong>
      </div>
      <div className="lecture-summary-share"><span>관련 원문 비중</span><span className="lecture-summary-bar" aria-hidden="true"><i style={{ width: pct(Math.min(1, cur.share)) }} /></span><b>{pct(cur.share)}</b></div>
      <h4>자료에서 확인한 내용</h4>
      <ul>{cur.points.map((p, j) => <li key={j}>{p}</li>)}</ul>
    </div>
    <p className="lecture-summary-source"><span>출처 강의 자료</span>{viewUrl ? <Link to={viewUrl}>{title}</Link> : <span>{title}</span>}{cur.pages && <small>{cur.pages}</small>}</p>
  </div>;
}
