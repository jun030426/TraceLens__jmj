> **2026-10-12 정책 갱신:** [확정 기획 v0.4](11_확정_기획_2026-10-12.md)를 최신 기준으로 적용한다. 이 문서의 충돌하는 이전 정책·설계는 [변경 대조표](12_기획_변경_대조표.md)를 따르며, 세부 계약 갱신과 미완료 구현은 [남은 개발 작업](13_남은_개발_작업.md)에 정리했다. 이 안내는 구현 완료를 의미하지 않는다.

# Lerny API 계약

버전 0.1 · 2026-10-09 · base path `/api/v1`

API가 인증, 과목 격리, 최초 제출, 공개 해설, 서버 채점의 최종 판정 지점이다. 브라우저의 정답 여부·진도·역할·점수·분반 귀속 값은 신뢰하지 않는다. 이 명세의 경로와 입력·응답 필드는 구현 시 OpenAPI 생성과 계약 테스트의 기준이다.

## 공통 규약

JSON은 snake_case, ID는 UUID, 시간은 UTC RFC3339, 날짜는 YYYY-MM-DD다. 목록은 `{items, next_cursor}`이며 limit 기본 20·최대100, 안정적인 `(created_at,id)` 커서를 사용한다. 변경 요청에는 `Idempotency-Key`를 받는다. 제출·세션 생성·실행·AI 작업·CSV 생성은 필수이며 같은 키/같은 본문은 같은 자원을 반환하고 다른 본문이면409다. 편집은 `If-Match` revision으로 낙관적 잠금을 적용한다.

성공은 200/201/204, 비동기 접수는202 `{job_id, status:"queued", resource_id, poll_url}`다. 오류는 `{error:{code,message,retryable,request_id,details?}}`로 반환한다. 내부 경로·스택·원문 프롬프트·비공개 출처를 오류에 넣지 않는다. 400 잘못된 요청,401 미인증,403 알려진 기능 권한 부족,404 접근 불가 또는 없는 타 과목 자원,409 상태/버전 충돌,413 크기 초과,422 유효성,429 과부하,503 서비스 장애로 구분한다.

로그인 쿠키와 CSRF 토큰으로 인증한다. 학생 API는 요청한 section이 현재 수강 범위인지 검사하고 서버에서 course를 도출한다. 과거 본인 기록은 별도 기록 조회 권한으로 반환한다. 운영 API는 운영 역할만으로 모든 수업 원문을 풀지 않고 배정된 검토 건과 접근 사유를 요구한다.

## 계정과 강의실

| 메서드와 경로 | 입력 | 응답과 제약 |
| --- | --- | --- |
| POST `/auth/signup` | login_id, password, display_name, privacy_notice_version | 201 user_id. student로만 생성 |
| POST `/auth/login` | login_id, password | 200 user, csrf_token + 세션 쿠키. 실패 횟수 제한 |
| POST `/auth/logout` | CSRF | 204 세션 폐기 |
| GET `/me` | 없음 | 본인 기본정보·자격·권한·고지 버전 |
| POST `/auth/reset-password` | one_time_token, new_password | 204, 운영자 발급 토큰 1회 사용·기존 세션 폐기 |
| GET `/classrooms` | 본인 수강 중·승인 대기 | 분반·강의·학기, 담당 교수 표시 이름(`teacher_name`), 실제 진도 주차(`current_week`: 자동 일정 또는 수동 지정, 개념만 지정하면 null) |
| POST `/enrollments` | join_code | 수강 등록 또는 승인 대기. 같은 과목 중복이면409 |
| DELETE `/enrollments/{id}` | 확인용 수강 id | 수강 취소, 즉시 접근 닫기, 보존 정책 안내 |
| POST `/me/deletion-requests` | confirmation | 202 deletion_request_id, deadline; 상태 조회는 GET `/me/deletion-requests` |

## 교수 운영

