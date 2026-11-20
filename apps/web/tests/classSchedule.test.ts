import assert from "node:assert/strict";
import test from "node:test";
import { scheduleName, submittedSlots } from "../src/classSchedule.ts";

test("수업 등록: 여러 요일·시간을 요일 순·시간 순으로 묶고 같은 시간은 한 번만 적는다", () => {
  assert.equal(
    scheduleName(["수", "월"], [{ start: "13:00", end: "14:15" }, { start: "10:00", end: "11:15" }, { start: "10:00", end: "11:15" }]),
    "월·수 10:00–11:15, 13:00–14:15",
  );
});

test("수업 등록: 요일·시간이 없거나 끝이 시작보다 빠르면 막는다", () => {
  assert.throws(() => scheduleName([], [{ start: "10:00", end: "11:00" }]), /요일/);
  assert.throws(() => scheduleName(["월"], [{ start: "", end: "" }]), /수업 시간/);
  assert.throws(() => scheduleName(["월"], [{ start: "11:00", end: "10:00" }]), /늦어야/);
  assert.throws(() => scheduleName(["월"], [{ start: "11:00", end: "" }]), /모두/);
});

test("수업 등록: 화면에 입력된 시간과 추가한 행을 제출 값으로 보존한다", () => {
  const form = new FormData();
  form.set("slot-start-0", "10:00"); form.set("slot-end-0", "12:00");
  form.set("slot-start-1", "14:00"); form.set("slot-end-1", "15:00");
  assert.equal(scheduleName(["화", "목"], submittedSlots(form, 2)), "화·목 10:00–12:00, 14:00–15:00");
  form.delete("slot-end-1");
  assert.throws(() => scheduleName(["화"], submittedSlots(form, 2)), /모두/);
});
