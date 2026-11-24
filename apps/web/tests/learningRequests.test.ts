import { test } from "node:test";
import assert from "node:assert/strict";
import { chatDailyWaitMessage, theoryChatBody, practiceChatBody, practiceSubmitBody, saveTutorChoice } from "../src/learningRequests.ts";

test("이론 해설 질문은 실습 전용 필드 없이 문제와 답안을 보내요", () => {
  const body = theoryChatBody("왜 틀렸나요?", "thread", "concept", "문제: 반복문\n내 답: 3");
  assert.equal(body.mode, "theory");
  assert.equal(body.concept_id, "concept");
  assert.match(body.message, /내 답: 3/);
  assert.equal("practice_context" in body, false);
  assert.equal("student_state" in body, false);
  const long = theoryChatBody("질문".repeat(1900), undefined, undefined, "문맥".repeat(1500));
  assert.equal(long.message.length, 4000);
  assert.ok(long.message.startsWith("질문".repeat(1900)));
});

test("실습 질문은 배정 문항과 모드가 필수이며 정답 자체는 첨부하지 않아요", () => {
  assert.deepEqual(practiceChatBody("다음 줄?", "exercise", "thread", "학생 코드"), {
    thread_id: "thread", mode: "practice", exercise_id: "exercise", message: "다음 줄?", practice_context: "학생 코드",
  });
  assert.equal(practiceChatBody("질문", "e", undefined, "x".repeat(4000)).practice_context.length, 3000);
});

test("최종 제출은 입력값과 보여 준 템플릿을 보존해요", () => {
  assert.deepEqual(practiceSubmitBody("exercise", "print('아직 미완성')"), { exercise_id: "exercise", source: "print('아직 미완성')" });
  const editor = { template: " 한😀[[빈칸]]:[[빈칸]]\n", fills: ["가:🧪", "나"] };
  assert.deepEqual(practiceSubmitBody("exercise", " 한😀가:🧪:나\n", editor),
    { exercise_id: "exercise", source: " 한😀가:🧪:나\n", editor });
});

test("이해도는 특정 답변에 저장하고 중단은 대기 중 작업부터 취소해요", async () => {
  const calls: {path: string; options: RequestInit}[] = [];
  const request = async (path: string, options: RequestInit) => { calls.push({ path, options }); };
  await saveTutorChoice(request, "s", "confused", "m");
  assert.equal(calls[0].path, "/sections/s/chat/messages/m/feedback");
  assert.equal(calls[0].options.method, "PUT");
  assert.deepEqual(JSON.parse(String(calls[0].options.body)), { value: "confused" });
  await saveTutorChoice(request, "s", "stop", "m", "j");
  assert.equal(calls[1].path, "/jobs/j/cancel");
  await saveTutorChoice(request, "s", "stop", "m");
  assert.deepEqual(JSON.parse(String(calls[2].options.body)), { value: "aborted" });
});

test("저장 실패나 답변 없는 피드백을 성공으로 대체하지 않아요", async () => {
  let writes = 0;
  const request = async () => { writes++; throw new Error("연결 실패"); };
  await assert.rejects(saveTutorChoice(request, "s", "understood"), /답변을 받은 뒤/);
  assert.equal(writes, 0);
  await assert.rejects(saveTutorChoice(request, "s", "understood", "m"), /연결 실패/);
  await assert.rejects(saveTutorChoice(request, "s", "stop", "m", "j"), /연결 실패/);
});

test("일일 한도에 도달하면 한국 시간으로 질문 처리 재개 시각을 안내해요", () => {
  const job = { status: "queued", error: { code: "GEMINI_DAILY_WAIT", retryable: true } };
  const message = chatDailyWaitMessage({ ...job, retry_at: "2030-01-01T16:00:00Z" });
  assert.match(message ?? "", /오늘 질문 처리 한도/);
  assert.match(message ?? "", /1월 2일.*1:00.*한국 시간/);
  assert.equal(chatDailyWaitMessage(job), undefined);
});

test("분당 대기에는 일일 한도 안내를 표시하지 않아요", () => {
  assert.equal(chatDailyWaitMessage({ status: "queued", error: { code: "GEMINI_PACING_WAIT", retryable: true },
    retry_at: "2030-01-01T16:00:00Z" }), undefined);
});

test("정상 답변에는 이전 대기 시각이 있어도 한도 안내를 표시하지 않아요", () => {
  assert.equal(chatDailyWaitMessage({ status: "succeeded", error: null, retry_at: "2030-01-01T16:00:00Z" }), undefined);
});
