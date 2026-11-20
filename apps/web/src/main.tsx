import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./style.css";
import "./landing.css"; // Shared page layouts, including authentication and the learning workspace.
import "./workspace-refinements.css";
import "./lerny-theme.css"; // Lerny 디자인 테마
import "./lerny-design.css"; // 전체 디자인
import "./lerny-dark.css"; // 다크 모드 (자동 생성) — 밝은 모드에는 영향 없어요
import "./lerny-dark-tweaks.css"; // 다크 모드 손질
import "./user-menu.css"; // 헤더의 내 정보 메뉴 — 다른 헤더 버튼 스타일보다 우선해요
import "./student-fit.css"; // 학생 화면 비율 맞춤 — 실습 퀴즈 한 화면 배치, 이론 퀴즈 북마크 탭
import "./vanish-input.css";
import "./confirm-dialog.css";
import "./chat-inputs.css";
import "./student-buttons.css"; // 학생 화면 버튼 색 — 모브와 이어지는 한 톤 진한 보라
import { applyTheme, getTheme } from "./theme";
applyTheme(getTheme(), location.pathname); // 첫 그림부터 고른 모드로 — 깜빡임 방지
createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
