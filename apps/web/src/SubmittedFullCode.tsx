export function SubmittedFullCode({ source, starter }: { source: string; starter: string }) {
  const starterLines = new Map<string, number>();
  for (const line of starter.replace(/\r\n/g, "\n").split("\n")) {
    const text = line.trimEnd();
    starterLines.set(text, (starterLines.get(text) ?? 0) + 1);
  }

  const groups: { written: boolean; lines: string[] }[] = [];
  for (const line of source.replace(/\r\n/g, "\n").split("\n")) {
    const text = line.trimEnd();
    const available = starterLines.get(text) ?? 0;
    const written = text.trim() !== "" && available === 0;
    if (available > 0) starterLines.set(text, available - 1);

    const group = groups.at(-1);
    if (group?.written === written) group.lines.push(line);
    else groups.push({ written, lines: [line] });
  }

  return groups.map(({ written, lines }, index) => (
    <span key={index} className={written ? "practice-written-code" : "practice-starter-code"}
      role={written ? "group" : undefined} aria-label={written ? "직접 입력한 코드" : undefined}
      tabIndex={written ? 0 : undefined} onClick={written ? event => event.currentTarget.focus() : undefined}>
      {lines.join("\n")}
    </span>
  ));
}
