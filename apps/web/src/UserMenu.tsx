/* [헤더] 이름(예: 테스트 학생)을 누르면 열리는 내 정보 메뉴
   - 내 정보 페이지로 가기 · 다크 모드 켜고 끄기 · 로그아웃
   - 좁은 화면(모바일 메뉴 안)에서는 펼친 채로 보여요. 스타일: user-menu.css (main.tsx 에서 맨 마지막에 불러와요) */
import { useCallback, useEffect, useId, useRef, useState, useSyncExternalStore } from "react";
import { Link, useLocation } from "react-router-dom";
import type { User } from "./api";
import { useTheme } from "./theme";

const ROLE_LABEL: Record<User["role"], string> = { student: "학생", teacher: "교수자", operator: "운영자" };

const desktopQuery = "(min-width: 761px)";
function subscribeDesktop(update: () => void) {
  const media = window.matchMedia(desktopQuery);
  media.addEventListener("change", update);
  return () => media.removeEventListener("change", update);
}
const getDesktop = () => window.matchMedia(desktopQuery).matches;

function initial(name: string) {
  const n = name.replace(/^테스트\s*/, "").trim() || name;
  return n.slice(0, 1);
}

export function UserMenu({ user, compact = false, onLogout }: { user: User; compact?: boolean; onLogout: () => void }) {
  const [open, setOpen] = useState(false);
  const [theme, setTheme] = useTheme();
  const box = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const panelId = useId();
  const desktop = useSyncExternalStore(subscribeDesktop, getDesktop, () => false);
  const nativePopover = desktop && typeof HTMLElement !== "undefined" && "popover" in HTMLElement.prototype;
  const { pathname } = useLocation();
  const dark = theme === "dark";

  useEffect(() => {
    if (panel.current?.hasAttribute("popover") && panel.current.matches(":popover-open")) panel.current.hidePopover();
    setOpen(false);
  }, [pathname, desktop]);
  // Popovers use the top layer. Retain the existing placement without requiring CSS anchors.
  const positionPanel = useCallback(() => {
    const rect = trigger.current?.getBoundingClientRect();
    if (!rect || !panel.current) return;
    panel.current.style.setProperty("--user-menu-top", `${rect.bottom + 10}px`);
    panel.current.style.setProperty("--user-menu-right", `${document.documentElement.clientWidth - rect.right}px`);
  }, []);
  useEffect(() => {
    if (!nativePopover || !open) return;
    window.addEventListener("resize", positionPanel);
    window.addEventListener("scroll", positionPanel, { capture: true, passive: true });
    return () => {
      window.removeEventListener("resize", positionPanel);
      window.removeEventListener("scroll", positionPanel, true);
    };
  }, [nativePopover, open, positionPanel]);
  useEffect(() => {
    // Only browsers without Popover need manual light-dismiss and Escape handling.
    if (!desktop || nativePopover || !open) return;
    const outside = (e: PointerEvent) => {
      if (!box.current?.contains(e.target as Node)) setOpen(false);
    };
    const esc = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setOpen(false);
        trigger.current?.focus();
      }
    };
    document.addEventListener("pointerdown", outside);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("pointerdown", outside);
      document.removeEventListener("keydown", esc);
    };
  }, [desktop, nativePopover, open]);

  const avatar = (big?: boolean) =>
    user.avatar ? (
      <img className={`user-menu-avatar ${big ? "big" : ""}`} src={user.avatar} alt="" />
    ) : (
      <span className={`user-menu-avatar ${big ? "big" : ""}`} aria-hidden="true">
        {initial(user.display_name)}
      </span>
    );

  return (
    <div className="user-menu" ref={box} data-open={open}>
      <button
        ref={trigger}
        type="button"
        className="user-menu-trigger"
        data-keep-menu
        aria-expanded={open}
        aria-controls={panelId}
        popoverTarget={nativePopover ? panelId : undefined}
        aria-label={compact ? `${user.display_name} 메뉴` : undefined}
        onClick={nativePopover ? undefined : () => setOpen(value => !value)}
      >
        {avatar()}
        {!compact && <span className="user-menu-name">{user.display_name}</span>}
        <svg className="user-menu-chev" aria-hidden="true" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="m6 9 6 6 6-6" />
        </svg>
      </button>

      <div ref={panel} id={panelId} className="user-menu-panel" popover={nativePopover ? "auto" : undefined}
        onBeforeToggle={event => { if (event.newState === "open") positionPanel(); }}
        onToggle={event => setOpen(event.newState === "open")}>
        <div className="user-menu-head">
          {avatar(true)}
          <div>
            <strong>{user.display_name}</strong>
            <span>
              {ROLE_LABEL[user.role]} · {user.login_id}
            </span>
          </div>
        </div>
        <Link to="/mypage" className="user-menu-item">
          <span>내 정보</span>
          <span aria-hidden="true">›</span>
        </Link>
        <button type="button" role="switch" aria-checked={dark} data-keep-menu className="user-menu-item user-menu-theme" onClick={() => setTheme(dark ? "light" : "dark")}>
          <span>다크 모드</span>
          <span className="user-menu-switch" aria-hidden="true">
            <i />
          </span>
        </button>
        <button type="button" className="user-menu-item user-menu-logout" onClick={onLogout}>
          로그아웃
        </button>
      </div>
    </div>
  );
}
