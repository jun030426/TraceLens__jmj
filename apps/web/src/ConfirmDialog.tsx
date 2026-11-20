// 화면 안에 뜨는 확인창 — 브라우저 기본 알림(window.confirm) 대신 써요.
// 사용법: const [confirm, confirmDialog] = useConfirm();  →  if (!(await confirm({ title, message }))) return;  그리고 JSX 어딘가에 {confirmDialog}
import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";

export type ConfirmOptions = { title: string; message?: ReactNode; confirmLabel?: string; cancelLabel?: string; tone?: "default" | "warn" };
type Request = ConfirmOptions;

export function useConfirm() {
  const [req, setReq] = useState<Request | null>(null);
  const pending = useRef<((ok: boolean) => void) | null>(null);
  const confirm = useCallback((o: ConfirmOptions) => new Promise<boolean>(resolve => {
    pending.current?.(false);
    pending.current = resolve;
    setReq(o);
  }), []);
  useEffect(() => () => { pending.current?.(false); pending.current = null; }, []);
  const close = useCallback((ok: boolean) => { pending.current?.(ok); pending.current = null; setReq(null); }, []);
  const dialog = req ? <ConfirmDialog {...req} onClose={close} /> : null;
  return [confirm, dialog] as const;
}

function ConfirmDialog({ title, message, confirmLabel = "확인", cancelLabel = "취소", tone = "default", onClose }: ConfirmOptions & { onClose: (ok: boolean) => void }) {
  const box = useRef<HTMLDialogElement>(null);
  const id = useId();
  useLayoutEffect(() => {
    const dialog = box.current!;
    const finish = () => {
      // StrictMode can queue a close event during cleanup, then reopen this node.
      if (dialog.open) return;
      const confirmed = dialog.returnValue === "confirm";
      dialog.returnValue = "";
      onClose(confirmed);
    };
    dialog.addEventListener("close", finish);
    dialog.showModal();
    // Safari versions without closedBy still need the existing outside-click behavior.
    const outside = (e: PointerEvent) => {
      const r = dialog.getBoundingClientRect();
      return e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom;
    };
    let pressedOutside = false;
    const down = (e: PointerEvent) => { pressedOutside = e.button === 0 && outside(e); };
    const up = (e: PointerEvent) => {
      if (pressedOutside && e.button === 0 && outside(e)) dialog.close();
      pressedOutside = false;
    };
    const needsLightDismiss = !("closedBy" in HTMLDialogElement.prototype);
    if (needsLightDismiss) {
      dialog.addEventListener("pointerdown", down);
      dialog.addEventListener("pointerup", up);
    }
    return () => {
      dialog.removeEventListener("close", finish);
      dialog.removeEventListener("pointerdown", down);
      dialog.removeEventListener("pointerup", up);
      dialog.close();
    };
  }, [onClose]);
  return createPortal(
    <dialog ref={box} className={`ln-confirm__box is-${tone}`} {...{ closedby: "any" }} aria-labelledby={`${id}-title`} aria-describedby={message ? `${id}-message` : undefined}>
      <h2 id={`${id}-title`}>{title}</h2>
      {message && <p id={`${id}-message`}>{message}</p>}
      <form method="dialog" className="ln-confirm__actions">
        <button type="submit" value="cancel" className="ln-confirm__cancel" ref={node => { node?.toggleAttribute("autofocus", tone === "warn"); }}>{cancelLabel}</button>
        <button type="submit" value="confirm" className="ln-confirm__ok" ref={node => { node?.toggleAttribute("autofocus", tone !== "warn"); }}>{confirmLabel}</button>
      </form>
    </dialog>, document.body);
}
