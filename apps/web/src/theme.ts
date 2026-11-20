/* [다크 모드] 사용자가 고른 화면 모드를 기억하고 <html data-theme> 에 적용해요.
   - 고른 값은 이 브라우저의 localStorage("lerny-theme")에만 저장돼요.
   - 랜딩 첫 화면("/")은 디자인을 그대로 보여 주려고 항상 밝은 모드예요.
   - 어두운 색은 lerny-dark.css(자동 생성) + lerny-dark-tweaks.css(손질) 에 있어요. */
import { useEffect, useState } from "react";

export type Theme = "light" | "dark";
const KEY = "lerny-theme";
const EVENT = "lerny-theme-change";

export function getTheme(): Theme {
  try {
    return localStorage.getItem(KEY) === "dark" ? "dark" : "light";
  } catch {
    return "light";
  }
}

export function setTheme(theme: Theme) {
  try {
    localStorage.setItem(KEY, theme);
  } catch {
    /* Storage may be disabled. */
  }
  window.dispatchEvent(new Event(EVENT));
}

/** 지금 화면에 실제로 입힐 모드 — 랜딩에서는 항상 밝게 */
export function applyTheme(theme: Theme, pathname: string) {
  const mode = theme === "dark" && pathname !== "/" ? "dark" : "light";
  document.documentElement.dataset.theme = mode;
  document.documentElement.style.colorScheme = mode;
}

export function useTheme(): [Theme, (t: Theme) => void] {
  const [theme, set] = useState<Theme>(getTheme);
  useEffect(() => {
    const sync = () => set(getTheme());
    window.addEventListener(EVENT, sync);
    window.addEventListener("storage", sync);
    return () => {
      window.removeEventListener(EVENT, sync);
      window.removeEventListener("storage", sync);
    };
  }, []);
  return [theme, setTheme];
}
