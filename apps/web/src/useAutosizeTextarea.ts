import { useLayoutEffect, type RefObject } from "react";

function resizeToContent(input: HTMLTextAreaElement) {
  input.style.height = "auto";
  input.style.height = `${input.scrollHeight + input.offsetHeight - input.clientHeight}px`;
}

/** Native CSS owns sizing where supported; older browsers retain automatic growth. */
export function useAutosizeTextarea(ref: RefObject<HTMLTextAreaElement | null>, value: string, active = true) {
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el || !active || CSS.supports("field-sizing", "content")) return;
    resizeToContent(el);
  }, [ref, value, active]);

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el || !active || CSS.supports("field-sizing", "content")) return;
    let live = true;
    let width = el.clientWidth;
    const observer = new ResizeObserver(() => {
      if (el.clientWidth !== width) {
        width = el.clientWidth;
        resizeToContent(el);
      }
    });
    observer.observe(el);
    void document.fonts.ready.then(() => { if (live) resizeToContent(el); });
    return () => { live = false; observer.disconnect(); };
  }, [ref, active]);
}
