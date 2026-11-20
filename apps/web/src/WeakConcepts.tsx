const views = [["students", "학생별 현황"], ["concepts", "개념별 현황"], ["questions", "질문 개념"]] as const;
const notes: Record<string, string> = {
  students: "학생을 선택하면 개념별 판단 근거와 제출 기록을 확인할 수 있어요.",
  concepts: "개념별로 독립 풀이와 복습이 필요한 학생을 확인하세요.",
  questions: "학생들이 질문한 개념과 분류 근거를 확인하세요.",
};
export function WeakConcepts({ view, onChange }: { view: string; onChange: (value: string) => void }) {
  return <div className="analysis-view-heading">
    <div className="prof-view-switch weak-views" role="group" aria-label="학습 분석 보기">
      {views.map(([key, label]) => <button key={key} type="button" className={view === key ? "selected" : ""}
        aria-pressed={view === key} onClick={() => onChange(key)}>{label}</button>)}
    </div>
    <p className="weak-views-note">{notes[view]}</p>
  </div>;
}
