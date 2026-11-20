// 풀코딩(직접 작성) 실행 전 간단 문법 자동수정 (2026-11-14).
// 콜론·괄호·세미콜론처럼 "줄 끝에 한두 글자가 빠진" 실수만 고쳐요. 줄 가운데를 바꾸거나 글자를 지우지는 않아요.
//   - 고친 코드로 실행하고, 화면에는 고친 줄을 빨간색으로 표시하고, 빠진 글자는 회색으로 깔아서 학생이 따라 쓰게 해요.
//   - 줄 끝에 붙이기만 하므로 줄 번호가 바뀌지 않고, 학생이 친 글자가 항상 고친 줄의 앞부분이에요(회색 따라쓰기와 맞아요).
// 다른 파일을 불러오지 않아서 node 테스트(tests/quickFix.test.ts)로 바로 확인할 수 있어요.

export type FixLanguage = "Python" | "Java" | "C";
export type FixKind = "colon" | "bracket" | "semicolon";
/** 고친 줄 하나 — line은 1부터, add는 줄 끝에 붙인 글자 */
export type QuickFix = { line: number; add: string; kinds: FixKind[]; message: string };
export type QuickFixResult = { code: string; fixes: QuickFix[] };

const PY_BLOCK = /^(if|elif|else|for|while|def|class|try|except|finally|with)\b/;
const PY_BARE = /^(else|try|finally)$/;
const CLIKE_NO_SEMI = /^(if|else|for|while|do|switch|case|default|try|catch|finally|class|interface|enum|public|private|protected|static|import|package|#|@|\/\/|\/\*|\*|\})/;
const OPEN: Record<string, string> = { "(": ")", "[": "]", "{": "}" };
const CLOSE: Record<string, string> = { ")": "(", "]": "[", "}": "{" };

const indent = (line: string) => (line.match(/^[ \t]*/)?.[0] ?? "").replace(/\t/g, "    ").length;

/** 한 줄을 훑어서 문자열 밖의 괄호 상태를 알려 줘요.
 *  open: 이 줄에서 닫히지 않은 여는 괄호(순서대로) · bad: 짝이 안 맞는 닫는 괄호가 있음
 *  comment: 줄 끝 주석이 있음 · unclosedString: 따옴표가 닫히지 않음 · topColon: 괄호 밖 콜론이 있음 */
function scan(line: string, language: FixLanguage) {
  const open: string[] = [];
  let bad = false, comment = false, topColon = false, quote = "";
  for (let i = 0; i < line.length; i++) {
    const c = line[i];
    if (quote) {
      if (c === "\\") { i++; continue; }
      if (c === quote) quote = "";
      continue;
    }
    if (c === '"' || c === "'") { quote = c; continue; }
    if (language === "Python" && c === "#") { comment = true; break; }
    if (language !== "Python" && c === "/" && (line[i + 1] === "/" || line[i + 1] === "*")) { comment = true; break; }
    if (OPEN[c]) open.push(c);
    else if (CLOSE[c]) { if (open[open.length - 1] === CLOSE[c]) open.pop(); else bad = true; }
    else if (c === ":" && open.length === 0) topColon = true;
  }
  return { open, bad, comment, unclosedString: !!quote, topColon };
}

/** 문자열·주석 밖의 여는 괄호 수 - 닫는 괄호 수 (괄호 종류 kinds만) */
function totalBalance(code: string, language: FixLanguage, kinds: string) {
  let n = 0;
  for (const line of code.split("\n")) {
    let quote = "";
    for (let i = 0; i < line.length; i++) {
      const c = line[i];
      if (quote) { if (c === "\\") i++; else if (c === quote) quote = ""; continue; }
      if (c === '"' || c === "'") { quote = c; continue; }
      if (language === "Python" && c === "#") break;
      if (language !== "Python" && c === "/" && (line[i + 1] === "/" || line[i + 1] === "*")) break;
      if (kinds.includes(c)) n++;
      else if (CLOSE[c] && kinds.includes(CLOSE[c])) n--;
    }
  }
  return n;
}

const LABEL: Record<FixKind, string> = { colon: "콜론(:)", bracket: "닫는 괄호", semicolon: "세미콜론(;)" };

function message(kinds: FixKind[], add: string) {
  const parts = kinds.map(k => k === "bracket" ? `${LABEL.bracket} ${add.replace(/[:;]/g, "")}` : LABEL[k]);
  return `${parts.join("와 ")}${kinds[kinds.length - 1] === "bracket" ? "가" : "이"} 빠져 있어서 줄 끝에 붙였어요.`;
}

/** 실행 전 간단 문법 자동수정 — 고칠 게 없으면 code가 그대로, fixes가 빈 배열이에요 */
export function quickFix(code: string, language: FixLanguage): QuickFixResult {
  // A line heuristic cannot distinguish multiline strings/comments or explicit
  // continuations reliably. Leave these programs intact instead of changing data.
  if (/'''|"""|\/\*|\\\r?\n/.test(code)) return { code, fixes: [] };
  const lines = code.split("\n");
  const fixes: QuickFix[] = [];
  // 괄호 고치기는 코드 전체의 괄호 수가 안 맞을 때만 해요 (Java·C의 중괄호 { }는 여러 줄에 걸치니 빼요)
  const kinds = language === "Python" ? "([{" : "([";
  const bracketsOff = totalBalance(code, language, kinds) <= 0;
  const nextLine = (i: number) => { for (let j = i + 1; j < lines.length; j++) if (lines[j].trim()) return lines[j]; return null; };
  const out = lines.map((line, i) => {
    const body = line.trim();
    if (!body) return line;
    const s = scan(line, language);
    if (s.comment || s.unclosedString || s.bad) return line;
    const next = nextLine(i);
    const nextTrim = next?.trim() ?? "";
    let add = "";
    const did: FixKind[] = [];
    // 1) 닫는 괄호 — 이 줄에서 연 괄호가 안 닫혔고, 다음 줄이 이어지는 줄(더 들여씀·닫는 괄호로 시작)이 아니면 닫아 줘요
    const unclosed = s.open.filter(c => kinds.includes(c));
    if (!bracketsOff && unclosed.length && unclosed.length === s.open.length) {
      const continues = next !== null && (indent(next) > indent(line) && !(language === "Python" && PY_BLOCK.test(body)) || (language === "Python" ? /^[)\]}]/ : /^[)\]]/).test(nextTrim));
      if (!continues) { add += unclosed.slice().reverse().map(c => OPEN[c]).join(""); did.push("bracket"); }
    }
    if (s.open.length && !did.includes("bracket")) return line;
    const fixedBody = body + add;
    // 2) Python: 블록을 여는 줄(if·for·def …)의 끝 콜론 — 다음 줄이 더 들여써져 있을 때만
    if (language === "Python" && PY_BLOCK.test(fixedBody) && !s.topColon && !fixedBody.endsWith(":")) {
      const opens = next !== null && indent(next) > indent(line);
      const first = fixedBody.match(PY_BLOCK)?.[1] ?? "";
      const bare = !PY_BARE.test(first) || PY_BARE.test(fixedBody); // else·try·finally는 낱말 하나만 있을 때만
      if (opens && bare) { add += ":"; did.push("colon"); }
    }
    // 3) Java·C: 한 줄 문장 끝 세미콜론 — 다음 줄이 이어지는 줄이 아닐 때만
    if (language !== "Python" && !CLIKE_NO_SEMI.test(fixedBody) && /[\w)\]"'+-]$/.test(fixedBody) && !/(\+\+|--)?[{};,:]$/.test(fixedBody) && !/[+\-*/%=&|<>!?]$/.test(fixedBody.replace(/(\+\+|--)$/, "x"))) {
      const continues = /^[{.+\-*/%=&|<>?:]/.test(nextTrim) || (next !== null && indent(next) > indent(line) && !/^[}]/.test(nextTrim));
      const looksLikeDecl = /^[\w<>[\],\s]+\s+\w+\s*\([^)]*\)$/.test(fixedBody) && (nextTrim.startsWith("{") || !next);
      if (!continues && !looksLikeDecl) { add += ";"; did.push("semicolon"); }
    }
    if (!add) return line;
    fixes.push({ line: i + 1, add, kinds: did, message: message(did, add) });
    return line + add;
  });
  return { code: fixes.length ? out.join("\n") : code, fixes };
}
