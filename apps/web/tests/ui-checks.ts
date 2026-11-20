/** Browser-only regression checks for tests/ui-regression.html. Never calls an API. */
export async function runUiChecks(): Promise<string> {
  const results: string[] = [];
  const wait = () => new Promise(resolve => setTimeout(resolve, 80));
  const button = (text: string) => Array.from(document.querySelectorAll<HTMLButtonElement>("button")).find(el => el.textContent?.trim() === text)!;
  const check = (name: string, ok: boolean) => { if (!ok) throw new Error(name); results.push(`PASS ${name}`); };
  try {
    button("확인창 열기").click(); await wait();
    let dialog = document.querySelector<HTMLDialogElement>("dialog")!;
    check("native modal blocks the background", dialog.matches(":modal"));
    check("default confirmation keeps primary focus", document.activeElement === button("확인"));
    button("확인창 열기").focus();
    check("background cannot receive focus", dialog.contains(document.activeElement));
    button("확인").click(); await wait();
    check("confirm resolves true", document.querySelector('[aria-label="확인 결과"]')?.textContent === "true");
    button("확인창 열기").click(); await wait();
    dialog = document.querySelector("dialog")!;
    dialog.close(); await wait();
    check("dismiss after confirmation does not reuse stale true", document.querySelector('[aria-label="확인 결과"]')?.textContent === "false");
    button("주의 확인창 열기").click(); await wait();
    check("warning starts on safe cancel action", document.activeElement === button("취소"));
    button("취소").click(); await wait();
    check("cancel resolves false", document.querySelector('[aria-label="확인 결과"]')?.textContent === "false");

    const trigger = document.querySelector<HTMLButtonElement>(".user-menu-trigger")!;
    const panel = document.querySelector<HTMLElement>(".user-menu-panel")!;
    if (matchMedia("(min-width: 761px)").matches) {
      trigger.click(); await wait();
      check("menu is visible after trigger", getComputedStyle(panel).display === "grid");
      check("menu ARIA follows open state", trigger.getAttribute("aria-expanded") === "true");
      trigger.click(); await wait();
      check("second trigger closes menu", getComputedStyle(panel).display === "none");
    } else {
      check("mobile menu stays inline and visible", getComputedStyle(panel).position === "static" && getComputedStyle(panel).display === "grid");
    }

    const input = document.querySelector<HTMLTextAreaElement>('textarea[name="message"]')!;
    const setValue = (value: string) => {
      Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!.call(input, value);
      input.dispatchEvent(new Event("input", { bubbles: true }));
    };
    const sent = () => Number(document.querySelector('[aria-label="전송 횟수"]')?.textContent);
    setValue("한글 조합 검증"); await wait();
    const initial = sent();
    input.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", keyCode: 13, isComposing: true, bubbles: true, cancelable: true })); await wait();
    check("composition Enter does not submit", sent() === initial);
    input.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", keyCode: 229, isComposing: false, bubbles: true, cancelable: true })); await wait();
    check("Safari 229 Enter does not submit", sent() === initial);
    input.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", keyCode: 13, shiftKey: true, bubbles: true, cancelable: true })); await wait();
    check("Shift+Enter does not submit", sent() === initial);
    input.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", keyCode: 13, bubbles: true, cancelable: true })); await wait();
    check("ordinary Enter submits exactly once", sent() === initial + 1);
    check("submission clears the draft", input.value === "");
    const emptyHeight = input.getBoundingClientRect().height;
    setValue(Array.from({ length: 30 }, (_, i) => `긴 질문 ${i + 1}: 문자열과 자료구조를 설명해 주세요.`).join("\n")); await wait();
    check("long draft grows and stays within 180px", input.getBoundingClientRect().height > emptyHeight && input.getBoundingClientRect().height <= 180.5);
    check("long draft remains scrollable", input.scrollHeight > input.clientHeight);
    setValue(""); await wait();
    check("cleared draft shrinks to original height", Math.abs(input.getBoundingClientRect().height - emptyHeight) < 1);
    const practice = document.querySelector<HTMLTextAreaElement>('textarea[name="practice-message"]')!;
    const practiceEmptyHeight = practice.getBoundingClientRect().height;
    // A wrapped placeholder can exceed the minimum on a narrow viewport, as before.
    check("practice input respects its 52px minimum", practiceEmptyHeight >= 51.5 && practiceEmptyHeight <= 180.5);
    const fillPractice = (value: string) => {
      Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!.call(practice, value);
      practice.dispatchEvent(new Event("input", { bubbles: true }));
    };
    fillPractice("질문 내용\n".repeat(30)); await wait();
    check("practice input grows to its 180px limit", Math.abs(practice.getBoundingClientRect().height - 180) < 1);
    check("practice long draft stays scrollable", practice.scrollHeight > practice.clientHeight);
    fillPractice(""); await wait();
    check("practice cleared draft restores initial height", Math.abs(practice.getBoundingClientRect().height - practiceEmptyHeight) < 1);
    return `${results.join("\n")}\n${results.length} checks passed`;
  } catch (error) {
    return `${results.join("\n")}\nFAIL ${(error as Error).message}`;
  }
}
