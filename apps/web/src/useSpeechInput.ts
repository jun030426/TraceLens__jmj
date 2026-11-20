import { useEffect, useRef, useState } from "react";

/* 브라우저 음성 인식(Web Speech API)으로 말한 내용을 글자로 받아요.
   지원하지 않는 브라우저에서는 supported=false 로 알려줘요. */
type Recognition = {
  lang: string;
  interimResults: boolean;
  continuous: boolean;
  onresult: ((e: { resultIndex: number; results: ArrayLike<{ isFinal: boolean; 0: { transcript: string } }> }) => void) | null;
  onerror: ((e: { error: string }) => void) | null;
  onend: (() => void) | null;
  start: () => void;
  stop: () => void;
};
type RecognitionCtor = new () => Recognition;

function recognitionCtor(): RecognitionCtor | undefined {
  const w = window as unknown as { SpeechRecognition?: RecognitionCtor; webkitSpeechRecognition?: RecognitionCtor };
  return w.SpeechRecognition || w.webkitSpeechRecognition;
}

export function useSpeechInput(onText: (text: string) => void) {
  const [listening, setListening] = useState(false);
  const [error, setError] = useState("");
  const ref = useRef<Recognition | null>(null);
  const textRef = useRef(onText);
  textRef.current = onText;
  const supported = typeof window !== "undefined" && !!recognitionCtor();
  useEffect(() => () => ref.current?.stop(), []);
  const start = (base: string) => {
    const Ctor = recognitionCtor();
    if (!Ctor) { setError("이 브라우저는 음성 입력을 지원하지 않아요. Chrome·Edge·Safari에서 사용해 주세요."); return; }
    setError("");
    const r = new Ctor();
    r.lang = "ko-KR";
    r.interimResults = true;
    r.continuous = true;
    const prefix = base.trim() ? base.trimEnd() + " " : "";
    let finalText = "";
    r.onresult = e => {
      let interim = "";
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const piece = e.results[i][0].transcript;
        if (e.results[i].isFinal) finalText += piece; else interim += piece;
      }
      textRef.current(prefix + finalText + interim);
    };
    r.onerror = e => setError(e.error === "not-allowed" || e.error === "service-not-allowed"
      ? "마이크 사용이 허용되지 않았어요. 브라우저 주소창의 권한 설정에서 마이크를 허용해 주세요."
      : e.error === "no-speech" ? "목소리가 들리지 않았어요. 다시 눌러 말해 주세요." : "음성 인식이 중단됐어요. 다시 시도해 주세요.");
    r.onend = () => { setListening(false); ref.current = null; };
    ref.current = r;
    try { r.start(); setListening(true); } catch { setError("음성 인식을 시작하지 못했어요."); }
  };
  const stop = () => ref.current?.stop();
  return { supported, listening, error, start, stop };
}
