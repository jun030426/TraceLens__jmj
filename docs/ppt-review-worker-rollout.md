# PPT 검증 복구와 전용 워커 적용안

## 승인할 값

| 항목 | 현재 워커 | 제안 |
|---|---|---|
| 일반 콘텐츠 RPM | 12 | 12 유지 |
| 유료 검증 RPM | 콘텐츠 값 사용 | 60 |
| 임베딩 RPM | 12 | 120 |
| 유료 검증 프로젝트 라벨 | lerny-paid-embedding | 동일 |
| 임베딩 쿼터 행 라벨 | lerny | 동일. 모델 gemini-embedding-2로 행을 구분 |

RPM은 앱의 허용량이다. 쿼터 조정기는 같은 프로젝트·모델에서 진행 중인 호출 하나에만 임대를 내준다. 모델 응답 시간, TPM 및 Google의 할당량에 따라 실측 처리량은 더 낮을 수 있다. 일반 콘텐츠와 유료 초안은 계속 콘텐츠 RPM을 사용한다. 유료 질문 검증도 기존 review 경로를 사용한다. 프로젝트 라벨은 앱 내부 집계에만 쓰인다.

## SSM 변경 초안

로컬에 `worker-policy.json`을 만들고 `<course-id>`에는 승인받은 강의 ID를 넣는다. 시각은 UTC로 보존한다. 키·DB URL·토큰을 이 파일에 넣을 필요가 없다.

```json
{
  "LERNY_GEMINI_REVIEW_COURSE_ID": "<course-id>",
  "LERNY_GEMINI_REVIEW_QUOTA_PROJECT": "lerny-paid-embedding",
  "LERNY_GEMINI_REVIEW_WEEK": "4",
  "LERNY_INSTRUCTOR_REVIEW_FROM_WEEK": "5",
  "LERNY_GEMINI_PAID_FROM_WEEK": "5",
  "LERNY_GEMINI_PAID_UPLOADS_SINCE": "2026-11-22T03:07:10.277879+00:00",
  "LERNY_GEMINI_REVIEW_REQUESTS_PER_MINUTE": "60",
  "LERNY_GEMINI_EMBEDDING_REQUESTS_PER_MINUTE": "120"
}
```

실행 위치는 저장소 루트다. 아래 첫 명령은 복호화 값 없이 현재 버전을 읽는다. 아래 예시의 11을 조회한 버전으로 대체한다. 두 번째 명령은 변경될 변수 이름만 출력한다. 세 번째 명령은 별도 승인 후 적용할 명령이다.

```sh
aws ssm get-parameter --profile lerny-deploy --region ap-southeast-2 --name /lerny/production/worker-env --query Parameter.Version --output text
python deploy/aws/manage.py worker-policy --file worker-policy.json --expected-version 11
python deploy/aws/manage.py worker-policy --file worker-policy.json --expected-version 11 --apply
```

`worker-policy`는 기존 SecureString을 메모리에서 병합하고 같은 KMS 키와 파라미터 등급을 사용한다. SSM PutParameter에는 비교 후 쓰기를 원자적으로 하는 옵션이 없으므로 적용 중에는 다른 배포자와 같은 파라미터를 동시에 쓰지 않는다. 상위 단계에서 `install`은 다른 설정과 릴리스도 갱신하므로 정책만 적용할 때는 `worker-policy`를 쓴다. 복구 시에는 변경 전 버전을 기록하고, 다른 변경이 없는지 확인한 뒤 복구할 필드만 검토한다.

## 빈 서버에서 SSM 복구 확인

