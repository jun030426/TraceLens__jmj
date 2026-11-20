// 실행 줄 주석 — 시각화의 "▶ 다음 N번째 줄" 옆에 그 줄이 하는 일을 코드 주석처럼 짧게 붙인다.
// 줄에 직접 쓴 주석(# … / // …)이 있으면 그걸 그대로 쓰고, 없으면 줄 모양을 보고 한 문장으로 만든다.
// 실행 결과(값)가 아니라 코드 글자만 보고 말한다 — 아직 실행 전인 "다음 줄"에도 쓸 수 있게.

const BLANK = /__blank(\d+)__/g;
const circled = (n: number) => (n >= 1 && n <= 20 ? String.fromCodePoint(0x2460 + n - 1) : `(${n})`);
const show = (s: string) => s.replace(BLANK, (_, n) => `빈칸 ${circled(Number(n))}`).trim();

/** 코드 끝 주석을 떼어 낸다 (문자열 안의 #, // 는 건드리지 않는다) */
export function splitComment(line: string): { code: string; comment: string } {
  let quote: string | null = null;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (quote) {
      if (ch === "\\") i++;
      else if (ch === quote) quote = null;
      continue;
    }
    if (ch === '"' || ch === "'") quote = ch;
    else if (ch === "#" || (ch === "/" && line[i + 1] === "/")) {
      return { code: line.slice(0, i).trimEnd(), comment: line.slice(i).replace(/^(#|\/\/)\s*/, "").trim() };
    }
  }
  return { code: line, comment: "" };
}

/** 이 줄이 하는 일을 한 문장으로. 알 수 없는 모양이면 빈 문자열 */
export function lineComment(raw: string): string {
  const { code, comment } = splitComment(raw);
  if (comment) return comment;
  const c = code.trim().replace(/;$/, "").trim();
  if (!c) return "";
  let m: RegExpMatchArray | null;

  // 반복
  if ((m = c.match(/^for\s+(.+?)\s+in\s+range\((.*)\)\s*:$/))) return `${show(m[1])}를 range(${show(m[2])}) 범위에서 하나씩 바꿔 가며 반복해요`;
  if ((m = c.match(/^for\s+(.+?)\s+in\s+(.+):$/))) return `${show(m[2])}에서 값을 하나씩 꺼내 ${show(m[1])}에 담으며 반복해요`;
  if ((m = c.match(/^for\s*\((?:[\w<>\[\]]+\s+)?(\w+)\s*:\s*(.+)\)\s*\{?$/))) return `${show(m[2])}에서 값을 하나씩 꺼내 ${m[1]}에 담으며 반복해요`;
  if ((m = c.match(/^for\s*\((.*);(.*);(.*)\)\s*\{?$/))) return `${show(m[2])}인 동안 반복해요 (한 바퀴마다 ${show(m[3])})`;
  if ((m = c.match(/^while\s*\(?(.+?)\)?\s*[:{]?$/))) return `${show(m[1])}이(가) 참인 동안 반복해요`;
  // 조건
  if ((m = c.match(/^(?:if|elif|else\s+if)\s*\(?(.+?)\)?\s*[:{]?$/)) && !/^if\s*\(.*\)\s*\S+.*;?$/.test(c.replace(/\{$/, ""))) return `${show(m[1])}이(가) 참인지 확인해요`;
  if ((m = c.match(/^if\s*\((.+?)\)\s*(.+)$/))) return `${show(m[1])}이(가) 참이면 ${show(m[2])}을(를) 실행해요`;
  if (/^(\}\s*)?else\s*[:{]?$/.test(c)) return "위 조건이 모두 거짓일 때 실행해요";
  // 함수
  if ((m = c.match(/^def\s+(\w+)\s*\((.*)\)\s*:$/))) return `함수 ${m[1]}(${m[2]})를 만들어요`;
  if ((m = c.match(/^return\s*(.*)$/))) return m[1] ? `${show(m[1])}의 값을 돌려주고 함수를 끝내요` : "함수를 끝내요";
  if (c === "break") return "반복을 바로 멈춰요";
  if (c === "continue") return "이번 바퀴를 건너뛰고 다음 바퀴로 가요";
  // 출력
  if ((m = c.match(/^(?:print|System\.out\.println|System\.out\.print|printf)\s*\((.*)\)$/))) return m[1] ? `${show(m[1])}을(를) 화면에 출력해요` : "빈 줄을 출력해요";
  // 리스트 메서드
  if ((m = c.match(/^([\w.\[\]]+)\.append\((.*)\)$/))) return `${show(m[1])} 끝에 ${show(m[2])}을(를) 붙여요`;
  if ((m = c.match(/^([\w.\[\]]+)\.pop\((.*)\)$/))) return `${show(m[1])}에서 값을 하나 꺼내요`;
  // 값 바꾸기
  if ((m = c.match(/^([\w.\[\]]+)\s*\+=\s*(.+)$/))) return `${show(m[1])}에 ${show(m[2])}을(를) 더해요`;
  if ((m = c.match(/^([\w.\[\]]+)\s*-=\s*(.+)$/))) return `${show(m[1])}에서 ${show(m[2])}을(를) 빼요`;
  if ((m = c.match(/^([\w.\[\]]+)\s*\*=\s*(.+)$/))) return `${show(m[1])}에 ${show(m[2])}을(를) 곱해요`;
  if ((m = c.match(/^([\w.\[\]]+)\s*(\+\+|--)$/))) return `${m[1]}을(를) 1 ${m[2] === "++" ? "늘려요" : "줄여요"}`;
  if ((m = c.match(/^(?:(?:const|let|var|final|int|long|double|float|char|boolean|String|auto)(?:\[\])?\s+)?([\w.\[\], ]+?)\s*=\s*(.+)$/)) && !/[=!<>]=/.test(c.split("=")[0] + "=")) {
    const name = show(m[1]);
    const v = m[2].trim();
    if (/^[\[{]/.test(v)) return `${name}에 ${v.startsWith("{") && !/:/.test(v) ? "배열을" : v.startsWith("{") ? "딕셔너리를" : "리스트를"} 만들어 담아요`;
    if (/^(-?\d+(\.\d+)?|"[^"]*"|'[^']*'|True|False|true|false|None|null)$/.test(v)) return `${name}에 ${v}을(를) 넣어요`;
    return `${name}에 ${show(v)}의 값을 넣어요`;
  }
  return "";
}
