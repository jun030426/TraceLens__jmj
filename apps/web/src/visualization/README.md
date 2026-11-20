# 실행 흐름 시각화 (인수인계 문서 18 구조)

```
Practice → useCodeTrace → CodeTracePlayer → adaptExecutionTrace(trace, source)
        → VisualizationHost(재생 엔진·안내) → VisualizationScreen(props)
```

- `../pythonTrace.ts` — 실행기 출력 계약 `ExecutionTrace` (frames, objects, stdout, causedByLine/nextLine)
- `traceAdapter.ts` — `adaptExecutionTrace` : 단계마다 `Observation`(id `step-N`, changes, events)을 만들고 전체를 freeze
- `executionEvents.ts` — 두 관측 사이 확인된 변화만 이벤트로: `array.swap|set|insert|remove|snapshot`, `variable.change` (evidence `snapshot-diff`)
- `playback.ts` — `usePlayback` : transition(kind initial/next/previous/seek/restart/tick + revision), 간격 100~10000ms,
  마지막에서 재생하면 처음부터, seek/next/previous/restart는 자동재생 정지
- `VisualizationHost.tsx` — 오래된 실행(stale)·일부만 기록·오류·빈 기록 안내, 화면 오류 경계
- `VisualizationScreen.tsx` + `screen/` — 펭귄 3D 무대. next·tick일 때만 previous→current 를 current.events로 연출

규칙: 화면 코드에서 소스 문자열을 분석하지 않는다 · AI로 결과를 추측하지 않는다 · 서버 배포/임의 코드 실행 지원을 주장하지 않는다.

팀원 원본 파일이 이 폴더에 없어 필드 이름은 인수인계 문서(18_시각화_화면_개발_인수인계)를 보고 다시 만들었다.
원본과 합칠 때 이름이 조금 다르면 `contracts.ts`·`pythonTrace.ts`만 맞추면 된다.
Java·C 기록은 `../visualizer/toExecutionTrace.ts`로 같은 계약으로 바꾼다.
