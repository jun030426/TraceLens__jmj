# Vercel·Supabase 이전과 AI 테스트 실행기

2026-10-13. 목표는 **개발 PC를 꺼도 일반 서비스가 동작하고, PC에는 모델 연산 테스트만 남기는 것**이다. 이번 변경은 배포용 코드와 검증을 준비한다. 실제 계정 설정·클라우드 배포·PC 종료 후 외부 기기 검증은 별도로 확인한다.

## 1. 배치 구조

| 역할 | 위치 | PC 종료의 영향 |
| --- | --- | --- |
| React 웹과 FastAPI, 기존 세션 로그인·권한 검사 | 같은 Vercel 프로젝트 | 없음 |
| 계정·강의·수강·학습 기록·작업 상태 | Supabase PostgreSQL | 없음 |
| 강의 자료 원본, 파일 업로드·다운로드 | Supabase 비공개 Storage | 없음 |
| 파일 형식 검사·텍스트 추출·검색·학습 정책·AI 결과 검증 및 저장 | Vercel API | 없음 |
| 클라우드 작업 호출·복구 | Supabase Cron + pg_net | 없음 |
| 임베딩과 모델 추론 | PC의 Ollama + `ai_runner.py` | AI 작업만 대기 |

기존 FastAPI 인증을 유지한다. Supabase Auth 설정이나 프런트용 Supabase 키는 이번 배포에 필요하지 않다. 과거 문서의 “Supabase 인증 사용”은 당시 계획이며, 이번 사용자 요청에 따른 구현은 일반 API와 기존 인증을 Vercel에서 실행한다.

PC 실행기는 DB·Storage 관리자 키를 받지 않는다. HTTPS API에 전용 토큰으로 접속해 `chat`/`embed` 요청만 가져오고 모델 응답만 돌려준다. 문서 추출·학생 코드 실행·채점 확정·DB 기록을 PC에서 수행하지 않는다. 미래 GPU 장치에서도 같은 실행기를 사용할 수 있고, 모델/API 프로토콜을 바꿀 경우 별도 어댑터가 필요하다. 학생 코드 실행은 계속 비활성이다.

## 2. 먼저 Supabase에서 준비할 것

1. 새 프로젝트를 생성한다. 한국 사용자를 기준으로 가까운 리전을 선택하고, 프로젝트 DB 비밀번호를 비공개 위치에 보관한다. 유료 플랜 전환은 별도 결정이다.
2. **Storage → 비공개 버킷 `lerny-materials`**를 생성한다. Public을 켜지 않고, 전체/버킷 파일 크기 한도를 50MB로 맞춘다. 공개 읽기·쓰기 정책은 추가하지 않는다. 파일 접근은 FastAPI 권한 확인과 서명 URL로 처리한다.
3. Connect에서 **Transaction pooler 연결 문자열**과 **Session pooler 연결 문자열**을 각각 확보한다. PC가 IPv6 직접 연결을 지원하면 마이그레이션은 Direct connection도 가능하다.
4. 프로젝트 URL과 **서버용 Secret key** 또는 기존 `service_role` 키를 확보한다. Publishable/anon 키를 서버 관리자 키 대신 넣지 않는다.
5. Integrations/Database Extensions에서 **Cron(pg_cron)**과 **pg_net**을 사용할 준비를 한다. 실제 스케줄은 API 배포 후 등록한다.

DB 연결은 기존 SQLAlchemy를 사용한다. 런타임 URI는 예를 들어 다음 형식이다. 실제 호스트/사용자는 대시보드의 Connect 값을 따른다.

```text
postgresql+psycopg://postgres.PROJECT_REF:URL_ENCODED_PASSWORD@POOLER_HOST:6543/postgres?sslmode=require
```

마이그레이션 URI는 Session pooler의 5432 또는 Direct connection을 사용한다. 비밀번호에 `@`, `#`, `%`, `/` 등이 있으면 URI 인코딩한다. **런타임 Transaction pooler와 마이그레이션 연결을 구분한다.** 런타임은 NullPool과 `prepare_threshold=None`을 사용한다.

