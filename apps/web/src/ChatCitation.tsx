import { Link } from "react-router-dom";
import type { Citation, Material } from "./api";
import { useLoad } from "./components";
import { citationViewUrl, sourceLabel } from "./sourceLabels";

export function useStudentHandouts(courseId: string, enabled = true) {
  const catalog = useLoad<{ items: Material[] }>(`/courses/${courseId}/materials`, false, enabled);
  return catalog.data?.items ?? [];
}

export function ChatCitation({ citation, handouts, newTab = false }: {
  citation: Citation; handouts: readonly Material[]; newTab?: boolean;
}) {
  const url = citationViewUrl(citation, handouts);
  const label = `${citation.title} · ${sourceLabel(citation.locator)}`;
  if (!url) return <span className="source-reference">{label}</span>;
  return <Link className="source-reference" to={url} target={newTab ? "_blank" : undefined}
    rel={newTab ? "noopener" : undefined} aria-label={newTab ? label + " (새 탭)" : undefined}>
    {label} <span className="go-arrow" aria-hidden="true">→</span>
  </Link>;
}
