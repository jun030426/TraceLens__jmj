import { createContext, useContext, useEffect, type ReactNode } from "react";
import { useLoad } from "./components";

export type ServiceSettings = {
  maintenance: boolean;
  message: string;
  server_hold: boolean;
  features: Record<string, boolean>;
};
const ServiceStatus = createContext<{
  data?: ServiceSettings;
  error: string;
  reload: () => void;
}>({ error: "", reload: () => {} });

export function ServiceStatusProvider({ children }: { children: ReactNode }) {
  const status = useLoad<ServiceSettings>("/service-status", true);
  useEffect(() => {
    const refresh = () => {
      if (!document.hidden) status.reload();
    };
    const timer = window.setInterval(refresh, 30000);
    document.addEventListener("visibilitychange", refresh);
    return () => {
      clearInterval(timer);
      document.removeEventListener("visibilitychange", refresh);
    };
  }, [status.reload]);
  return (
    <ServiceStatus.Provider value={status}>{children}</ServiceStatus.Provider>
  );
}
export const useServiceStatus = () => useContext(ServiceStatus);

export function featureBlock(
  data: ServiceSettings | undefined,
  feature: string,
  error = "",
) {
  if (error)
    return "서비스 상태를 확인하지 못했어요. 새로고침 후 다시 시도해 주세요.";
  if (!data) return "서비스 상태를 확인하고 있어요.";
  if (data.maintenance)
    return (
      data.message || "서비스 점검 중이에요. 점검이 끝나면 이용할 수 있어요."
    );
  if (data.server_hold)
    return "작업 서버가 중지 또는 재개 대기 중이에요. 관리자가 접수를 재개하면 이용할 수 있어요.";
  if (!data.features[feature])
    return "이 기능은 운영 점검으로 잠시 중지됐어요. 관리자가 재개하면 이용할 수 있어요.";
  return "";
}