1. 승인받은 별도 검증 인스턴스에 같은 릴리스와 런타임을 준비한다. 운영 작업 선점을 방지하려면 서비스 자동 시작을 끈 상태로 검증한다. `remote_install.py`는 파라미터에서 읽은 JSON을 `/etc/lerny/worker.json`에 0600으로 설치하고 서비스 파일을 설치한다.
2. `systemctl show lerny-material lerny-embedding -p DropInPaths`로 두 유닛에 추가 설정이 없는지 확인한다. root 전용 프로세스에서 SSM을 복호화해 읽은 JSON과 설치 파일을 객체 단위로 비교한다. 로그에는 일치 여부와 파라미터 버전만 남긴다.
3. `apps/api/tests/test_aws_worker_policy.py`의 깨끗한 환경 복원 테스트는 실제 `start_worker.py`가 JSON을 로딩하고 권한을 낮춘 뒤 어떤 명령과 설정을 넘기는지 가짜 계정과 exec로 확인한다. `test_gemini_quota.py`는 테스트 프로젝트에서 RPM과 프로젝트·모델 해시를 검증한다. 운영 큐, 키, 모델 요청은 복구 검증에 필요하지 않다.
4. 같은 강의와 등록 5주차, 기준 시각 직전·정각의 PPT에 대해 각각 무료/교수 검토 경로와 유료 검토 경로를 대조한다. 다른 강의·4주차·PDF·일반 생성도 각각 대조한다. 유료 검토 경로가 유료 검증 키를 선택하는지 확인한다.
5. 데이터 복구는 설정 복구와 별개다. 재시도 전에 `/var/lib/lerny-worker/document-materials`와 `gemini-calls`를 기존 절대 경로에 보존한다. 패키징 도구는 엔진의 소스·JSON을 Linux 릴리스와 같은 LF로 담는다. 배포 전에 `PYTHONPATH=apps/api python -m pytest apps/api/tests/test_ppt_page_recovery.py`를 실행한다. `ppt_checkpoint_versions.json`은 검토한 운영 엔진과 이번 릴리스의 전체 코드 해시 쌍만 허용한다. 다른 코드·원본·영수증이 섞이면 중지한다.
6. 위 검증과 승인이 끝나면 각 서비스의 메모리 한도와 호스트의 여유 메모리를 확인한다. embedding 서비스는 `embed`와 `rag_reindex`를, interactive 서비스는 학생의 채팅과 채점을 맡는다. material 서비스는 나머지 허용 유형과 주기적 정리를 담당한다. 기존 PPT를 중단한 서버는 아래의 학생 전용 워커 전환 순서를 따른다.

검증 인스턴스에서 두 환경을 읽기 전용으로 대조하는 예시다. 실행할 셸에서 AI Studio로 확인한 유료 검증 키의 마지막 네 글자를 환경변수 `EXPECTED_PAID_REVIEW_KEY_SUFFIX`로 내보낸다. 인스턴스 역할의 SSM 읽기 권한으로 실행하며 키 비교 결과에는 값이 표시되지 않는다.

```sh
release=$(readlink -f /opt/lerny/current)
sudo --preserve-env=EXPECTED_PAID_REVIEW_KEY_SUFFIX "/opt/lerny/runtimes/$(basename "$release")/bin/python" - <<'PY'
import json
import os
from pathlib import Path
import boto3

expected_suffix = os.environ.get("EXPECTED_PAID_REVIEW_KEY_SUFFIX", "")
if len(expected_suffix) != 4:
    raise SystemExit("Set EXPECTED_PAID_REVIEW_KEY_SUFFIX to the last four characters of the paid review key")
param = boto3.client("ssm", region_name="ap-southeast-2").get_parameter(
    Name="/lerny/production/worker-env", WithDecryption=True)["Parameter"]
ssm = json.loads(param["Value"])
disk = json.loads(Path("/etc/lerny/worker.json").read_text())
assert ssm == disk, "SSM and worker.json differ"
required = {
    "LERNY_GEMINI_REVIEW_COURSE_ID", "LERNY_GEMINI_REVIEW_WEEK",
    "LERNY_GEMINI_REVIEW_QUOTA_PROJECT", "LERNY_INSTRUCTOR_REVIEW_FROM_WEEK",
    "LERNY_GEMINI_PAID_FROM_WEEK", "LERNY_GEMINI_PAID_UPLOADS_SINCE",
    "LERNY_GEMINI_REVIEW_REQUESTS_PER_MINUTE", "LERNY_GEMINI_EMBEDDING_REQUESTS_PER_MINUTE",
}
assert required <= disk.keys(), "worker policy incomplete"
if not disk["GEMINI_EMBEDDING_API_KEY"].endswith(expected_suffix):
    raise SystemExit("Paid review key mismatch")
print("worker policy matches SSM version", param["Version"])
PY
```

