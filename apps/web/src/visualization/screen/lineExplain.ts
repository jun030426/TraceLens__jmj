// 시각화 설명 문장 — "방금 실행한 줄이 무엇을 했는지"를 학생 말로 풀어 준다.
//
// 근거는 기록에 있는 사실뿐이다: 방금 실행한 줄(causedByLine)의 글자, 그다음에 실행할 줄(nextLine),
// 지금 단계의 변수 값, 직전 단계와의 출력 차이. 코드를 다시 실행하거나 추측해서 값을 지어내지 않는다.
// 조건이 참/거짓인지는 "다음 줄이 그 블록 안으로 들어갔는지"로 판단한다 (들여쓰기로 블록을 찾는다).
import type { TraceValue } from "../../pythonTrace.ts";
import type { Observation } from "../contracts.ts";
import { valueText } from "./sceneModel.ts";

export type LineExplain = {
  /** 방금 실행한 줄 */
  line: number;
  /** 설명 한 문장 */
  text: string;
  /** 조건을 값으로 바꿔 쓴 식 (예: "5 > 2") — 있을 때만 */
  detail?: string;
  kind: "loop-in" | "loop-out" | "cond-true" | "cond-false" | "assign" | "print" | "def" | "return" | "other";
};

const indentOf = (s: string) => s.match(/^[ \t]*/)![0].replace(/\t/g, "    ").length;
const blank = (s: string) => !s.trim() || /^\s*(#|\/\/)/.test(s);

/** L번째 줄(1부터)이 여는 블록의 마지막 줄 — 들여쓰기가 더 깊은 줄이 이어지는 데까지 */
export function blockEnd(lines: readonly string[], L: number): number {
  const base = indentOf(lines[L - 1] ?? "");
  let end = L;
  for (let i = L; i < lines.length; i++) {
    const s = lines[i];
    if (blank(s)) continue;
    // C·Java의 닫는 괄호 `}`는 여는 줄과 같은 깊이라도 그 블록의 끝이다
    if (indentOf(s) > base) { end = i + 1; continue; }
    if (/^\s*}/.test(s) && indentOf(s) === base) end = i + 1;
    break;
  }
  return end;
}

/** 다음 줄이 L이 여는 블록 안(닫는 `}` 줄은 빼고)이면 블록에 들어간 것이다 */
const entered = (lines: readonly string[], L: number, next: number | null) => {
  if (next === null || next <= L) return false;
  const end = blockEnd(lines, L);
  return next < end || (next === end && !/^\s*}/.test(lines[end - 1] ?? ""));
};

type Vars = Map<string, TraceValue>;

