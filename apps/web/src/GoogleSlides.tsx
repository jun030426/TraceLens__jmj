import { useEffect, useState } from "react";
import { api, post } from "./api";
import { ErrorNotice, useLoad } from "./components";

type Connection = { configured: boolean; connected: boolean; rendering_enabled: boolean };
type Deck = { id: string; status: string; error_code: string | null; presentation_url: string | null;
  plan_ready: boolean; review_token: string | null; poster_url?: string | null; slides: { heading: string; script: string; preview_url: string }[] };
type Item = { video_id: string; title: string; slides: Deck | null };
const labels: Record<string, string> = { queued: "슬라이드 준비 대기", running: "슬라이드 준비 중",
  waiting_google: "Google 연결 대기", waiting_ai: "AI 연결 대기", failed: "확인 필요",
  review_required: "설명 화면 검토 필요", approved: "설명 화면 검토 완료" };
const errors: Record<string, string> = {
  GOOGLE_SLIDES_SETUP_REQUIRED: "운영자의 Google 연결 설정이 필요해요.",
  GOOGLE_SLIDES_CONNECT_REQUIRED: "Lerny 공용 슬라이드 연결이 필요해요. 운영자가 연결 상태를 확인하고 있어요.",
  GOOGLE_SLIDES_RECONNECT_REQUIRED: "Lerny 공용 Google 연결이 만료됐어요. 운영자가 다시 연결해야 해요.",
  GOOGLE_SLIDES_ACCESS_REQUIRED: "Google Slides·Drive API와 파일 접근 권한을 확인해 주세요.",
  GOOGLE_SLIDES_UNAVAILABLE: "Google에 연결하지 못했어요. 잠시 후 이어서 준비해 주세요.",
  GOOGLE_SLIDES_CREATION_UNCERTAIN: "파일 생성 접수 여부를 확인 중이에요. 중복 생성을 막기 위해 멈췄어요.",
  GOOGLE_SLIDES_CHANGED_REVIEW_REQUIRED: "Google에서 편집한 내용이 있어요. 수정본을 다시 가져와 검토해 주세요.",
  GOOGLE_SLIDES_SCRIPT_MISMATCH: "슬라이드 순서나 발표자 노트가 대본과 달라요. Google에서 대본과 맞춰 주세요.",
  SLIDES_CONTENT_REVIEW_REQUIRED: "대본과 설명 내용이 맞는지 추가 검토가 필요해요.",
  SLIDES_LAYOUT_REVIEW_REQUIRED: "설명 화면의 글자 분량이나 구성을 추가 검토해야 해요.",
  SLIDES_SCRIPT_CHANGED: "대본이 변경됐어요. 현재 대본의 슬라이드를 준비해 주세요.",
  POSTER_TEXT_OVERFLOW: "썸네일에 담기에는 제목이나 요약이 길어요. 설명 구성안을 확인해 주세요.",
  POSTER_REVIEW_REQUIRED: "썸네일 준비와 검토가 필요해요.",
  POSTER_CHANGED_REVIEW_REQUIRED: "저장된 썸네일이 검토본과 달라요. 다시 확인해 주세요.",
  SOURCE_REVOKED: "원본 자료의 사용 상태가 변경됐어요.",
};

export function GoogleSlidesConnection() {
  const status = useLoad<Connection>("/google-slides/connection", true);
  useEffect(() => {
    const refresh = () => status.reload();
    window.addEventListener("focus", refresh);
    return () => window.removeEventListener("focus", refresh);
  }, [status.reload]);
  return <details className="google-slides-connection">
    <summary>설명 슬라이드 자동 구성 · {status.data?.connected ? "공용 연동 준비 완료" : "운영 연결 확인 중"}</summary>
    <p>Lerny 공용 Google 슬라이드 연동으로 대본 구간에 맞는 설명 화면을 만들고 영상 장면에 연결해요. 교수자별 Google 로그인은 필요하지 않아요.</p>
    <p>베이지·브라운 공통 디자인으로 썸네일과 핵심 설명·코드·비교 화면을 구성해요. 완성된 영상과 자료의 학생 공개 여부는 교수자가 결정해요.</p>
    {status.data && !status.data.rendering_enabled && <p>새 영상 제작은 크레딧 충전 후 재개할 때까지 중지 중이에요.</p>}
    <ErrorNotice text={status.error} />
    <button type="button" onClick={status.reload}>연동 상태 확인</button>
  </details>;
}

