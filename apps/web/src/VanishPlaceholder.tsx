import { useEffect, useLayoutEffect, useRef, useState, type RefObject } from "react";

/* 질문 칸 예시 문구 — 'placeholders and vanish input' 느낌 (11-16)
   · 칸이 비어 있으면 예시 질문이 몇 초마다 아래에서 올라오며 바뀌어요.
   · 글자를 적기 시작하면 예시 문구가 바로 꺼지지 않고 위로 살짝 떠오르며 흐려져 사라져요.
   · 질문을 보내면 보낸 글이 한 글자씩 흩어지며 사라져요.
   진짜 placeholder 대신 질문 칸 위에 겹쳐 보이는 글이라서, 글꼴·여백은 질문 칸에서 그대로 읽어 와 맞추고, 색은 다른 칸의 예시 글자색과 같아요.
   '동작 줄이기' 설정에서는 움직임 없이 바로 바뀌어요. */

const ROTATE_MS = 3200;

type Props = {
  textarea: RefObject<HTMLTextAreaElement | null>;
  examples: string[];
  /* 칸에 글이 있으면 true — 예시 문구가 흐려지며 사라져요 */
  hidden: boolean;
  /* 방금 보낸 질문 — 바뀔 때마다 흩어지며 사라지는 효과를 한 번 보여 줘요 */
  sent?: { text: string; key: number } | null;
};

export function VanishPlaceholder({ textarea, examples, hidden, sent }: Props) {
  const box = useRef<HTMLSpanElement>(null);
  const [index, setIndex] = useState(0);
  const [burst, setBurst] = useState<{ text: string; key: number } | null>(null);
  const list = examples.length ? examples : [""];
  const key = list.join("\u0000");

  // 예시 목록이 바뀌면 (예: 음성 듣는 중) 첫 문구부터 다시 보여 줘요
  useEffect(() => setIndex(0), [key]);

  // 칸이 비어 있을 때만 예시가 돌아가요
  useEffect(() => {
    if (hidden || list.length < 2) return;
    const t = setInterval(() => setIndex(i => (i + 1) % list.length), ROTATE_MS);
    return () => clearInterval(t);
  }, [hidden, key]);

  // 보낸 글이 흩어지는 효과는 잠깐만 그려요
  useEffect(() => {
    if (!sent?.text.trim()) return;
    setBurst(sent);
    const t = setTimeout(() => setBurst(b => (b?.key === sent.key ? null : b)), 1100);
    return () => clearTimeout(t);
  }, [sent?.key]);

  // 질문 칸의 글꼴·여백·색을 그대로 가져와요 (크기가 바뀌면 다시 맞춰요)
  useLayoutEffect(() => {
    const ta = textarea.current, el = box.current;
    if (!ta || !el) return;
    const sync = () => {
      const s = getComputedStyle(ta);
      el.style.setProperty("--vp-pt", `${parseFloat(s.paddingTop) + parseFloat(s.borderTopWidth)}px`);
      el.style.setProperty("--vp-pl", `${parseFloat(s.paddingLeft) + parseFloat(s.borderLeftWidth)}px`);
      el.style.setProperty("--vp-pr", `${parseFloat(s.paddingRight) + parseFloat(s.borderRightWidth)}px`);
      el.style.setProperty("--vp-font", s.font);
      el.style.setProperty("--vp-lh", s.lineHeight);
      el.style.setProperty("--vp-text", s.color);
      el.style.top = `${ta.offsetTop}px`;
      el.style.left = `${ta.offsetLeft}px`;
      el.style.width = `${ta.offsetWidth}px`;
      el.style.height = `${ta.offsetHeight}px`;
    };
    sync();
    const ro = new ResizeObserver(sync);
    ro.observe(ta);
    return () => ro.disconnect();
  }, [textarea]);

  const text = list[index % list.length];
  return (
    <span ref={box} className={`vanish-ph ${hidden || burst ? "is-typing" : ""}`} aria-hidden="true">
      <span key={`${key}-${index}`} className="vanish-ph__line">{text}</span>
      {burst && <span key={`burst-${burst.key}`} className="vanish-ph__burst">
        {Array.from(burst.text.slice(0, 160)).map((ch, i, arr) => (
          <span key={i} style={{
            animationDelay: `${Math.round((i / Math.max(arr.length, 1)) * 260)}ms`,
            ["--vp-dx" as string]: `${((i * 37) % 13) - 6}px`,
            ["--vp-dy" as string]: `${-10 - ((i * 53) % 11)}px`,
          }}>{ch}</span>
        ))}
      </span>}
    </span>
  );
}
