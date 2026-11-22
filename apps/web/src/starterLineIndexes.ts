// Match the longest sequence shared by the starter and submission without reordering lines.
export function starterLineIndexes(lines: string[], starter: string): Set<number> {
  const original = starter.split("\n").map(line => line.trimEnd()).filter(Boolean);
  const submitted = lines.map((line, index) => ({ text: line.trimEnd(), index })).filter(line => line.text);
  const widths = original.length + 1;
  const scores = new Uint16Array((submitted.length + 1) * widths);
  for (let i = submitted.length - 1; i >= 0; i--) {
    for (let j = original.length - 1; j >= 0; j--) {
      const pos = i * widths + j;
      scores[pos] = submitted[i].text === original[j] ? 1 + scores[pos + widths + 1]
        : Math.max(scores[pos + widths], scores[pos + 1]);
    }
  }
  const matched = new Set<number>();
  let i = 0, j = 0;
  while (i < submitted.length && j < original.length) {
    const pos = i * widths + j;
    if (submitted[i].text === original[j]) {
      matched.add(submitted[i].index);
      i++;
      j++;
    } else if (scores[pos + widths] >= scores[pos + 1]) i++;
    else j++;
  }
  return matched;
}
