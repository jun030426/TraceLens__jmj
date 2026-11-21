import { conceptVideoPoster } from "./conceptVideoPoster";
import { useEffect, useRef, useState } from "react";
import { LectureVideo, type LectureVideoHandle } from "./LectureVideo";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { type Classroom, type Material } from "./api";
import { ErrorNotice, Notice, useLoad } from "./components";
import { ResourceBrowser } from "./ResourceBrowser";
import { LectureSummary } from "./LectureSummary";
import { matchesSearch } from "./listNavigation";
import "./instructor.css";

export type ConceptVideo = { id: string; title: string; concept_id: string; material_id: string; source_title: string; week: number; position: number; status: string; duration_seconds: number | null; play_url: string | null; poster_url?: string | null; error_code?: string };
export const videoState = (status: string) => ({ready:"재생 가능",script_pending:"대본 준비 중",queued:"영상 생성 대기",submitting:"영상 요청 중",processing:"영상 제작 중",storing:"영상 저장 중",waiting_ai:"AI 처리 대기",held:"검토 대기",failed:"처리 실패",needs_attention:"생성 상태 확인 필요",revoked:"자료 변경됨"} as Record<string,string>)[status] || "준비 중";

export function InstructorClass() {
  const { sectionId = "" } = useParams();
  const rooms = useLoad<{ items: Classroom[] }>("/classrooms");
  const room = rooms.data?.items.find(r => r.section.id === sectionId && r.status === "active");
  if (rooms.error) return <section className="student-home"><ErrorNotice text={rooms.error} /><button onClick={rooms.reload}>다시 불러오기</button></section>;
  if (!rooms.data) return <section className="student-home"><Notice>강의실을 불러오는 중이에요…</Notice></section>;
  if (!room) return <section className="student-home"><Notice>수강 중인 강의실에서 이용할 수 있어요. <Link to="/courses">내 강의로</Link></Notice></section>;
  return <InstructorContent key={sectionId} room={room} />;
}

