# 실습 제출 시점 정보 마이그레이션

| 항목 | 값 |
|---|---|
| 운영 적용 상태 | 승인 대기 |
| Alembic | `b60d9c84f210` → `4ebad9697835` |
| 전환 API | #42 머지 `53775563bd23d614e92a42a3e913315df2656e39`, 운영 배포 `dpl_9G2WyAzucddWvF9QkmUtrEFGMWx6` |
| 파일 | `migrations/versions/4ebad9697835_practice_submission_snapshot.py` |
| Git 원본 파일 SHA-256 | `625c1df8ba75bd4d43af6adb0bbd6486b78ba18b168cb6d3a7f86f947f1b094e` |

`upgrade`는 `practice_attempts.submission_snapshot`을 기본값 없는 nullable JSON 컬럼으로 추가한다. 기존 제출은 SQL NULL로 남는다. 이전 워커는 매핑된 컬럼만 읽고 쓰며 채점 작업의 입력은 기존 `attempt_id`다.

격리 PostgreSQL에서 빈 DB부터 부모 리비전까지 올린 뒤 upgrade·downgrade·재적용을 검증했다. 빈칸 제출을 만들어 둔 상태에서 컬럼을 추가한 뒤 기존 채점 코드로 처리하고, 같은 문제의 전체 구현도 새로 제출해 채점했다. 두 제출은 모두 채점 완료였고 스냅샷은 SQL NULL이었다. downgrade 뒤에도 두 제출의 채점 결과가 남았다.

## 적용 순서

1. #42 이후의 전환 API에서 운영 도메인과 배포 커밋, `/api/v1/health/ready`와 `/api/v1/health/learning` 200을 확인한다. 이 API는 두 리비전 중 정확히 한 행을 허용한다.
2. 대상은 `ap-southeast-2`의 `i-0c64182a7dada987a`에서 실행 중인 워커가 사용하는 DB다. 워커 프로세스의 DB 설정과 `/etc/lerny/worker.json`의 일치를 값 노출 없이 확인한다. DB에서 부모 리비전 한 행, 기존 제5장 작업, 대상 테이블, 새 컬럼 부재를 조회한다. 다른 배포와 PPT 재시도 여부를 확인하고 운영 승인을 받는다.
3. 승인 후 머지된 커밋의 Alembic 트리를 서버의 임시 디렉터리에 준비한다. 새 리비전 파일의 SHA-256을 위 값과 대조한다. `lerny-worker` 사용자, 워커 설정, `/opt/lerny/venv/bin/python` 환경에서 임시 디렉터리의 Alembic 설정으로 `python -m alembic upgrade 4ebad9697835`를 실행한다. PostgreSQL 연결에 짧은 `lock_timeout`을 적용한다. 잠금 획득에 실패하면 결과를 보고한다.
4. 적용 직후 두 헬스 엔드포인트의 200, Alembic 새 리비전 한 행, 컬럼의 JSON 타입·nullable·기본값 부재를 확인한다. 실행 시각·커밋·임시 경로·실행 파일 해시·결과를 이 문서에 기록하고 임시 파일을 정리한다. 적용한 마이그레이션 파일은 그 바이트로 보존한다.
5. 제출 시점 정보를 읽고 쓰는 API를 배포한다. 그 뒤 별도 배포로 헬스와 공유 데이터 도구가 새 리비전만 요구하도록 맞춘다.

## 복원 순서

- 운영 DB 적용 전에는 직전 정상 Vercel 배포를 복원할 수 있다. 먼저 대상 배포와 이유를 보고한다.
- 운영 DB 적용 후에는 **코드를 먼저** 복원한다. 위 #42 배포는 새 DB에서 동작하며 새 컬럼을 읽거나 쓰지 않는다. 새 컬럼을 사용하는 워커가 이미 배포된 경우 그 워커도 호환 버전으로 복원한 뒤 헬스와 생존 신호를 확인한다.
- DB까지 복원해야 하면 저장된 제출 스냅샷이 제거된다는 점과 백업 대상을 먼저 보고하고 승인을 받는다. 같은 파일 해시와 워커 DB를 대조한 뒤 `python -m alembic downgrade b60d9c84f210`을 실행한다. 부모 리비전과 두 헬스 응답을 확인한다.