export function TeachingSlides({ courseId, generationId }: { courseId: string; generationId: string }) {
  const path = `/courses/${courseId}/content-generations/${generationId}/lecture-slides`;
  const data = useLoad<{ items: Item[] }>(path, true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [checked, setChecked] = useState<Record<string, string>>({});
  useEffect(() => {
    const timer = window.setInterval(() => { if (!document.hidden) data.reload(); }, 15000);
    return () => window.clearInterval(timer);
  }, [data.reload]);
  const run = async (fn: () => Promise<unknown>) => {
    if (busy) return; setBusy(true); setError("");
    try { await fn(); data.reload(); } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };
  return <section className="teaching-slides" aria-label="대본별 Google 설명 슬라이드">
    <h4>대본별 설명 슬라이드</h4>
    <p>현재 대본으로 썸네일과 설명 화면을 준비해요. 기존 영상은 보존하며 새 영상은 제작하지 않아요.</p>
    <ErrorNotice text={error || data.error} />{message && <p role="status">{message}</p>}
    <div className="weekly-content-actions"><button type="button" disabled={busy} onClick={() => run(async () => {
      const result = await api<{ count: number }>(path, post({}));
      setMessage(`${result.count}개 대본의 슬라이드 준비를 요청했어요. 완료된 구성안과 파일은 재사용해요.`);
    })}>슬라이드 준비·이어서 진행</button><button type="button" onClick={data.reload}>상태 새로고침</button></div>
    {data.data?.items.map(item => {
      const deck = item.slides;
      return <details key={item.video_id} className="teaching-slide-deck"><summary>{item.title} · {deck ? labels[deck.status] || deck.status : "슬라이드 준비 전"}</summary>
        {deck?.error_code && <p role="status">{errors[deck.error_code] || `슬라이드 준비를 완료하지 못했어요. (${deck.error_code})`}</p>}
        {deck?.plan_ready && !deck.slides.length && <p>설명 구성안 저장 완료 · Google 파일 준비 대기</p>}
        {deck?.presentation_url && <a href={deck.presentation_url} target="_blank" rel="noreferrer">Google 슬라이드에서 확인·편집 ↗</a>}
        {deck?.poster_url && <figure className="teaching-slide-previews"><img src={deck.poster_url} alt={`${item.title} 재생 전 썸네일`} loading="lazy" /><figcaption>재생 전 썸네일</figcaption></figure>}
        {!!deck?.slides.length && <ol className="teaching-slide-previews">{deck.slides.map((slide, i) => <li key={slide.preview_url}>
          <strong>{i + 1}. {slide.heading}</strong><img src={slide.preview_url} alt={`${item.title} 설명 화면 ${i + 1}`} loading="lazy" />
          <p><strong>이 화면의 대본</strong></p><blockquote>{slide.script}</blockquote>
        </li>)}</ol>}
        {deck?.presentation_url && <button type="button" disabled={busy || deck.status === "running"} onClick={() => run(() =>
          api(`/lecture-slides/${deck.id}/refresh`, post({}))) }>Google 수정본 다시 가져오기</button>}
        {deck?.status === "review_required" && deck.review_token && <div className="weekly-content-publish">
          <label><input type="checkbox" checked={checked[deck.id] === deck.review_token} onChange={event => setChecked(values =>
            ({ ...values, [deck.id]: event.target.checked ? deck.review_token! : "" }))} />썸네일·설명 화면과 해당 대본의 내용·순서가 맞는지 확인했어요.</label>
          <button type="button" disabled={busy || checked[deck.id] !== deck.review_token} onClick={() => run(() =>
            api(`/lecture-slides/${deck.id}/approve`, post({ review_token: deck.review_token })))}>슬라이드 검토 완료</button>
          <p>검토 완료는 영상 제작이나 학생 공개를 시작하지 않아요.</p>
        </div>}
      </details>;
    })}
  </section>;
}
