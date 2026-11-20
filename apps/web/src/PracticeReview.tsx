import { useEffect, useRef } from "react";
import { ErrorNotice, useLoad } from "./components";
import { LearningText } from "./LearningText";
import { lineComment } from "./visualization/screen/lineComment";
import "./practice-learning.css";

export type PracticeExplanation = {
  title: string; kind: string; language: string; description: string; requirements: string[];
  reference: string; blanks: string[]; example_input: string; expected: string;
};
export const practiceKindLabel = (kind?: string) => kind === "full" ? "풀코딩" : "빈칸 채우기";

export function PracticeExplanationView({ value, focusOnOpen = false }: { value: PracticeExplanation; focusOnOpen?: boolean }) {
  const panel = useRef<HTMLElement>(null);
  useEffect(() => {
    if (!focusOnOpen) return;
    panel.current?.focus({ preventScroll: true });
    panel.current?.scrollIntoView({ block: "nearest" });
  }, [focusOnOpen]);
  const lines = value.reference.split("\n").flatMap((code, i) => {
    const text = lineComment(code);
    return text ? [{ line: i + 1, code, text }] : [];
  });
  return <section ref={panel} tabIndex={-1} className="practice-explanation" aria-label="답지와 해설">
    <h3>{practiceKindLabel(value.kind)} · 답지와 해설</h3>
    <LearningText text={value.description} />
    <h4>문제 조건</h4><ul>{value.requirements.map((r, i) => <li key={i}>{r}</li>)}</ul>
    {!!value.blanks.length && <><h4>빈칸별 답</h4><ol className="practice-blank-answers">{value.blanks.map((answer, i) => <li key={i}><span>빈칸 {i + 1}</span><pre><code>{answer}</code></pre></li>)}</ol></>}
    <h4>모범 코드</h4><pre><code>{value.reference}</code></pre>
    {!!lines.length && <details><summary>코드 줄별 설명</summary><ol className="practice-code-notes">{lines.map(item => <li key={item.line}><b>{item.line}번째 줄</b><code>{item.code.trim()}</code><p>{item.text}</p></li>)}</ol></details>}
    <div className="practice-example"><div><h4>예시 입력 선언</h4><pre><code>{value.example_input}</code></pre></div><div><h4>예시 출력</h4><pre><code>{value.expected || "(출력 없음)"}</code></pre></div></div>
    <p className="muted">제출 코드와 모범 코드를 비교하고, 입력이 달라질 때도 같은 처리 순서가 적용되는지 확인해 보세요. 최종 채점은 여러 입력으로 검증해요.</p>
  </section>;
}

export function PracticeAttemptReview({ sectionId, attemptId }: { sectionId: string; attemptId: string }) {
  const review = useLoad<PracticeExplanation>(`/sections/${sectionId}/practice/attempts/${attemptId}/explanation`);
  if (review.error) return <><ErrorNotice text={review.error} /><button type="button" onClick={review.reload}>해설 다시 불러오기</button></>;
  return review.data ? <PracticeExplanationView value={review.data} /> : <p role="status">제출한 실습의 해설을 불러오는 중이에요…</p>;
}
