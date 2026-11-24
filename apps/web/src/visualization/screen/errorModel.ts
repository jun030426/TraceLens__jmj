// 오류 장면 모델 — 실행 기록에 남은 예외 문구(예: "IndexError: list index out of range")를
// 학생이 읽을 수 있는 "어디서·왜"로 바꾼다. three.js는 모른다.
// 소스 코드 글자는 분석하지 않는다. 예외 문구와 그 순간 장면(배열 길이·변수 이름)만 쓴다.
import type { Scene } from "./sceneModel.ts";

export type ErrorKind = "index" | "zero" | "name" | "key" | "null" | "type" | "recursion" | "attribute" | "value" | "indentation" | "syntax" | "other";

export type ErrorInfo = {
  kind: ErrorKind;
  /** 예외 이름 (IndexError, ArrayIndexOutOfBoundsException …) */
  name: string;
  /** 한 줄 제목 — "없는 칸을 열려고 했어요" */
  title: string;
  /** 왜 났는지 — 학생 눈높이 설명 */
  why: string;
  /** 고쳐 볼 방향 한 줄 */
  hint: string;
  /** 원래 예외 문구 */
  raw: string;
  /** 무대에서 짚어 줄 대상 — 예외 문구와 장면에서 확실히 알 수 있을 때만 채운다 */
  target?: { objectId?: string; index?: number; length?: number; varName?: string; key?: string };
};

const nameOf = (raw: string) => (raw.match(/^([A-Za-z_][\w.]*)(?::|$)/)?.[1] ?? "").split(".").pop() ?? "";

