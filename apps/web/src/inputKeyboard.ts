/** Safari may report the IME-confirming Enter after compositionend (keyCode 229). */
export function isComposingInput(event: Pick<KeyboardEvent, "isComposing" | "keyCode">): boolean {
  return event.isComposing || event.keyCode === 229;
}
