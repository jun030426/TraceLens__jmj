import { useEffect, useImperativeHandle, useRef, useState, type Ref } from "react";
import { ErrorNotice } from "./components";
import { videoPlayback } from "./videoPlayback";

export type LectureVideoHandle = { retryIfFailed: () => void };
export function LectureVideo({ src, poster, onEnded, ref }: {
  src: string; poster?: string; onEnded: () => void; ref?: Ref<LectureVideoHandle>;
}) {
  const element = useRef<HTMLVideoElement>(null);
  const playback = useRef<ReturnType<typeof videoPlayback> | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    const controller = videoPlayback(element.current!, src, setError);
    playback.current = controller;
    return () => { controller.dispose(); playback.current = null; };
  }, [src]);
  useImperativeHandle(ref, () => ({ retryIfFailed: () => playback.current?.retryIfFailed() }), []);
  return <>
    {error && <div><ErrorNotice text={error} /><button type="button" onClick={() => playback.current?.retry()}>영상 다시 재생</button></div>}
    <video ref={element} poster={poster} controls controlsList="nodownload" playsInline preload="none"
      onContextMenu={event => event.preventDefault()}
      style={{ width: "100%", display: "block", aspectRatio: "16 / 9" }} src={src} onEnded={onEnded} />
  </>;
}
