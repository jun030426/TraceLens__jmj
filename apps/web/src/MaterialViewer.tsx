import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import type { Classroom } from "./api";
import { ErrorNotice, Notice, useLoad } from "./components";
import "./material-viewer.css";

type Preview = {
  material_id: string; course_id: string; title: string; version_id: string;
  status: "preparing" | "ready" | "failed"; message?: string;
  pages: { number: number; width?: number; height?: number; text: string; image_url: string | null }[];
};

export function MaterialViewer() {
  const { materialId = "" } = useParams();
  return <MaterialDocument key={materialId} materialId={materialId} />;
}

function MaterialDocument({ materialId }: { materialId: string }) {
  const preview = useLoad<Preview>(`/materials/${materialId}/preview`, true);
  const rooms = useLoad<{ items: Classroom[] }>("/classrooms");
  const heading = useRef<HTMLHeadingElement>(null);
  const preparing = preview.data?.status === "preparing";
  useEffect(() => { heading.current?.focus(); }, []);
  useEffect(() => {
    if (!preparing || preview.error) return;
    const timer = setInterval(preview.reload, 5000);
    return () => clearInterval(timer);
  }, [preparing, preview.error, preview.reload]);
  const room = rooms.data?.items.find(r => r.course.id === preview.data?.course_id && r.status === "active");
  return <section className="student-home material-viewer">
    <Link className="cr-back" to={room ? `/classrooms/${room.section.id}` : "/courses"}>← 강의실로</Link>
    <header className="material-viewer-heading"><h1 ref={heading} tabIndex={-1}>{preview.data?.title || "강의자료"}</h1><p>강의자료는 이 화면에서 열람할 수 있어요.</p></header>
    <ErrorNotice text={preview.error} />
    {preview.error && <button type="button" onClick={preview.reload}>다시 불러오기</button>}
    {!preview.data && !preview.error && <Notice>강의자료를 불러오는 중이에요…</Notice>}
    {preparing && <Notice>강의자료 화면을 준비하고 있어요. 준비가 끝나면 자동으로 표시됩니다. 잠시 후에도 표시되지 않으면 다시 방문해 주세요.</Notice>}
    {preview.data?.status === "failed" && <Notice>{preview.data.message}</Notice>}
    {preview.data?.status === "ready" && <DocumentPages key={preview.data.version_id} preview={preview.data} />}
  </section>;
}

function DocumentPages({ preview }: { preview: Preview }) {
  const [index, setIndex] = useState(0);
  const [zoom, setZoom] = useState(false);
  const [failedImage, setFailedImage] = useState<string | null>(null);
  const [retry, setRetry] = useState(0);
  const page = preview.pages[index];
  if (!page) return <Notice>표시할 페이지가 없어요.</Notice>;
  const imageUrl = page.image_url ? `${page.image_url}?retry=${retry}` : "";
  return <>
    <nav className="material-viewer-toolbar" aria-label="강의자료 페이지 이동">
      <button type="button" disabled={index === 0} onClick={() => setIndex(i => i - 1)}>← 이전</button>
      <label>페이지 <select aria-label="강의자료 페이지" value={index} onChange={e => setIndex(Number(e.target.value))}>
        {preview.pages.map((p, i) => <option key={p.number} value={i}>{p.number} / {preview.pages.length}</option>)}
      </select></label>
      <button type="button" disabled={index === preview.pages.length - 1} onClick={() => setIndex(i => i + 1)}>다음 →</button>
      {page.image_url && <button type="button" aria-pressed={zoom} onClick={() => setZoom(z => !z)}>{zoom ? "화면에 맞추기" : "확대 보기"}</button>}
    </nav>
    <p className="material-viewer-page-status" role="status">{page.number} / {preview.pages.length} 페이지</p>
    {page.image_url && failedImage === imageUrl && <div><ErrorNotice text="페이지를 불러오지 못했어요. 다시 시도해 주세요." /><button type="button" onClick={() => setRetry(n => n + 1)}>페이지 다시 불러오기</button></div>}
    <figure className="material-viewer-page">
      {page.image_url ? <div className={`material-viewer-canvas${zoom ? " is-zoomed" : ""}`} tabIndex={0} role="region" aria-label={`${page.number}페이지 설명 화면`}>
        <img key={imageUrl} src={imageUrl} width={page.width} height={page.height} alt={`${preview.title} ${page.number}페이지${page.text ? ", 아래 텍스트 보기에서 내용을 읽을 수 있어요." : ""}`} onError={() => setFailedImage(imageUrl)} />
      </div> : <div className="material-viewer-text">{page.text}</div>}
      <figcaption>{preview.title} · {page.number}페이지</figcaption>
    </figure>
    {page.image_url && page.text && <details className="material-viewer-transcript" key={page.number}><summary>이 페이지 텍스트 보기</summary><div className="material-viewer-text">{page.text}</div></details>}
  </>;
}
