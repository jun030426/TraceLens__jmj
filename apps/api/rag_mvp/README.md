# 강의자료 최소 RAG

기존에 추출한 스택 강의 PPT 중 텍스트 중심 12개 슬라이드로 로컬 흐름을 연결한다.

`원본 XML 대조 → 슬라이드별 청크 → Gemini 임베딩 → LlamaIndex 로컬 저장 → 질문 임베딩 → 벡터·키워드 검색 → Gemini 답변 → 출처·인용 확인`

## 실행

프로젝트 루트에서 `zsh ./RAG_최소흐름_실행.command`를 **일반 Mac Terminal**에서 실행한다. 영상 벤치마크가 실행 중이면 종료 후 실행하도록 안내한다. 키는 기존 루트 `.env`의 `GEMINI_API_KEY`를 사용하며 키를 로그에 남기지 않는다.

런처는 `.venv-rag`에 별도로 LlamaIndex를 설치한다. 기존 영상/음성 가상환경을 변경하지 않는다. 설치 후 네트워크 없는 테스트(실제 LlamaIndex 저장·로드 테스트 포함)가 통과해야 API 호출을 시작한다. 최초 자료 임베딩 12회, 평가 질문 3개의 질문 임베딩/답변 6회로 정상 경로는 총 18회다. 오류 재시도가 있으면 증가한다. 무료 이용 가능 여부와 한도는 계정/모델에 따르며 유료로 자동 전환하거나 다른 모델로 대체하지 않는다.

완료 문구: **전체 완료: 실제 임베딩 → 검색 → Gemini 답변 최소 점검 통과**

설치 후 개별 명령:

```sh
.venv-rag/bin/python -m rag_mvp prepare
.venv-rag/bin/python -m rag_mvp index
.venv-rag/bin/python -m rag_mvp ask '스택의 Pop과 Peek는 어떻게 달라?'
.venv-rag/bin/python -m rag_mvp chat
.venv-rag/bin/python -m rag_mvp evaluate
```

`chat`은 단일 질문을 반복하는 터미널 UI이며 이전 질문/답변을 기억하지 않는다. `/exit`로 종료한다. `search '질문'`은 API 없는 키워드 검색 진단용이며 벡터 검색이나 AI 답변이 아니다.

## 데이터와 모델

- 입력: `outputs/extraction-compare/native/slides.jsonl` 및 원본 PPT. 원본 SHA256과 각 슬라이드 XML 텍스트 포함 여부를 대조한다. 원본 내용의 사실성·레이아웃까지 검증한 의미는 아니다.
- 범위: chapter6 슬라이드 4, 8, 12, 18, 20, 22, 23, 24, 25, 26, 28, 29. 이미지·검토 표시·정답지·영상 데이터 제외. 짧은 슬라이드 전체를 1개 검색 단위로 유지한다.
- 임베딩: `gemini-embedding-2`, 768차원. 문서와 질문의 입력 형식을 구분하고 자동 잘림을 끈다. 모델/차원/자료가 달라지면 다른 인덱스를 사용한다.
- 검색: LlamaIndex `0.14.25` 로컬 벡터 인덱스 + 간단한 한국어 2글자 토큰/영문 BM25 방식 키워드 검색. 각각 상위 8개를 순위 결합하여 상위 4개를 전달한다. 수치가 정답 확률을 의미하지 않는다.
- 답변: 기존 영상 실험에서 사용한 `gemini-3.8-flash`를 별도 답변 프롬프트로 호출한다. API가 모델/키/한도를 거부하면 중지한다.
- 프레임워크의 기본 OpenAI 모델이나 가짜 임베딩으로 대체하는 경로는 없다. 합성 벡터는 테스트에만 사용한다.

## 근거 확인 및 한계

답변은 문장·출처 ID·원문 인용을 포함하는 JSON으로 받는다. 모든 문장의 출처가 검색 결과에 포함되어 있고 인용문이 해당 원문에 실제 존재해야 표시한다. `+`와 `*` 같은 기호는 같은 것으로 정규화하지 않는다. 하나라도 실패하면 답변 전체를 보류한다. 모델이 근거 부족을 판단하면 답변을 생성하지 않은 상태로 표시한다.

**인용문 존재 검사는 그 인용이 답변을 의미적으로 충분히 뒷받침하는지까지 보장하지 않는다.** 평가 3문항도 검색 대상 포함, 인용 검증, 범위 밖 질문 보류에 대한 최소 점검이며 전체 정확도 측정이 아니다. 실제 답변 내용은 결과 JSON에서 별도 평가해야 한다.

질문 및 API 응답은 로컬 `outputs/rag-mvp/`에 저장된다. 요청/자료/모델이 동일하면 API 캐시를 재사용한다. 저장된 자료 임베딩은 질문마다 다시 만들지 않는다. CLI별 호출 상한 80회, 요청 간 최소 2초는 이 실험의 설정이며 제공자 한도를 보장하지 않는다. 일시적 오류는 최대 3회 시도, DNS 오류/일일 한도 등은 중지한다.

