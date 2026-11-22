import { starterLineIndexes } from "./starterLineIndexes";
export function SubmittedFullCode({ source, starter }: { source: string; starter: string }) {
  const lines = source.split("\n");
  const matched = starterLineIndexes(lines, starter);
  const groups: { written: boolean; lines: string[] }[] = [];
  for (const [index, line] of lines.entries()) {
    const written = line.trim() !== "" && !matched.has(index);
    const group = groups.at(-1);
    if (group?.written === written) group.lines.push(line);
    else groups.push({ written, lines: [line] });
  }

  return groups.map(({ written, lines }, index) => (
    <span key={index} className={written ? "practice-written-code" : "practice-starter-code"}
      role={written ? "group" : undefined} aria-label={written ? "직접 입력한 코드" : undefined}
      tabIndex={written ? 0 : undefined} onClick={written ? event => event.currentTarget.focus() : undefined}>
      {lines.join("\n")}{index < groups.length - 1 ? "\n" : ""}
    </span>
  ));
}
