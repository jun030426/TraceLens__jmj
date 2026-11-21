import { useState } from "react";
import { StepHints } from "./StepHints";

export function TheoryHints({ storageKey, loadQuote }: { storageKey: string; loadQuote: () => Promise<string> }) {
  const [quote, setQuote] = useState("");
  async function openHint() {
    const text = await loadQuote();
    if (!text?.trim()) throw new Error("이 문항의 힌트를 불러올 수 없어요.");
    setQuote(text);
  }
  return <StepHints storageKey={storageKey} onUsed={openHint} hints={[
    <blockquote style={{ margin: 0, whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{quote}</blockquote>,
  ]} />;
}