```sh
systemctl daemon-reload
systemctl enable lerny-material.service lerny-embedding.service lerny-interactive.service
systemctl restart lerny-material.service
systemctl start lerny-embedding.service lerny-interactive.service
systemctl is-active lerny-material.service lerny-embedding.service lerny-interactive.service
```

이 명령들은 승인 이후 사용할 운영안이다. 분리한 material 서비스만 시작하면 임베딩 작업은 전용 워커가 시작될 때까지 대기한다. 되돌릴 때는 먼저 현재 작업이 끝날 때까지 기다리고, 역할 분리 전의 material 릴리스와 서비스 구성을 함께 복원한다.

### AWS 설치기의 Python 기동 검사

1. 릴리스 아카이브를 Git 원본과 바이트 단위로 대조한다. 첫 전환에서는 **새 릴리스의** `deploy/aws/remote_install.py`를 사용한다. 이전 설치기를 호출하거나 의존성 파일이 같다는 이유로 새 런타임 준비를 생략하면 새 시작 스크립트가 실행할 Python이 없다.
2. 설치기는 시스템 `/usr/bin/python3.12`로 릴리스별 `/opt/lerny/runtimes/<digest>`를 준비한다. uv의 관리형 Python 탐색과 다운로드를 끄고 잠금 파일로 동기화한다. 수동 복구했던 공유 `/opt/lerny/venv`는 이전 릴리스의 복원을 위해 보존한다. 새 릴리스 관련 운영 명령에서는 새 런타임의 `bin/python`을 쓴다.
3. 설치기는 활성 릴리스를 교체하기 전에 `lerny-worker`와 `lerny-code`로 각각 Python을 실행한다. 실제 인터프리터가 시스템 Python과 같고, 워커 진입 모듈을 새 릴리스에서 읽을 수 있어야 한다. 검사 실패 시 설치 명령은 실패하고 `installed=false`, `services_started=false`를 출력한다. 기존 릴리스와 서비스 PID를 확인한 뒤 원인을 해결한다.
4. 다음 배포에서 두 계정의 검사 통과, 설치 성공 및 `services_started=false`, 기존 PID 유지를 확인한다. 큐를 확인하며 interactive → embedding → material → code → video 순서로 재시작하고 매번 새 PID의 실행 파일, 릴리스별 실행 인자와 생존 신호를 확인한다. 복원 시 이전 릴리스로 `current`를 되돌려 해당 릴리스의 런처와 가상환경을 함께 사용한다.

### 학생 채팅·채점 전용 워커로 전환

장시간 PPT 추출을 중단해 둔 서버에서는 위의 일괄 시작 명령을 건너뛴다.

