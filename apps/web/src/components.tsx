import { useCallback, useEffect, useState, useRef, type ReactNode } from "react";
import { api } from "./api";
export const field = (f: FormData, k: string) => String(f.get(k) || "");
export function useLoad<T>(path: string, keepPrevious = false, enabled = true) {
  const [data, setData] = useState<T>();
  const [error, setError] = useState("");
  const [rev, setRev] = useState(0);
  const previousPath = useRef(path);
  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    setError("");
    if (!keepPrevious || previousPath.current !== path) setData(undefined);
    previousPath.current = path;
    if (!enabled) return;
    api<T>(path, { signal: controller.signal })
      .then((v) => {
        if (active) setData(v);
      })
      .catch((e) => {
        if (active) setError(e.message);
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [path, rev, keepPrevious, enabled]);
  const reload = useCallback(() => setRev((v) => v + 1), []);
  return { data, error, reload };
}
export function Notice({ children }: { children: ReactNode }) {
  return (
    <p className="message" role="status">
      {children}
    </p>
  );
}
export function ErrorNotice({ text }: { text: string }) {
  return text ? (
    <p className="error" role="alert">
      {text}
    </p>
  ) : null;
}
export function Input({
  label,
  name,
  type = "text",
  minLength,
  maxLength = 200,
}: {
  label: string;
  name: string;
  type?: string;
  minLength?: number;
  maxLength?: number;
}) {
  return (
    <label>
      {label}
      <input
        name={name}
        type={type}
        minLength={minLength}
        maxLength={maxLength}
        required
      />
    </label>
  );
}
export function Form({
  children,
  onSubmit,
  label = "저장",
  actionRole = "primary",
  onCancel,
  beside,
  disabled = false,
}: {
  children: ReactNode;
  disabled?: boolean;
  /** 제출 버튼과 같은 줄 왼쪽에 둘 것 (예: 음성 질문 버튼) */
  beside?: ReactNode;
  onSubmit: (f: FormData) => Promise<void>;
  label?: string;
  actionRole?: "primary" | "secondary" | "danger";
  onCancel?: () => void;
}) {
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <form
      className="form"
      onSubmit={async (e) => {
        e.preventDefault();
        if (disabled || busy) return;
        const f = new FormData(e.currentTarget);
        setBusy(true);
        setError("");
        try {
          await onSubmit(f);
        } catch (e) {
          setError(e instanceof Error ? e.message : "처리하지 못했어요.");
        } finally {
          setBusy(false);
        }
      }}
    >
      <fieldset disabled={busy || disabled}>{children}</fieldset>
      <ErrorNotice text={error} />
      {onCancel ? (
        <div className="form-actions">
          <button
            className={
              actionRole === "primary" ? "primary" : `action-${actionRole}`
            }
            disabled={busy || disabled}
          >
            {busy ? "처리 중…" : label}
          </button>
          <button
            type="button"
            className="action-secondary"
            disabled={busy}
            onClick={onCancel}
          >
            취소
          </button>
        </div>
      ) : beside ? (
        <div className="form-action-row">
          {beside}
          <button
            className={
              actionRole === "primary" ? "primary" : `action-${actionRole}`
            }
            disabled={busy || disabled}
          >
            {busy ? "처리 중…" : label}
          </button>
        </div>
      ) : (
        <button
          className={
            actionRole === "primary" ? "primary" : `action-${actionRole}`
          }
          disabled={busy || disabled}
        >
          {busy ? "처리 중…" : label}
        </button>
      )}
    </form>
  );
}
