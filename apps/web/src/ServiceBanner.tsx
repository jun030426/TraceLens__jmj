import { useServiceStatus } from "./ServiceStatus";
import "./admin.css";
const features: Record<string, string> = {
  uploads: "자료 업로드·분석",
  rag: "RAG 질문",
  grading: "실습·이론 채점",
  content: "학습 콘텐츠 생성",
  videos: "새 영상 생성",
};
export function ServiceBanner() {
  const { data } = useServiceStatus();
  if (
    !data ||
    (!data.maintenance &&
      !data.server_hold &&
      Object.values(data.features || {}).every(Boolean))
  )
    return null;
  return (
    <aside className="admin-service-banner" role="status">
      <strong>{data.maintenance ? "서비스 점검" : "일부 기능 일시정지"}</strong>
      <span>
        {data.maintenance
          ? data.message
          : data.server_hold
            ? "작업 서버 점검 중이에요. 기존 자료와 학습 기록은 확인할 수 있어요."
            : Object.entries(data.features)
                .filter(([, on]) => !on)
                .map(([key]) => features[key])
                .join(", ") + " 기능이 잠시 중지됐어요."}
      </span>
    </aside>
  );
}
