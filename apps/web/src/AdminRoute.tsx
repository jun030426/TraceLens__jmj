import { lazy, Suspense } from "react";
import { Notice } from "./components";
const Console = lazy(() =>
  import("./Admin").then((module) => ({ default: module.AdminPage })),
);
export function AdminPage() {
  return (
    <Suspense fallback={<Notice>관리자 화면을 불러오고 있어요…</Notice>}>
      <Console />
    </Suspense>
  );
}
