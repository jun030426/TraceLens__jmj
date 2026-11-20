// 테스트 화면(로그인 화면의 "학생용 화면" 버튼)에서 질문하면 서버 대신 여기서 예시 답변을 만들어요.
// 실제 서버처럼 "질문 접수 → 잠시 뒤 답변 완료" 흐름을 흉내 내서, 질문 창이 어떻게 보이는지 확인할 수 있어요.
// 답변은 미리 써 둔 예시 문장이에요. 실습에서 온 질문이면 함께 보낸 풀이 상황(문제·채점 결과·시각화 줄)을 보고 고르고,
// 정답 코드는 알려 주지 않아요. 실제 서비스에서는 공개 강의 자료의 원문 문장이 답변으로 와요.
import type { Answer } from "./api";

type Ref = { week: number; topic: string; page: number };
const SORT: Ref = { week: 14, topic: "정렬 알고리즘", page: 5 };
const ARRAY: Ref = { week: 2, topic: "배열과 리스트", page: 8 };
const SEARCH: Ref = { week: 15, topic: "탐색 알고리즘", page: 3 };

const cite = (r: Ref) => ({ material_id: `m${r.week}`, version_id: `v${r.week}`, title: `${r.week}주차 · ${r.topic}`, locator: { page: r.page }, excerpt: "" });
const grounded = (answer: string, ...refs: Ref[]): Answer => ({ answer_kind: "grounded", answer, citations: refs.map(cite) });

/** 함께 보낸 풀이 상황에서 "항목: 값" 한 줄 꺼내기 */
const field = (ctx: string, name: string) => ctx.match(new RegExp(`^${name}: (.*)$`, "m"))?.[1] || "";

