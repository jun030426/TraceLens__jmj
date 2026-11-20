// Refresh the authenticated endpoint, never extend a storage URL's lifetime.
type Media = Pick<HTMLVideoElement, "src" | "currentTime" | "duration" | "paused" | "error" | "ended" | "load" | "play" | "addEventListener" | "removeEventListener">;
export function videoPlayback(media: Media, source: string, report: (message: string) => void) {
  let disposed = false, failed = false, automaticRetries = 0, serial = 0;
  let position = 0, restore: number | null = null, shouldPlay = false;
  const errorMessage = "영상을 재생하지 못했어요. 연결을 확인한 뒤 다시 재생해 주세요.";
  const play = () => { if (!disposed) void media.play().catch(() => { /* Native controls remain available if autoplay is blocked. */ }); };
  const refresh = (manual: boolean) => {
    if (disposed) return;
    if (manual) { automaticRetries = 0; shouldPlay = true; }
    failed = false;
    restore = position;
    report("");
    const url = new URL(source, location.href);
    url.searchParams.set("playback_retry", `${Date.now()}-${++serial}`);
    media.src = url.href;
    media.load();
  };
  const listeners: Record<string, EventListener> = {
    timeupdate: () => { if (restore === null && Number.isFinite(media.currentTime)) position = media.currentTime; },
    play: () => { shouldPlay = true; },
    pause: () => { if (!media.error && restore === null) shouldPlay = false; },
    ended: () => { shouldPlay = false; position = 0; },
    loadedmetadata: () => {
      if (restore === null) return;
      const target = Number.isFinite(media.duration) ? Math.min(restore, Math.max(0, media.duration - 0.05)) : restore;
      restore = null;
      if (target > 0) media.currentTime = target;
      if (shouldPlay) play();
    },
    playing: () => { failed = false; report(""); },
    error: () => {
      failed = true;
      // One automatic retry per selected video. Persistent failures need user action.
      if ((media.error?.code === 2 || media.error?.code === 4) && automaticRetries++ === 0) refresh(false);
      else report(errorMessage);
    },
  };
  for (const [event, listener] of Object.entries(listeners)) media.addEventListener(event, listener);
  return {
    retry: () => refresh(true),
    retryIfFailed: () => { if (failed || media.error) refresh(true); },
    dispose: () => {
      disposed = true;
      for (const [event, listener] of Object.entries(listeners)) media.removeEventListener(event, listener);
    },
  };
}