/** 예외 문구 하나를 설명으로 바꾼다. 장면은 "어느 배열·변수인지" 짚을 때만 쓴다 */
export function explainError(raw: string, scene: Scene): ErrorInfo {
  const name = nameOf(raw) || "오류";
  const msg = raw.replace(/^[^:]*:\s*/, "");
  const base = { name, raw };

  if (name === "IndentationError" || name === "TabError") {
    return {
      ...base,
      kind: "indentation",
      title: "들여쓰기 오류로 실행 전에 멈췄어요",
      why: msg,
      hint: name === "TabError"
        ? "탭과 공백을 섞어 쓴 부분을 찾아 공백으로 통일해 보세요."
        : "표시된 줄과 바로 위 줄을 보고, 같은 블록에 속한 줄의 들여쓰기를 맞춰 보세요.",
    };
  }
  if (name === "SyntaxError") {
    return {
      ...base,
      kind: "syntax",
      title: "문법 오류로 실행 전에 멈췄어요",
      why: msg,
      hint: "표시된 줄과 바로 위 줄의 괄호, 따옴표, 콜론을 확인해 보세요.",
    };
  }

  // ── 없는 칸 (인덱스 범위 밖) ──
  if (/IndexError|IndexOutOfBounds/i.test(raw)) {
    const m = raw.match(/Index\s+(-?\d+)\s+out of bounds for length\s+(\d+)/i);
    const index = m ? Number(m[1]) : undefined;
    const length = m ? Number(m[2]) : undefined;
    // 길이가 같은 배열이 무대에 딱 하나일 때만 "그 배열"이라고 짚는다. 길이를 모르면 배열이 하나뿐일 때만
    const rows = scene.rows.filter(r => (length === undefined ? true : r.cells.length + r.hidden === length));
    const row = rows.length === 1 ? rows[0] : undefined;
    const len = length ?? (row ? row.cells.length + row.hidden : undefined);
    const who = row?.names.length ? row.names.join(", ") : "이 배열";
    const range = len === undefined ? "0번부터 (길이 − 1)번까지" : len === 0 ? "하나도 없어요 (빈 배열)" : `0번부터 ${len - 1}번까지`;
    return {
      ...base,
      kind: "index",
      title: index !== undefined ? `${index}번 칸은 없어요` : "없는 칸을 열려고 했어요",
      why:
        len === 0
          ? `${who}은(는) 비어 있어서 열 수 있는 칸이 없어요.`
          : index !== undefined
            ? `${who}에는 칸이 ${range} 있는데, ${index}번 칸을 찾았어요.`
            : `${who}에 있는 칸은 ${range}예요. 그 밖의 번호로 칸을 찾았어요.`,
      hint: "칸 번호를 만드는 변수(i, j …)가 마지막에 얼마가 되는지 확인해 보세요. 길이와 같아지면 이미 범위 밖이에요.",
      target: row ? { objectId: row.objectId, index, length: len } : index !== undefined ? { index, length: len } : undefined,
    };
  }

  // ── 0으로 나누기 ──
  if (/ZeroDivision|by zero|divide by zero|SIGFPE/i.test(raw))
    return {
      ...base,
      kind: "zero",
      title: "0으로 나눴어요",
      why: "어떤 수도 0으로 나눌 수 없어요. 나누는 쪽 값이 이 순간 0이었어요.",
      hint: "나누기 전에 나누는 값이 0인지 먼저 확인해 보세요.",
    };

  // ── 없는 이름 ──
  if (/NameError|UnboundLocalError|cannot find symbol|undeclared/i.test(raw)) {
    const v = raw.match(/name '([^']+)'|local variable '([^']+)'|variable '([^']+)'/);
    const varName = v ? v[1] ?? v[2] ?? v[3] : undefined;
    return {
      ...base,
      kind: "name",
      title: varName ? `'${varName}'라는 이름이 아직 없어요` : "아직 없는 이름을 썼어요",
      why: varName ? `${varName}에 값을 넣기(만들기) 전에 먼저 읽으려고 했어요. 무대에도 ${varName} 로봇이 없어요.` : "만들기 전에 이름을 먼저 썼어요.",
      hint: "이름의 철자와, 값을 넣는 줄이 쓰는 줄보다 먼저 실행되는지 확인해 보세요.",
      target: varName ? { varName } : undefined,
    };
  }

  // ── 사전에 없는 키 ──
  if (/KeyError/.test(raw)) {
    const key = msg.replace(/^['"]|['"]$/g, "");
    return {
      ...base,
      kind: "key",
      title: key ? `'${key}' 키가 사전에 없어요` : "사전에 없는 키예요",
      why: "사전(딕셔너리)에 들어 있지 않은 키로 값을 꺼내려고 했어요.",
      hint: "꺼내기 전에 `키 in 사전`으로 있는지 확인하거나 get()을 써 보세요.",
      target: key ? { key } : undefined,
    };
  }

  // ── 아무것도 가리키지 않음 ──
  if (/NullPointer|SIGSEGV|Segmentation|NoneType/i.test(raw))
    return {
      ...base,
      kind: "null",
      title: "아무것도 가리키지 않는 값을 썼어요",
      why: /NoneType/.test(raw)
        ? "값이 None(없음)인 변수를 리스트나 객체처럼 쓰려고 했어요."
        : "가리키는 곳이 없는(null) 변수로 값을 읽거나 쓰려고 했어요. 화살표가 어디에도 닿지 않은 상태예요.",
      hint: "그 변수가 이 순간 무엇을 가리키는지 무대의 화살표로 확인해 보세요.",
    };

  if (/RecursionError|StackOverflow/i.test(raw))
    return {
      ...base,
      kind: "recursion",
      title: "함수가 끝없이 자기 자신을 불렀어요",
      why: "멈추는 조건(기저 사례)에 닿지 못해서 함수 호출이 계속 쌓였어요.",
      hint: "함수가 멈추는 조건과, 부를 때마다 값이 그 조건에 가까워지는지 확인해 보세요.",
    };

  if (/TypeError|ClassCast|incompatible/i.test(raw))
    return { ...base, kind: "type", title: "자료형이 맞지 않아요", why: `서로 함께 쓸 수 없는 종류의 값을 섞었어요. (${msg})`, hint: "무대에서 각 값이 숫자인지 글자인지 확인해 보세요." };
  if (/AttributeError/.test(raw))
    return { ...base, kind: "attribute", title: "그 값에는 없는 기능이에요", why: `이 값의 종류에는 없는 속성이나 함수를 불렀어요. (${msg})`, hint: "값의 종류(리스트, 글자, 숫자 …)에 맞는 함수인지 확인해 보세요." };
  if (/ValueError|NumberFormat/i.test(raw))
    return { ...base, kind: "value", title: "값의 모양이 맞지 않아요", why: `종류는 맞지만 쓸 수 없는 값이 들어왔어요. (${msg})`, hint: "변환하려는 값이 정말 숫자 모양인지 확인해 보세요." };

  return { ...base, kind: "other", title: "실행 중에 문제가 생겼어요", why: msg || raw, hint: "멈춘 줄과 그 직전 단계의 값을 비교해 보세요." };
}
