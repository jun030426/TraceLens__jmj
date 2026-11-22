import { circled } from "./visualizer/blanks";
import type { BlankSpan } from "./SubmittedCode";
import "./practice-blanks.css";

export function SubmittedBlankCode({ source, spans }: { source: string; spans: BlankSpan[] }) {
  const parts = [];
  let cursor = 0;
  for (const [index, span] of spans.entries()) {
    if (span.number !== index + 1 || !Number.isInteger(span.start) || !Number.isInteger(span.end)
        || span.start < cursor || span.end <= span.start || span.end > source.length) return source;
    // String.slice and the saved offsets both count UTF-16 code units.
    parts.push(source.slice(cursor, span.start), <span key={span.number}>
      <span className="blank-editor__num" aria-label={`빈칸 ${span.number}`}>{circled(span.number)}</span>
      <mark className="practice-submitted-blank">{source.slice(span.start, span.end)}</mark>
    </span>);
    cursor = span.end;
  }
  return [...parts, source.slice(cursor)];
}
