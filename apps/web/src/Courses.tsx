import { WeeklyProgress } from "./WeeklyProgress";
import { useContext, useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { Auth } from "./Auth";
import {
  api,
  post,
  type Classroom,
  type Concept,
  type Course,
  type Enrollment,
  type Section,
  type Term,
} from "./api";
import { Form, Input, Notice, ErrorNotice, field, useLoad } from "./components";
import { ExamPlans } from "./ExamPrep";
import { Materials } from "./Learning";
import { QuestionBank, Analytics } from "./Theory";

import { PagedList } from "./StudentLists";
import { matchesSearch } from "./listNavigation";

export function Dashboard() {
  const { user } = useContext(Auth);
  return user?.role === "student" ? (
    <StudentHome />
  ) : user?.role === "teacher" ? (
    <TeacherHome />
  ) : (
    <Operator />
  );
}
function StudentHome() {
  const { data, error, reload } = useLoad<{ items: Classroom[] }>(
    "/classrooms",
  );
  const [message, setMessage] = useState("");
  const [search, setSearch] = useState("");
  const [term, setTerm] = useState("");
  const terms = [...new Map((data?.items || []).map(c => [c.term.id, c.term])).values()];
  const matches = (c: Classroom) => (!term || c.term.id === term) && matchesSearch(search,c.course.title,c.section.title,c.teacher_name);
  const active = data?.items.filter((c) => c.status === "active" && matches(c)) || [];
  const waiting = data?.items.filter((c) => c.status !== "active" && matches(c)) || [];
  return (
    <div className="student-home courses-page">
      <div className="student-greeting">
        <div>
          <span className="student-eyebrow">YOUR CLASSROOMS</span>
          <h1>내 강의</h1>
          <p>우리 수업의 자료에서, 나만의 이해까지 이어가세요.</p>
        </div>
        <Link className="courses-back" to="/student">
          학생 홈으로 ↗
        </Link>
      </div>
      <ErrorNotice text={error} />
      <div className="courses-layout">
        <div className="courses-list">
          {!!data?.items.length && <div className="student-list-tools"><label>내 강의 검색<input type="search" value={search} onChange={e => setSearch(e.target.value)} placeholder="강의·분반·교수 이름" /></label><label>학기<select value={term} onChange={e => setTerm(e.target.value)}><option value="">전체 학기</option>{terms.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}</select></label></div>}
          <div className="courses-list-heading">
            <h2>수강 중인 강의</h2>
            {data && <span>{active.length}개 강의</span>}
          </div>
          {!data ? (
            <div className="student-empty" role="status">
              {error
                ? "강의를 불러오지 못했어요."
                : "내 강의를 불러오는 중이에요…"}
              {error && (
                <button
                  type="button"
                  className="courses-retry"
                  onClick={reload}
                >
                  다시 불러오기
                </button>
              )}
            </div>
          ) : active.length ? (
            <PagedList items={active} label="강의" resetKey={`${search}:${term}`}>{visible => <div className="courses-card-grid">
              {visible.map((c, i) => (
                <Link
                  to={`/classrooms/${c.section.id}`}
                  key={c.enrollment_id}
                  className={`student-course student-course-${i % 3}`}
                >
                  <div className="student-course-top">
                    <span>{c.term.name}</span>
                    <b>↗</b>
                  </div>
                  <div className="student-course-symbol" aria-hidden="true">
                    {["▤", "◇", "⌘"][i % 3]}
                  </div>
                  <h3>{c.course.title}</h3>
                  <p>{c.section.title}</p>
                  <span className="student-course-bottom">
                    강의실 들어가기 <i>→</i>
                  </span>
                </Link>
              ))}
            </div>}</PagedList>
          ) : (
            <div className="student-empty">
              <strong>{search || term ? "조건에 맞는 수강 강의가 없어요." : "아직 수강 중인 강의가 없어요."}</strong>
              <p>
                {search || term ? "검색어 또는 학기를 바꿔 전체 강의를 확인해 보세요." : "교수님이 알려주신 수강 코드를 입력하고 첫 강의에 참여해 보세요."}
              </p>
            </div>
          )}
          {waiting.length > 0 && (
            <section className="courses-waiting">
              <div className="courses-list-heading">
                <h2>승인 대기 중</h2>
                <span>{waiting.length}개 강의</span>
              </div>
              <PagedList items={waiting} label="승인 대기 강의" resetKey={`${search}:${term}`}>{visible => visible.map((c) => (
                <article key={c.enrollment_id} className="courses-waiting-card">
                  <div>
                    <span>
                      {c.term.name} · {c.section.title}
                    </span>
                    <h3>{c.course.title}</h3>
                  </div>
                  <span className="courses-status">승인 대기</span>
                </article>
              ))}</PagedList>
              <p>수강 승인이 완료되면 강의실에 들어갈 수 있어요.</p>
            </section>
          )}
        </div>
        <aside className="courses-enroll" aria-labelledby="enroll-title">
          <span className="student-eyebrow">MAKE A CONNECTION</span>
          <div className="courses-enroll-icon" aria-hidden="true">
            ＋
          </div>
          <h2 id="enroll-title">새로운 수업에 참여하기</h2>
          <p>교수님에게 받은 수강 코드를 입력해 주세요.</p>
          <Form
            label="수강 신청하기 →"
            onSubmit={async (f) => {
              setMessage("");
              await api("/enrollments", post({ join_code: field(f, "code") }));
              setMessage(
                "수강 신청을 보냈어요. 강의 목록에서 참여 상태를 확인해 주세요.",
              );
              reload();
            }}
          >
            <label>
              수강 코드
              <input
                name="code"
                placeholder="수강 코드를 입력해 주세요"
                maxLength={200}
                autoComplete="off"
                autoCapitalize="none"
                spellCheck={false}
                required
              />
            </label>
          </Form>
          {message && (
            <p className="courses-success" role="status">
              {message}
            </p>
          )}
          <div className="courses-enroll-note">
            <strong>수강 코드를 모르겠다면?</strong>
            <p>
              해당 수업의 교수님에게 문의해 주세요. 승인 대기 중인 강의는 승인
              후 이용할 수 있어요.
            </p>
          </div>
        </aside>
      </div>
      <div className="courses-bottom-note">
        <span aria-hidden="true">↗</span>
        <p>강의실에서 자료 확인, AI 질문, 퀴즈와 복습을 이어갈 수 있어요.</p>
      </div>
    </div>
  );
}
function TeacherHome() {
  const courses = useLoad<{ items: Course[] }>("/courses"),
    terms = useLoad<{ items: Term[] }>("/terms");
  const { user } = useContext(Auth);
  const [createOpen, setCreateOpen] = useState(false);
  return (
    <section className="student-home teacher-home">
      <div className="teacher-greeting"><div><span className="student-eyebrow">YOUR TEACHING SPACE</span><h1>{user?.display_name?.replace(/\s*교수(?:님)?$/, "")} 교수님, 안녕하세요.</h1><p>수업의 자료부터 학생의 이해까지, 한곳에서 연결하세요.</p></div><a href="#create-course" onClick={() => setCreateOpen(true)} className="ln-cta">새 강의 만들기 ＋</a></div>
      <div className="teacher-list-heading"><h2>담당 강의 {courses.data && <span className="teacher-course-count">{courses.data.items.length}</span>}</h2><span>강의별 수업 운영 현황을 확인하세요.</span></div>
      {!courses.data && !courses.error && <Notice>강의를 불러오는 중이에요…</Notice>}
      {courses.data?.items.length === 0 && <Notice>아직 담당 강의가 없어요. 새 강의를 만들어 수업을 시작해 보세요.</Notice>}
      <ErrorNotice text={courses.error || terms.error} />
      <div className="cards teacher-course-grid">
        {courses.data?.items.map((c) => (
          <TeacherCourseCard key={c.id} course={c} term={terms.data?.items.find(t => t.id === c.term_id)?.name} />
        ))}
      </div>
      <details className="create-course" id="create-course" open={createOpen} onToggle={e => setCreateOpen(e.currentTarget.open)}>
        <summary>새로운 수업 준비하기 <span>강의 만들기 · 학기 등록</span></summary>
        <div className="columns">
          <section className="panel">
            <h2>과목 만들기</h2>
            <Form
              label="과목 생성"
              onSubmit={async (f) => {
                await api(
                  "/courses",
                  post({
                    title: field(f, "title"),
                    term_id: field(f, "term"),
                    teaching_language: field(f, "language"),
                  }),
                );
                courses.reload();
              }}
            >
              <Input label="과목명" name="title" />
              <label>
                학기
                <select name="term" required>
                  <option value="">학기를 선택해 주세요</option>
                  {terms.data?.items.map((t) => (
                    <option key={t.id} value={t.id}>
                      {t.name}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                수업 주 언어
                <select name="language">
                  <option value="python">Python</option>
                  <option value="java">Java</option>
                  <option value="c">C</option>
                </select>
              </label>
            </Form>
          </section>
          <section className="panel">
            <h2>학기 등록</h2>
            <Form
              label="학기 등록"
              onSubmit={async (f) => {
                await api(
                  "/terms",
                  post({
                    name: field(f, "name"),
                    starts_on: field(f, "start"),
                    ends_on: field(f, "end"),
                  }),
                );
                terms.reload();
              }}
            >
              <Input label="학기 이름" name="name" />
              <Input label="시작일" name="start" type="date" />
              <Input label="종료일" name="end" type="date" />
            </Form>
          </section>
        </div>
      </details>
    </section>
  );
}
function TeacherCourseCard({ course, term }: { course: Course; term?: string }) {
  const sections = useLoad<{ items: Section[] }>(`/courses/${course.id}/sections`);
  const base = `/professor/courses/${course.id}`;
  const [title, ...subtitle] = course.title.split(/\s+[—–]\s+/);
  const language = { python: "Python", java: "Java", c: "C" }[course.teaching_language] || course.teaching_language;
  return <article className="card teacher-course-card">
    <div className="teacher-card-meta"><span>{term || "학기 확인 중"}</span><span>{language}</span></div>
    <Link className="teacher-course-title" to={base}><h2>{title}</h2><span aria-hidden="true">↗</span></Link>
    {subtitle.length > 0 && <p className="teacher-course-subtitle">{subtitle.join(" — ")}</p>}
    <div className="teacher-section-list"><span>분반 {sections.data && <b>{sections.data.items.length}</b>}</span><p>{sections.error ? "분반 정보를 불러오지 못했어요." : sections.data ? sections.data.items.length ? sections.data.items.map(s => s.title).join(" · ") : "아직 분반이 없어요." : "분반 확인 중…"}</p></div>

    <nav className="teacher-card-actions" aria-label={`${course.title} 관리`}><Link to={`${base}?tab=materials`}>자료 관리</Link><Link to={`${base}?tab=sections`}>분반·수강생</Link><Link to={`${base}?tab=analytics`}>학습 분석</Link></nav>
  </article>;
}
function Operator() {
  const [token, setToken] = useState("");
  return (
    <section>
      <span className="eyebrow">운영 담당자</span>
      <h1>교수 계정 발급</h1>
      <section className="panel narrow">
        <Form
          label="계정 발급"
          onSubmit={async (f) => {
            const r = await api<{ one_time_token: string }>(
              "/ops/teachers",
              post({
                login_id: field(f, "login_id"),
                display_name: field(f, "name"),
              }),
            );
            setToken(r.one_time_token);
          }}
        >
          <Input
            label="교수 아이디"
            name="login_id"
            minLength={3}
            maxLength={100}
          />
          <Input label="교수 이름" name="name" maxLength={100} />
        </Form>
        {token && (
          <Notice>
            24시간 안에 사용할 비밀번호 설정 토큰입니다. 교수님께 안전하게
            전달해 주세요.<code className="token">{token}</code>
            <Link to="/reset">비밀번호 설정 화면</Link>
          </Notice>
        )}
      </section>
    </section>
  );
}

export function TeacherCourse() {
  const { courseId = "" } = useParams();
  const course = useLoad<Course>("/courses/" + courseId);
  const sections = useLoad<{ items: Section[] }>(
    "/courses/" + courseId + "/sections",
  );
  const concepts = useLoad<{ items: Concept[] }>(
    "/courses/" + courseId + "/concepts",
  );
  const [analysisSection, setAnalysisSection] = useState("");
  const [params, setParams] = useSearchParams();
  const requestedTab = params.get("tab") || "overview";
  const tab = requestedTab === "held" ? "overview" : requestedTab;
  const setTab = (value: string) => setParams({ tab: value });
  if (course.error) return <ErrorNotice text={course.error} />;
  return (
    <section className="student-home teacher-course-page">
      <Link className="teacher-course-back" to="/professor">← 담당 강의</Link>
      <div className="teacher-course-heading"><div><span className="student-eyebrow">YOUR COURSE WORKSPACE</span><h1>{course.data?.title.split(/\s+[—–]\s+/)[0] || "강의 불러오는 중…"}</h1>{course.data && <p>{course.data.title.split(/\s+[—–]\s+/).slice(1).join(" — ") || "수업 운영과 학생의 학습을 한곳에서 관리하세요."}</p>}</div>{course.data && <span className="teacher-language-badge">수업 언어 · {({python: "Python", java: "Java", c: "C"}[course.data.teaching_language] || course.data.teaching_language)}</span>}</div>
      <nav className="tabs teacher-course-tabs" aria-label="강의 관리 메뉴">{[["overview","강의 개요"],["materials","강의 자료"],["analytics","학생 학습 현황"],["exams","시험 대비"],["settings","수업 설정"]].map(([id,title]) => <button key={id} className={(tab===id || id==="settings" && ["concepts","questions","sections"].includes(tab))?"selected":""} aria-current={(tab===id || id==="settings" && ["concepts","questions","sections"].includes(tab))?"page":undefined} onClick={()=>setTab(id)}>{title}</button>)}</nav>
      {["concepts","questions","sections"].includes(tab) && <button className="teacher-settings-back" onClick={()=>setTab("settings")}>← 수업 설정</button>}
      {tab === "exams" && <ExamPlans courseId={courseId} />}
      {tab === "settings" && <section className="teacher-settings-page"><div className="teacher-tab-heading"><div><h2>수업 설정</h2><p>분반 운영과 학습 콘텐츠 설정을 관리하세요.</p></div></div><div className="teacher-settings-note"><p>공개 자료를 기준으로 학습 콘텐츠가 자동 준비됩니다. 수업 운영에 필요한 항목만 변경하세요.</p><button onClick={()=>setTab("materials")}>강의 자료 관리 →</button></div><div className="teacher-settings-section"><h3>수업 운영</h3><button className="teacher-settings-row" onClick={()=>setTab("sections")}><span><strong>분반·수강생 관리</strong><small>분반 등록, 수강 코드 발급과 신청 승인을 관리하세요.</small></span><span aria-hidden="true">↗</span></button></div><div className="teacher-settings-section"><div className="teacher-settings-section-title"><h3>학습 콘텐츠 조정</h3><span>필요할 때만</span></div><p>자동으로 준비된 내용에 교수님의 수업 의도를 더하고 싶을 때 사용하세요.</p><button className="teacher-settings-row" onClick={()=>setTab("concepts")}><span><strong>분반 학습 범위</strong><small>자료 기준 자동 적용을 확인하거나, 다룬 개념을 직접 지정하세요.</small></span><span aria-hidden="true">↗</span></button><button className="teacher-settings-row" onClick={()=>setTab("questions")}><span><strong>생성 문항 관리</strong><small>준비된 문항을 확인하고, 추가 생성하거나 사용을 중지하세요.</small></span><span aria-hidden="true">↗</span></button></div></section>}

      {tab === "materials" && <Materials courseId={courseId} teacher />}
      {tab === "overview" && <TeacherCourseOverview sections={sections.data?.items} error={sections.error} setTab={setTab} />}
      {tab === "questions" && (
        <QuestionBank
          courseId={courseId}
          concepts={concepts.data?.items || []}
        />
      )}
      {tab === "analytics" && <div className="teacher-analytics-page"><div className="teacher-tab-heading"><div><h2>학생 학습 현황</h2><p>분반의 이론 퀴즈 참여와 개념별 이해도를 확인하세요.</p></div><label>분반 선택<select value={sections.data?.items.some(s => s.id === analysisSection) ? analysisSection : sections.data?.items[0]?.id || ""} onChange={e => setAnalysisSection(e.target.value)}>{sections.data?.items.map(s => <option key={s.id} value={s.id}>{s.title}</option>)}</select></label></div><ErrorNotice text={sections.error} />{!sections.data && !sections.error && <Notice>분반을 불러오는 중이에요…</Notice>}{sections.data?.items.length === 0 && <Notice>분반을 만들면 학습 현황을 확인할 수 있어요.</Notice>}{sections.data?.items.length ? <Analytics key={analysisSection || sections.data.items[0].id} sectionId={sections.data.items.some(s => s.id === analysisSection) ? analysisSection : sections.data.items[0].id} /> : null}</div>}
      {tab === "sections" && (
        <div className="teacher-sections-page">
          <div className="teacher-tab-heading"><div><h2>분반·수강생</h2><p>분반을 구성하고 수강 코드와 학생 참여 상태를 관리하세요.</p></div><span>{sections.data ? `${sections.data.items.length}개 분반` : ""}</span></div>
          {!sections.data && !sections.error && <Notice>분반을 불러오는 중이에요…</Notice>}
          {sections.data?.items.length === 0 && <Notice>아직 분반이 없어요. 첫 분반을 만들어 주세요.</Notice>}
          <ErrorNotice text={sections.error} />
          <div className="cards teacher-section-cards">
            {sections.data?.items.map((s) => (
              <SectionPanel
                key={s.id}
                section={s}
                sections={sections.data!.items}
              />
            ))}
          </div>
          <section className="panel teacher-section-add">
            <h2>분반 추가</h2>
            <Form
              label="분반 생성"
              onSubmit={async (f) => {
                await api(
                  "/courses/" + courseId + "/sections",
                  post({ title: field(f, "title") }),
                );
                sections.reload();
              }}
            >
              <Input label="분반 이름" name="title" />
            </Form>
          </section>
        </div>
      )}
      {tab === "concepts" && <TeacherLearningScope courseId={courseId} sections={sections.data?.items} concepts={concepts.data?.items} error={sections.error || concepts.error} reloadSections={sections.reload} reloadConcepts={concepts.reload} />}

    </section>
  );
}
function TeacherLearningScope({ courseId, sections, concepts, error, reloadSections, reloadConcepts }: { courseId: string; sections?: Section[]; concepts?: Concept[]; error: string; reloadSections: () => void; reloadConcepts: () => void }) {
  const [selectedSection, setSelectedSection] = useState("");
  const section = sections?.find(s => s.id === selectedSection) || sections?.[0];
  return <div className="teacher-concepts-page teacher-scope-page">
    <div className="teacher-tab-heading"><div><h2>분반 학습 범위</h2><p>분반의 자동 학습 범위를 확인하고, 필요한 경우에만 직접 조정하세요.</p></div><button type="button" onClick={() => { reloadSections(); reloadConcepts(); }}>새로고침</button></div>
    <ErrorNotice text={error} />
    {!sections || !concepts ? !error && <Notice>학습 범위를 불러오는 중이에요…</Notice> : <>
      <div className="teacher-scope-layout"><section className="panel teacher-scope-main">
        <div className="teacher-scope-step"><span>01</span><div><h3>분반 선택</h3><p>범위를 적용할 분반을 선택하세요.</p></div></div>
        {sections.length ? <div className="teacher-scope-sections">{sections.map(s => <button type="button" key={s.id} aria-pressed={s.id === section?.id} onClick={() => setSelectedSection(s.id)}>{s.title}<small>{s.progress.length}개 개념 적용 중</small></button>)}</div> : <Notice>분반·수강생에서 분반을 먼저 만들어 주세요.</Notice>}
        {section && <WeeklyProgress key={section.id} sectionId={section.id} reload={reloadSections} />}
        {section && <details key={section.id + ":" + section.revision} className="teacher-manual-scope"><summary><span>고급 설정 · 전체 개념 직접 지정</span><small>{section.progress_mode === "manual" ? "직접 지정한 범위 사용 중" : "필요할 때만 변경하세요"}</small></summary><p>저장하면 이 분반은 수동 설정으로 전환됩니다. 이후 공개되는 자료의 개념은 자동으로 추가되지 않아요.</p><ScopeEditor key={section.id + ":" + section.revision} section={section} concepts={concepts} reload={reloadSections} /></details>}
      </section><details className="teacher-scope-guide"><summary>학습 범위는 어떻게 적용되나요?</summary><p>자동 진행은 현재 주차까지 공개된 자료의 개념을 포함합니다.</p><p>진도가 달라졌다면 배운 주차와 마지막 개념을 지정하세요. 직접 지정한 범위는 자동 진행으로 복귀할 때까지 유지됩니다.</p><div>학생의 이론 퀴즈에 적용됩니다. 실습 범위와 실제 성적에는 적용되지 않습니다.</div></details></div>
      <details className="teacher-concept-library" open={undefined}><summary><span>학습 개념 관리 <small>{concepts.length}개 등록</small></span><span>개념 확인·추가</span></summary><p className="teacher-panel-description">수업에 필요한 개념이 없을 때 추가하세요. 자료에서 추출한 개념도 이곳에 표시됩니다. 직접 등록한 개념은 분반 학습 범위에 지정해 사용할 수 있어요.</p><div className="teacher-concept-library-layout"><div>{concepts.length ? concepts.map(c => <div className="teacher-concept-item" key={c.id}><strong>{c.name}</strong><p>{c.description || "등록된 설명이 없어요."}</p></div>) : <Notice>첫 학습 개념을 추가해 주세요.</Notice>}</div><Form label="개념 추가" onSubmit={async f => { await api(`/courses/${courseId}/concepts`, post({name:field(f,"name"),description:field(f,"description")})); reloadConcepts(); }}><h3>새 개념 추가</h3><Input label="개념 이름" name="name" /><label>설명<textarea name="description" maxLength={2000} rows={3} /></label></Form></div></details>
    </>}
  </div>;
}
function ScopeEditor({ section, concepts, reload }: { section: Section; concepts: Concept[]; reload: () => void }) {
  const [selected, setSelected] = useState<string[]>(section.progress);
  const [baseline, setBaseline] = useState(section.progress);
  const [revision, setRevision] = useState(section.revision);
  const [search, setSearch] = useState("");
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const changed = selected.length !== baseline.length || selected.some(id => !baseline.includes(id));
  const filtered = concepts.filter(c => `${c.name} ${c.description}`.toLowerCase().includes(search.toLowerCase()));
  const save = async () => {
    setSaving(true); setError(""); setMessage("");
    try { const saved = await api<{revision: number}>(`/sections/${section.id}/progress`, {method:"PUT",headers:{"If-Match":String(revision)},body:JSON.stringify({concept_ids:selected,mode:"manual"})}); setRevision(saved.revision); setBaseline(selected); setMessage("학습 범위를 저장했어요."); }
    catch(e) { setError((e as Error).message); }
    finally { setSaving(false); }
  };
  return <div className="teacher-scope-editor"><div className="teacher-scope-step"><span>02</span><div><h3>배운 개념 선택</h3><p>오늘까지 수업에서 다룬 개념을 선택하세요.</p></div></div><label className="teacher-scope-search">개념 찾기<input value={search} onChange={e => setSearch(e.target.value)} placeholder="개념 이름 또는 설명 검색" /></label><div className="teacher-scope-options">{filtered.map(c => <label className={selected.includes(c.id) ? "is-selected" : ""} key={c.id}><input type="checkbox" checked={selected.includes(c.id)} disabled={saving} onChange={e => { setSelected(e.target.checked ? [...selected,c.id] : selected.filter(id => id !== c.id)); setMessage(""); }} /><span><strong>{c.name}</strong><small>{c.description || "등록된 설명이 없어요."}</small></span></label>)}{!filtered.length && <p className="teacher-panel-description">{concepts.length ? "검색 결과가 없어요." : "아래 학습 개념 관리에서 개념을 먼저 추가해 주세요."}</p>}</div><ErrorNotice text={error} />{message && <p className="teacher-scope-saved" role="status">{message}</p>}<div className="teacher-scope-save"><div><strong>{selected.length}개 개념 선택</strong><span>{selected.length ? `${section.title}의 이론 퀴즈 범위` : "선택하지 않으면 오늘의 이론 퀴즈가 제공되지 않아요."}</span></div><button type="button" className="primary" disabled={saving || !changed || !!message} onClick={() => void save()}>{saving ? "저장 중…" : "학습 범위 저장"}</button></div>{message && <button className="teacher-scope-refresh" onClick={reload}>저장된 범위 확인 →</button>}</div>;
}
function TeacherCourseOverview({ sections, error, setTab }: { sections?: Section[]; error: string; setTab: (tab: string) => void }) {
  const [rosters, setRosters] = useState<Record<string, Enrollment[]> | null>(null);
  const [rosterError, setRosterError] = useState("");
  useEffect(() => {
    let active = true;
    setRosters(null); setRosterError("");
    if (sections) Promise.all(sections.map(async s => [s.id, (await api<{items: Enrollment[]}>(`/sections/${s.id}/enrollments`)).items] as const))
      .then(rows => { if (active) setRosters(Object.fromEntries(rows)); })
      .catch(() => { if (active) setRosterError("수강 현황을 불러오지 못했어요. 분반·수강생에서 다시 확인해 주세요."); });
    return () => { active = false; };
  }, [sections]);
  const pending = rosters ? Object.values(rosters).flat().filter(e => e.status === "pending").length : null;
  return <div className="teacher-course-overview">
    <ErrorNotice text={error || rosterError} />
    <div className="teacher-approval-note"><div><strong>수강 신청</strong><span>{pending === null ? rosterError ? "현황을 확인하지 못했어요." : "확인 중…" : pending ? `${pending}명이 승인을 기다리고 있어요.` : "승인을 기다리는 학생이 없어요."}</span></div><button onClick={() => setTab("sections")}>수강생 관리 →</button></div>
    <div className="teacher-work-heading"><h2>분반별 학습 현황</h2><button className="teacher-text-action" onClick={() => setTab("analytics")}>자세히 보기 →</button></div>
    <p className="teacher-learning-description">이론 퀴즈 참여와 개념별 정답률을 살펴보고, 다음 수업에서 짚어줄 내용을 확인하세요.</p>
    <div className="teacher-learning-grid">{sections?.map(s => <TeacherSectionLearning key={s.id} section={s} />)}</div>
    <div className="teacher-work-heading"><h2>분반별 현황 <span className="teacher-course-count">{sections ? sections.length : "—"}</span></h2><button className="teacher-text-action" onClick={() => setTab("sections")}>분반 관리 →</button></div>
    <div className="teacher-section-table">{!sections ? <p className="teacher-section-empty">{error ? "분반을 불러오지 못했어요." : "분반 확인 중…"}</p> : !sections.length ? <p className="teacher-section-empty">아직 분반이 없어요. 분반 관리에서 첫 분반을 만들어 주세요.</p> : <><div className="teacher-section-row teacher-section-labels"><span>분반</span><span>수강 중</span><span>승인 대기</span><span>진도 설정</span></div>{sections.map(s => <div className="teacher-section-row" key={s.id}><strong>{s.title}</strong><span>{rosters ? `${rosters[s.id]?.filter(e => e.status === "active").length ?? 0}명` : "—"}</span><span>{rosters ? `${rosters[s.id]?.filter(e => e.status === "pending").length ?? 0}명` : "—"}</span><button onClick={() => setTab("concepts")}>{s.progress.length}개 개념 <span aria-hidden="true">→</span></button></div>)}</>}</div>
    <div className="teacher-work-heading"><h2>자주 쓰는 관리</h2></div>
    <div className="teacher-quick-links">{[["materials", "강의 자료", "자료 등록·공개 관리"], ["sections", "수강생 관리", "수강 승인·분반 관리"], ["concepts", "수업 진도", "자동 진행 확인·실제 진도 조정"]].map(([id,title,desc]) => <button key={id} onClick={() => setTab(id)}><strong>{title}</strong><span>{desc}</span><i aria-hidden="true">↗</i></button>)}</div>
  </div>;
}
function TeacherSectionLearning({ section }: { section: Section }) {
  const stats = useLoad<{summary: {participation: number; accuracy: number | null}; concepts: {id: string; name: string; valid: number; accuracy: number | null}[]}>(`/sections/${section.id}/analytics`);
  const review = stats.data?.concepts.filter(c => c.valid > 0 && c.accuracy !== null && c.accuracy < 70).sort((a,b) => a.accuracy! - b.accuracy!).slice(0,3) || [];
  return <article className="teacher-learning-card"><h3>{section.title}</h3><ErrorNotice text={stats.error} /><div className="teacher-learning-metrics"><div><span>제출 답안</span><strong>{stats.data ? stats.data.summary.participation : "—"}<small>건</small></strong></div><div><span>정답률</span><strong>{stats.data ? stats.data.summary.accuracy ?? "—" : "—"}<small>%</small></strong></div></div><div className="teacher-concept-review"><span>다시 살펴볼 개념 <small>정답률 70% 미만</small></span>{!stats.data ? <p>{stats.error ? "학습 데이터를 확인하지 못했어요." : "학습 현황 확인 중…"}</p> : review.length ? <ul>{review.map(c => <li key={c.id}><span>{c.name}</span><b>{c.accuracy}%</b></li>)}</ul> : <p>{stats.data.concepts.some(c => c.valid > 0) ? "현재 기준에 해당하는 개념이 없어요." : "학습 기록이 쌓이면 개념별 현황을 보여드려요."}</p>}</div></article>;
}
function SectionPanel({
  section,
  sections,
}: {
  section: Section;
  sections: Section[];
}) {
  const [code, setCode] = useState(""),
    [error, setError] = useState("");
  const roster = useLoad<{ items: Enrollment[] }>(
    "/sections/" + section.id + "/enrollments",
  );
  const action = async (fn: () => Promise<unknown>) => {
    setError("");
    try {
      await fn();
      roster.reload();
    } catch (e) {
      setError((e as Error).message);
    }
  };
  return (
    <section className="card teacher-section-panel">
      <div className="teacher-section-panel-heading"><h2>{section.title}</h2><span>{roster.data ? `${roster.data.items.filter(e => e.status === "active").length}명 수강 중` : "현황 확인 중"}</span></div>
      <details className="teacher-join-settings"><summary>수강 코드 발급·입장 설정</summary><p>새 코드를 발급하면 기존 코드는 만료됩니다.</p>
      <Form
        label="새 수강 코드 발급"
        onSubmit={async (f) => {
          const r = await api<{ join_code: string }>(
            "/sections/" + section.id + "/join-code",
            post({ approval_required: f.has("approval") }),
          );
          setCode(r.join_code);
        }}
      >
        <label className="check">
          <input type="checkbox" name="approval" />
          교수 승인 후 입장
        </label>
      </Form>
      {code && (
        <Notice>
          새 코드 발급 시 기존 코드는 만료됩니다.
          <code className="token">{code}</code>
        </Notice>
      )}
      </details>
      <div className="teacher-roster-heading"><h3>수강생</h3><button type="button" onClick={roster.reload}>새로고침</button></div>
      <ErrorNotice text={error || roster.error} />
      {!roster.data && !roster.error && <Notice>수강생을 불러오는 중이에요…</Notice>}
      {roster.data?.items.length === 0 && <div className="teacher-roster-empty">아직 참여한 학생이 없어요. 수강 코드를 학생들에게 안내해 주세요.</div>}
      {roster.data?.items.map((e) => (
        <div className="roster" key={e.id}>
          <strong>{e.display_name}</strong>
          <span>
            {e.status === "active"
              ? "수강 중"
              : e.status === "pending"
                ? "승인 대기"
                : e.status === "transferred"
                  ? "분반 이동"
                  : "수강 취소"}
          </span>
          {e.status === "pending" && (
            <button
              className="primary"
              onClick={() =>
                void action(() =>
                  api("/enrollments/" + e.id + "/approve", post({})),
                )
              }
            >
              승인
            </button>
          )}
          {e.status === "active" && sections.length > 1 && (
            <Form
              label="분반 이동"
              actionRole="secondary"
              onSubmit={async (f) => {
                await action(() =>
                  api(
                    "/enrollments/" + e.id + "/transfer",
                    post({ target_section_id: field(f, "target") }),
                  ),
                );
              }}
            >
              <label>
                이동할 분반
                <select name="target">
                  {sections
                    .filter((s) => s.id !== section.id)
                    .map((s) => (
                      <option key={s.id} value={s.id}>
                        {s.title}
                      </option>
                    ))}
                </select>
              </label>
            </Form>
          )}
        </div>
      ))}
    </section>
  );
}
export function StudentClass() {
  const { sectionId = "" } = useParams();
  const rooms = useLoad<{ items: Classroom[] }>("/classrooms");
  const room = rooms.data?.items.find(
    (r) => r.section.id === sectionId && r.status === "active",
  );
  if (rooms.error) return <ErrorNotice text={rooms.error} />;
  if (!rooms.data) return <Notice>강의실을 불러오는 중…</Notice>;
  if (!room)
    return (
      <Notice>
        수강 중인 강의실이 아니에요. <Link to="/courses">내 강의실로</Link>
      </Notice>
    );
  return (
    <div className="student-home classroom-page">
      <Link to="/courses" className="classroom-back">
        ← 내 강의
      </Link>
      <section className="classroom-intro">
        <div>
          <span className="student-eyebrow">YOUR CLASSROOM</span>
          <p className="classroom-meta">
            {room.term.name} · {room.teacher_name} · {room.section.title}
          </p>
          <h1>{room.course.title}</h1>
          <p className="classroom-description">
            자료에서 시작해 질문하고, 오늘 배운 내용을 나의 이해로 연결하세요.
          </p>
        </div>
        <div className="classroom-emblem" aria-hidden="true">
          ▤
        </div>
      </section>
      <Link className="classroom-exam-link" to={`/exam-prep?course=${room.course.id}`}>시험 대비 · 공개된 시험 범위와 연습문제 확인 →</Link>
      <Link className="instructor-classroom-entry" to={`/classrooms/${sectionId}/lectures`}><span><small>MEET YOUR AI INSTRUCTOR</small><strong>개념 하나씩, AI 강사와 함께.</strong><span>주차별 강의 자료와 연결된 짧은 강의를 만나보세요.</span></span><span>AI 강의 보기 ↗</span></Link>
      <section className="classroom-actions" aria-label="강의실 학습 바로가기">
        {[
          {
            url: `/ai?section=${sectionId}`,
            label: "AI 질문",
            desc: "궁금했던 개념을 자료의 근거와 함께 확인해요.",
            symbol: "?",
            tag: "ASK",
          },
          {
            url: `/quiz?section=${sectionId}`,
            label: "퀴즈와 복습",
            desc: "오늘의 문항을 풀고, 지난 결과를 다시 살펴보세요.",
            symbol: "✓",
            tag: "PRACTICE",
          },
          {
            url: `/attendance?section=${sectionId}`,
            label: "내 학습 기록",
            desc: "개념별 학습 현황과 복습할 내용을 확인해요.",
            symbol: "↗",
            tag: "REFLECT",
          },
        ].map((item, i) => (
          <Link
            to={item.url}
            key={item.tag}
            className={`classroom-action classroom-action-${i}`}
          >
            <div>
              <span className="student-eyebrow">
                0{i + 1} / {item.tag}
              </span>
              <span className="classroom-action-arrow">↗</span>
            </div>
            <span className="classroom-action-icon" aria-hidden="true">
              {item.symbol}
            </span>
            <h2>{item.label}</h2>
            <p>{item.desc}</p>
          </Link>
        ))}
      </section>
      <section className="classroom-materials">
        <div className="classroom-materials-intro">
          <span className="student-eyebrow">START WITH THE SOURCE</span>
          <p>교수님이 공유한 자료를 확인하고, 수업의 맥락 안에서 학습하세요.</p>
        </div>
        <Materials key={room.section.id} courseId={room.course.id} currentWeek={room.current_week} />
      </section>
      <p className="classroom-bottom">
        하나의 수업, 이어지는 학습. 궁금한 순간에는 언제든 질문으로 돌아오세요.
      </p>
    </div>
  );
}