| 메서드와 경로 | 입력 | 응답과 제약 |
| --- | --- | --- |
| POST `/courses` | term_id, title, teaching_language | 201 course. 발급된 교수만 |
| GET/PATCH `/courses/{id}` | PATCH title, teaching_language, If-Match | course와 revision. 대표/편집 권한 |
| POST/GET `/courses/{id}/sections` | POST title | 생성/목록 |
| PUT `/sections/{id}/progress` | concept_ids, If-Match | progress_revision. 분반별 범위 |
| POST `/sections/{id}/join-code` | expires_at, approval_required | 원문 코드 1회 반환, 해시 저장 |
| GET `/sections/{id}/enrollments` | 상태 필터 | 교수용 명단 |
| POST `/enrollments/{id}/approve` | 없음 | 승인 후 활성 수강 |
| POST `/enrollments/{id}/transfer` | target_section_id | 같은 과목만. 시험 진행 중409 |
| POST/PATCH `/courses/{id}/staff` | teacher_id, can_analyze, can_edit, active | 대표 교수만, 기존 교수 계정만 |
| POST `/ops/teachers` | login_id, display_name | 운영자 발급, 일회용 초기 비밀번호 변경 필요 |
| POST `/ops/users/{id}/reset-token` | reason | 일회용 토큰, 짧은 만료, 감사 기록 |

## 자료와 개념

업로드는 임시 파일 접수 → 메타데이터 확인 → 안전 검사·저장 확정 순서다. 파일은 HTTP multipart로 API를 통과하며 공개 object URL을 직접 발급하지 않는다.

| 메서드와 경로 | 입력 | 응답과 제약 |
| --- | --- | --- |
| POST `/courses/{id}/materials` | multipart file, kind, week, visibility, internal_use, replaces_id? | 201 material_id, version_id, file_status, processing_job_id. 미분류 공개 금지 |
| GET `/courses/{id}/materials` | week, kind | 역할별 원본 열람·AI 상태 분리 목록 |
| GET `/materials/{id}/file` | version_id? | 파일 스트림, 매번 ACL 검사; 위험 MIME은 attachment |
| PATCH `/materials/{id}/access` | visibility, internal_use, If-Match | 최신 revision, access_epoch. 즉시 종속 접근 차단 |
| POST `/materials/{id}/versions` | 새 file, If-Match | 새 버전 접수; 기존 물리 파일 덮어쓰기 금지 |
| GET/PUT `/materials/{id}/transcript` | PUT text, If-Match | OCR/전사 revision, 재처리 job |
| POST `/materials/{id}/reprocess` | text_revision_id | 202, 편집 권한 |
| DELETE `/materials/{id}` | If-Match | 202, 즉시 접근 차단·비동기 삭제 |
| GET `/courses/{id}/concepts` | status | 개념·근거·매핑 상태 |
| PATCH `/concepts/{id}` | name, description, If-Match | 교수 편집을 보존한 revision |
| POST `/concepts/{id}/merge` | target_id, reason | 같은 과목, 순환 금지, 재집계 job |

## 챗봇과 작업 조회

POST `/sections/{id}/chat/messages` 입력은 `{thread_id?, message}`다. 최대 4,000자, 공개 근거 컨텍스트만 사용하며202를 반환한다. GET `/chat/threads/{id}`는 본인 대화와 검증된 출처만 반환한다. 완료 결과는 `{answer, answer_kind, citations:[{material_id,version_id,locator,excerpt}], supplements, limitations}`이고 answer_kind는 grounded/insufficient/conflict다. 실패를 insufficient로 바꾸지 않는다.

현재 화면의 GET `/sections/{id}/chat/history`는 본인 수강 분반의 질문 기록을 조회한다. `q`(질문 본문 검색, 최대 200자), `offset`(기본 0), `limit`(기본 50, 1~50)을 받으며 `{items,total,offset,limit,has_more,thread_id,job_id}`를 반환한다. 최신 생성 시각·ID 순서로 페이지를 고른 뒤 해당 페이지의 항목은 대화 순서대로 반환한다. 각 항목에 `id,created_at,question,answer,error`가 있다. 공개 범위가 바뀐 답변은 검색 결과에서도 가린다. 최근 대화는 3건, 기록 검색은 8건씩 조회하며 50건 이후도 페이지로 접근할 수 있다.

