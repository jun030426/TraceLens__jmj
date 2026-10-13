import { useEffect, useState, type ReactNode } from "react";
import { api } from "./api";
export const field = (f: FormData, k: string) => String(f.get(k) || "");
export function useLoad<T>(path: string) {
  const [data, setData] = useState<T>();
  const [error, setError] = useState("");
  const [rev, setRev] = useState(0);
  useEffect(() => {
    let active = true;
    setError("");
    setData(undefined);
    api<T>(path)
      .then((v) => {
        if (active) setData(v);
      })
      .catch((e) => {
        if (active) setError(e.message);
      });
    return () => {
      active = false;
    };
  }, [path, rev]);
  return { data, error, reload: () => setRev((v) => v + 1) };
}
export function Notice({ children }: { children: ReactNode }) {
  return (
    <p className="message" role="status">
      {children}
    </p>
  );
}
export function AIAvailability() {
  const [offline, setOffline] = useState(false);
  useEffect(() => {
    let active = true;
    const check = () => void api<{ status: string }>("/ai/status").then(value => {
      if (active) setOffline(value.status === "offline");
    }).catch(() => { /* The page handles its own connectivity errors. */ });
    check();
    const timer = setInterval(check, 30000);
    return () => { active = false; clearInterval(timer); };
  }, []);
  return offline ? <Notice>AI 기능이 현재 대기 중이에요. 요청은 보관되며 연결 후 처리됩니다. 기존 자료와 학습 기록은 계속 확인할 수 있어요.</Notice> : null;
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
}: {
  children: ReactNode;
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
      <fieldset disabled={busy}>{children}</fieldset>
      <ErrorNotice text={error} />
      {onCancel ? (
        <div className="form-actions">
          <button
            className={
              actionRole === "primary" ? "primary" : `action-${actionRole}`
            }
            disabled={busy}
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
      ) : (
        <button
          className={
            actionRole === "primary" ? "primary" : `action-${actionRole}`
          }
          disabled={busy}
        >
          {busy ? "처리 중…" : label}
        </button>
      )}
    </form>
  );
}