## 결과

- `corpus.json`: 출처와 XML 대조 결과가 포함된 12개 청크
- `indexes/`: 실제 임베딩을 저장한 LlamaIndex 인덱스 (실제 실행 후 생성)
- `answers/`: 각 질문의 검색 자료, 생성 후보, 인용 판정, 시간 및 API 호출 수
- `최소RAG_답변.html`: 가장 최근 답변
- `evaluation.json`: 실제 API 최소 점검 결과 (실제 실행 후 생성)
- `logs/`: 사용자 터미널 실행 로그

아직 서비스 업로드 UI, 상시 워커/큐, Supabase, Vercel 배포, 사용자 인증/분반 권한, 대화 기억, 개인화, 퀴즈·숏츠 연결은 포함하지 않는다. 현재 코드는 로컬 자료 12개로 연결을 검증하기 위한 MVP다.

## 확인한 공식 문서

- [Gemini 임베딩 입력 형식](https://ai.google.dev/gemini-api/docs/embeddings)
- [Gemini 임베딩 REST API](https://ai.google.dev/api/embeddings)
- [LlamaIndex 벡터 인덱스](https://developers.llamaindex.ai/python/framework/module_guides/indexing/vector_store_index/)
- [LlamaIndex 저장·불러오기](https://developers.llamaindex.ai/python/framework/module_guides/storing/save_load/)

## PPTX·Word 코드 청크 준비 (2026-11-01)

기본 12개 슬라이드 실험에 더해 `prepare --input`으로 새 PPTX/DOCX를 읽을 수 있다.
이 경로는 API를 호출하지 않는다. 원문 OOXML 텍스트/문단/탭/줄바꿈과 코드 스타일,
Python 구문을 이용해 본문과 코드 후보를 분리한다. 코드 상자 또는 연속 코드 문단을
하나의 독립 청크로 유지하며, 긴 코드도 자르지 않는다. 기존 `prepare`도 코드가 있는
슬라이드는 평탄화된 추출문 대신 원본 XML의 코드/본문을 분리한다. 기존 역할·보류 검사는 유지한다.

```sh
.venv-rag/bin/python -m rag_mvp prepare --input '/절대경로/강의.pptx' '/절대경로/설명.docx' --output outputs/my-code-material-v1
```

- `corpus.json`: 사용 후보 본문과 독립 코드 청크. 코드 `text`는 언어를 아는 경우
  `python` 등의 언어 표시가 있는 Markdown fence다. `code_text`와 `source_text`는
  원문 근거를 보존한다. 출처 해시·XML part·슬라이드/문단 위치·문자 범위를 기록한다.
- `native-evidence.json`: 분리 전 원문과 분리 범위. 제외 부분까지 원본 재대조 가능.
- `review-queue.json`: 불완전/불명확 코드, 이미지, 표 구조, 숨김·수정 이력 등.
  이 항목은 임베딩에 포함하지 않는다. API 재검증을 임의로 실행하지 않는다.
- `summary.json`: 처리 범위와 API 0회 기록. 처리 건수는 정확도 점수가 아니다.

자동 언어 추론은 Python 중심이다. 명시된 Markdown fence는 다른 언어도 보존하지만,
언어를 확정할 수 없는 일반 문서 코드와 들여쓰기가 레이아웃에만 있는 코드는 보류한다.
그림으로 붙인 코드에는 기존 시각 추출·검증 경로가 필요하다. Python 구문 통과는
원문의 내용·실행 결과·교수자의 의도가 맞다는 보증이 아니다. 표와 이미지까지 검증한
전체 자료 처리 완료로 간주하지 않는다. 이 native 경로로 기존 공통 파이프라인의
보류를 해제하거나 기존 OCR/시각 검사를 대체하지 않는다.

자료 등록 화면에서 새 `corpus.json`을 등록하면 동일한 코드 청크가 `ScopedRag`를 통해
LlamaIndex 임베딩에 전달된다. 등록 시와 임베딩 직전에 코드 표현과 원문을 다시 검사한다.
기존 인덱스는 덮어쓰지 않는다. 모델 입력이 너무 길면 자동 잘림 대신 제공자 오류로 중단된다.
실제 임베딩은 사용자가 아래 명령을 실행할 때만 API를 호출한다.

```sh
.venv-rag/bin/python -m rag_mvp index --output outputs/my-code-material-v1
```

오프라인 회귀검사: `.venv-rag/bin/python -m unittest rag_mvp.test_document_ingest rag_mvp.test_markdown -v`
실제 LlamaIndex 저장/검색 테스트에는 합성 벡터만 사용한다. 전처리 결과를 정답지로
간주하거나 기존 활성 자료에 자동 등록하지 않는다.
