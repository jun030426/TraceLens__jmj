import { useNavigate } from "react-router-dom";
import "./practice-chat.css";

/**
 * [AI 질문 아이콘] 학생이 강의실에 들어간 뒤의 화면 오른쪽 아래에 떠 있는 둥근 챗봇 아이콘이에요.
 * - 실습 퀴즈 화면의 질문 아이콘(.practice-chat-fab, Practice.tsx)과 같은 모양·색을 그대로 써요.
 * - 누르면 지금 강의실의 AI 질문 화면으로 이동하고, 질문 입력창에 커서를 놓아요.
 * - App.tsx 에서 강의실 문맥이 있을 때만 그려요. AI 질문 화면과 실습 화면(자체 아이콘이 있음)에는 나오지 않아요.
 */

const COMPOSER = ".chat-composer textarea, .chat-composer input:not([type=hidden])";

function focusComposer(tries = 40) {
  const field = document.querySelector<HTMLElement>(COMPOSER);
  if (field) {
    field.scrollIntoView({ block: "center", behavior: "smooth" });
    field.focus({ preventScroll: true });
    return;
  }
  if (tries > 0) window.setTimeout(() => focusComposer(tries - 1), 100);
}

/** 보라색 말풍선 챗봇 아이콘 — 오른쪽 아래 아이콘·실습 질문 아이콘·개념 퀴즈 해설 아래 바로가기가 같은 모양을 써요 */
export function ChatBubbleIcon({ size = 26 }: { size?: number }) {
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} aria-hidden="true">
      <path d="M4 5.5A2.5 2.5 0 0 1 6.5 3h11A2.5 2.5 0 0 1 20 5.5v8a2.5 2.5 0 0 1-2.5 2.5H10l-4.2 3.6c-.5.4-1.3.1-1.3-.6V16A2.5 2.5 0 0 1 4 13.5z" fill="currentColor" />
      <circle cx="8.5" cy="9.6" r="1.1" fill="var(--fab-dot, #fff)" />
      <circle cx="12" cy="9.6" r="1.1" fill="var(--fab-dot, #fff)" />
      <circle cx="15.5" cy="9.6" r="1.1" fill="var(--fab-dot, #fff)" />
    </svg>
  );
}

export function ChatFab({ sectionId }: { sectionId: string }) {
  const navigate = useNavigate();
  return (
    <button
      type="button"
      className="practice-chat-fab"
      aria-label="AI에게 질문하기"
      onClick={() => {
        navigate(`/ai?section=${encodeURIComponent(sectionId)}`);
        window.setTimeout(() => focusComposer(), 0);
      }}
    >
      <ChatBubbleIcon />
      <span className="practice-chat-fab__label" aria-hidden="true">AI에게 질문하기</span>
    </button>
  );
}
