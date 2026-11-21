import type { Citation, Material } from "./api";

/** Only link to a version that the student can open in the handout viewer. */
export function citationViewUrl(citation: Citation, handouts: readonly Material[]) {
  const handout = handouts.find(material => material.id === citation.material_id);
  if (!handout?.view_url || !citation.version_id || handout.version?.id !== citation.version_id) return null;
  const params = new URLSearchParams({ version_id: citation.version_id });
  const page = citation.locator.page ?? citation.locator.slide;
  if (typeof page === "number" && Number.isSafeInteger(page) && page > 0) params.set("page", String(page));
  return handout.view_url + "?" + params;
}

/** Render only supported source locations, never raw extractor metadata. */
export function sourceLabel(locator: Record<string, unknown>) {
  if (typeof locator.page === "number") return `${locator.page}쪽`;
  if (typeof locator.slide === "number") return `슬라이드 ${locator.slide}`;
  if (typeof locator.paragraph === "number") return `${locator.paragraph}번째 문단`;
  if (typeof locator.table === "number") return `표 ${locator.table}`;
  return locator.kind === "edited_text" ? "확인·수정한 원문" : "자료 원문";
}