1. 전환을 승인한 뒤 임시 타이머를 `systemctl disable --now lerny-interactive-temp.timer`로 중지하고, `systemctl is-active lerny-interactive-temp.service`가 `inactive`가 될 때까지 실행 중인 학생 작업을 기다린다.
2. 새 유닛을 포함한 릴리스를 설치하고 `systemctl enable --now lerny-interactive.service`를 실행한다. 이 유닛은 기존 material과 같은 시작 스크립트로 worker.json을 읽고 lerny-worker 권한으로 내려간다. 설치와 시작 사이에는 새 학생 작업이 DB 큐에서 기다린다.
3. 운영자 화면에서 ‘학생 채팅·채점’의 최근 응답을 확인한다. 학생 소유의 `chat`, `practice_grade`, `grade`만 해당한다. 선점은 생성 시각과 ID 순서이며, 잠긴 작업은 다른 워커에 맡긴다. 운영 기능 정지와 제공자·lease 조건도 함께 적용된다.
4. 제5장 재개를 별도로 승인한 시점에 material을 활성화한다. 그때까지 새 자료 처리와 주기적 정리는 대기한다. 임베딩은 기존 전용 서비스가 맡는다.
5. 이전 릴리스로 되돌릴 때는 활성 작업을 마친 뒤 상시 interactive 서비스를 중지·비활성화한다. 임시 타이머를 다시 쓸 경우 먼저 타이머가 요구하는 릴리스와 material 중지 상태를 복원하고 타이머를 활성화한다.

## 쪽 보류와 비용

- 125개 블록 응답을 100개로 잘라 버리면 원문이 누락된다. 지정된 수동 재시도 회차에서 해당 검증 단계만 원본을 다시 보고, 그래도 형식이 맞지 않으면 그 쪽과 그 쪽에 의존하는 연결을 보류한다. 같은 회차에서 할당량 때문에 재개해도 보류 쪽에 다시 과금하지 않는다.
- 정수 좌표의 한 변만 경계를 넘고, 차이가 12/1000 이하이면서 원래 폭·높이의 2% 이하일 때만 경계로 자른다. 빈 상자나 뒤집힌 상자는 제외한다. 캐시에 원래 응답 해시, 레이어와 항목 위치, 보정 전후 좌표를 기록한다. 기존 원본 대조와 계산 검증은 계속 수행한다.
- 보정된 ID 집합은 원본에 연결된 전체 기대 ID와 정확히 일치해야 한다. 누락·중복·추가 ID는 통과하지 않는다. 기존 잘못된 보정본은 감사용으로 보존하고 해당 단계만 새 프롬프트로 실행한다.
- 보류 쪽은 `extracted_text`, 학생용 검색 청크, 임베딩 및 원본 도형 보충 추출에서 제외한다. 업로드된 원본의 공개 범위는 기존 자료 정책을 따른다. 교수자는 보류 목록에서 쪽 번호와 이유를 본다. 다른 쪽의 검증된 내용은 배포할 수 있고, 검증된 내용이 하나도 없으면 버전이 `needs_review`가 된다.
- 기존 수동 재시도는 `_ai_generation`을 증가시켜 작업의 게이트웨이 응답 캐시 전체를 새 네임스페이스로 바꾼다. 문서 엔진의 완료 체크포인트는 원본·모델·엔진과 경로가 같으면 별도로 살아 있다. 이번 변경은 PPT 추출의 두 검증 실패 코드에 한해 `_ppt_review_round`만 올린다. 삭제·새 버전 업로드·일괄 캐시 비우기는 세 작업 복구 절차에 포함되지 않는다.
- 완료된 작업에서 일부 쪽이 계속 보류되면 교수자 보류 목록으로 인계된다. 일반 작업 재시도 API는 실패한 작업에만 열려 있다. 기존 성공 작업의 청크와 임베딩을 다시 쓰는 버튼은 이 변경 범위에 포함되지 않는다.
- 우선 대면실습5 한 건으로 확인한 뒤 제5장, 마지막으로 제4장을 고려한다. 캐시를 복원해도 이전에 시작하지 않은 쪽, 연결 검증, 도형 보충은 새 호출 대상이다. 운영 모델 비용은 파일 수나 체크포인트 수와 일대일로 대응하지 않는다.

## 운영 마이그레이션 적용 기록

2026-11-23 01:02:01 KST에 AWS 워커가 사용 중인 운영 DB의 Alembic 리비전을 `af3e227a01db`에서 `b60d9c84f210`으로 올렸다. 당시 Vercel 운영 커밋 `48b566b`는 두 리비전을 모두 지원했다.

