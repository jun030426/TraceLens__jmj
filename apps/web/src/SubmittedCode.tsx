import { SubmittedBlankCode } from "./SubmittedBlankCode";
import { SubmittedFullCode } from "./SubmittedFullCode";

export type BlankSpan = { number: number; start: number; end: number };
export type SubmissionSnapshot = { kind: "blank"; spans: BlankSpan[] } | { kind: "full"; starter_code: string };

function CodeContent({ source, snapshot }: { source: string; snapshot?: SubmissionSnapshot | null }) {
  if (snapshot?.kind === "blank") return <SubmittedBlankCode source={source} spans={snapshot.spans} />;
  if (snapshot?.kind === "full") return <SubmittedFullCode source={source} starter={snapshot.starter_code} />;
  return source;
}

export function SubmittedCode(props: { source: string; snapshot?: SubmissionSnapshot | null }) {
  return <pre className="practice-submitted-code"><code><CodeContent {...props} /></code></pre>;
}
