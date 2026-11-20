# Lerny

교수자의 강의 자료를 바탕으로 질문, 퀴즈, AI 강의와 코드 실습을 연결하는 학습 서비스입니다.

2026-11-10 통합본은 **팀원의 최신 프론트와 최신 RAG 엔진**을 기준으로 합니다. 기존 작업에서는 로그인·권한·DB·작업 큐·파일 저장·영상 연결에 필요한 부분을 가져왔습니다. 통합 범위, 실행 방법, 검증 결과와 남은 연결은 [통합 기록](docs/20_팀원_최신본_통합.md)을 확인하세요. 이전 날짜의 문서는 당시 상태를 기록한 이력입니다.

## 구성

- `apps/web`: 최신 React/TypeScript 화면, 브라우저 Python 실행, Java/C 트레이스 UI
- `apps/api/lerny`: FastAPI 서비스, 팀 엔진 어댑터, 인증·권한·자료 버전·작업 큐
- `apps/api/rag_mvp`, `quiz_mvp`, `video_extraction`: 최신 팀원 엔진과 원본 회귀 검사
- `migrations`: 기존 DB 스키마 이력
- `scripts/Start-Team.ps1`: 통합본 점검 및 개별 서비스 실행
- `scripts/Run-TeamEngine.ps1`: 팀 엔진 CLI의 Windows 진입점

## 현재 PC에서 실행

Gemini·HeyGen·Supabase·Vercel 설정은 서버용 파일 하나로 관리합니다. [통합 환경 설정](docs/21_통합_환경설정.md)과 `scripts/team.env.example`을 기준으로 입력하세요.

저장소: `C:\Users\USER\dev\Lerny` / 별도 런타임: `C:\Users\USER\LernyData`

```powershell
cd C:\Users\USER\dev\Lerny
.\scripts\Start-Team.ps1 -Component check
# 서로 다른 터미널에서 실행. 기존 포트를 쓰는 프로세스는 먼저 확인합니다.
.\scripts\Start-Team.ps1 -Component api
.\scripts\Start-Team.ps1 -Component worker
.\scripts\Start-Team.ps1 -Component web
```

웹은 `http://127.0.0.1:5173`, API는 `http://127.0.0.1:8000`입니다. DB 연결과 마이그레이션은 별도 선행 조건이며 실행 스크립트가 기존 DB를 변경하지 않습니다. 전달된 ZIP에는 `.env`와 임베딩 데이터가 없었습니다. 키·모델 설정 및 실제 호출을 켜는 방법은 [통합 기록](docs/20_팀원_최신본_통합.md#환경-설정과-실행)에 있습니다. 기본 실행에서는 API 호출이 꺼져 있습니다.

## 확인한 범위

- API 320개 통과, 실행 환경이 필요한 트레이스 3개 건너뜀
- 프론트 회귀 42개 통과, TypeScript/Vite 빌드 통과
- 엔진 핵심·공통 검사 44개 및 하위 사례 30개 통과
- 합성 계정으로 교수자/학생 로그인, 강의 자료, RAG 설정 대기, 질문 등록·대기·취소를 브라우저에서 확인

원본 검증 데이터가 필요한 PDF 회귀 1개는 자료 미제공으로 미검증입니다. 실제 Gemini 응답 품질, 대용량 미디어 처리, Java/C 격리 실행, 실제 영상 제작 및 운영 배포를 완료했다는 의미는 아닙니다.

기획은 [확정 기획](docs/11_확정_기획_2026-10-12.md), 기존 인수인계는 [저장소 이전 기록](docs/15_저장소_이전과_개발_인수인계.md)을 참고합니다.