GET `/jobs/{id}`는 `{id,kind,status,attempt,queue_position?,progress?,result_ref?,error?}`를 반환한다. queue_position은 추정치 표시이며 비공개 다른 작업 정보를 포함하지 않는다. POST `/jobs/{id}/cancel`은 queued 또는 취소 가능한 running만 취소하고 이미 확정된 채점을 지우지 않는다. POST `/jobs/{id}/retry`는 소유자/관리자 권한과 retryable 검사 후 새 attempt를 만든다.

## 학습과 제출

| 메서드와 경로 | 입력 | 응답과 제약 |
| --- | --- | --- |
| POST `/sections/{id}/daily-sessions` | mode:theory/practice | 200 기존/201 새 세션. 서버 날짜 기준 원자적 생성 |
| GET `/learning-sessions/{id}` | 없음 | items, assigned_reason, answered_count, available_count, status. 정답·private rubric 제외 |
| POST `/sections/{id}/more-sessions` | mode, concept_id? | 자유/추가 학습 세션, 추천 순서 기록 |
| POST `/session-items/{id}/episodes` | purpose:first/retry | episode_id. independent 여부는 서버 판정 |
| POST `/episodes/{id}/hints` | level:1..3 | 공개 근거 힌트, 힌트 사용 서버 기록. 시험 중403 |
| PUT `/episodes/{id}/drafts/{language}` | source, revision | 언어별 초안 revision. 최대32KiB |
| POST `/episodes/{id}/runs` | language, source, sample_input? | 202 공개 테스트 실행. 공식 제출 아님 |
| POST `/episodes/{id}/attempts` | answer_type, answer 또는 language+source | 201 저장 또는202 저장+채점 job. 서버에서 유형·문항·권한 검사 |
| GET `/attempts/{id}` | 없음 | submission_status, grade_status, outcome?, public_feedback?, execution_summary?, eligible_for_mastery |
| GET `/attempts/{id}/trace` | cursor? | 본인 허용 trace. 비공개 테스트 trace 제외 |
| GET `/session-items/{id}/explanation` | attempt_id | 제출 여부·과제 공개·시험 상태 검사 후 공개 해설 |
| POST `/attempts/{id}/appeals` | reason | 열린 이의 1개, 자동 재판정1회 후 검토 |
| POST `/attempts/{id}/self-checks` | public_criterion_checks | 자기 점검 기록, 서버 점수·mastery 변경 없음 |
| GET `/sections/{id}/my-progress` | domain, concept_id?, language? | 이해 상태, 적격 근거 수, review_due, 이론/실습 구분 |

현재 학생 학습 기록 화면에 연결된 호환 API는 다음과 같다. 위의 최종 학습 엔진 계약과 구분한다.

- GET `/my/learning-sessions`: 선택 필터 `section_id`, `date_from`, `date_to`(양 끝 포함), `offset`(기본 0), `limit`(기본 100, 1~100). 본인의 현재 수강 분반만 조회하며 지정 분반 권한을 검사한다. `{items,total,offset,limit,has_more}`를 반환하고 날짜 내림차순·ID 내림차순으로 페이지를 나눈다. 잘못된 기간이나 범위는 422다.
- GET `/sections/{id}/my-learning`: `{items,current_week,today}`를 반환한다. 항목은 `id,concept,weeks,in_scope,valid_recent,correct_recent,mastered,review_due,review_session_id,review_question_id`다. 주차는 공개된 활성 자료와 유효한 문항 출처로 연결하며, 현재 진도와 전체 개념을 구분한다. 기존 이해도 산정(최근 독립 채점 답안 최대 5건, 정답 4건 이상·성공 일자 2일 이상)을 유지한다. 기록이 없는 개념은 이해 부족으로 판정하지 않는다.

객관식 answer는 choice_id, 서술형은 text(최대4,000자), 실습 예측은 predicted_output, 빈칸·구현은 source다. 실습 예측도 해당 언어 모범 프로그램의 서버 실행 결과로 검증한다. 클라이언트의 passed, score, is_first 등은 입력 스키마에서 금지한다. 모의고사 제출도 같은 저장·검증 엔진을 쓰고 응답에서 해설을 숨긴다.

