# 실행 흐름(시각화) 격리 환경

실습 화면의 "실행 흐름 보기"가 Java·C 코드를 기록할 때 쓰는 격리 컨테이너예요.
API 서버는 학생 코드를 직접 실행하지 않고, 아래 명령으로 이 컨테이너를 매번 새로 띄워
`python -m lerny.tracing.runner`에 코드를 넘겨요. (Python은 학생 브라우저에서 기록해요.)

## 켜는 방법

1. 이미지 빌드 (저장소 루트에서)

   ```bash
   docker build -f deploy/trace-sandbox/Dockerfile -t lerny-trace:0.1 .
   ```

2. `%USERPROFILE%\LernyData\secrets\app.json`(또는 `$LERNY_RUNTIME_ROOT/secrets/app.json`)에
   실행 명령을 넣어요. 비어 있으면 시각화 실행은 꺼진 상태(503)로 남아요.

   ```json
   {
     "trace_sandbox_command": [
       "docker", "run", "--rm", "-i",
       "--network", "none", "--read-only",
       "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
       "--pids-limit", "128", "--memory", "768m", "--cpus", "1",
       "--tmpfs", "/tmp:rw,exec,size=64m",
       "lerny-trace:0.1"
     ]
   }
   ```

3. API를 다시 시작하면 `/api/v1/capabilities`의 `code_visualization`이 `true`가 돼요.

## 확인할 것 (공개 전 필수)

- docs/06의 격리 조건(네트워크 없음, 비루트, read-only, cap-drop ALL, 자원 제한)을 실제 Linux
  실행 호스트에서 시험한 뒤에만 학생에게 공개해요. 컨테이너는 같은 커널을 쓰므로 완전한 방어가 아니에요.
- gdb는 자기 자식 프로세스만 ptrace해요. Docker 기본 seccomp에서 동작하는지 실행 호스트에서 확인해요.
- 컨테이너 안에서 기록기 테스트: `LERNY_TRACE_SANDBOX_TESTS=1 python -m pytest apps/api/tests/test_tracing.py`
- Dockerfile의 OpenJDK 17은 Debian bookworm 패키지 기준이에요. docs/06의 OpenJDK 21로 맞추려면
  JDK 21이 들어 있는 베이스 이미지로 바꾸고 digest를 고정해요.

## 지원 범위와 한계

| 언어 | 기록 방법 | 보이는 것 | 아직 안 되는 것 |
| --- | --- | --- | --- |
| Java | JDI (디버거) | 기본형·문자열·배열·ArrayList·사용자 객체 필드·별칭·호출/반환값·예외 | HashMap 등 내부 구조, 다중 스레드 |
| C | gdb | 기본형·배열·문자열·구조체·구조체 포인터(연결 리스트)·호출·NULL·신호(Segfault 등) | 반환값, malloc/free 사건, 해제 후 참조 진단, 한 줄짜리 반복문의 회차별 기록 |
| Python | 브라우저 Pyodide (서버 runner도 지원) | TraceLens와 같음 | input(), 외부 패키지 |
