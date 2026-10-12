/** Render only supported source locations, never raw extractor metadata. */
export function sourceLabel(locator: Record<string, unknown>) {
  if (typeof locator.page === "number") return `${locator.page}쪽`;
  if (typeof locator.slide === "number") return `슬라이드 ${locator.slide}`;
  if (typeof locator.paragraph === "number") return `${locator.paragraph}번째 문단`;
  if (typeof locator.table === "number") return `표 ${locator.table}`;
  return locator.kind === "edited_text" ? "확인·수정한 원문" : "자료 원문";
}
