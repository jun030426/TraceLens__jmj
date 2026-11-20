import { useCallback, useEffect, useState } from "react";

/* 브라우저 음성 합성(speechSynthesis)으로 AI 강사 답변을 소리 내어 읽어요.
   지원하지 않는 브라우저에서는 supported=false 로 알려줘요. */
function synth(): SpeechSynthesis | undefined {
  return typeof window !== "undefined" && "speechSynthesis" in window ? window.speechSynthesis : undefined;
}

function koreanVoice(s: SpeechSynthesis) {
  return s.getVoices().find(v => v.lang?.toLowerCase().startsWith("ko"));
}

export function useSpeechOutput() {
  const supported = !!synth() && typeof SpeechSynthesisUtterance !== "undefined";
  const [speaking, setSpeaking] = useState(false);
  const stop = useCallback(() => {
    synth()?.cancel();
    setSpeaking(false);
  }, []);
  const speak = useCallback((text: string) => {
    const s = synth();
    if (!s || !supported || !text.trim()) return;
    s.cancel();
    const u = new SpeechSynthesisUtterance(text);
    u.lang = "ko-KR";
    const voice = koreanVoice(s);
    if (voice) u.voice = voice;
    u.onstart = () => setSpeaking(true);
    u.onend = () => setSpeaking(false);
    u.onerror = () => setSpeaking(false);
    s.speak(u);
  }, [supported]);
  useEffect(() => () => { synth()?.cancel(); }, []);
  return { supported, speaking, speak, stop };
}
