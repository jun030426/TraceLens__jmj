import test from "node:test";
import assert from "node:assert/strict";
import { conceptValidationMessage, materialProgress, jobMessage, type Processing, type ProcessingJob } from "../src/materialProcessing.ts";
import type { Material } from "../src/api.ts";

const material: Material = {id:"m",title:"자료",kind:"lecture",week:1,visibility:"public",internal_use:"none",revision:1,
  version:{id:"v",status:"extracted",filename:"자료.txt",error_code:null}};
const job = (kind:string, status:string, extra:Partial<ProcessingJob>={}):ProcessingJob => ({
  id:kind,kind,status,is_current:true,retryable:false,concept_id:null,error_code:null,result_status:null,retry_at:null,...extra,
});
const processing = (jobs:ProcessingJob[]):Processing => ({material_id:"m",version_id:"v",source_status:"extracted",jobs});
const ready = {...material,version:{...material.version!,status:"ready"}};

test("paid version budget failure requires operator approval for either worker", () => {
  for (const kind of ["extract", "embed"]) {
    const failed = job(kind, "failed", {error_code: "GEMINI_PAID_CALL_BUDGET_EXCEEDED"});
    assert.match(jobMessage(failed), /운영자의 한도 상향 승인/);
    assert.match(jobMessage(failed), /완료된 결과는 보존/);
  }
});

test("concept validation failures distinguish quote length from provider unavailability",()=>{
  const message=jobMessage(job("weekly_content","failed",{error_code:"CONCEPT_QUOTE_TOO_SHORT"}));
  assert.match(message,/인용문.*5자.*보정/); assert.doesNotMatch(message,/503|서비스.*지연/);
  assert.equal(conceptValidationMessage({concept_index:2,batch_number:1,reason:"quote_too_short"}),"자료 묶음 1 · 개념 3: 인용문이 5자 미만이에요.");
  assert.match(conceptValidationMessage({concept_index:null,reason:"response_format"}),/응답 전체.*형식/);
  assert.doesNotMatch(conceptValidationMessage({concept_index:0,reason:"untrusted raw text"}),/untrusted raw text/);
});

test("legacy deferral is a hold, never endless processing or a historical model failure",()=>{
  const result=materialProgress(material,processing([
    job("embed","failed",{id:"old",is_current:false,error_code:"LOCAL_MODEL_MISSING"}),
    job("embed","waiting_ai",{error_code:"LEGACY_BACKFILL_DEFERRED"}),
  ]));
  assert.equal(result.tone,"held"); assert.match(result.hint,/이전 자료.*보류/);
  assert.equal(result.stages[0].tone,"ready");assert.equal(result.history.length,1);
});
test("success replacing a previous failed concept does not hide another concept failure",()=>{
  const result=materialProgress(ready,processing([
    job("auto_concepts","succeeded"),job("questions","failed",{id:"old",is_current:false}),
    job("questions","succeeded",{concept_id:"a"}),job("questions","failed",{id:"b",concept_id:"b"}),
  ]));
  assert.equal(result.tone,"failed");assert.equal(result.jobs.length,3);
});
test("all current concepts and questions must complete before usage is ready",()=>{
  assert.equal(materialProgress(ready,processing([job("auto_concepts","succeeded")])).tone,"pending");
  assert.equal(materialProgress(ready,processing([job("auto_concepts","succeeded"),job("questions","cancelled")])).tone,"held");
  assert.equal(materialProgress(ready,processing([job("auto_concepts","succeeded"),job("questions","succeeded")])).tone,"ready");
});
test("no source code is not presented as successful practice generation",()=>{
  const result=materialProgress(ready,processing([job("auto_concepts","succeeded"),job("questions","succeeded"),job("practice_prepare","succeeded",{result_status:"no_verified_source_code"})]));
  assert.equal(result.tone,"ready");assert.match(result.hint,/실습은 생성하지 않았/);
});
test("private and reference materials do not wait for automatic generation",()=>{
  assert.equal(materialProgress({...ready,visibility:"private"},processing([])).tone,"neutral");
  assert.equal(materialProgress({...ready,kind:"answer"},processing([])).tone,"neutral");
});
test("new file version or query failure cannot inherit readiness of an old version",()=>{
  const result=materialProgress({...ready,version:{...ready.version,id:"v2"}},processing([job("auto_concepts","succeeded"),job("questions","succeeded")]));
  assert.equal(result.tone,"unknown");assert.equal(result.jobs.length,0);
  assert.equal(materialProgress(ready,processing([]),{error:"network"}).tone,"unknown");
});
test("service pause holds waiting work but preserves completed learning",()=>{
  assert.equal(materialProgress(material,processing([job("embed","running")]),{uploadsBlocked:true,contentBlocked:true}).tone,"running");
  assert.equal(materialProgress(material,processing([job("embed","queued")]),{uploadsBlocked:true,contentBlocked:true}).tone,"held");
  assert.equal(materialProgress(ready,processing([job("auto_concepts","succeeded"),job("questions","succeeded")]),{uploadsBlocked:true,contentBlocked:true}).tone,"ready");
});
test("source review and failure are visible before content readiness",()=>{
  assert.equal(materialProgress({...material,version:{...material.version!,status:"needs_review"}},processing([])).tone,"held");
  assert.equal(materialProgress({...material,version:{...material.version!,status:"failed"}},processing([])).tone,"failed");
});
test("unknown errors get a useful next action and successful retries ignore stale error text",()=>{
  assert.match(jobMessage({status:"failed",error_code:"UNRECOGNIZED",result_status:null}),/관리자/);
  assert.equal(jobMessage({status:"succeeded",error_code:"LOCAL_MODEL_MISSING",result_status:null}),"처리가 완료됐어요.");
});

test("media input admission errors explain interruption and preserve source",()=>{
  const message=jobMessage({status:"failed",error_code:"GEMINI_INPUT_BUDGET_EXCEEDED",result_status:null});
  assert.match(message,/입력량 한도.*중단/);
  assert.match(message,/원본과 저장된 분석 결과는 유지/);
});

test("exhausted service retries are held with preserved results, never endless automatic retry",()=>{
  const state=materialProgress({...material,version:{...material.version!,status:"failed",error_code:"GEMINI_SERVICE_RETRY_EXHAUSTED"}},processing([job("extract","failed",{error_code:"GEMINI_SERVICE_RETRY_EXHAUSTED"})]));
  assert.equal(state.tone,"held");
  assert.match(state.hint,/5회.*자동 재시도를 멈췄/);
  assert.match(state.hint,/저장된 결과부터 이어서/);
});

test("narration validation shows measured length and rejected unit without a concept NaN",()=>{
  assert.match(conceptValidationMessage({code:"SHORTS_NARRATION_LENGTH",actual_characters:334}),/334자.*360~400자/);
  assert.match(conceptValidationMessage({code:"NARRATION_UNSUPPORTED",target:"/lesson/narration/1"}),/^대본 2:.*공개 원문/);
  assert.doesNotMatch(conceptValidationMessage({code:"NARRATION_REVIEW_INVALID"}),/NaN|개념/);
});

test("video credit exhaustion identifies API credits and preserved outputs",()=>{
  const text=jobMessage({status:"failed",error_code:"HEYGEN_API_CREDITS_REQUIRED",result_status:null});
  assert.match(text,/API 크레딧.*충전/);
  assert.match(text,/대본과 완료된 영상은 유지/);
});
