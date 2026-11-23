// 화면 모델 — 관측 한 단계(Observation)를 "무대에 무엇을 세울까"로 바꾼다. three.js는 모른다.
// 값은 관측된 그대로만 쓴다: 소스 문자열을 분석하거나 빠진 정보를 추측하지 않는다.
import type { TraceObject, TraceValue } from "../../pythonTrace.ts";
import type { Observation, Recording, VisualizationEvent } from "../contracts.ts";
import { isArrayObject } from "../executionEvents.ts";

export type Cell = { text: string; num: number | null };
export type Row = { objectId: string; names: string[]; cells: Cell[]; hidden: number; type: string; links?: string[] };
export type Var = { key: string; name: string; text: string; num: number | null };
export type Sign = { objectId: string; names: string[]; text: string };
export type Scene = { frameId: string | null; stack: string[]; vars: Var[]; rows: Row[]; signs: Sign[] };

export const EMPTY_SCENE: Scene = { frameId: null, stack: [], vars: [], rows: [], signs: [] };

/** 디버거 표시 문자열이 순수한 숫자일 때만 숫자로 읽는다 (크기 표현용) */
export const numOf = (text: string | undefined): number | null => {
  if (!text || !/^-?\d+(\.\d+)?(e-?\d+)?$/i.test(text)) return null;
  const n = Number(text);
  return Number.isFinite(n) ? n : null;
};

const short = (s: string, n = 14) => (s.length > n ? s.slice(0, n - 1) + "…" : s);

/** 값 하나를 짧은 글자로 — 참조는 따라가되 한 단계만 (순환 참조를 펼치지 않는다) */
export function valueText(v: TraceValue | undefined, objects: Readonly<Record<string, TraceObject>>): string {
  if (!v) return "?";
  if (v.kind === "unsupported") return v.text ? `${short(v.text)}` : "(표시 불가)";
  if (v.kind === "primitive") return (v.text ?? "") + (v.truncated ? "…" : "");
  const o = v.object_id ? objects[v.object_id] : undefined;
  if (!o) return "→ ?";
  if (o.unsupported) return `→ ${o.type}`;
  if (o.items) return `[${o.length ?? o.items.length}칸]`;
  return `→ ${o.type}`;
}

function objectSummary(o: TraceObject, objects: Readonly<Record<string, TraceObject>>): string {
  if (o.unsupported) return `${o.type} (표시할 수 없는 값)`;
  if (o.entries) {
    const shown = o.entries.slice(0, 4).map(([k, v]) => `${k}: ${short(valueText(v, objects), 8)}`).join(", ");
    return `${o.type} { ${shown}${o.entries.length > 4 || o.truncated ? ", …" : ""} }`;
  }
  return o.type;
}

/** 관측 한 단계의 무대 — 지금 실행 중인 프레임(가장 안쪽)의 변수만 세운다 */
export function sceneOf(obs: Observation | null): Scene {
  if (!obs || obs.frames.length === 0) return EMPTY_SCENE;
  const top = obs.frames[obs.frames.length - 1];
  const vars: Var[] = [];
  const rowNames = new Map<string, string[]>();
  const signNames = new Map<string, string[]>();
  for (const { name, value } of top.variables) {
    if (value.kind === "reference" && value.object_id) {
      const o = obs.objects[value.object_id];
      if (isArrayObject(o) && !o.unsupported) {
        rowNames.set(o.id, [...(rowNames.get(o.id) ?? []), name]);
        continue;
      }
      if (o && (o.entries || o.unsupported)) {
        signNames.set(o.id, [...(signNames.get(o.id) ?? []), name]);
        continue;
      }
    }
    const text = valueText(value, obs.objects);
    vars.push({ key: `${top.id}:${name}`, name, text, num: value.kind === "primitive" ? numOf(value.text) : null });
  }
  const rows: Row[] = [...rowNames].map(([objectId, names]) => {
    const o = obs.objects[objectId] as TraceObject & { items: TraceValue[] };
    const cells = o.items.map(it => ({ text: valueText(it, obs.objects), num: it.kind === "primitive" ? numOf(it.text) : null }));
    return { objectId, names, cells, hidden: Math.max(0, (o.length ?? cells.length) - cells.length), type: o.type };
  });
  const covered = new Set<string>();
  for (const { name, value } of top.variables) {
    const object = value.object_id ? obs.objects[value.object_id] : undefined;
    const head = object?.entries?.find(([key]) => key === "head")?.[1];
    const root = head?.kind === "reference" ? head.object_id : value.object_id;
    if (!root || covered.has(root)) continue;
    const cells: Cell[] = [];
    const links: string[] = [];
    const indexes = new Map<string, number>();
    for (let id: string | undefined = root; id && !indexes.has(id);) {
      const fields: Map<string, TraceValue> = new Map(obs.objects[id]?.entries);
      const next: TraceValue | undefined = fields.get("next");
      const data = fields.get("value") ?? fields.get("data") ?? fields.get("val");
      if (!next || !data) break;
      indexes.set(id, cells.length);
      covered.add(id);
      cells.push({ text: valueText(data, obs.objects), num: null });
      id = next.kind === "reference" ? next.object_id ?? undefined : undefined;
      const target = id ? indexes.get(id) : undefined;
      links.push(!id ? valueText(next, obs.objects) : target === undefined ? String(cells.length + 1) : String(target + 1));
    }
    if (cells.length) {
      if (Number(links.at(-1)) > cells.length) links[links.length - 1] = "?";
      rows.push({ objectId: `list:${root}`, names: [name], cells, links, hidden: 0, type: "linked-list" });
      if (object) signNames.delete(object.id);
    }
  }
  const signs: Sign[] = [...signNames].map(([objectId, names]) => ({ objectId, names, text: objectSummary(obs.objects[objectId], obs.objects) }));
  return { frameId: top.id, stack: obs.frames.map(f => f.name), vars, rows, signs };
}

