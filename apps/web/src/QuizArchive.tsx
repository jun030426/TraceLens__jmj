import { Link, useParams } from "react-router-dom";
import { ErrorNotice, Notice, useLoad } from "./components";
import "./quiz-archive.css";

type Week = { week: number; theory: boolean; practice: number };
type Archive = { course_title: string; section_title: string; current_week: number; weeks: Week[] };
type Day = { index: number; date: string | null; session_id: string | null; total: number; submitted: number };

export const archivePath = (sectionId: string, week?: string | number) =>
  `/quiz/${encodeURIComponent(sectionId)}/archive${week == null ? "" : "/" + week}`;

export function QuizArchive({ theory = false }: { theory?: boolean }) {
  const { sectionId = "", week } = useParams();
  const base = archivePath(sectionId);
  const archive = useLoad<Archive>(`/sections/${sectionId}/quiz-archive`);
  const selected = archive.data?.weeks?.find(w => String(w.week) === week);
  const title = week ? `${week}주차 ${theory ? "개념 퀴즈" : "퀴즈"}` : "이전 퀴즈";
  const parent = theory ? archivePath(sectionId, week) : week ? base : `/quiz?section=${sectionId}`;
  return <section className="student-home quiz-catalog quiz-archive-page">
    <Link className="cr-back" to={parent}>← {theory ? `${week}주차 퀴즈` : week ? "주차 목록" : "퀴즈 목록"}</Link>
    <div className="quiz-titlebar"><h1>{title}</h1>
      {archive.data && <p className="quiz-course-meta">{archive.data.course_title} · {archive.data.section_title}</p>}
    </div>
    <ErrorNotice text={archive.error} />
    {archive.error && <button onClick={archive.reload}>다시 불러오기</button>}
    {!archive.data && !archive.error && <Notice>퀴즈 목록을 불러오는 중이에요.</Notice>}
    {archive.data && (!week ? <nav className="qa-week-grid" aria-label="퀴즈 주차">
      {archive.data.weeks?.map(w => {
        const current = w.week === archive.data!.current_week;
        const ready = w.theory || w.practice > 0;
        const contents = <><strong>{w.week}주차</strong>
          <small>{current && <b className="qa-current">이번 주</b>}{ready ? "퀴즈 보기 →" : "준비 전"}</small></>;
        return ready
          ? <Link key={w.week} className="qa-week" aria-current={current ? "date" : undefined} to={archivePath(sectionId, w.week)}>{contents}</Link>
          : <div key={w.week} className="qa-week qa-unavailable" aria-current={current ? "date" : undefined}>{contents}</div>;
      })}
    </nav> : !selected ? <Notice>주차 목록에서 1~15주차 중 하나를 선택해 주세요.</Notice>
      : theory ? <ArchiveDays key={sectionId + week} sectionId={sectionId} week={week} />
      : <div className="quiz-mode-grid" role="group" aria-label="퀴즈 종류">
        {([{ label: "개념 퀴즈", description: "날짜별로 풀기", ready: selected.theory, url: base + "/" + week + "/theory" },
           { label: "실습 퀴즈", description: "주차 문제 한 번에 보기", ready: selected.practice > 0, url: `/classrooms/${sectionId}/practice?week=${week}` }]).map(card => {
          const content = <><div className="quiz-mode-top"><span className="quiz-mode-tag">{card.label}</span>
            {card.ready && <span className="quiz-mode-arrow go-arrow" aria-hidden="true">→</span>}</div>
            <h4>{card.description}</h4>{!card.ready && <small>준비 전</small>}</>;
          return card.ready ? <Link key={card.label} className="quiz-mode-card" to={card.url}>{content}</Link>
            : <div key={card.label} className="quiz-mode-card qa-unavailable">{content}</div>;
        })}
      </div>)}
  </section>;
}

function ArchiveDays({ sectionId, week }: { sectionId: string; week: string }) {
  const days = useLoad<{ days: Day[] }>(`/sections/${sectionId}/quiz-archive/${week}/days`);
  return <><ErrorNotice text={days.error} />
    {days.error && <button onClick={days.reload}>다시 불러오기</button>}
    {!days.data && !days.error && <Notice>날짜별 문항을 불러오는 중이에요.</Notice>}
    <nav className="qa-days" aria-label="개념 퀴즈 날짜">{days.data?.days?.map(d => {
      const done = d.total > 0 && d.submitted >= d.total;
      const status = !d.total ? "준비 전" : done ? "✓ 완료" : d.submitted ? `${d.submitted}/${d.total}문제 풀이` : "시작 전";
      const content = <><span><strong>{d.index}일차</strong>{d.date && <time dateTime={d.date}>{d.date.replaceAll("-", ". ")}</time>}</span>
        <span className={done ? "qa-done" : ""}>{status}{!!d.total && <b aria-hidden="true"> →</b>}</span></>;
      const key = d.session_id || d.index;
      return d.total ? <Link key={key} className="qa-day" to={`${archivePath(sectionId, week)}/theory/${d.index}${d.session_id ? "?session=" + d.session_id : ""}`}>{content}</Link>
        : <div key={key} className="qa-day qa-unavailable">{content}</div>;
    })}</nav></>;
}
