// 세 언어 공통 실행 장면 진입점 (파일 이름은 호환성을 위해 PythonTracePlayer).
// 실행 기록을 화면용 공통 데이터로 바꿔 VisualizationHost에 넘긴다.
import { useMemo } from "react";
import type { ExecutionTrace } from "./pythonTrace";
import { adaptExecutionTrace } from "./visualization/traceAdapter";
import { VisualizationHost } from "./visualization/VisualizationHost";

export function CodeTracePlayer({ trace, source, stale = false }: { trace: ExecutionTrace; source: string; stale?: boolean }) {
  const recording = useMemo(() => adaptExecutionTrace(trace, source), [trace, source]);
  return <VisualizationHost recording={recording} stale={stale} />;
}