/** 실행 내내 같은 잣대 — 배열별 |값| 최댓값·최장 길이, 숫자 변수 전체의 |값| 최댓값 */
export type Scale = { maxAbs: Map<string, number>; maxLen: Map<string, number>; maxVarAbs: number };

export function scaleOf(recording: Recording): Scale {
  const maxAbs = new Map<string, number>();
  const maxLen = new Map<string, number>();
  let maxVarAbs = 0;
  for (const step of recording.steps) {
    for (const o of Object.values(step.objects)) {
      if (!isArrayObject(o)) continue;
      maxLen.set(o.id, Math.max(maxLen.get(o.id) ?? 0, o.items.length));
      for (const it of o.items) {
        const n = it.kind === "primitive" ? numOf(it.text) : null;
        if (n !== null) maxAbs.set(o.id, Math.max(maxAbs.get(o.id) ?? 0, Math.abs(n)));
      }
    }
    for (const f of step.frames)
      for (const v of f.variables) {
        const n = v.value.kind === "primitive" ? numOf(v.value.text) : null;
        if (n !== null) maxVarAbs = Math.max(maxVarAbs, Math.abs(n));
      }
  }
  return { maxAbs, maxLen, maxVarAbs };
}

/** 무대가 이번 이동에서 연출할 움직임 — 모두 current.events에서만 읽는다 */
export type StageMotion = {
  swaps: { objectId: string; i: number; k: number }[];
  sets: { objectId: string; index: number }[];
  inserts: { objectId: string; index: number; count: number }[];
  changedVars: Set<string>;
  /** 이번 단계에서 새로 생긴 변수 (신규 표시용) */
  addedVars: Set<string>;
  /** 바뀐 칸·변수의 "이전 → 새 값" 글자. 칸은 `${objectId}:${index}`, 변수는 변수 key */
  diffs: Map<string, { from: string; to: string }>;
  crash: boolean;
};

export const NO_MOTION: StageMotion = { swaps: [], sets: [], inserts: [], changedVars: new Set(), addedVars: new Set(), diffs: new Map(), crash: false };

export function motionOf(events: readonly VisualizationEvent[], obs: Observation | null): StageMotion {
  const m: StageMotion = { swaps: [], sets: [], inserts: [], changedVars: new Set(), addedVars: new Set(), diffs: new Map(), crash: obs?.event === "exception" };
  const objects = obs?.objects ?? {};
  for (const e of events) {
    if (e.type === "array.swap") m.swaps.push({ objectId: e.target.objectId, i: e.indices[0], k: e.indices[1] });
    else if (e.type === "array.set") {
      m.sets.push({ objectId: e.target.objectId, index: e.index });
      m.diffs.set(`${e.target.objectId}:${e.index}`, { from: valueText(e.before, objects), to: valueText(e.after, objects) });
    }
    else if (e.type === "array.insert") m.inserts.push({ objectId: e.target.objectId, index: e.index, count: e.values.length });
    else if (e.type === "variable.change" && e.change.kind === "changed") {
      m.changedVars.add(e.change.id);
      m.diffs.set(e.change.id, { from: valueText(e.change.before, objects), to: valueText(e.change.after, objects) });
    }
    else if (e.type === "variable.change" && e.change.kind === "added") m.addedVars.add(e.change.id);
  }
  return m;
}
