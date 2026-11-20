import "./learning-text.css";

/** Text-only formatting: React escapes HTML; no HTML injection or remote content. */
export function LearningText({ text }: { text: string }) {
  return <div className="learning-text">{text.replace(/\r/g, "").split(/\n\s*\n/).map((paragraph, i) =>
    <p key={i}>{paragraph.split(/(`[^`\n]+`)/g).map((part, j) =>
      part.startsWith("`") && part.endsWith("`") ? <code key={j}>{part.slice(1, -1)}</code> : part
    )}</p>
  )}</div>;
}
