/** Synthetic API responses only; excluded from production entrypoints and authentication. */
import { createRoot } from "react-dom/client";
import { WeeklyContent } from "../src/WeeklyContent";
import { ServiceStatusProvider } from "../src/ServiceStatus";
import "../src/style.css";
import "../src/lerny-theme.css";
import "../src/lerny-design.css";
import "../src/lerny-dark.css";
import "../src/lerny-dark-tweaks.css";
import "../src/confirm-dialog.css";

const legacy = new URLSearchParams(location.search).has("legacy");
const sources = [{material_id:"fixture-material",title:"자료구조 강의자료.pptx",kind:"lecture",version_id:"fixture-version",ready:true,status:"ready"}];
const jobs = ["weekly_content","questions","practice_prepare"].map(kind => ({id:kind,kind,status:"succeeded",required:true,held:[],error_code:null,retry_at:null,result_status:"ready"}));
const detail = {
  id:"fixture-generation",week:3,status:"draft",state:legacy ? "generating" : "ready",stale:false,can_publish:!legacy,
  video_mode:legacy ? "all" : "none",review_token:"f".repeat(64),sources,jobs,blockers:[],published_at:null,
  counts:{concepts:1,questions:1,practice:1,videos:legacy ? 1 : 0,videos_ready:0,videos_deferred:0},
  concepts:[{id:"fixture-concept",name:"스택",description:"스택은 마지막에 넣은 값을 먼저 꺼내요.",version_id:"fixture-version"}],
  questions:[{id:"q",concept_id:"fixture-concept",kind:"mcq",prompt:"스택에서 먼저 꺼내는 값은?",options:["마지막 값","첫 값","가운데 값","무작위 값"],solution:{answer_index:0,explanation:"마지막에 넣은 값을 먼저 꺼내요.",criteria:[]},sources:[{chunk_id:"chunk",quote:"스택은 후입선출 자료구조예요."}],sources_current:true}],
  practice:[{id:"p",title:"스택 실습",kind:"blank",language:"python",prompt:"배열의 합을 출력하세요.",template:"total = [[빈칸]]",reference:"total = sum(numbers)",tests:[{input:"numbers = [1, 2]",expected:"3"}],sources:[],status:"ready"}],
  videos:legacy ? [{id:"deferred",title:"스택 설명",concept_id:"fixture-concept",included:true,status:"queued",play_url:null}] : [],
};
let generated = legacy;
window.fetch = async (input, init) => {
  const url = String(input), body = JSON.parse(String(init?.body || "{}"));
  let data: unknown = {items:[]}, status = 200;
  if (url.endsWith("/service-status")) data = {maintenance:false,server_hold:false,features:{content:true},message:""};
  else if (url.endsWith("/google-slides/connection")) data = {configured:true,connected:true,rendering_enabled:false};
  else if (url.endsWith("/weekly-content")) data = {default_video_mode:"none",items:[{week:3,sources,source_hash:"a".repeat(64),sources_ready:true,draft:generated && detail.status === "draft" ? detail : null,published:detail.status === "published" ? detail : null}]};
  else if (url.endsWith("/content")) {generated=true;data={generation_id:detail.id,reused:false};}
  else if (url.endsWith("/video-selection")) {
    if (body.mode !== "none") throw Error("Fixture permits only video exclusion");
    detail.video_mode="none";detail.state="ready";detail.can_publish=true;
    detail.videos.forEach(video=>video.included=false);detail.counts.videos=0;detail.counts.videos_deferred=1;detail.review_token="n".repeat(64);data=detail;
  }
  else if (url.endsWith("/publish")) {
    if (!body.reviewed || !detail.can_publish || body.review_token !== detail.review_token) {status=409;data={error:{message:"검토 확인이 필요해요."}};}
    else {detail.status="published";detail.state="published";detail.can_publish=false;data={status:"published"};}
  }
  else if (url.endsWith("/fixture-generation")) data=detail;
  return new Response(JSON.stringify(data),{status,headers:{"Content-Type":"application/json"}});
};
createRoot(document.getElementById("root")!).render(<ServiceStatusProvider><main className="app"><h1>교수자 주차별 콘텐츠 검증</h1><p>합성 데이터로만 동작하는 로컬 검증 화면입니다.</p><WeeklyContent courseId="fixture" refreshKey="fixture"/></main></ServiceStatusProvider>);