참고: [DB 연결](https://supabase.com/docs/guides/database/connecting-to-postgres), [API 키](https://supabase.com/docs/guides/getting-started/api-keys), [파일 크기 제한](https://supabase.com/docs/guides/storage/uploads/file-limits).

## 3. 비공개 설정 파일 준비

현재 장치의 체크아웃은 `C:\Users\USER\dev\Lerny`다. OneDrive의 빈 작업 폴더에서 실행하지 않는다.

```powershell
cd C:\Users\USER\dev\Lerny
. .\scripts\Enter-Dev.ps1
uv run --locked python scripts/init_cloud_config.py
```

이미 파일이 있으면 덮어쓰지 않는다. 아래 파일은 Git 밖에만 보관한다.

- `%USERPROFILE%\LernyData\secrets\cloud-app.json`: 클라우드 설정. `REPLACE` 부분을 실제 값으로 채운다.
- `%USERPROFILE%\LernyData\secrets\ai-runner.json`: PC에는 웹 주소·AI 실행기 토큰·모델 이름만 둔다.

두 토큰은 초기화 도구가 서로 다른 난수로 생성한다. `LERNY_AI_WORKER_TOKEN`은 실행기와 Vercel에, `CRON_SECRET`은 Vercel과 Supabase Vault에 같은 값을 넣는다. 채팅·Git·브라우저 소스·스크린샷에 비밀 값을 붙이지 않는다.

## 4. Vercel 프로젝트 설정

GitHub의 `jun030426/TraceLens__jmj`를 Import하고 다음과 같이 설정한다. 로컬 변경을 GitHub에 반영하는 작업은 사용자의 별도 원격 쓰기 허가 후 수행한다.

| 설정 | 값 |
| --- | --- |
| Root Directory | 저장소 루트. `apps/web`로 지정하지 않음 |
| Framework | FastAPI |
| Build Command | `python scripts/build_vercel.py` (`vercel.json`에 포함) |
| Output Directory | 수동 override를 비워 둠 |
| Production Branch | `master` |
| Python | `pyproject.toml`의 3.12 기준 |

빌드 도구는 Vite를 빌드해 루트 `public/`에 복사한다. API와 웹을 같은 출처로 제공하며, SPA 경로 새로고침은 `index.html`로 연결한다. `/api/`와 정적 자산 경로는 SPA rewrite에서 제외한다. DB 마이그레이션이나 운영자 생성은 빌드 중 실행하지 않는다.

Vercel Environment Variables의 **Production**에 다음을 설정한다. 비밀 값은 Sensitive로 보관한다. Preview에는 운영 DB/관리자 키를 연결하지 않는다. Preview가 필요하면 별도 Supabase 개발 프로젝트와 전용 토큰을 사용한다.

기존 Supabase 프로젝트를 Vercel 통합으로 연결한 경우 `POSTGRES_URL`, `SUPABASE_URL`, `SUPABASE_SECRET_KEY`(또는 `SUPABASE_SERVICE_ROLE_KEY`)를 그대로 읽는다. `POSTGRES_URL`은 SQLAlchemy psycopg URI와 SSL 설정으로 변환한다. 별도의 `LERNY_DATABASE_URL`·`LERNY_SUPABASE_SERVICE_KEY`를 중복 입력하지 않아도 된다. `LERNY_*` 값을 직접 설정하면 통합 값보다 우선한다. 출처 목록을 직접 지정하지 않으면 Vercel의 `VERCEL_PROJECT_PRODUCTION_URL`을 사용한다.

| 이름 | 값 |
| --- | --- |
| `LERNY_DEPLOYMENT` | `cloud` |
| `LERNY_DATABASE_URL` | Transaction pooler SQLAlchemy URI |
| `LERNY_DATABASE_POOL_MODE` | `transaction` |
| `LERNY_ALLOWED_ORIGINS` | `["https://실제프로젝트.vercel.app"]`. 도메인 추가 시 정확한 HTTPS 출처를 배열에 추가, 끝 `/` 없음 |
| `LERNY_COOKIE_SECURE` | `true` |
| `LERNY_SUPABASE_URL` | `https://프로젝트ID.supabase.co` |
| `LERNY_SUPABASE_SERVICE_KEY` | 서버용 Secret key / service_role |
| `LERNY_STORAGE_BUCKET` | `lerny-materials` |
| `LERNY_CLOUD_FILE_LIMIT_MB` | `50` |
| `LERNY_AI_WORKER_TOKEN` | 비공개 파일에 생성된 실행기 토큰 |
| `CRON_SECRET` | 별도로 생성된 스케줄러 토큰 |
| `LERNY_MODEL_NAME` | 현재 기본값 `qwen3:4b-instruct` |

`LERNY_MIGRATION_DATABASE_URL`은 PC의 일회성 설정용이며 Vercel에는 넣을 필요가 없다. `VITE_` 환경변수로 DB 비밀번호나 관리자 키를 만들지 않는다. 환경변수를 변경한 뒤에는 재배포한다.

Vercel Deployment Protection을 사용할 경우 PC와 Supabase 호출에도 인증이 필요하다. 해당 프로젝트의 Automation Bypass 값을 PC 설정의 `vercel_protection_bypass`와 Vault의 `lerny_vercel_bypass`에 각각 보관한다. 웹 사용자에게 공개할 Production 주소의 접근 정책도 확인한다. 우회 키를 URL 쿼리나 Git에 넣지 않는다.

참고: [FastAPI 배포](https://vercel.com/docs/frameworks/backend/fastapi), [함수 제한](https://vercel.com/docs/functions/limitations).

## 5. 테이블과 최초 운영자 생성

`cloud-app.json`의 실제 값과 마이그레이션 URI를 채운 후 현재 체크아웃에서 실행한다.

```powershell
. .\scripts\Enter-Dev.ps1
uv run --locked python scripts/prepare_cloud.py --bootstrap
```

이 작업은 클라우드 DB에 Alembic head까지 적용한다. 기존 데이터는 삭제하지 않는다. 애플리케이션 테이블과 `alembic_version`에는 RLS를 활성화하고 브라우저용 허용 정책을 만들지 않는다. DB 소유자/서버 역할은 SQLAlchemy를 통해 접근하며 사용자 권한은 FastAPI가 검사한다. Supabase 관리 스키마(`auth`, `storage` 등)는 변경하지 않는다.

운영자가 없는 DB에서만 최초 계정을 만든다. 비밀번호는 `%USERPROFILE%\LernyData\secrets\initial-cloud-operator.json`에 저장되며, 처음 로그인할 때 변경해야 한다. 기존 로컬 운영자 파일과 비밀번호는 덮어쓰지 않는다. 교수 계정은 기존 운영자 화면/API로 발급한다.

이 초기화가 끝난 뒤 PC의 PostgreSQL/API를 실행해 둘 필요는 없다. 클라우드 자격 증명 파일은 초기화·관리 시에만 사용하고 AI 실행기는 읽지 않는다.

## 6. Supabase에서 클라우드 작업 스케줄 등록

API가 배포된 후 Supabase Vault에서 다음 Secret을 생성한다.

| Vault 이름 | 값 |
| --- | --- |
| `lerny_tick_url` | `https://실제도메인/api/internal/jobs/tick` |
| `lerny_cron_secret` | Vercel `CRON_SECRET`과 동일 |
| `lerny_vercel_bypass` | Deployment Protection 사용 시에만 Automation Bypass 값 |

그다음 SQL Editor에서 [cloud_scheduler.sql](../scripts/cloud_scheduler.sql)을 실행한다. 이름이 `lerny-cloud-jobs`인 스케줄을 매분 실행하도록 등록하며, 같은 이름으로 다시 실행하면 갱신한다. **매분 호출 주체는 PC가 아닌 Supabase**다. Vercel Hobby의 일일 Cron 제한에 의존하지 않는다.

Cron/pg_net 실행 이력에서 2xx 응답을 확인한다. 401이면 두 곳의 `CRON_SECRET`, Vercel 로그인 페이지/보호 오류이면 Automation Bypass 설정을 확인한다. URL은 `/api/internal/jobs/tick`까지 포함해야 한다. 초기 작업은 다음 스케줄까지 약 1분 대기할 수 있다. 반복 호출 비용·쿼터는 양쪽 대시보드에서 확인하고 필요 시 주기를 조정한다.

파일 추출은 클라우드에서 완료되고 임베딩 작업을 따로 만든다. 각 AI 요청은 `model_calls`에 기록된다. 응답이 없으면 작업은 `waiting_ai`로 남고 함수는 종료된다. 실행기가 결과를 올리면 기존 성공 응답을 재사용하여 처리를 이어가고, 다음 미완료 모델 요청에서 다시 대기한다. 생성 중간의 DB 변경은 롤백되어 문항이 중복 저장되지 않는다. 작업/모델 실행에는 임대 만료와 재요청 처리가 있다.

참고: [Supabase Cron](https://supabase.com/docs/guides/cron/quickstart), [pg_net](https://supabase.com/docs/guides/database/extensions/pg_net).

## 7. AI 테스트할 때만 PC에서 실행

`ai-runner.json`의 `cloud_url`을 배포 주소로 수정한다. 현재 앱 모델은 여전히 `qwen3:4b-instruct`이며 실험용 9B/TTS로 자동 교체하지 않는다. 바꾸려면 Vercel `LERNY_MODEL_NAME`, 실행기 `allowed_models`, 설치 모델을 함께 맞추고 기존 품질 관문을 검증한다.

Ollama가 이미 실행 중이면 재시작하지 않는다. 실행되지 않았을 때만 별도 터미널에서 `Start-Model.ps1`을 실행한다. 로컬 모델은 외부 클라우드 자동 대체 없이 사용한다.

```powershell
.\scripts\Start-AiTest.ps1
```

필요한 프로그램은 Ollama와 AI 실행기뿐이다. `Start-Local.ps1`, `Start-Api.ps1`, `Start-Web.ps1`, 기존 `Start-Worker.ps1`, 로컬 PostgreSQL은 클라우드 서비스 운영에 필요하지 않다. 실행기를 끄면 90초 안에 AI 오프라인으로 표시된다. 처리 중 종료되면 모델 요청의 임대 만료 후 다른 실행기가 다시 가져갈 수 있다.

## 8. 기존 로컬 데이터가 필요할 때

Git 배포는 로컬 계정·강의·파일을 자동 복사하지 않는다. 새 Supabase DB에 새 테스트 계정을 만드는 경우에는 기존 로컬 데이터 이관이 필요 없다. 기존 계정·강의를 유지해야 한다면 먼저 외부 경로에 DB 백업을 만들고, **빈 클라우드 앱 테이블**에 앱 데이터만 복원한다. `auth`/`storage` 관리 스키마, `alembic_version`, 만료될 로그인 세션·토큰은 복원 대상에서 제외한다. 신규 운영자 생성 전에 복원하며, 이미 데이터가 있는 DB에 덮어쓰기나 `--clean` 복원을 하지 않는다.

기존 데이터 복원 여부·대상 확인 후 원본 파일을 다음 도구로 복사할 수 있다.

```powershell
uv run --locked python scripts/migrate_cloud_files.py
```

이 도구는 클라우드 DB의 `MaterialVersion.object_key`에 대응하는 로컬 원본을 SHA-256으로 확인해 비공개 Storage에 복사한다. 로컬 원본은 삭제하지 않으며, 이미 존재하는 클라우드 파일의 내용이 다르면 중단한다. 데이터 복원/원본 복사/검증이 끝나기 전에는 기존 파일 경로를 제거하지 않는다. 이관 대상·실행 기록 없이 기존 데이터가 옮겨졌다고 표시하지 않는다.

## 9. 완료 검증

- `/api/v1/health/live`: API 응답 확인.
- `/api/v1/health/ready`: DB 스키마와 비공개 Storage를 확인하고 준비되면 200. 모델/PC는 확인하지 않는다.
- `/api/v1/health/learning`: 전체 학습 품질·격리 관문은 여전히 미완료이므로 503. 일반 배포의 상태 확인 URL로 쓰지 않는다.
- 다른 기기에서 **PC 웹/API/DB/워커/모델 모두 종료한 상태**로 로그인, 교수·학생 권한, 강의·분반·수강 정보 저장과 조회, 파일 업로드/다운로드, 기존 문항·학습 기록·통계 조회를 확인한다.
- 같은 상태에서 업로드 원본 저장과 클라우드 텍스트 추출이 끝나고 AI 임베딩만 대기하는지 확인한다.
- AI 실행기를 켜면 임베딩·개념·문항 생성이 이어지는지, 서술형 제출 후 채점 확정이 클라우드에서 이루어지는지 확인한다.
- 비수강생/다른 교수의 파일 접근, 취소된 AI 결과, 만료된 임대, 중복 업로드 완료 요청을 확인한다.
- `/login`, `/classrooms/...`, `/quiz/results/...` 주소의 직접 진입과 새로고침, `/api/없는경로`의 JSON 404를 확인한다.

로컬 PostgreSQL 기반 테스트에서 Storage와 모델 응답은 합성 대체로 검증한다. 이는 실제 Supabase 서명 업로드·Vercel 빌드/배포·Cron 실행의 성공을 대신하지 않는다. 50MB 문서와 최악의 PDF 파싱 시간, 실제 수업 자료 품질·다수 사용자 부하는 별도 실측한다. 현재 업로드는 서명 PUT이며 중간 끊김 시 재업로드한다. 대용량 재개 업로드(TUS)는 후속 개선이다.

## 10. 변경 상태

배포용 엔트리포인트·빌드/라우팅·클라우드 환경 설정·DB 풀·RLS 마이그레이션·비공개 파일 업로드·다운로드·클라우드 CPU 처리·모델 요청 큐·전용 실행기·상태 표시·초기화/이관 도구를 추가했다. 계정 설정 전에는 실제 클라우드 연결 완료로 보지 않는다. 실제 배포 URL, 적용 마이그레이션, Cron 이력, PC 종료 검증 결과를 확인한 뒤 여기에 추가한다.

2026-10-13 적용 기록:

- 기존 Supabase `Lerny` (`gwuzahbpnnedzqopxkiv`, 서울 리전)에서 빈 앱 스키마를 확인한 후 Alembic 초기→`a7b18d65ec90` SQL을 MCP로 적용했다. 앱/버전 테이블 27개에 RLS 활성화를 확인했다. DB 비밀번호를 PC에 복사하지 않았다.
- 비공개 `lerny-materials` 버킷(50MB)과 `pg_cron`·`pg_net` 확장을 준비했다. 실제 주기 작업은 배포 URL 확인 후 등록한다.
- Vercel `kigkig495-2084s-projects/lerny` (`prj_l1hy0WZuGPfyl2NNiTGz7HL1hyYv`)를 만들었다. 사용자가 기존 Supabase 계정 통합을 완료했고 Production DB/서버 키의 변수 이름과 대상 환경을 확인했다. 비밀 값은 출력하지 않았다.
- API 회귀 43개, 프런트 회귀 9개, TypeScript/Vite 빌드가 통과했다. 실제 Alembic 적용·되돌리기도 로컬 전용 테스트 DB의 격리 스키마에서 검증했다.
- 모델 요청의 임시 입력/응답은 종료된 작업에 한해 1일 후 정리한다. 만료된 업로드의 staging 원본도 스케줄에서 정리하며, 게시된 자료 원본과 학습 기록은 이 정리에서 삭제하지 않는다.