export function sampleAnswer(question: string, practiceContext?: string): Answer {
  const q = question.replace(/\s+/g, " ");
  const ctx = practiceContext || "";
  const title = field(ctx, "실습 문제") || q;
  const has = (...words: string[]) => words.some(w => q.includes(w));
  const kind = /버블|정렬/.test(title) ? "bubble" : /평균/.test(title) ? "average" : /가장 큰|최댓값|최대/.test(title) ? "max" : null;

  // 1) 채점 결과·오류에 대한 질문
  if (has("문법")) return grounded("코드는 실행되기 전에 먼저 문장 규칙(문법)에 맞는지 검사를 받아요. 괄호나 따옴표의 짝이 맞는지, 대입은 '=' 하나로 썼는지, 비교는 '=='로 썼는지 확인해 보세요. 빈칸 안에는 줄 전체가 아니라 그 자리에 들어갈 식만 쓰면 돼요.", ARRAY);
  if (has("오류", "에러", "멈춰", "멈춘")) {
    if (kind === "bubble") return grounded("버블 정렬은 j번째 칸과 j+1번째 칸을 비교해요. 그래서 j가 마지막 칸까지 가면 j+1번째 칸은 리스트 밖이라 '없는 칸' 오류가 나요. 안쪽 반복이 j를 어디까지 보내야 j+1이 항상 리스트 안에 있을지 시각화의 배열 칸 번호와 함께 세어 보세요.", SORT, ARRAY);
    return grounded("실행 중 오류는 문법은 맞지만 실행하다가 할 수 없는 일을 만났을 때 생겨요. 리스트 밖의 칸을 읽거나, 아직 값을 넣지 않은 변수를 쓰는 경우가 많아요. 시각화의 '⚠ 오류 장면'에서 바로 앞 단계의 변수 값을 확인하면 원인을 찾기 쉬워요.", ARRAY);
  }
  if (has("끝나지", "무한", "멈추지")) return grounded("반복이 끝나려면 반복 조건이 언젠가는 거짓이 되어야 해요. 반복할 때마다 조건에 쓰인 변수가 끝 쪽으로 한 걸음씩 움직이는지, 범위의 끝이 리스트 길이와 맞는지 확인해 보세요.", ARRAY);
  if (has("결과가", "다르게", "다른 결과", "틀렸")) {
    if (kind === "bubble") return grounded("버블 정렬에서 두 칸의 값을 바꿀 때, 한쪽 값을 다른 칸에 먼저 덮어쓰면 원래 값이 사라져요. 그러면 같은 숫자가 두 번 남고 하나는 없어져요. 시각화에서 교환하는 줄을 지난 직후 두 칸의 값이 정말 서로 바뀌었는지 확인해 보세요.", SORT);
    if (kind === "average") return grounded("평균은 '모든 값의 합 ÷ 개수'예요. 합계 변수가 처음에 0에서 시작하는지, 반복할 때마다 이전 합계에 이번 값을 더해 다시 저장하는지 확인해 보세요. 시각화에서 total 값이 반복마다 어떻게 바뀌는지 보면 어디서 달라지는지 찾을 수 있어요.", ARRAY);
    if (kind === "max") return grounded("가장 큰 수 찾기는 '지금까지 본 값 중 가장 큰 값'을 하나 기억해 두고, 더 큰 값을 만날 때만 바꾸는 방식이에요. 처음 기억해 둘 값과, 비교할 때 쓰는 부등호 방향을 다시 확인해 보세요.", SEARCH, ARRAY);
    return grounded("실행은 됐지만 결과가 다르면 중간 어딘가에서 값이 기대와 다르게 바뀐 거예요. 시각화를 처음부터 한 단계씩 넘기며, 변수 값이 처음으로 예상과 달라지는 줄을 찾아보세요.", ARRAY);
  }
  if (has("맞는지", "왜 맞")) return grounded(`${title.replace(/\s*\(.*\)$/, "")} 문제의 핵심은 반복할 때마다 값이 정해진 규칙대로 바뀐다는 점이에요. 시각화를 다시 재생하며 반복 한 번이 끝날 때마다 무엇이 확정되는지 확인해 보면 풀이가 왜 맞는지 설명할 수 있어요.`, kind === "bubble" ? SORT : ARRAY);

  // 2) 특정 줄·빈칸에 대한 질문
  if (has("무슨 일", "줄")) {
    if (has("range", "for")) return grounded("for 반복문은 범위 안의 값을 하나씩 변수에 넣으며 같은 코드를 되풀이해요. range(끝)은 0부터 끝-1까지의 수를 차례로 만들어요. 시각화에서 반복 변수 값이 한 단계마다 어떻게 늘어나는지 확인해 보세요.", ARRAY);
    if (has("if")) return grounded("if 문은 조건이 참일 때만 그 아래 코드를 실행해요. 시각화에서 조건이 참인 단계와 거짓인 단계를 비교해 보면 언제 아래 줄이 실행되는지 알 수 있어요.", ARRAY);
    if (has("print")) return grounded("print는 괄호 안 값을 화면(실행 결과)에 출력해요. 실행 결과 탭에서 이 줄이 출력한 값을 기대한 출력과 비교해 보세요.", ARRAY);
    return grounded("이 줄은 오른쪽 식의 값을 계산해 왼쪽 변수에 저장해요. 시각화에서 이 줄을 실행하기 직전과 직후의 변수 값을 비교해 보세요.", ARRAY);
  }
  if (has("빈칸")) {
    if (kind === "bubble") return grounded("버블 정렬의 안쪽 반복은 이웃한 두 칸을 비교하고, 순서가 틀리면 두 값을 맞바꿔요. 한 바퀴가 끝날 때마다 가장 큰 값이 맨 뒤로 가서 자리가 확정돼요. 그래서 바깥 반복이 한 번 돌 때마다 비교할 칸이 하나씩 줄어들어요.", SORT);
    if (kind === "average") return grounded("합계를 구할 때는 먼저 합계 변수를 0으로 두고, 반복마다 '지금까지의 합계 + 이번 값'을 다시 합계에 저장해요. 평균은 다 더한 합계를 값의 개수로 나눈 값이에요.", ARRAY);
    if (kind === "max") return grounded("가장 큰 값을 찾을 때는 첫 번째 값을 일단 가장 큰 값으로 기억하고, 다음 값들과 하나씩 비교해요. 지금 값이 기억한 값보다 크면 그 값으로 바꿔 기억해요.", SEARCH, ARRAY);
  }

  // 3) 개념 설명
  if (kind === "bubble" || has("버블", "정렬")) return grounded("버블 정렬은 이웃한 두 원소를 비교해 순서가 틀리면 서로 바꾸는 과정을 반복하는 정렬이에요. 한 바퀴가 끝날 때마다 가장 큰 값이 맨 뒤로 이동해 자리가 확정되고, n개의 값이면 최대 n-1바퀴를 돌아요.", SORT);
  if (kind === "average" || has("평균", "합계")) return grounded("누적 합은 반복문으로 값을 하나씩 더해 가는 방법이에요. 합계를 담을 변수를 0으로 시작하고 반복마다 값을 더해요. 평균은 그 합계를 개수로 나눠 구해요.", ARRAY);
  if (kind === "max" || has("최댓값", "가장 큰")) return grounded("최댓값 찾기는 순차 탐색의 한 종류예요. 처음부터 끝까지 한 번씩 보면서 지금까지 가장 큰 값을 기억해 두고, 더 큰 값을 만나면 바꿔요.", SEARCH);
  return { answer_kind: "insufficient", answer: "공개된 강의 자료에서 답변 근거를 찾지 못했어요.", citations: [] };
}

/* 테스트 화면의 질문 → 답변 작업. 질문을 받으면 1.5초 뒤 답변이 완료돼요. */
const jobs = new Map<string, { at: number; answer: Answer }>();
let seq = 0;

export function testChatAsk(body: { message?: string; practice_context?: string | null; thread_id?: string | null }) {
  const id = `test-job-${++seq}`;
  jobs.set(id, { at: Date.now(), answer: { ...sampleAnswer(body.message || "", body.practice_context || ""), mode: "test_sample" } as Answer });
  return { job_id: id, thread_id: body.thread_id || "test-thread", status: "queued" };
}

export function testJob(id: string) {
  const job = jobs.get(id);
  if (!job) return { id, status: "failed", result: null, error: { code: "NOT_FOUND", retryable: false } };
  return Date.now() - job.at < 1500
    ? { id, status: "running", result: null, error: null }
    : { id, status: "succeeded", result: job.answer, error: null };
}
