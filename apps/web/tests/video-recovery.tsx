// Local-only fixture. The test server rejects the first media request, then accepts a refreshed URL.
import { useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { LectureVideo, type LectureVideoHandle } from "../src/LectureVideo";
import "../src/style.css";

function Fixture() {
  const [failure, setFailure] = useState(false);
  const [ended, setEnded] = useState(false);
  const player = useRef<LectureVideoHandle>(null);
  return <main style={{ maxWidth: 800, margin: "24px auto" }}><h1>영상 복구 검증</h1>
    <p>합성 HTTP 실패를 사용하는 로컬 검증 화면입니다. 운영 API를 호출하지 않습니다.</p>
    <button onClick={() => { setFailure(!failure); setEnded(false); }}>{failure ? "일시 오류로 전환" : "지속 오류로 전환"}</button>
    <button onClick={() => player.current?.retryIfFailed()}>목록 새로고침</button>
    <p role="status">{failure ? "지속 오류" : "첫 요청 실패 → 주소 갱신 후 복구"}{ended ? " · 재생 완료" : ""}</p>
    <LectureVideo key={String(failure)} ref={player} src={`/__video-recovery-fixture.mp4?persistent=${Number(failure)}`}
      onEnded={() => setEnded(true)} />
  </main>;
}
createRoot(document.getElementById("root")!).render(<Fixture />);
