import { runUiChecks } from "./ui-checks";
import { useAutosizeTextarea } from "../src/useAutosizeTextarea";
import { isComposingInput } from "../src/inputKeyboard";
import "../src/confirm-dialog.css";
import "../src/chat-inputs.css";
import { StrictMode, useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { MemoryRouter, useLocation } from "react-router-dom";
import { useConfirm } from "../src/ConfirmDialog";
import { UserMenu } from "../src/UserMenu";
import { applyTheme, useTheme } from "../src/theme";
import type { User } from "../src/api";
import "../src/style.css";
import "../src/workspace-refinements.css";
import "../src/lerny-theme.css";
import "../src/lerny-design.css";
import "../src/lerny-dark.css";
import "../src/lerny-dark-tweaks.css";
import "../src/user-menu.css";
import "../src/practice-chat.css";
import "../src/student-fit.css";
import "../src/student-buttons.css";
/* Only synthetic UI controls; no API, authentication, or model requests. */
const user = { id: "ui-fixture", display_name: "테스트 학생", login_id: "ui-fixture", role: "student" } as User;
function Inputs({ practice = false }: { practice?: boolean }) {
  const [draft, setDraft] = useState("");
  const [sent, setSent] = useState(0);
  const input = useRef<HTMLTextAreaElement>(null);
  useAutosizeTextarea(input, draft);
  return <section className={practice ? "practice-chat is-open" : "chat-page"} style={practice ? {position:"static",width:400,maxWidth:"100%",height:"auto",marginTop:24} : undefined}><div className={practice ? "practice-chat__form" : "chat-composer"}><form className="form" onSubmit={e => { e.preventDefault(); setSent(n => n + 1); setDraft(""); }}><label>질문<textarea ref={input} name={practice ? "practice-message" : "message"} value={draft} onChange={e => setDraft(e.target.value)} rows={1} maxLength={4000} required placeholder="궁금한 점을 적거나 마이크를 눌러 말해 보세요." onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey && !isComposingInput(e.nativeEvent)) { e.preventDefault(); e.currentTarget.form?.requestSubmit(); } }} /></label><button type="submit">질문하기</button><output aria-label="전송 횟수">{sent}</output></form></div></section>;
}
function Fixture() {
  const [confirm, dialog] = useConfirm();
  const [checks, setChecks] = useState("");
  const [result, setResult] = useState("대기");
  const [logout, setLogout] = useState(0);
  const [theme] = useTheme();
  const route = useLocation();
  useEffect(() => applyTheme(theme, "/ui-test"), [theme]);
  return <><header className="app-header" data-menu-open="true"><nav id="app-navigation" style={{display:"flex",justifyContent:"flex-end",width:"100%"}}><UserMenu user={user} onLogout={() => setLogout(n => n + 1)} /></nav></header><main className="app student-main" style={{maxWidth:900,margin:"100px auto",padding:24}}><h1>UI 회귀 검증</h1><button type="button" onClick={async () => setResult(String(await confirm({title:"답안을 제출할까요?",message:"지금 작성한 답안을 제출해요."})))}>확인창 열기</button><button type="button" onClick={async () => setResult(String(await confirm({title:"마칠까요?",message:"아직 작성하지 않은 내용이 있어요.",tone:"warn"})))}>주의 확인창 열기</button><button type="button" onClick={async () => setResult(String(await confirm({title:"추가 정보",message:<>설명을 읽고 <a href="#details">자세한 내용</a>을 확인해 주세요.</>})))}>링크 확인창 열기</button><output aria-label="확인 결과">{result}</output><p>이동 경로: {route.pathname} · 로그아웃 요청: {logout}</p><Inputs /><Inputs practice /><button type="button" onClick={async () => setChecks(await runUiChecks())}>동작 자동 검사</button><pre data-testid="ui-results">{checks}</pre>{dialog}<p style={{marginTop:700}} id="details">페이지 아래 검증 영역</p></main></>;
}
createRoot(document.getElementById("root")!).render(<StrictMode><MemoryRouter><Fixture /></MemoryRouter></StrictMode>);
