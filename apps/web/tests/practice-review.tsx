/** Synthetic in-memory API only. This entry is excluded from the production build. */
import { createRoot } from "react-dom/client";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { Auth } from "../src/Auth";
import { PracticeWorkspace, PracticeResults } from "../src/Practice";
import { LearningText } from "../src/LearningText";
import type { User } from "../src/api";
import "../src/style.css";
import "../src/workspace-refinements.css";
import "../src/lerny-theme.css";
import "../src/lerny-design.css";
import "../src/lerny-dark.css";
import "../src/lerny-dark-tweaks.css";
import "../src/student-fit.css";
import "../src/student-buttons.css";
import "../src/confirm-dialog.css";
const start = "public class Main {\n  public static void main(String[] args) {\n    int n = 3;\n";
const end = "\n  }\n}";
const description = "주어진 정수에서 다음 수를 구하세요.\n\n입력 선언을 유지하고, `n + 1`의 값을 출력하세요.\n공백과 줄바꿈을 확인하세요.";
const items = ["blank", "full"].map(kind => ({id:kind,kind,title:"다음 수 출력하기",description,
  template:start+(kind === "blank" ? "    System.out.println([[빈칸]]);" : "    // 출력 코드를 작성하세요")+end,
  expected:"4",example_input:"int n = 3;",requirements:["시작 코드의 입력 선언을 유지하세요.","입력이 달라져도 같은 규칙으로 처리하세요."],available_helpers:[]}));
const reference = start + "    System.out.println(n + 1);" + end;
const attempts: Record<string, unknown>[] = [];
const hints: Record<string, number> = {};
const review = (id: string) => ({...items.find(q => q.id === id)!,language:"java",reference,blanks:id === "blank" ? ["n + 1"] : []});
window.fetch = async (input, init) => {
  const url = String(input), body = JSON.parse(String(init?.body || "{}"));
  let data: unknown = {items:[]}, status = 200;
  if (url.endsWith("/classrooms")) data = {items:[{status:"active",section:{id:"fixture",title:"검증 분반"},course:{title:"실습 검증",teaching_language:"java"}}]};
  else if (url.endsWith("/daily")) data = {id:"fixture-plan",items,status:"ready",week:2};
  else if (url.endsWith("/attempts")) data = {items:attempts};
  else if (url.endsWith("/submit")) { data = {id:body.exercise_id,practice_session_id:"fixture-plan",exercise_id:body.exercise_id,status:"graded",correct:true,source:body.source,independent:true,created_at:new Date().toISOString(),feedback:{message:"검증 통과",passed:2,total:2},exercise:items.find(q=>q.id === body.exercise_id)}; attempts.unshift(data as Record<string, unknown>); }
  else if (url.endsWith("/explanation")) data = review(url.split("/").at(-2)!);
  else if (url.endsWith("/help")) {
    const id = body.exercise_id, submitted = attempts.some(a=>a.exercise_id === id);
    if (body.kind === "hint") hints[id] = body.step;
    data = {hints_used:hints[id] || 0,hints:Array.from({length:hints[id]||0},(_,i)=>`힌트 ${i+1}: 입력과 출력의 관계를 확인하세요.`),max_hint_steps:id === "full" ? 4 : 3,can_view_answer:submitted};
    if (body.kind === "answer") { if (submitted) data = {...data as object, explanation:review(id)}; else {status=409;data={error:{message:"최종 제출 후 볼 수 있어요."}};} }
  }
  return new Response(JSON.stringify(data), {status,headers:{"Content-Type":"application/json"}});
};
const user = {id:"practice-fixture",role:"student",display_name:"검증 학생"} as User;
createRoot(document.getElementById("root")!).render(<Auth.Provider value={{user,loading:false,refresh:async()=>{}}}><MemoryRouter initialEntries={["/classrooms/fixture/practice"]}><main className="app student-main"><Routes><Route path="/classrooms/:sectionId/practice" element={<PracticeWorkspace/>}/><Route path="/classrooms/:sectionId/practice/results" element={<PracticeResults/>}/></Routes><aside><h2>이론 해설 서식 검사</h2><LearningText text={'소수점 형식은 `{bmi:10.2f}`예요.\n\n두 번째 문단입니다. <script>는 글자로만 표시돼요.'}/></aside></main></MemoryRouter></Auth.Provider>);