#36부터는 `alembic_version`에 `b60d9c84f210` 한 행이 있어야 API가 DB를 준비 상태로 판정한다. 병렬 검증 코드가 새 점유 컬럼과 예산 테이블을 사용하기 때문이다. 공유 데이터 점검 스크립트도 같은 기준을 사용한다. 데이터 이관 시에는 원본과 대상이 각각 이 기준을 통과해야 한다.

- **파일 출처** — #36 커밋 `b6c7c6e92855339b10266eab122c90c235bc6c69`의 `migrations/versions/b60d9c84f210_concurrent_gemini_leases.py`. 원본과 서버 파일의 SHA-256은 모두 `206aea7ec6b45298208472045d561a6b87511bedd65bf206ff95bc7fee63d3f7`였다. 이 파일의 리비전·부모·본문은 이후 rebase에서도 그대로 유지한다. 후속 변경에는 새 리비전을 추가한다.
- **위치와 환경** — 인스턴스 `i-0c64182a7dada987a`의 `/tmp/lerny-quota-migration-zc1ls9sm/migrations`에 위 커밋의 리비전 파일 21개를 준비했다. SSM Run Command에서 `lerny-worker` 권한과 `/opt/lerny/venv/bin/python`으로 실행했다. 실행 중인 embedding 워커, `/etc/lerny/worker.json`, 실제 SQLAlchemy 연결의 DB 호스트 일치를 확인했다.
- **실행 명령** — 같은 연결의 트랜잭션에서 기존 리비전, 제5장 행, 큐 상태를 재확인했다. Alembic의 `script_location`을 위 임시 경로로 설정하고 `cfg.attributes["connection"] = connection`을 지정한 뒤 `alembic.command.upgrade(cfg, "b60d9c84f210")`를 호출했다. CLI의 대응 명령은 `alembic upgrade b60d9c84f210`이다.
- **결과** — 커밋 직후 운영 `/api/v1/health/ready`는 200이었고 DB·스토리지 모두 `ready`였다. 별도 연결에서 `gemini_quotas.active_leases`가 nullable JSON이고 `gemini_paid_call_budgets`의 RLS가 활성화된 것을 확인했다. `anon`·`authenticated`에는 테이블·컬럼 권한이 없고, 테이블 소유자 외 명시적 권한은 `service_role`에만 있었다. 검증 뒤 임시 디렉터리를 삭제했다.
- **복원 순서** — #36 코드가 배포된 뒤에는 먼저 해당 API와 워커를 이전 스키마를 지원하는 릴리스로 복원한다. DB 복원이 필요하면 위 커밋에서 리비전 파일을 다시 준비하고 같은 운영 대상을 확인한 뒤 `alembic downgrade af3e227a01db`를 실행한다. 이 명령은 새 예산 테이블의 데이터와 `active_leases` 컬럼을 제거한다. 복원 후 DB 리비전과 운영 readiness를 확인한다.

## 유료 PPT 검증 병렬 처리

기본 동시 요청 수는 1이다. 병렬 처리를 적용하려면 마이그레이션 `b60d9c84f210`을 먼저 적용하고 material·embedding 양쪽에 같은 게이트웨이 코드를 배포한다. 이전 워커의 기존 점유도 만료될 때까지 한 자리로 센다.