function InstructorContent({ room }: { room: Classroom }) {
  const materials = useLoad<{ items: Material[] }>(`/courses/${room.course.id}/materials`);
  const videos = useLoad<{ items: ConceptVideo[]; shared: boolean }>(`/sections/${room.section.id}/concept-videos`, true);
  const [params, setParams] = useSearchParams();
  const [infoTab, setInfoTab] = useState("관련 자료");
  const [search, setSearch] = useState("");
  const player = useRef<LectureVideoHandle>(null);
  const items = videos.data?.items || [];
  const sources = (materials.data?.items || []).filter(m => m.visibility === "public" && m.kind === "lecture" && !!m.view_url);
  const weeks = [...new Set([...sources.map(m => m.week), ...items.map(v => v.week)])].sort((a,b) => a-b);
  const requested = Number(params.get("week"));
  const week = weeks.includes(requested) ? requested : weeks[0];
  const weekVideos = items.filter(v => v.week === week);
  const selectedVideo = weekVideos.find(v => v.id === params.get("video")) || weekVideos[0];
  const weekSources = sources.filter(m => m.week === week);
  const selectedMaterial = weekSources.find(m => m.id === selectedVideo?.material_id) || weekSources[0];
  const summaryMaterialId = selectedVideo?.material_id || selectedMaterial?.id;
  const summaryTitle = selectedVideo?.source_title || selectedMaterial?.title || "수업 학습 근거";
  const pending = items.some(v => ["script_pending","queued","submitting","processing","storing","waiting_ai"].includes(v.status));
  useEffect(() => {
    if (!videos.data || !pending && items.length) return;
    const timer = setInterval(videos.reload, 15000);
    return () => clearInterval(timer);
  }, [pending, videos.data, videos.reload, items.length]);
  const choose = (w: number, video?: string) => {
    const next = new URLSearchParams(); next.set("week",String(w));
    if (video) next.set("video",video);
    setParams(next, {replace:true});
  };
  const nextVideo = selectedVideo ? items[items.findIndex(v => v.id === selectedVideo.id)+1] : undefined;
  const query = search.trim();
  const weekQuery = Number(query.match(/^(\d{1,2})\s*(주차|주)?$/)?.[1]) || null;
  const matchesVideo = (v: ConceptVideo) => weekQuery ? v.week === weekQuery : matchesSearch(query, v.title, v.source_title);
  const [half, setHalf] = useState<number | null>(null);
  const [collapsed, setCollapsed] = useState<number[]>([]);
  const lastWeek = weeks.at(-1) || 0;
  const shownHalf = half ?? ((week || 0) > 9 ? 1 : 0);
  const matchingSources = sources.filter(m => weekQuery ? m.week === weekQuery : matchesSearch(query, m.title));
  const shownWeeks = weeks.filter(w => {
    if (!query) return lastWeek <= 9 || shownHalf === 2 || (shownHalf === 0 ? w <= 9 : w > 9);
    return matchingSources.some(m => m.week === w) || items.some(v => v.week === w && matchesVideo(v));
  });
  const courseTitle = room.course.title.split(/\s+[—–]\s+/)[0];
  return <section className="student-home instructor-page">
    <Link className="cr-back" to="/courses"><span aria-hidden="true">←</span> 내 강의로</Link>
    <div className="instructor-page-heading"><div><h1>AI 강의</h1><p>개념을 보고, 직접 풀어보세요.</p></div><div className="instructor-breadcrumb"><Link to={`/classrooms/${room.section.id}`}>{courseTitle}</Link>{room.term?.name && <><span aria-hidden="true">·</span><span>{room.term.name}</span></>}{room.teacher_name && <><span aria-hidden="true">·</span><span>{room.teacher_name}</span></>}<span aria-hidden="true">·</span><span>{room.section.title}</span></div></div>
    <ErrorNotice text={materials.error || videos.error} />
    {(materials.error || videos.error) && <button type="button" onClick={() => { materials.reload(); videos.reload(); }}>강의 자료 다시 불러오기</button>}
    <div className="instructor-learning-layout"><div className="instructor-main-column">
      {selectedVideo?.status === "ready" && selectedVideo.play_url ? <section className="instructor-stage" aria-label={selectedVideo.title}>
        <LectureVideo ref={player} key={selectedVideo.id} poster={conceptVideoPoster(selectedVideo.id, selectedVideo.poster_url)} src={selectedVideo.play_url}
          onEnded={() => { if (nextVideo?.status === "ready") choose(nextVideo.week,nextVideo.id); }} />
      </section> : <section className="instructor-stage" aria-label="개념 영상 준비 상태">
        <div className="instructor-stage-top"><span>Lerny 강의실</span><span>{selectedVideo ? videoState(selectedVideo.status) : videos.data ? "공개 대기" : "불러오는 중"}</span></div>
        <div className="instructor-board"><span className="instructor-board-kicker">{week ? `${week}주차` : "개념별 강의"}</span><h2>{selectedVideo?.title || "아직 공개된 개념 강의가 없어요."}</h2>
          <p>{selectedVideo ? "영상이 완성되면 같은 자리에서 재생할 수 있어요." : "교수님이 콘텐츠를 생성하고 검토한 뒤 공개하면 이곳에서 학습할 수 있어요. 공개된 강의자료는 먼저 확인할 수 있어요."}</p></div>
      </section>}
      <div className="instructor-lecture-heading is-stacked"><div className="instructor-lecture-label-row"><span className="instructor-week-label">{week ? `${week}주차${selectedVideo ? ` · 개념 ${selectedVideo.position}` : ""}` : "개념별 강의"}</span></div><div className="instructor-lecture-title-row"><h2>{selectedVideo?.title || "콘텐츠 공개를 기다리고 있어요."}</h2></div></div>
      <div className="instructor-action-bar"><Link className="primary instructor-study-action" to={`/quiz?section=${room.section.id}`}>오늘의 문제 풀기 ↗</Link>
        {nextVideo && <button onClick={() => choose(nextVideo.week,nextVideo.id)}>다음 개념: {nextVideo.title} →</button>}</div>
      <section className="instructor-details"><div className="instructor-info-tabs" role="group" aria-label="강의 부가 정보">{["관련 자료","강의 안내","강의 자료 요약"].map(tab => <button key={tab} aria-pressed={infoTab===tab} onClick={() => setInfoTab(tab)}>{tab}</button>)}</div>
        {infoTab==="강의 안내" && <div className="instructor-info-content"><h3>개념별 짧은 설명, 나에게 맞는 문제</h3><p>영상은 같은 강의실의 모든 학생에게 동일하게 제공돼요. 이론은 하루 5문항으로, 4일차부터 나의 오답과 취약 개념을 반영해 복습해요.</p></div>}
        {infoTab==="강의 자료 요약" && (summaryMaterialId ? <LectureSummary key={`${summaryMaterialId}:${selectedVideo?.concept_id || ""}`} materialId={summaryMaterialId} title={summaryTitle} viewUrl={weekSources.find(m => m.id === summaryMaterialId)?.view_url} conceptId={selectedVideo?.concept_id}/> : <Notice>공개된 자료가 아직 없어요.</Notice>)}
        {infoTab==="관련 자료" && <div className="instructor-info-content"><h3>교수님이 공개한 원본 자료</h3><ResourceBrowser key={week} items={weekSources} label="관련 자료">{visible => <ul className="instructor-source-list">{visible.map(m => <li key={m.id}><span>{m.title}</span><Link to={m.view_url!}>자료 열기 ↗</Link></li>)}</ul>}</ResourceBrowser></div>}
      </section>
    </div><aside id="instructor-side-panel" className="instructor-curriculum" aria-label="주차별 개념 영상"><div id="instructor-list-panel">
      <div className="instructor-curriculum-heading"><h2 id="instructor-curriculum-title">AI 강의 자료</h2><span>{items.length}개 영상 · {weeks.length}개 주차</span></div>
      <p className="instructor-curriculum-note">강의자료의 개념 순서로 표시돼요. 준비 중인 영상은 완료 후 재생할 수 있어요.</p>
      <button onClick={() => { videos.reload(); player.current?.retryIfFailed(); }}>목록 새로고침</button>
      <label className="material-week-search instructor-week-search"><span aria-hidden="true">⌕</span><input type="search" aria-label="AI 강의 자료 검색" value={search} onChange={e => setSearch(e.target.value)} placeholder="주차·개념·자료 이름 검색" /></label>
      {lastWeek > 9 && <div className="material-week-split instructor-week-split" role="group" aria-label="주차 묶음">
        {([[2, "전체 주차"], [0, "1–9주차"], [1, `10–${lastWeek}주차`]] as const).map(([id, label]) => <button key={id} type="button" aria-pressed={shownHalf === id} className={shownHalf === id ? "is-active" : ""} onClick={() => { setHalf(id); setSearch(""); }}>{label}{room.current_week != null && room.current_week > 0 && id !== 2 && (id === 0 ? room.current_week <= 9 : room.current_week > 9) && <span className="material-week-split-dot" aria-label="현재 진도 포함" />}</button>)}
      </div>}
      {!weeks.length && <Notice>{videos.data ? "교수님이 공개한 첫 자료를 기다리고 있어요." : "강의 목록을 불러오는 중이에요…"}</Notice>}
      {!!query && !shownWeeks.length && <p className="student-list-empty">검색한 강의가 없어요.</p>}
      <div className="instructor-week-list">{shownWeeks.map(w => {
        const expanded = !!query || w === week && !collapsed.includes(w);
        const entries = items.filter(v => v.week === w && matchesVideo(v));
        return <div key={w} className={`instructor-week ${expanded ? "is-open" : ""} ${w === room.current_week ? "is-current" : ""} ${w === week ? "is-selected" : ""}`}>
          <button className="instructor-week-toggle" aria-expanded={expanded} aria-controls={`instructor-week-${w}`} onClick={() => {
            if (w === week && !query) setCollapsed(old => old.includes(w) ? old.filter(x => x !== w) : [...old, w]);
            else { choose(w); setSearch(""); setCollapsed(old => old.filter(x => x !== w)); }
          }}><span><b>{String(w).padStart(2,"0")}</b>{w}주차{w === room.current_week && <em className="instructor-week-now">현재 진도</em>}</span><span>영상 {items.filter(v => v.week === w).length}개 <i aria-hidden="true">{expanded ? "−" : "+"}</i></span></button>
          {expanded && <div id={`instructor-week-${w}`} className="instructor-week-items">
            {entries.map(v => <button key={v.id} aria-pressed={selectedVideo?.id === v.id} onClick={() => choose(w,v.id)}>
              <span className="instructor-item-icon instructor-item-no">{String(v.position).padStart(2,"0")}</span><span><strong>{v.title.replace(/^\s*\d{1,2}\s*주차\s*[·:\-–]\s*/, "")}</strong><small>{videoState(v.status)}{v.duration_seconds ? ` · ${Math.round(v.duration_seconds)}초` : ""}</small></span>
              {selectedVideo?.id === v.id && <span className="instructor-current-dot" aria-label="선택됨" />}
            </button>)}
            {query && matchingSources.filter(m => m.week === w).map(m =>
              <Link key={m.id} to={m.view_url!}>{m.title} · 자료 열기 ↗</Link>)}
            {!entries.length && !query && <p className="muted">이 주차에 공개된 개념 영상이 아직 없어요. 관련 자료를 먼저 확인할 수 있어요.</p>}
          </div>}
        </div>;
      })}</div>
      </div>
    </aside></div>
  </section>;
}
