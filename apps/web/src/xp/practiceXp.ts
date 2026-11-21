export const XP_CHANGED = "lerny-xp-changed";

export function notifyPracticeSubmit() {
  window.dispatchEvent(new Event(XP_CHANGED));
}