서술형 응답 예시는 `{grade_status:"held", outcome:null, participation_counted:true, reason_code:"RUBRIC_EVIDENCE_UNSTABLE"}`다. 학생에게 내부 채점 요소 원문을 반환하지 않는다. 코드는 `{verdict:"time_limit", counted_as_attempt:true, trace_status:"unavailable"}`처럼 학습 실패와 인프라 실패를 구분한다.

## 문제 은행과 품질

| 메서드와 경로 | 입력 | 응답과 제약 |
| --- | --- | --- |
| GET `/courses/{id}/questions` | concept_id, type, status, language | 교수용 목록·검증 상태 |
| POST `/courses/{id}/question-jobs` | concept_ids, kinds, count, languages | 202 생성 job. 공개 생성/내부 검증 단계 분리 |
| POST `/courses/{id}/questions` | prompt, kind, concept_id, assessment, sources | 수동 문항도 검증 후 활성화 |
| POST `/questions/{id}/revisions` | 수정 필드, reason, If-Match | 새 revision, 이전 풀이 보존 |
| POST `/questions/{id}/suspend` | reason | 신규 배정 중지, 오류 확정과는 구분 |
| POST `/reports` | target_type, target_id, category, reason | 신고 접수, 중복 제한; 점수 자동 변경 없음 |
| GET/PATCH `/ops/reviews/{id}` | PATCH resolution, reason, expected_revision | 배정 건만, 감사·재채점·재집계 연결 |

## 시험과 대시보드

POST/GET `/courses/{id}/exams`는 title, concept_ids, starts_at, ends_at, duration_minutes, composition을 생성/조회한다. PATCH `/exams/{id}`는 revision을 요구하고 시작된 시험의 문항·시간을 소급 변경하지 않는다. PUT `/exams/{id}/section-overrides/{sectionId}`는 분반 범위·일시를 재정의한다. POST `/exams/{id}/sessions`는 서버 시각으로 시작을 판정하며 POST `/exam-sessions/{id}/finish`는 중복 종료에 안전하다. 시간 만료는 서버가 종료한다.

GET `/courses/{id}/analytics`와 GET `/sections/{id}/analytics`는 기간·concept_id·domain·language 필터를 받는다. 응답은 `{numerator,denominator,held_count,student_count,as_of,metrics_version,breakdowns}`다. GET `/courses/{id}/students/{studentId}/analytics`는 분석 권한과 소속 관계를 검사하고 답안·코드·질문 개념/횟수를 반환하되 개인 대화 전체는 제외한다.

POST `/courses/{id}/exports`는 동일 필터와 CSV 종류로202를 반환한다. 완료 파일 다운로드도 교수의 현재 분석 권한을 재검사하고 수식 시작 문자로 인한 CSV 실행을 방지한다. GET `/notifications`, PATCH `/notifications/{id}`는 본인 사이트 알림 조회·읽음 처리다.

## 계약 검증

### 현재 로컬 구현: 교수 학생 답안 탐색 (2026-10-12)

GET `/sections/{section_id}/students/{student_id}/learning`은 교수의 현재 분석 권한과 해당 학생의 분반 수강 관계를 확인한다. 선택 필터는 `date_from`, `date_to`(제출 시각의 한국 시간 날짜, 양 끝 포함), `concept_id`, `offset`(기본 0), `limit`(기본 200, 1~200)다. 날짜 역전·잘못된 페이지 범위는 422다. `{items,total,offset,limit,has_more}`를 반환하고 제출 시각 내림차순·ID 내림차순으로 페이지를 나눈다. 기존 답안 전문·문항·개념명·피드백·독립 풀이 여부·제출 시각을 유지한다. 프런트는 10건씩 조회하며 200건 이후 기록도 접근할 수 있다. 이 엔드포인트는 위의 목표 통합 분석 API와 구분한다.

경로별 인증 없는 요청, 타 과목 ID 교체, 같은 Idempotency-Key 재전송, 다른 본문으로 키 재사용, 오래된 If-Match, 삭제·비공개 직후 재조회, 보류 점수 누락을 테스트한다. API 구현 시 라우터에서 OpenAPI를 생성하고 프론트 타입을 생성한다. 이 문서는 동작 기준이며 아직 실행 중인 API나 완성된 OpenAPI 파일을 의미하지 않는다.
