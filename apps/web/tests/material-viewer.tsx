// Synthetic, isolated fixture. Not included in production navigation or authentication.
import { createRoot } from "react-dom/client";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { MaterialViewer } from "../src/MaterialViewer";
import "../src/style.css";
import "../src/lerny-theme.css";
import "../src/lerny-design.css";
import "../src/lerny-dark.css";
import "../src/student-fit.css";
import "../src/student-buttons.css";

const params = new URLSearchParams(location.search);
document.documentElement.dataset.role = "student";
document.documentElement.dataset.theme = params.has("dark") ? "dark" : "light";
if (params.has("mobile")) document.getElementById("root")!.style.maxWidth = "390px";
const slide = (n: number) => `/tests/handout-${n}.svg`;
window.fetch = async input => {
  const url = String(input);
  if (url.endsWith("/classrooms")) return Response.json({items:[{course:{id:"course"},section:{id:"section"},status:"active"}]});
  if (params.has("error")) return Response.json({error:{message:"열람할 수 있는 강의자료가 아닙니다."}}, {status:404});
  return Response.json({material_id:"handout",course_id:"course",title:"자료구조의 이해 · 테스트 강의자료",version_id:"v1",status:params.has("preparing")?"preparing":"ready",pages:[1,2].map(number => ({number,width:1200,height:675,text:number === 1?"배열은 원소들을 순서대로 저장합니다.":"인덱스 2로 세 번째 원소 30을 찾습니다.",image_url:slide(number)}))});
};
createRoot(document.getElementById("root")!).render(<MemoryRouter initialEntries={["/materials/handout/view"]}><main className="app student-main"><Routes><Route path="/materials/:materialId/view" element={<MaterialViewer/>}/></Routes></main></MemoryRouter>);
