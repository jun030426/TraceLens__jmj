# 필기 처리 역할별 위치

| 폴더 | 역할 | 실제 파일 |
|---|---|---|
| `recognition/` | 원본 근거 준비·필기/기호 판독·OCR | `ink_evidence.py`, `ink_marks.py`, `ink_ocr.py` |
| `context/` | 음성 설명과 필기 연결 | `ink_context.py` |
| `correction/` | 차이 검사·오류 복구·원본 재검사 | `ink_discrepancy.py`, `ink_recovery.py`, `ink_recheck.py` |
| `policy/` | 경고·보류·관리자 검토 판정 | `ink_policy.py`, `ink_conservative_review.py` |
| `runner/` | 전체 처리·묶음·중단 후 이어 실행 | `ink_pipeline.py`, `ink_continue.py`, `ink_continue_v2.py`, `ink_auto_continue.py` |
| `selection/` | 사용할 데이터 선별 | `usable_selection.py` |

현재 이어 실행 시작점은 `runner/ink_auto_continue.py`입니다. 각 파일을 개별 실행할 필요 없이 프로젝트 최상위의 `미처리필기_개선이어검증.command`를 사용합니다. 그 실행 파일의 모듈 경로도 새 위치로 수정했습니다.

실제 파일은 한 곳에만 있으며, 이전 버전의 함수도 현재 버전에서 재사용합니다. 폴더 이동은 추출·판정 기준을 바꾸지 않습니다. 기존 결과와 검사 근거는 원래 위치에 보존합니다.
