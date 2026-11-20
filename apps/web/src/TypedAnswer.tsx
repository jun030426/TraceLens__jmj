import { useEffect, useRef, useState, type ReactNode } from "react";

/** 답변이 한 글자씩 적히는 듯 보여 주고, 다 적히면 출처 같은 children을 보여 줘요 (AI 질문 · 실습 질문 공통) */
export function TypedAnswer({ text, animate, children }: { text: string; animate: boolean; children?: ReactNode }) {
  const reduce = typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
  const [shown, setShown] = useState(animate && !reduce ? 0 : text.length);
  useEffect(() => {
    if (shown >= text.length) return;
    const step = Math.max(1, Math.ceil(text.length / 120));
    const t = setTimeout(() => setShown(n => Math.min(text.length, n + step)), 20);
    return () => clearTimeout(t);
  }, [shown, text.length]);
  const done = shown >= text.length;
  // 글이 적히는 동안 대화 창이 아래 끝을 따라가요 (위로 올려 읽고 있으면 건드리지 않아요)
  const ref = useRef<HTMLParagraphElement>(null);
  useEffect(() => {
    const box = ref.current?.closest<HTMLElement>(".chat-messages, .practice-chat__list");
    if (box && box.scrollHeight - box.scrollTop - box.clientHeight < 120) box.scrollTop = box.scrollHeight;
  }, [shown, done]);
  return <>
    <p ref={ref} className={done ? undefined : "chat-typed"} aria-busy={!done}>{text.slice(0, shown)}{!done && <span className="chat-caret" aria-hidden="true" />}</p>
    {done && children}
  </>;
}
