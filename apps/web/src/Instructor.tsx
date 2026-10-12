import { ResourceBrowser } from "./ResourceBrowser";
import { PagedList } from "./StudentLists";
import { matchesSearch } from "./listNavigation";
import { useContext, useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { Auth } from "./Auth";
import { type Classroom, type Material } from "./api";
import { ErrorNotice, Notice, useLoad } from "./components";
import { Chat } from "./Learning";
import "./instructor.css";

function PlayMark({ size = 20 }: { size?: number }) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="m9 5 11 7-11 7V5Z" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" /></svg>;
}
function PersonMark() {
  return <svg viewBox="0 0 100 120" fill="none" aria-hidden="true"><circle cx="50" cy="32" r="20" /><path d="M14 112V94c0-21 16-36 36-36s36 15 36 36v18M37 60l13 18 13-18M50 78v34" /></svg>;
}

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
  const { user } = useContext(Auth);
  const materials = useLoad<{ items: Material[] }>(`/courses/${room.course.id}/materials`);
  const [params, setParams] = useSearchParams();
  const [instructor, setInstructor] = useState(0);
  const [preferenceNote, setPreferenceNote] = useState("");
  const [infoTab, setInfoTab] = useState("관련 자료");
  const [pickerOpen, setPickerOpen] = useState(false);
  const [sideTab, setSideTab] = useState("강의 목록");
  const [sourceSearch, setSourceSearch] = useState("");
  const [collapsedWeeks, setCollapsedWeeks] = useState<number[]>([]);
  const preferenceKey = `lerny-instructor:${user?.id}`;
  useEffect(() => {
    try { const value = Number(localStorage.getItem(preferenceKey) || "0"); setInstructor(Number.isInteger(value) && value >= 0 && value < 4 ? value : 0); }
    catch { setPreferenceNote("강사 선택은 현재 화면에서만 유지돼요."); }
  }, [preferenceKey]);
  const chooseInstructor = (index: number) => {
    setInstructor(index);
    try { localStorage.setItem(preferenceKey, String(index)); setPreferenceNote("선호 강사를 이 브라우저에 저장했어요."); }
    catch { setPreferenceNote("강사 선택은 현재 화면에서만 유지돼요."); }
  };
  const sources = (materials.data?.items || []).filter(m => m.visibility === "public" && ["lecture", "example", "assignment", "transcript"].includes(m.kind));
  const weeks = [...new Set(sources.map(m => m.week))].sort((a, b) => a - b);
  const requestedWeek = Number(params.get("week"));
  const week = weeks.includes(requestedWeek) ? requestedWeek : weeks[0];
  const weekSources = sources.filter(m => m.week === week);
  const selected = weekSources.find(m => m.id === params.get("material")) || weekSources[0];
  const select = (nextWeek: number, id?: string) => {
    const next = new URLSearchParams(params); next.set("week", String(nextWeek));
    if (id) next.set("material", id); else next.delete("material");
    setParams(next, { replace: true });
  };
  const courseTitle = room.course.title.split(/\s+[—–]\s+/)[0];
  const hasData = !!materials.data;
  return <section className="student-home instructor-page">
    <div className="instructor-breadcrumb"><Link to={`/classrooms/${room.section.id}`}>{courseTitle}</Link><span aria-hidden="true">/</span><span>{room.section.title}</span></div>
    <div className="instructor-page-heading"><div><h1>AI 강의</h1><p>개념을 보고, 질문하고, 직접 풀어보세요.</p></div><div className="instructor-current-teacher"><span className={`instructor-avatar instructor-avatar-${instructor}`}><PersonMark /></span><span>함께할 강사<strong>강사 {String(instructor + 1).padStart(2, "0")}</strong></span><button aria-expanded={pickerOpen} aria-controls="instructor-selection" onClick={() => setPickerOpen(!pickerOpen)}>{pickerOpen ? "선택 닫기" : "강사 변경"}</button></div></div>
    <section id="instructor-selection" className="instructor-picker" hidden={!pickerOpen} aria-label="AI 강사 선택"><div className="instructor-picker-heading"><h3>함께할 AI 강사</h3><span>지금은 선택 화면 미리보기예요. 외모와 목소리는 제작 후 연결돼요.</span></div><div className="instructor-picker-options">{[0, 1, 2, 3].map(index => <button key={index} type="button" aria-pressed={instructor === index} onClick={() => chooseInstructor(index)} className={instructor === index ? "is-selected" : ""}><span className={`instructor-avatar instructor-avatar-${index}`}><PersonMark /></span><span><strong>강사 {String(index + 1).padStart(2, "0")}</strong><small>{index < 2 ? "여성" : "남성"} · 제작 예정</small></span><span className="instructor-pick-check" aria-hidden="true">{instructor === index ? "✓" : ""}</span></button>)}</div>{preferenceNote && <p className="instructor-preference-note" role="status">{preferenceNote}</p>}</section>
    <ErrorNotice text={materials.error} />
    {materials.error && <button onClick={materials.reload}>자료 다시 불러오기</button>}
    <div className="instructor-learning-layout">
      <div className="instructor-main-column">
        <section className="instructor-stage" aria-label="강의 영상 준비 화면">
          <div className="instructor-stage-top"><span>LERNY CLASSROOM</span><span className="instructor-stage-state">화면 미리보기</span></div>
          <div className="instructor-stage-scene">
            <div className="instructor-board">
              <span className="instructor-board-kicker">{week ? `WEEK ${String(week).padStart(2, "0")}` : "YOUR NEXT CONCEPT"}</span>
              <h2>{hasData ? "하나의 개념이,\n나의 이해가 되도록." : "강의 자료를 확인하고 있어요."}</h2>
              <div className="instructor-board-rule" />
              <div className="instructor-board-flow" aria-label="강의 구성 안내"><span><i>01</i>개념 이해</span><b aria-hidden="true">→</b><span><i>02</i>예시 연결</span><b aria-hidden="true">→</b><span><i>03</i>직접 확인</span></div>
              <p>설명에 맞춰 펼쳐지는 도표, 코드, 그리고 예시.</p>
            </div>
            <div className="instructor-figure"><div className="instructor-figure-halo" /><PersonMark /><span>강사 {String(instructor + 1).padStart(2, "0")}</span></div>
          </div>
          <div className="instructor-stage-caption"><span className="instructor-play-placeholder"><PlayMark /></span><div><strong>아직 재생할 강의 영상이 없어요.</strong><span>공개 자료를 읽거나, 궁금한 개념을 먼저 질문해 보세요.</span></div></div>
        </section>
        <div className="instructor-lecture-heading"><div><span className="instructor-week-label">{week ? `${week}주차 · 선택한 원본 자료` : "개념별 강의"}</span><h2>{selected?.title || "공개 자료로 강의를 준비해요."}</h2></div></div>
        <div className="instructor-action-bar"><div><Link className="primary instructor-study-action" to={`/quiz?section=${room.section.id}`}>오늘의 문제 풀기 <span aria-hidden="true">↗</span></Link><button className="action-secondary" onClick={() => { setSideTab("질문하기"); requestAnimationFrame(() => { const panel = document.getElementById("instructor-side-panel"); if (window.matchMedia("(max-width: 820px)").matches) panel?.scrollIntoView({ behavior: "auto", block: "start" }); panel?.querySelector<HTMLTextAreaElement>("textarea")?.focus({ preventScroll: true }); }); }}>궁금한 내용 질문하기</button></div><span>영상 시청 없이도 학습할 수 있어요.</span></div>
        <section className="instructor-details"><div className="instructor-info-tabs" aria-label="강의 부가 정보">{["관련 자료", "강의 안내"].map(tab => <button key={tab} aria-pressed={infoTab === tab} onClick={() => setInfoTab(tab)}>{tab}</button>)}</div>
          {infoTab === "강의 안내" && <div className="instructor-info-content"><h3>보고, 이해하고, 직접 풀어보세요.</h3><p>공개된 강의 자료의 핵심 개념을 AI 강사와 함께 살펴보는 공간이에요. 개념별 2~3분 강의를 목표로 준비하며, 강의 시청 없이 바로 문제를 풀어도 괜찮아요.</p><div className="instructor-info-points"><span>01 개념별 짧은 설명</span><span>02 칠판으로 보는 예시</span><span>03 문제로 이어지는 이해</span></div></div>}
          {infoTab === "관련 자료" && <div className="instructor-info-content"><h3>교수님이 공개한 원본 자료</h3>{weekSources.length ? <ResourceBrowser key={week} items={weekSources} label="관련 자료">{visible => <ul className="instructor-source-list">{visible.map(m => <li key={m.id}><span>{m.title}</span><a href={`/api/v1/materials/${m.id}/file`}>원본 받기 ↗</a></li>)}</ul>}</ResourceBrowser> : <p>공개된 자료가 등록되면 이곳에서 확인할 수 있어요.</p>}</div>}
        </section>
      </div>
      <aside id="instructor-side-panel" className="instructor-curriculum" aria-label="강의 목록과 질문"><div className="instructor-side-tabs">{["강의 목록", "질문하기"].map(tab => <button key={tab} aria-pressed={sideTab === tab} aria-controls={tab === "강의 목록" ? "instructor-list-panel" : "instructor-chat-panel"} onClick={() => setSideTab(tab)}>{tab}</button>)}</div><div id="instructor-chat-panel" className="instructor-inline-chat" hidden={sideTab !== "질문하기"}><Chat sectionId={room.section.id} /><p className="instructor-chat-note">현재 강의실 자료 기반 질문이에요. 영상 시점 연결과 음성 대화는 준비 중이에요.</p></div><div id="instructor-list-panel" hidden={sideTab !== "강의 목록"}><div className="instructor-curriculum-heading"><div><span className="student-eyebrow">YOUR LEARNING PATH</span><h2 id="instructor-curriculum-title">주차별 자료</h2></div><span>{weeks.length}개 주차</span></div>
        <p className="instructor-curriculum-note">영상이 연결되면 개념 제목·길이·시청 상태를 이곳에서 확인할 수 있어요.</p>
        {!hasData && !materials.error && <Notice>주차별 자료를 불러오는 중이에요…</Notice>}
        {hasData && !weeks.length && <div className="instructor-curriculum-empty"><PlayMark size={28} /><h3>첫 강의를 기다리고 있어요.</h3><p>교수님이 자료를 공개하면 주차별로 표시돼요.</p></div>}
        <div className="student-list-tools"><label>주차별 자료 검색<input type="search" value={sourceSearch} onChange={e => setSourceSearch(e.target.value)} placeholder="자료 이름으로 검색" /></label></div>
        {!!sourceSearch && !sources.some(m => matchesSearch(sourceSearch,m.title)) && <p className="student-list-empty">검색한 자료가 없어요.</p>}
        <div className="instructor-week-list">{weeks.filter(w => sources.some(m => m.week === w && matchesSearch(sourceSearch,m.title))).map(w => <div key={w} className={`instructor-week ${w === week && !collapsedWeeks.includes(w) ? "is-open" : ""}`}><button className="instructor-week-toggle" aria-expanded={!!sourceSearch || w === week && !collapsedWeeks.includes(w)} aria-controls={`instructor-week-${w}`} onClick={() => { if (sourceSearch) { setSourceSearch(""); select(w); setCollapsedWeeks(values => values.filter(value => value !== w)); } else if (w === week) setCollapsedWeeks(values => values.includes(w) ? values.filter(value => value !== w) : [...values, w]); else { select(w); setCollapsedWeeks(values => values.filter(value => value !== w)); } }}><span><b>{String(w).padStart(2, "0")}</b>{w}주차</span><span>{sources.filter(m => m.week === w).length}개 자료 <i aria-hidden="true">{sourceSearch || w === week && !collapsedWeeks.includes(w) ? "−" : "+"}</i></span></button>{(!!sourceSearch || w === week && !collapsedWeeks.includes(w)) && <div id={`instructor-week-${w}`} className="instructor-week-items"><PagedList key={`${w}:${selected?.id}`} items={sources.filter(m => m.week === w && matchesSearch(sourceSearch,m.title))} label={`${w}주차 목록`} resetKey={sourceSearch} initialPage={Math.max(0,Math.floor(weekSources.findIndex(m => m.id === selected?.id)/6))}>{visible => visible.map(m => <button key={m.id} aria-pressed={m.id === selected?.id} onClick={() => { select(w, m.id); setSourceSearch(""); }}><span className="instructor-item-icon"><PlayMark size={14} /></span><span><strong>{m.title}</strong><small>자료 열람 가능 · 영상 준비 전</small></span>{m.id === selected?.id && <span className="instructor-current-dot" aria-label="선택됨" />}</button>)}</PagedList></div>}</div>)}</div>
        </div>
      </aside>
    </div>
  </section>;
}