- 첫 운영값으로 `LERNY_GEMINI_REVIEW_CONCURRENCY=4`, `LERNY_GEMINI_REVIEW_REQUESTS_PER_MINUTE=60`을 제안한다. 기존 임베딩 120 RPM과 일반 콘텐츠 12 RPM은 각각 별도 정책이다. 동시 수를 늘려도 모델·프로젝트별 RPM, TPM, RPD와 공급자의 재시도 대기 시간을 따른다.
- 시각 검증은 쪽별로 저장한다. 연결 검사는 양쪽의 완료 체크포인트가 있는 쌍만 실행한다. 같은 요청은 응답 캐시를 공유한다. 진행 중 서버를 정지했다면, 재개 전에 완료된 응답과 제출 상태가 불확실한 요청을 구분한다. 응답을 받기 전에 프로세스가 죽은 요청은 자동 재전송하지 않는다.
- PPT의 실행당 80회 처리는 체크포인트에서 이어진다. 버전 예산은 실행 회차를 넘어 유료 리뷰와 자료 임베딩의 신규 전송 예약을 합산한다. 기본 상한은 자료 버전당 1,500회다. `LERNY_GEMINI_DEFAULT_PAID_CALL_BUDGET`으로 0~10,000 사이의 정수로 변경할 수 있다. 0이면 처음부터 새 유료 전송이 차단된다. 학생 질문·채점처럼 자료 버전이 없는 호출과 일반 콘텐츠 호출은 이 예산을 쓰지 않는다.
- `gemini_paid_call_budgets`의 기존 행은 계속 사용한다. 과거 미집계 기간은 소급 계산하지 않는다. 특정 버전에 `LERNY_GEMINI_PAID_CALL_BUDGET={"version_id":"<material-version-id>","max_new_calls":1800}`을 설정하면 기본보다 높거나 낮은 **누적 상한**이 적용된다. 예를 들어 이미 1,500회를 사용한 자료에 300회를 더 승인할 때 1,800을 지정한다. 다른 버전에는 기본값이 적용된다.
- 전송 직전 예약은 이미 진행 중인 요청과 명시적 공급자 재시도도 포함한다. 완료 캐시 적중과 할당량 대기는 새 예약을 사용하지 않는다. 예약 직후 프로세스가 죽으면 그 자리는 사용한 것으로 남긴다. 상한에 도달하면 다음 유료 요청은 `GEMINI_PAID_CALL_BUDGET_EXCEEDED`로 중단되고 서비스 프로세스는 유지된다.
- 리뷰·임베딩별 허용 건수는 `gemini_paid_call_budgets`의 해당 버전 행에서 확인한다. 각 작업의 `gemini-calls/<작업 해시>/attempts/`에는 신규 제출 시각, 용도와 요청 해시가 남는다. 재시작·배포로 통신 결과가 불확실한 요청의 실제 과금 여부는 공급자 집계로 확인한다.

### 버전 예산에 도달한 자료

1. 교수자 화면에서 처리 작업이 실패하고 운영자의 한도 상향 승인이 필요하다는 메시지가 표시된다. 추출 작업은 버전도 실패로 표시한다. 임베딩만 실패했다면 이미 완료된 원문 분석은 유지된다. 작업은 자동 재시도하지 않는다. 기존 예산으로 수동 재시도해도 신규 유료 전송은 0회다.
2. 운영자가 해당 버전의 리뷰·임베딩 누계와 저장된 진척을 확인하고 추가 비용을 승인한다. 특정 버전의 새 누적 상한을 material과 embedding 양쪽에 동일하게 적용한다. 프로세스가 읽은 값과 활성 작업 유무를 확인하고 교수자 화면에서 재시도한다. 예산 실패 재시도는 기존 호출 영수증과 PPT 체크포인트를 그대로 사용한다.
3. 배포 순서는 오류 문구를 제공하는 Vercel API·웹, AWS 워커 순이다. Vercel의 비전용 런타임은 Gemini 전송 전에 차단된다. 전환 동안에는 구버전 워커가 기본 상한을 적용하지 않으므로 작업이 비었을 때 5종을 순차 전환한다. 롤백 시에는 필요한 자료에 기존 단일 버전 예산을 유지하고 AWS를 먼저 이전 릴리스로 복구한다. Vercel도 복원할 경우 현 DB 리비전을 허용하는 배포를 선택한다. DB 마이그레이션, 예산 행 삭제, 체크포인트 초기화는 필요하지 않다.
