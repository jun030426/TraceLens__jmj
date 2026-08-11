# Algo-Scope

**Python 코드 자동 시각화 샌드박스**

Algo-Scope는 사용자가 작성한 Python 알고리즘 코드를 별도 설정 없이 실행하고, 실행 중 발생하는 변수 변화, 리스트 변화, 함수 호출, 반복 흐름, 출력 결과를 자동 추적하여 PixiJS 기반 2D 그래픽으로 재생하는 웹 애플리케이션입니다.

핵심 목표는 사용자가 `visualize()` 같은 보조 함수를 작성하지 않아도 코드의 실행 흐름과 자료구조 변화를 자동으로 읽어내어 알고리즘이 어떻게 움직이는지 직관적으로 보여주는 것입니다.

## 핵심 방향

- 1차 버전은 Python만 지원합니다.
- 중심 기능은 완전 자동 추적입니다.
- 보안 강화는 후순위로 두되, 실행 계층은 추후 Docker sandbox로 교체 가능하게 분리합니다.
- 무한 루프와 대량 반복은 실제로 무한 생성하지 않고 step 제한과 반복 압축으로 처리합니다.
- 화려한 비주얼보다 먼저 코드 상태를 의미 있는 시각 이벤트로 변환하는 규칙을 명확히 정의합니다.

## MVP 지원 범위

- `int`, `float`, `str`, `bool`, `None` 변수 추적
- 1차원 리스트 시각화
- 2차원 리스트 기본 시각화
- `dict`, `set`, 객체는 요약 형태로 표시
- 현재 실행 라인 하이라이트
- 변수 값 변경 감지
- 리스트 원소 변경 감지
- `append`, `pop`, swap 패턴 감지
- 함수 호출/리턴 및 call stack 표시
- `stdout`, `stderr` 출력 표시
- 반복문 진행 상태 표시

초기 제외 대상:

- C, C++, Java 지원
- 임의 클래스 내부 구조의 완전 시각화
- 멀티스레드, 멀티프로세스 코드
- 파일 시스템 접근
- 네트워크 접근
- 매우 큰 자료구조의 전체 정밀 렌더링

## 시스템 아키텍처

```text
Python Code
→ Trace Runner
→ Raw Snapshot Collector
→ Diff Analyzer
→ Algorithm Event Detector
→ Visualization Mapper
→ WebSocket Stream
→ Web Worker Parser
→ PixiJS Renderer
```

### Backend

- Node.js + Express
- Python Runner 실행 관리
- 실행 세션 생성
- trace 수집 및 WebSocket 스트리밍
- 초기 개발 단계에서는 로컬 Python subprocess 사용
- 이후 Docker sandbox로 교체 가능하게 `Runner` 인터페이스 분리

### Frontend

- Monaco Editor
- PixiJS
- GSAP
- Web Worker
- Playback Controller
- Console Output Panel
- Variable / Call Stack Panel

## 자동 추적 전략

Python 실행 추적은 다음 방식을 조합합니다.

- `sys.settrace`로 라인 단위 실행 추적
- frame locals를 읽어 현재 변수 상태 수집
- 이전 snapshot과 비교하여 변경점 계산
- AST 분석으로 비교식, 인덱스 접근, swap 구문 패턴 보조 감지
- 리스트 변경은 값 전체 복사 대신 diff 중심으로 기록
- 너무 큰 값은 preview 형태로 축약

자동 추적의 핵심은 코드를 완벽히 해석하는 것이 아니라, 실제 실행 중 변한 상태를 정확히 잡고 그 변화에서 시각적으로 의미 있는 이벤트를 추론하는 것입니다.

## 반복 및 무한 루프 처리

- 기본 최대 step 수를 둡니다.
- 같은 라인이 과도하게 반복되면 반복 구간으로 압축합니다.
- 무한 루프 의심 시 실행을 중단하고 `step_limit_exceeded` 상태를 표시합니다.
- 프론트엔드는 압축된 반복을 빠른 애니메이션 또는 반복 배지로 표현합니다.
- 사용자는 playback 속도를 조절할 수 있습니다.

## WebSocket Payload

```json
{
  "type": "snapshot",
  "sessionId": "session_abc",
  "seq": 15,
  "currentLine": 12,
  "event": {
    "name": "array_swap",
    "targets": ["arr[1]", "arr[2]"]
  },
  "variables": [
    { "name": "i", "type": "int", "value": 3 },
    { "name": "j", "type": "int", "value": 7 }
  ],
  "structures": [
    {
      "id": "arr",
      "kind": "array",
      "elements": [
        { "index": 0, "value": 5, "state": "default" },
        { "index": 1, "value": 15, "state": "active_neon" },
        { "index": 2, "value": 2, "state": "active_neon" }
      ]
    }
  ],
  "stdout": ""
}
```

추가 메시지 타입:

- `session_started`
- `snapshot`
- `stdout`
- `stderr`
- `runtime_error`
- `step_limit_exceeded`
- `execution_done`
- `execution_cancelled`

## 시각화 기준

- `list[int]` → 막대그래프 또는 셀 배열
- 변수 → 변수 패널
- 현재 라인 → Monaco Editor 라인 하이라이트
- 함수 호출 → call stack 패널
- `append` → 새 노드 생성 애니메이션
- `pop` → 노드 제거 애니메이션
- swap → 두 노드 위치 교환
- 비교 추정 → 두 노드 네온 강조
- 반복 진행 → 인덱스 포인터 이동

비주얼 효과:

- active 값에는 neon glow 적용
- swap에는 GSAP Elastic 또는 Back easing 적용
- 인덱스 포인터 이동에는 trail 효과 적용
- 완료된 요소는 green 계열 highlight
- 비교 중 요소는 pink/cyan 계열 highlight
- 전체 테마는 deep dark IDE 스타일

## 보안 개발 단계

초기 개발에서는 기능 검증을 우선합니다. 단, 구조는 처음부터 sandbox 교체를 고려합니다.

최종 단계에서 적용할 보안:

- Docker container 실행
- memory limit
- CPU limit
- timeout
- network none
- non-root user
- read-only filesystem
- process count 제한
- stdout/stderr 크기 제한
- 파일 접근 제한

## 개발 우선순위

1. Python 코드 실행 및 line trace 수집
2. 변수/list snapshot 생성
3. diff analyzer 구현
4. Monaco 라인 하이라이트
5. PixiJS 배열 시각화
6. swap/update/append/pop 이벤트 감지
7. playback controls
8. 반복 제한 및 압축
9. Web Worker 분리
10. Docker sandbox 및 보안 강화

## 현재 프로토타입

현재 저장소는 프론트엔드 경험 검증용 Vite + React 프로토타입입니다.

- Monaco Editor 기반 Python 입력 화면
- Python 코드에서 숫자 리스트를 감지하는 클라이언트 mock trace
- Bubble Sort, Linear Search, Binary Search 프리셋
- 코드 패턴에 따른 렌더링 모드 자동 선택
- 정렬 알고리즘은 PixiJS 막대 그래프로 시각화
- 선형/이진 탐색 알고리즘은 셀 기반 포인터 뷰로 시각화
- GSAP 기반 swap 애니메이션
- neon glow 및 pointer trail 표현
- playback controls
- 변수, call stack, console 출력 패널

실제 Python 실행, `sys.settrace`, WebSocket, Docker sandbox는 다음 단계에서 백엔드로 추가합니다.

## 실행 방법

```bash
npm install
npm run dev
```

빌드 확인:

```bash
npm run build
```
