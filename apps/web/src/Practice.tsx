import { useContext, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Auth } from "./Auth";
import { type Classroom } from "./api";
import { ErrorNotice, Notice, useLoad } from "./components";

type Language = "Python" | "Java" | "C";
export function PracticeWorkspace() {
  const { sectionId = "" } = useParams();
  const { user } = useContext(Auth);
  const rooms = useLoad<{ items: Classroom[] }>("/classrooms");
  const room = rooms.data?.items.find(r => r.section.id === sectionId && r.status === "active");
  const language: Language = ({ python: "Python", java: "Java", c: "C" } as Record<string, Language>)[room?.course.teaching_language.toLowerCase() || ""] || "Python";
  const [drafts, setDrafts] = useState<Partial<Record<Language, string>>>({});
  const [resultTab, setResultTab] = useState("실행 결과");
  const [saved, setSaved] = useState("");
  const key = `lerny-practice-draft:${user?.id}:${sectionId}`;
  useEffect(() => {
    setDrafts({}); setSaved("");
    try {
      const value = JSON.parse(sessionStorage.getItem(key) || "{}");
      if (value && typeof value === "object" && !Array.isArray(value)) {
        setDrafts(Object.fromEntries(Object.entries(value).filter(([k, v]) => ["Python", "Java", "C"].includes(k) && typeof v === "string" && new TextEncoder().encode(v).length <= 32768)));
      }
    } catch { setSaved("이 탭에서는 초안 저장을 사용할 수 없어요."); }
  }, [key]);
  const edit = (text: string) => {
    if (new TextEncoder().encode(text).length > 32768) { setSaved("코드는 최대 32KB까지 작성할 수 있어요."); return; }
    const next = { ...drafts, [language]: text }; setDrafts(next);
    try { sessionStorage.setItem(key, JSON.stringify(next)); setSaved("이 탭에 초안 저장됨"); }
    catch { setSaved("초안을 저장하지 못했어요. 코드를 복사해 보관해 주세요."); }
  };
  return <section className="student-home practice-page">
    <Link className="practice-back" to={`/quiz?section=${sectionId}`}>← 퀴즈 목록</Link>
    <div className="practice-heading"><div><span className="student-eyebrow">LEARN BY BUILDING</span><h1>오늘의 실습</h1><p>{room?.course.title.split(/\s+[—–]\s+/)[0] || "실습"}{room ? ` · ${room.section.title}` : ""}</p></div><span className="practice-draft-note">수업에 지정된 언어로 실습을 진행해요.</span></div>
    <ErrorNotice text={rooms.error} />
    {!rooms.data ? <Notice>강의 정보를 불러오는 중이에요…</Notice> : !room ? <Notice>수강 중인 강의실을 확인해 주세요.</Notice> : <>
    <div className="practice-layout">
      <section className="practice-problem">
        <div className="practice-panel-label"><span className="student-eyebrow">PROBLEM</span><span>문제 설명</span></div>
        <div className="practice-types" aria-label="일일 실습 구성"><span>직접 구현</span><span>하루 2문제</span></div>
        <h2>개념을 코드로 연결해요.</h2><p className="practice-problem-description">문제를 읽고 수업 언어로 풀어 보세요. 실행 결과를 확인한 뒤 최종 답안을 제출할 수 있어요.</p>
        <details className="practice-problem-details"><summary>문제 조건과 입출력 예제</summary><div className="practice-problem-empty"><span aria-hidden="true">&lt;/&gt;</span><strong>배정된 문제를 기다리고 있어요.</strong><p>문제가 연결되면 조건과 입출력 예제가 이곳에 표시돼요.</p></div></details>
        <details className="practice-guide"><summary>실습은 이렇게 진행해요</summary><ol><li>문제의 조건과 예제를 확인해요.</li><li>수업 언어로 답안을 작성해요.</li><li>실행으로 확인한 뒤 최종 제출해요.</li></ol></details>
      </section>
      <div className="practice-workbench">

        <section className="practice-editor-panel" aria-labelledby="practice-editor-title">
          <div className="practice-editor-toolbar"><h2 id="practice-editor-title">코드 작성</h2><span className="practice-fixed-language">수업 언어 · {language}</span></div>
          <div className="practice-file-bar"><span>{language === "Python" ? "main.py" : language === "Java" ? "Main.java" : "main.c"}</span><span aria-live="polite">{saved || "코드 초안 · 최대 32KB"}</span></div>
          <label className="practice-code-label"><span className="practice-sr-only">{language} 코드</span><textarea spellCheck={false} autoCapitalize="none" autoComplete="off" value={drafts[language] || ""} onChange={e => edit(e.target.value)} placeholder="이곳에 코드를 작성해 보세요." /></label>
          <div className="practice-editor-actions"><span>실행은 제출로 기록되지 않아요.</span><div><button disabled>코드 실행</button><button className="primary" disabled>최종 제출 ↗</button></div></div>
        </section>

        <section className="practice-output-panel"><div className="practice-output-tabs" role="tablist" aria-label="결과 보기">{["실행 결과", "테스트", "시각화"].map(t => <button role="tab" id={`practice-tab-${t}`} aria-selected={resultTab === t} aria-controls="practice-output" key={t} onClick={() => setResultTab(t)}>{t}</button>)}</div><div id="practice-output" role="tabpanel" aria-labelledby={`practice-tab-${resultTab}`} className="practice-output-empty"><strong>{resultTab === "실행 결과" ? "실행 결과가 여기에 표시돼요." : resultTab === "테스트" ? "공개 테스트 결과를 확인하는 공간이에요." : "코드의 실행 흐름을 살펴보는 공간이에요."}</strong><p>현재 실습 문제 배정·격리 실행 기능은 연결 전이에요.</p></div></section>
      </div>
    </div><p className="practice-mobile-note">실습 코드 작성은 넓은 데스크톱 화면에서 이용하면 더 편리해요.</p></>}
  </section>;
}