/** 조건식 속 변수·배열 칸을 지금 값으로 바꿔 쓴다. 모르는 부분은 그대로 둔다 */
export function substitute(expr: string, vars: Vars, obs: Observation): string {
  const val = (name: string) => vars.get(name);
  const num = (s: string): number | null => {
    const t = s.trim();
    if (/^-?\d+$/.test(t)) return Number(t);
    const m = t.match(/^([A-Za-z_]\w*)\s*(?:([+-])\s*(\d+))?$/);
    if (!m) return null;
    const v = val(m[1]);
    if (!v || v.kind !== "primitive" || !/^-?\d+$/.test(v.text ?? "")) return null;
    const base = Number(v.text);
    return m[2] ? base + (m[2] === "+" ? 1 : -1) * Number(m[3]) : base;
  };
  // 배열 칸: name[식]
  let out = expr.replace(/\b([A-Za-z_]\w*)\s*\[([^\[\]]+)\]/g, (all, name: string, idx: string) => {
    const v = val(name);
    const o = v?.kind === "reference" && v.object_id ? obs.objects[v.object_id] : undefined;
    const i = num(idx);
    if (!o?.items || i === null) return all;
    const at = i < 0 ? o.items.length + i : i;
    return at >= 0 && at < o.items.length ? valueText(o.items[at], obs.objects) : all;
  });
  // 홀로 쓰인 변수 이름 (속성·함수 이름·문자열 안은 건드리지 않는다)
  out = out.replace(/(^|[^\w."'.])([A-Za-z_]\w*)(?![\w(."'])/g, (all, pre: string, name: string) => {
    if (/^(and|or|not|in|is|True|False|None|true|false|null)$/.test(name)) return all;
    const v = val(name);
    return v?.kind === "primitive" ? pre + (v.text ?? name) : all;
  });
  return out.replace(/\s+/g, " ").trim();
}

/** 조건 앞뒤의 괄호 한 겹을 벗긴다 — `(a) and (b)`처럼 괄호가 짝이 안 맞으면 그대로 둔다 */
function unwrap(c: string): string {
  let t = c.trim().replace(/:$/, "").trim();
  if (!t.startsWith("(") || !t.endsWith(")")) return t;
  let depth = 0;
  for (let i = 0; i < t.length; i++) {
    if (t[i] === "(") depth++;
    else if (t[i] === ")") { depth--; if (depth === 0 && i < t.length - 1) return t; }
  }
  return t.slice(1, -1).trim();
}

/** 값 뒤에 붙는 "이에요/예요" — 숫자는 읽는 소리의 받침으로 고른다 (2·4·5·9로 끝나면 받침 없음) */
export function ieyo(v: string): string {
  const t = v.trim();
  if (/^-?\d+(\.\d+)?$/.test(t)) {
    const last = t[t.length - 1];
    // 10, 100처럼 0으로 끝나면 "십·백·천"(받침 있음), 그 밖엔 마지막 숫자 소리
    return t + (/[2459]/.test(last) && !/^-?\d*0$/.test(t) ? "예요" : "이에요");
  }
  const ch = t.charCodeAt(t.length - 1);
  if (ch >= 0xac00 && ch <= 0xd7a3) return t + ((ch - 0xac00) % 28 ? "이에요" : "예요");
  return t + "이에요";
}

const COND_WORD: Record<string, string> = { and: "그리고", or: "또는", not: "아님" };
const prettyCond = (c: string) => c.replace(/\b(and|or|not)\b/g, w => COND_WORD[w]).replace(/&&/g, "그리고").replace(/\|\|/g, "또는");

/** 방금 실행한 줄을 설명한다. 설명할 줄이 없으면 null */
export function explainLine(source: string, cur: Observation, prev: Observation | null): LineExplain | null {
  const L = cur.causedByLine;
  if (!L || cur.event === "exception") return null;
  const lines = source.split("\n");
  const raw = lines[L - 1] ?? "";
  const s = raw.trim().replace(/[;{]\s*$/, "").trim();
  const next = cur.nextLine || null;
  const top = cur.frames[cur.frames.length - 1];
  const vars: Vars = new Map((top?.variables ?? []).map(v => [v.name, v.value]));
  const show = (name: string) => { const v = vars.get(name); return v ? valueText(v, cur.objects) : null; };
  // 반복 줄에 "몸통에서 돌아왔는지(한 번 더)" "위에서 처음 들어왔는지(시작)" — 직전에 실행한 줄로 판단한다
  const fromBody = (() => { const p = prev?.causedByLine; return !!p && p > L && p <= blockEnd(lines, L); })();
  const loopIn = (name: string) => {
    const v = show(name);
    const val = v !== null ? `${name}이(가) ${v}일 때` : `${name}에 다음 값을 넣고`;
    return fromBody ? `반복을 한 번 더 해요. 이번에는 ${val} 반복 안쪽 줄을 실행해요.` : `반복을 시작해요. 처음에는 ${val} 반복 안쪽 줄을 실행해요.`;
  };

  // 반복: Python `for x in ...:` / Java·C `for (초기; 조건; 증가)` / 향상된 for `for (int x : arr)`
  let m = s.match(/^for\s+([A-Za-z_]\w*)(?:\s*,\s*[A-Za-z_]\w*)*\s+in\s+(.+?):?$/);
  if (m) {
    return entered(lines, L, next)
      ? { line: L, kind: "loop-in", text: loopIn(m[1]) }
      : { line: L, kind: "loop-out", text: fromBody ? `${m[1]}에 넣을 값을 다 썼어요. 반복을 끝내고 다음으로 넘어가요.` : `반복할 값이 하나도 없어서 반복 안쪽 줄을 건너뛰어요.` };
  }
  m = s.match(/^for\s*\(\s*(?:[\w<>\[\]]+\s+)?([A-Za-z_]\w*)\s*:\s*(.+)\)$/);
  if (m) {
    return entered(lines, L, next)
      ? { line: L, kind: "loop-in", text: loopIn(m[1]) }
      : { line: L, kind: "loop-out", text: `${m[2].trim()}의 값을 다 썼어요. 반복을 끝내고 다음으로 넘어가요.` };
  }
  m = s.match(/^for\s*\(([^;]*);([^;]*);([^)]*)\)$/);
  if (m) {
    const cond = m[2].trim();
    const detail = cond ? substitute(cond, vars, cur) : undefined;
    return entered(lines, L, next)
      ? { line: L, kind: "loop-in", detail, text: `반복 조건 ${cond}이(가) 참이라 반복 안쪽 줄을 실행해요.` }
      : { line: L, kind: "loop-out", detail, text: `반복 조건 ${cond}이(가) 거짓이 되어 반복을 끝내요.` };
  }
  // while
  m = s.match(/^while\b\s*(.+)$/);
  if (m) {
    const cond = unwrap(m[1]);
    return entered(lines, L, next)
      ? { line: L, kind: "loop-in", detail: substitute(cond, vars, cur), text: `조건 ${prettyCond(cond)}이(가) 참이라 반복 안쪽 줄을 실행해요.` }
      : { line: L, kind: "loop-out", detail: substitute(cond, vars, cur), text: `조건 ${prettyCond(cond)}이(가) 거짓이 되어 반복을 끝내요.` };
  }
  // if / elif / else if
  m = s.match(/^(?:if|elif|else\s+if|}\s*else\s+if)\b\s*(.+)$/);
  if (m) {
    const cond = unwrap(m[1]);
    return entered(lines, L, next)
      ? { line: L, kind: "cond-true", detail: substitute(cond, vars, cur), text: `조건 ${prettyCond(cond)}이(가) 참이에요. 그래서 안쪽 줄을 실행해요.` }
      : { line: L, kind: "cond-false", detail: substitute(cond, vars, cur), text: `조건 ${prettyCond(cond)}이(가) 거짓이에요. 그래서 안쪽 줄을 건너뛰어요.` };
  }
  // 함수 만들기
  m = s.match(/^def\s+([A-Za-z_]\w*)\s*\(/);
  if (m) return { line: L, kind: "def", text: `${m[1]}() 함수를 만들어 뒀어요. 지금 실행하는 건 아니고, 부를 때 실행돼요.` };
  // 돌려주기
  m = s.match(/^return\b\s*(.*)$/);
  if (m) return { line: L, kind: "return", text: m[1] ? `${m[1]}의 값을 돌려주고 함수를 끝내요.` : "함수를 끝내고 부른 곳으로 돌아가요." };
  // 출력
  if (/^(print\s*\(|System\.out\.print|printf\s*\(|puts\s*\()/.test(s)) {
    const added = cur.stdout.slice(prev?.stdout.length ?? 0).replace(/\n$/, "");
    return { line: L, kind: "print", text: added ? `화면에 "${added.length > 40 ? added.slice(0, 39) + "…" : added}"을(를) 출력했어요.` : "화면에 출력했어요." };
  }
  // 두 값 바꾸기: a, b = b, a
  m = s.match(/^([^=]+?)\s*,\s*([^=]+?)\s*=\s*([^=]+?)\s*,\s*([^=]+)$/);
  if (m && m[1].trim() === m[4].trim() && m[2].trim() === m[3].trim())
    return { line: L, kind: "assign", text: `${m[1].trim()}와(과) ${m[2].trim()}의 값을 서로 바꿨어요.` };
  // 대입: x = 식 / x += 식 / int x = 식 / arr[i] = 식
  m = s.match(/^(?:(?:final\s+)?[\w<>\[\]]+\s+)?([A-Za-z_]\w*(?:\s*\[[^\]]+\])?)\s*([+\-*/%]?)=(?!=)\s*(.+)$/);
  if (m) {
    const target = m[1].replace(/\s+/g, "");
    const name = target.replace(/\[.*$/, "");
    const after = target === name ? show(name) : substitute(target, vars, cur);
    const op = { "+": "더해서", "-": "빼서", "*": "곱해서", "/": "나눠서", "%": "나눈 나머지를 구해서" }[m[2]];
    const expr = m[3].trim();
    const ref = target === name ? vars.get(name) : undefined;
    const arr = ref?.kind === "reference" && ref.object_id ? cur.objects[ref.object_id] : undefined;
    // 배열을 새로 만든 줄: "nums에 4칸짜리 배열을 저장했어요"
    if (!m[2] && arr?.items) return { line: L, kind: "assign", text: `${target}에 ${arr.length ?? arr.items.length}칸짜리 배열 ${expr.length > 30 ? "" : expr + "을(를) "}만들어 저장했어요.`.replace("배열 만들어", "배열을 만들어") };
    const literal = /^(-?\d+(\.\d+)?|"[^"]*"|'[^']*'|True|False|None|true|false|null)$/.test(expr);
    const got = after !== null && after !== target ? after : null;
    if (op) return { line: L, kind: "assign", text: `${target}에 ${expr}을(를) ${op} 다시 저장했어요.${got !== null ? ` 이제 ${target}은(는) ${ieyo(got)}.` : ""}` };
    if (literal || got === null || got === expr) return { line: L, kind: "assign", text: `${target}에 ${expr}을(를) 저장했어요.` };
    return { line: L, kind: "assign", text: `${expr}을(를) 계산하면 ${ieyo(got)}. 그 값을 ${target}에 저장했어요.` };
  }
  // i++ / i--
  m = s.match(/^([A-Za-z_]\w*)\s*(\+\+|--)$/) ?? s.match(/^(\+\+|--)\s*([A-Za-z_]\w*)$/)?.reverse() as RegExpMatchArray | null;
  if (m) {
    const name = /^[A-Za-z_]/.test(m[1]) ? m[1] : m[2];
    const up = s.includes("++");
    const v = show(name);
    return { line: L, kind: "assign", text: `${name}을(를) 1 ${up ? "늘렸어요" : "줄였어요"}.${v !== null ? ` 이제 ${name}은(는) ${ieyo(v)}.` : ""}` };
  }
  return null;
}
