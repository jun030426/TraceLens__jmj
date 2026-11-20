// 11/18: 랜딩 실습 미리보기의 시각화를 실제 앱 3D 무대(visualization/screen/CharacterStage)로 보여 줘요.
// 미리보기는 실제 실행 기록 대신 지금 장면(리스트 + 변수)만 손으로 만들어 넘겨요.
import { useMemo } from "react";
import { CharacterStage } from "./PreviewCharacterStage";
import { NO_MOTION, numOf, type Scene, type Scale, type StageMotion } from "../visualization/screen/sceneModel";

const ZOOM = 0.8; // 무대를 더 가까이

export type Stage3DVar = { name: string; v: number | null; tag?: "신규" | "변경" };

export default function Stage3DPreview({
  name,
  arr,
  vars,
  cur,
  stepKey,
}: {
  cur: number;
  name: string;
  arr: number[];
  vars: Stage3DVar[];
  /** 장면이 바뀔 때마다 달라지는 값 — 바뀌면 무대가 움직임을 다시 연출해요 */
  stepKey: string;
}) {
  const input = useMemo(() => {
    const scene: Scene = {
      frameId: "main",
      stack: ["main"],
      rows: [
        {
          objectId: name,
          names: [], // 배열을 가리키는 로봇 · 화살표는 빼서 무대를 좁고 크게
          cells: arr.map((v) => ({ text: String(v), num: v })),
          hidden: 0,
          type: "list",
        },
      ],
      vars: vars
        .filter((x) => x.v !== null)
        .map((x) => ({ key: `main:${x.name}`, name: x.name, text: String(x.v), num: numOf(String(x.v)) })),
      signs: [],
    };
    const marks: StageMotion = {
      ...NO_MOTION,
      changedVars: new Set(vars.filter((x) => x.tag === "변경").map((x) => `main:${x.name}`)),
      addedVars: new Set(vars.filter((x) => x.tag === "신규").map((x) => `main:${x.name}`)),
      diffs: new Map(),
    };
    const scale: Scale = {
      maxAbs: new Map([[name, Math.max(...arr.map(Math.abs))]]),
      maxLen: new Map([[name, arr.length]]),
      maxVarAbs: Math.max(1, ...vars.map((x) => Math.abs(x.v ?? 0))),
    };
    return { before: scene, after: scene, motion: marks, marks, scale, preview: { cur: cur >= 0 ? { objectId: name, index: cur } : null, zoom: ZOOM } };
  }, [name, arr, vars, cur]);

  return (
    <div className="sp-stage3d">
      <CharacterStage input={input} animKey={stepKey} durationMs={650} />
    </div>
  );
}