export function PracticeResults() {
  const { sectionId = "" } = useParams();
  const rooms = useLoad<{ items: Classroom[] }>("/classrooms");
  const room = rooms.data?.items.find(r => r.section.id === sectionId && r.status === "active");
  const [tab, setTab] = useState("테스트 결과");
  return <section className="student-home practice-results-page">
    <Link className="practice-back" to={`/quiz?section=${sectionId}`}>← 퀴즈 목록</Link>
    <span className="student-eyebrow result-eyebrow">BUILD. CHECK. UNDERSTAND.</span>
    <h1>실습 결과와 복습</h1>
    <p className="result-intro">실행한 과정을 돌아보고, 다음 풀이의 연결고리를 찾아보세요.</p>
    <ErrorNotice text={rooms.error} />
    {!rooms.data ? <Notice>강의 정보를 불러오는 중이에요…</Notice> : !room ? <Notice>수강 중인 강의실을 확인해 주세요.</Notice> : <>
      <section className="practice-result-summary">
        <div><span className="student-eyebrow">YOUR PRACTICE</span><h2>{room.course.title.split(/\s+[—–]\s+/)[0]}</h2><p>{room.section.title} · 실습</p></div>
        <span className="practice-result-state">제출 기록 없음</span>
        <div className="practice-result-metrics"><div><span>제출한 문제</span><strong>—</strong></div><div><span>검증 완료</span><strong>—</strong></div><div><span>다시 살펴볼 문제</span><strong>—</strong></div></div>
        <p className="practice-result-policy">실행과 최종 제출은 구분돼요. 최종 제출한 답안의 검증 결과를 이곳에서 확인해요.</p>
      </section>
      <div className="practice-result-grid">
        <section className="practice-result-card"><div className="practice-result-card-heading"><span className="student-eyebrow">SUBMISSIONS</span><h2>문항별 제출 결과</h2></div><div className="practice-result-empty"><span aria-hidden="true">&lt;/&gt;</span><h3>아직 제출한 실습이 없어요.</h3><p>직접 구현 문제의 제출 상태와<br />검증 결과가 차례로 쌓이는 공간이에요.</p><Link className="ln-cta" to={`/classrooms/${sectionId}/practice`}>실습 풀이로 이동 ↗</Link></div></section>
        <section className="practice-result-card"><div className="practice-output-tabs" aria-label="제출 상세 보기">{["테스트 결과", "제출 코드", "해설"].map(t => <button key={t} aria-pressed={tab === t} onClick={() => setTab(t)}>{t}</button>)}</div><div className="practice-result-empty"><h3>{tab === "테스트 결과" ? "테스트로 풀이를 확인해요." : tab === "제출 코드" ? "제출한 코드를 다시 읽어 보세요." : "풀이의 이유를 연결해 보세요."}</h3><p>{tab === "테스트 결과" ? "제출 기록을 선택하면 공개 테스트의 입력·기대 출력·실제 출력을 확인할 수 있어요." : tab === "제출 코드" ? "언어와 함께 최종 제출한 코드가 표시되는 공간이에요." : "문항별 해설과 관련 개념을 확인하는 공간이에요."}</p><span className="practice-result-empty-note">실습 제출 기능 연결 전 · 현재 제출 기록 없음</span></div></section>
      </div>
      <div className="practice-result-bottom"><p>실행 결과를 이해하는 것도 배움의 한 과정이에요.</p><Link to={`/ai?section=${sectionId}`}>이 강의에 질문하기 ↗</Link><Link to={`/attendance?section=${sectionId}&domain=practice`}>학습 기록 보기 ↗</Link></div>
    </>}
  </section>;
}
