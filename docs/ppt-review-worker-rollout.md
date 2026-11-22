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
6. 위 검증과 승인이 끝나면 유휴 상태에서 변경된 material 서비스와 embedding 서비스를 함께 활성화한다. `lerny-embedding.service`는 `embed`와 `rag_reindex`만 선점한다. material 서비스는 그 외 기존 허용 유형을 선점하고 정리를 담당한다. Gemini 클라우드의 Vercel tick은 CPU 작업을 계속 처리한다. systemd 안은 두 프로세스를 같은 사용자로 격리하고 별도의 메모리 한도를 둔다. 호스트 여유 메모리를 확인한 뒤 동시에 시작한다.

검증 인스턴스에서 두 환경을 읽기 전용으로 대조하는 예시다. 실행할 셸에서 AI Studio로 확인한 유료 검증 키의 마지막 네 글자를 환경변수 `EXPECTED_PAID_REVIEW_KEY_SUFFIX`로 내보낸다. 인스턴스 역할의 SSM 읽기 권한으로 실행하며 키 비교 결과에는 값이 표시되지 않는다.

```sh
sudo --preserve-env=EXPECTED_PAID_REVIEW_KEY_SUFFIX /opt/lerny/venv/bin/python - <<'PY'
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
systemctl enable lerny-material.service lerny-embedding.service
systemctl restart lerny-material.service
systemctl start lerny-embedding.service
systemctl is-active lerny-material.service lerny-embedding.service
```

이 명령들은 승인 이후 사용할 운영안이다. 분리한 material 서비스만 시작하면 임베딩 작업은 전용 워커가 시작될 때까지 대기한다. 되돌릴 때는 먼저 현재 작업이 끝날 때까지 기다리고, 역할 분리 전의 material 릴리스와 서비스 구성을 함께 복원한다.

## 쪽 보류와 비용

- 125개 블록 응답을 100개로 잘라 버리면 원문이 누락된다. 지정된 수동 재시도 회차에서 해당 검증 단계만 원본을 다시 보고, 그래도 형식이 맞지 않으면 그 쪽과 그 쪽에 의존하는 연결을 보류한다. 같은 회차에서 할당량 때문에 재개해도 보류 쪽에 다시 과금하지 않는다.
- 정수 좌표의 한 변만 경계를 넘고, 차이가 12/1000 이하이면서 원래 폭·높이의 2% 이하일 때만 경계로 자른다. 빈 상자나 뒤집힌 상자는 제외한다. 캐시에 원래 응답 해시, 레이어와 항목 위치, 보정 전후 좌표를 기록한다. 기존 원본 대조와 계산 검증은 계속 수행한다.
- 보정된 ID 집합은 원본에 연결된 전체 기대 ID와 정확히 일치해야 한다. 누락·중복·추가 ID는 통과하지 않는다. 기존 잘못된 보정본은 감사용으로 보존하고 해당 단계만 새 프롬프트로 실행한다.
- 보류 쪽은 `extracted_text`, 학생용 검색 청크, 임베딩 및 원본 도형 보충 추출에서 제외한다. 업로드된 원본의 공개 범위는 기존 자료 정책을 따른다. 교수자는 보류 목록에서 쪽 번호와 이유를 본다. 다른 쪽의 검증된 내용은 배포할 수 있고, 검증된 내용이 하나도 없으면 버전이 `needs_review`가 된다.
- 기존 수동 재시도는 `_ai_generation`을 증가시켜 작업의 게이트웨이 응답 캐시 전체를 새 네임스페이스로 바꾼다. 문서 엔진의 완료 체크포인트는 원본·모델·엔진과 경로가 같으면 별도로 살아 있다. 이번 변경은 PPT 추출의 두 검증 실패 코드에 한해 `_ppt_review_round`만 올린다. 삭제·새 버전 업로드·일괄 캐시 비우기는 세 작업 복구 절차에 포함되지 않는다.
- 완료된 작업에서 일부 쪽이 계속 보류되면 교수자 보류 목록으로 인계된다. 일반 작업 재시도 API는 실패한 작업에만 열려 있다. 기존 성공 작업의 청크와 임베딩을 다시 쓰는 버튼은 이 변경 범위에 포함되지 않는다.
- 우선 대면실습5 한 건으로 확인한 뒤 제5장, 마지막으로 제4장을 고려한다. 캐시를 복원해도 이전에 시작하지 않은 쪽, 연결 검증, 도형 보충은 새 호출 대상이다. 운영 모델 비용은 파일 수나 체크포인트 수와 일대일로 대응하지 않는다.
