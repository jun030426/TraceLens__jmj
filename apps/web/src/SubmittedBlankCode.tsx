import { circled, type BlankTemplate } from "./visualizer/blanks";
import "./practice-blanks.css";

export function SubmittedBlankCode({ source, template }: { source: string; template: BlankTemplate }) {
  const lines = source.split("\n");
  if (lines.length !== template.lines.length) return source;

  return lines.map((line, lineIndex) => {
    const parts = template.lines[lineIndex];
    if (parts.every(part => typeof part === "string")) return line + (lineIndex < lines.length - 1 ? "\n" : "");

    let cursor = 0;
    const rendered = parts.map((part, index) => {
      if (cursor < 0) return null;
      if (typeof part === "string") {
        if (!line.startsWith(part, cursor)) { cursor = -1; return null; }
        cursor += part.length;
        return part;
      }

      const next = parts[index + 1];
      const end = typeof next !== "string" ? line.length
        : index + 1 === parts.length - 1 && line.endsWith(next)
          ? line.length - next.length
          : line.indexOf(next, cursor);
      if (end <= cursor) { cursor = -1; return null; }
      const value = line.slice(cursor, end);
      cursor = end;
      return <span key={part.blank}>
        <span className="blank-editor__num" aria-label={`빈칸 ${part.blank}`}>{circled(part.blank)}</span>
        <mark className="practice-submitted-blank">{value}</mark>
      </span>;
    });
    return <span key={lineIndex}>
      {cursor === line.length ? rendered : line}{lineIndex < lines.length - 1 ? "\n" : ""}
    </span>;
  });
}

