// 실습 페이지의 "코드 실행" 요청 — 실행 결과 탭과 시각화 탭이 같은 기록 하나를 나눠 쓴다.
import { useCallback, useState } from "react";
import { runPractice, type PracticeLanguage, type PracticeRun } from "./visualizer/practiceRun";
import type { StopLines, TraceStage } from "./visualizer/trace/tracerClient";

export function useCodeTrace(language: PracticeLanguage, sectionId: string) {
  const [run, setRun] = useState<PracticeRun | null>(null);
  const [stage, setStage] = useState<TraceStage | null>(null);
  // stopLines: 빈칸 채우기 — 안 채운 빈칸 줄 직전에서 실행을 멈춘다
  const execute = useCallback(async (code: string, stopLines: StopLines = {}, displayCode = code) => {
    setStage("executing");
    try {
      const result = await runPractice(language, code, sectionId, setStage, stopLines);
      setRun({ ...result, code: displayCode });
    } finally {
      setStage(null);
    }
  }, [language, sectionId]);
  const reset = useCallback(() => setRun(null), []);
  return { run, stage, execute, reset };
}
