// 캐릭터 3D 무대 — 「파이썬 자료구조 캐릭터 시각화 설계서」의 캐릭터로 실행 상태를 보여 준다.
//   · 배열/리스트 원소 = 젤리 (몸 앞 흰 배지에 값, 아래 선반에 칸 번호)
//   · 스택(이름에 stack/스택) 원소 = 펭귄 (아래에서 위로 쌓이고 맨 위에 top 표시)
//   · 변수 = 로봇 (몸통에 이름표, 머리 위 말풍선에 값). 배열을 가리키는 변수는 관(튜브)으로 배열에 이어진다
//   · 변화는 색만이 아니라 글자 태그(신규·교환·변경)로도 알린다
// 그리는 상태는 늘 after(=current) 장면이다. before와 motion은 순방향 한 단계 이동에서만 움직임을 연출한다.
// 태그(marks)는 움직임과 따로, 이번 단계 이벤트에서 늘 읽는다 — 동작 줄이기 설정이어도 무엇이 바뀌었는지 보인다.
import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { RoomEnvironment } from "three/examples/jsm/environments/RoomEnvironment.js";
import { nameSprite, setSpriteText, signTexture, makeSign, textTexture } from "../../visualizer/stage3d/models";
import type { Row, Scale, Scene, StageMotion } from "./sceneModel";
import type { ErrorInfo } from "./errorModel";

// error: 이 단계가 예외 단계일 때만 채운다 — 무대가 "어디서·왜" 멈췄는지 짚어 준다
// pause: 빈칸 채우기 실습에서 안 채운 빈칸 앞에 멈췄을 때 무대 위에 띄울 안내 (오류가 아니라 보라색)
export type CharacterStageInput = { before: Scene; after: Scene; motion: StageMotion; marks: StageMotion; scale: Scale; error?: ErrorInfo | null; pause?: string | null };

const C = {
  background: "#f6f1f8",
  floor: "#efe7f3",
  panel: "#efe4f1",
  shelf: "#d9c6e0",
  jelly: "#9fdcbf",
  fresh: "#ffb994",
  cur: "#93bff2",
  robot: "#ddd5ee",
  accent: "#b58ad6",
  wire: "#7b4a80",
  peng: "#3d3a55",
  beak: "#f2a65a",
  ink: "#3b3f52",
  stop: "#d2402e",
};

// [다크 모드] 무대 바탕 · 바닥 · 선반만 보랏빛 밤 톤으로 — 캐릭터 색은 그대로 둬요 (화면 모드가 바뀌면 무대를 새로 그려요)
const STAGE_DARK = { background: "#1c1524", floor: "#241b2e", panel: "#2f2540", shelf: "#4a3b5f", err: "#3a1c24", ground: "#3a2b4a" };
const isDarkTheme = () => typeof document !== "undefined" && document.documentElement.dataset.theme === "dark";

const SP = 1.25; // 칸 간격
const ROW_GAP = 3.6;
const JELLY = 0.95;
const ROBOT = 1.0;
const VAR_GAP = 1.55;
const BOT_ROW = 6; // 로봇 한 줄 최대 인원
const BOT_LINE_GAP = 2.3;

const clamp01 = (p: number) => Math.min(1, Math.max(0, p));
const bump = (p: number) => Math.sin(Math.PI * clamp01(p));
const ease = (p: number) => 1 - Math.pow(1 - clamp01(p), 3);
const inOut = (p: number) => (p < 0.5 ? 2 * p * p : 1 - Math.pow(-2 * p + 2, 2) / 2);
const backOut = (p: number) => {
  const c = 1.7;
  const x = clamp01(p) - 1;
  return 1 + (c + 1) * x * x * x + c * x * x;
};
const lerp = (a: number, b: number, t: number) => a + (b - a) * t;

const isStackRow = (row: Row) => row.names.some(n => /stack|스택/i.test(n));

// ── 재질·모양 (한 번만 만든다) ─────────────────────────────────────────

const mat = (color: string, o: THREE.MeshPhysicalMaterialParameters = {}) =>
  new THREE.MeshPhysicalMaterial({ color, roughness: 0.32, metalness: 0, clearcoat: 0.6, clearcoatRoughness: 0.25, ...o });

let blob: THREE.LatheGeometry | null = null;
/** 젤리 몸 — 아래가 평평한 물방울 */
const blobGeo = () =>
  (blob ??= new THREE.LatheGeometry(
    [[0, 0], [0.4, 0.005], [0.5, 0.09], [0.52, 0.3], [0.49, 0.55], [0.42, 0.76], [0.3, 0.92], [0.15, 1], [0, 1.02]].map(([x, y]) => new THREE.Vector2(x, y)),
    40,
  ));

const pill = (text: string, color = C.ink, bg = "rgba(255,255,255,0.96)") =>
  new THREE.Sprite(new THREE.SpriteMaterial({ map: textTexture(text, { color, bg, pill: true, w: 256, h: 112, weight: 800 }), depthWrite: false, toneMapped: false }));
const setPill = (s: THREE.Sprite, text: string, color = C.ink, bg = "rgba(255,255,255,0.96)") => {
  (s.material as THREE.SpriteMaterial).map = textTexture(text, { color, bg, pill: true, w: 256, h: 112, weight: 800 });
};

type Char = {
  kind: "jelly" | "peng" | "robot";
  root: THREE.Group; // 자리
  body: THREE.Group; // 뛰기·눌림
  eyes: THREE.Mesh[];
  tint?: THREE.MeshPhysicalMaterial;
  ball?: THREE.Mesh;
  flippers?: THREE.Mesh[];
  value: THREE.Sprite; // 값 배지
  tag: THREE.Sprite; // 신규/교환/변경
  extra?: THREE.Sprite; // 칸 번호 또는 이름표
  top: number;
  text: string;
  tagText: string;
  seed: number;
  /** 흐리게 할 재질과 원래 불투명도 */
  mats?: { m: THREE.Material; base: number }[];
  dim?: number;
};

const TAG = { fresh: "#c0541c", swap: "#2a64b0", change: "#6b2fb3" };
// 변화 말풍선 — "2 → 5"처럼 이전 값과 새 값을 함께 보여 준다 (길면 글자를 줄여 맞춘다)
const tagTexture = (text: string, bg: string) => textTexture(text, { color: "#ffffff", bg, pill: true, w: 448, h: 112, weight: 800 });

function makeTag(): THREE.Sprite {
  const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: tagTexture("신규", TAG.fresh), depthWrite: false, toneMapped: false }));
  s.scale.set(1.15, 0.29, 1);
  s.visible = false;
  return s;
}

function setTag(c: Char, text: string, bg: string = TAG.change) {
  const key = text + bg;
  if (c.tagText === key) return;
  c.tagText = key;
  c.tag.visible = !!text;
  if (text) (c.tag.material as THREE.SpriteMaterial).map = tagTexture(text, bg);
}

/** 이번 단계에서 안 바뀐 캐릭터는 흐리게 — 바뀐 곳에 눈이 가게 한다. 변화 말풍선(tag)은 흐리지 않는다 */
function setDim(c: Char, target: number, instant: boolean) {
  if (!c.mats) {
    c.mats = [];
    c.dim = 0;
    c.root.traverse(o => {
      if (o === c.tag) return;
      const m = (o as THREE.Mesh).material as THREE.Material | undefined;
      if (!m || Array.isArray(m)) return;
      m.transparent = true;
      c.mats!.push({ m, base: m.opacity });
    });
  }
  c.dim = instant ? target : (c.dim ?? 0) + (target - (c.dim ?? 0)) * 0.15;
  const k = 1 - 0.68 * c.dim;
  for (const { m, base } of c.mats) m.opacity = base * k;
}

function setValue(c: Char, text: string, changed = false) {
  const key = text + (changed ? "*" : "");
  if (c.text === key) return;
  c.text = key;
  setPill(c.value, text, changed ? "#ffffff" : C.ink, changed ? C.wire : "rgba(255,255,255,0.96)");
}

function makeJelly(seed: number, index: number): Char {
  const root = new THREE.Group();
  const body = new THREE.Group();
  root.add(body);
  const tint = mat(C.jelly, { roughness: 0.18, clearcoat: 1, clearcoatRoughness: 0.08, transparent: true, opacity: 0.93 });
  const shell = new THREE.Mesh(blobGeo(), tint);
  shell.scale.set(1, 1, 0.86);
  shell.castShadow = true;
  body.add(shell);
  const eyeM = new THREE.MeshStandardMaterial({ color: "#221a24", roughness: 0.25 });
  const cheekM = new THREE.MeshStandardMaterial({ color: "#f29bb0", transparent: true, opacity: 0.55 });
  const eyes: THREE.Mesh[] = [];
  for (const sx of [-0.14, 0.14]) {
    const e = new THREE.Mesh(new THREE.SphereGeometry(0.052, 16, 12), eyeM);
    e.position.set(sx, 0.62, 0.405);
    e.scale.set(1, 1.25, 0.6);
    body.add(e);
    eyes.push(e);
    const ck = new THREE.Mesh(new THREE.SphereGeometry(0.06, 12, 10), cheekM);
    ck.position.set(sx * 1.75, 0.52, 0.38);
    ck.scale.set(1, 0.55, 0.3);
    body.add(ck);
  }
  const mouth = new THREE.Mesh(new THREE.TorusGeometry(0.055, 0.013, 8, 16, Math.PI), eyeM);
  mouth.rotation.z = Math.PI;
  mouth.position.set(0, 0.55, 0.43);
  body.add(mouth);
  const hl = new THREE.Mesh(new THREE.SphereGeometry(0.09, 12, 10), new THREE.MeshBasicMaterial({ color: "#ffffff", transparent: true, opacity: 0.55 }));
  hl.position.set(-0.2, 0.82, 0.3);
  hl.scale.set(1.4, 0.7, 0.5);
  body.add(hl);
  // 값 배지 — 몸 앞 아래쪽
  const value = pill("");
  value.scale.set(0.62, 0.27, 1);
  value.position.set(0, 0.27, 0.62);
  body.add(value);
  const tag = makeTag();
  root.add(tag);
  const idx = new THREE.Sprite(new THREE.SpriteMaterial({ map: textTexture(String(index), { color: "#6f6386", w: 128, h: 128, weight: 700 }), depthWrite: false, toneMapped: false }));
  idx.scale.set(0.32, 0.32, 1);
  root.add(idx);
  return { kind: "jelly", root, body, eyes, tint, value, tag, extra: idx, top: 1.05, text: "", tagText: "", seed };
}

function makePenguin(seed: number): Char {
  const root = new THREE.Group();
  const body = new THREE.Group();
  root.add(body);
  const dark = mat(C.peng, { roughness: 0.45, clearcoat: 0.4 });
  const white = mat("#ffffff", { roughness: 0.5 });
  const orange = mat(C.beak, { roughness: 0.5 });
  const b = new THREE.Mesh(new THREE.SphereGeometry(0.5, 32, 24), dark);
  b.scale.set(1, 0.98, 0.82);
  b.position.y = 0.5;
  b.castShadow = true;
  body.add(b);
  const belly = new THREE.Mesh(new THREE.SphereGeometry(0.36, 28, 20), white);
  belly.scale.set(0.95, 1, 0.5);
  belly.position.set(0, 0.44, 0.3);
  body.add(belly);
  const eyes: THREE.Mesh[] = [];
  for (const sx of [-0.13, 0.13]) {
    const w = new THREE.Mesh(new THREE.SphereGeometry(0.072, 14, 10), white);
    w.position.set(sx, 0.74, 0.33);
    body.add(w);
    const p = new THREE.Mesh(new THREE.SphereGeometry(0.038, 12, 8), new THREE.MeshStandardMaterial({ color: "#1d1a26" }));
    p.position.set(sx, 0.74, 0.39);
    body.add(p);
    eyes.push(p);
  }
  const beak = new THREE.Mesh(new THREE.ConeGeometry(0.065, 0.15, 14), orange);
  beak.rotation.x = Math.PI / 2;
  beak.position.set(0, 0.64, 0.43);
  body.add(beak);
  const flippers: THREE.Mesh[] = [];
  for (const sx of [-1, 1]) {
    const f = new THREE.Mesh(new THREE.SphereGeometry(0.2, 16, 12), dark);
    f.scale.set(0.32, 1, 0.6);
    f.position.set(sx * 0.47, 0.5, 0);
    f.rotation.z = sx * 0.35;
    body.add(f);
    flippers.push(f);
    const ft = new THREE.Mesh(new THREE.SphereGeometry(0.1, 12, 8), orange);
    ft.scale.set(1, 0.32, 1.3);
    ft.position.set(sx * 0.16, 0.03, 0.2);
    body.add(ft);
  }
  const value = pill("");
  value.scale.set(0.62, 0.27, 1);
  value.position.set(0, 0.4, 0.62);
  body.add(value);
  const tag = makeTag();
  root.add(tag);
  return { kind: "peng", root, body, eyes, flippers, value, tag, top: 1.05, text: "", tagText: "", seed };
}

function makeRobot(seed: number, name: string): Char {
  const root = new THREE.Group();
  const body = new THREE.Group();
  root.add(body);
  const rm = mat(C.robot, { roughness: 0.35, metalness: 0.15, clearcoat: 0.8 });
  const dark = new THREE.MeshStandardMaterial({ color: "#2b2029", roughness: 0.3 });
  const head = new THREE.Mesh(new THREE.BoxGeometry(0.72, 0.42, 0.5), rm);
  head.position.y = 0.92;
  head.castShadow = true;
  body.add(head);
  const eyes: THREE.Mesh[] = [];
  for (const sx of [-0.16, 0.16]) {
    const e = new THREE.Mesh(new THREE.BoxGeometry(0.1, 0.12, 0.02), dark);
    e.position.set(sx, 0.93, 0.26);
    body.add(e);
    eyes.push(e);
  }
  const ant = new THREE.Mesh(new THREE.CylinderGeometry(0.018, 0.018, 0.18, 8), rm);
  ant.position.y = 1.21;
  body.add(ant);
  const ball = new THREE.Mesh(new THREE.SphereGeometry(0.055, 14, 10), mat(C.accent, { emissive: C.accent, emissiveIntensity: 0.35 }));
  ball.position.y = 1.32;
  body.add(ball);
  const torso = new THREE.Mesh(new THREE.BoxGeometry(0.64, 0.48, 0.44), rm);
  torso.position.y = 0.38;
  torso.castShadow = true;
  body.add(torso);
  // 몸통 이름표
  const plate = nameSprite(name, "#5b3a8c");
  plate.scale.set(0.9, 0.27, 1);
  plate.position.set(0, 0.38, 0.5);
  body.add(plate);
  // 머리 위 값 말풍선
  const value = pill("");
  value.scale.set(0.78, 0.34, 1);
  value.position.set(0, 1.68, 0);
  body.add(value);
  const tag = makeTag();
  root.add(tag);
  return { kind: "robot", root, body, eyes, ball, value, tag, extra: plate, top: 2.0, text: "", tagText: "", seed };
}

/** 이름표 스프라이트의 글자를 바꾼다 (같으면 그대로) */
function renamePlate(c: Char, name: string) {
  if (!c.extra || c.extra.userData.name === name) return;
  c.extra.userData.name = name;
  setSpriteText(c.extra, name, "#5b3a8c");
}

/** 쉴 때의 숨쉬기·깜빡임 — 동작 줄이기면 멈춘다 */
function idle(c: Char, t: number, calm: boolean) {
  const ph = c.seed * 0.7;
  if (calm) {
    c.eyes.forEach(e => (e.scale.y = c.kind === "jelly" ? 1.25 : 1));
    return;
  }
  const blink = (t + c.seed * 0.37) % 3.6 < 0.12 ? 0.15 : 1;
  c.eyes.forEach(e => (e.scale.y = (c.kind === "jelly" ? 1.25 : 1) * blink));
  if (c.kind === "robot" && c.ball) {
    c.ball.position.y = 1.32 + Math.sin(t * 3 + ph) * 0.025;
    c.body.rotation.y = Math.sin(t * 0.8 + ph) * 0.08;
  }
  if (c.kind === "peng") c.body.rotation.z = Math.sin(t * 1.6 + ph) * 0.04;
}

/** 젤리 숨쉬기 — 가로세로가 번갈아 살짝 부푼다 */
const breathe = (t: number, seed: number) => 1 + Math.sin(t * 2.2 + seed * 0.7) * 0.025;

function setSquash(c: Char, sy: number) {
  const k = 1 / Math.sqrt(Math.max(0.2, sy));
  c.body.scale.set(k, sy, k);
}

// ── 관(튜브) — 변수 로봇에서 배열 판으로 ─────────────────────────────

// 관 = "이 변수가 저 배열을 가리킨다(참조)"는 뜻. 값을 복사해 든 게 아니라 배열이 있는 곳을 알고 있다는 표시다.
type Wire = { tube: THREE.Mesh; head: THREE.Mesh; label: THREE.Sprite; key: string };
const ARROW = "#8a3fd1";
const wireMat = new THREE.MeshStandardMaterial({ color: ARROW, roughness: 0.3, emissive: ARROW, emissiveIntensity: 0.35 });

function setWire(w: Wire, a: THREE.Vector3, b: THREE.Vector3, grow: number) {
  // 끝점과 진행도가 그대로면 관을 다시 만들지 않는다 (매 프레임 새 도형을 만들지 않게)
  const sig = [a.x, a.y, a.z, b.x, b.y, b.z, grow].map(v => v.toFixed(3)).join(",");
  if (w.tube.userData.sig === sig) return;
  w.tube.userData.sig = sig;
  const mid = a.clone().lerp(b, 0.5);
  mid.y += 1.1;
  const curve = new THREE.QuadraticBezierCurve3(a, mid, b);
  w.tube.userData.curve = curve; // 마우스가 화살표 위에 있는지 잴 때 쓴다
  w.tube.geometry.dispose();
  w.tube.geometry = new THREE.TubeGeometry(curve, 40, 0.075, 10, false);
  const count = w.tube.geometry.index!.count;
  w.tube.geometry.setDrawRange(0, Math.floor(count * clamp01(grow)));
  const tan = curve.getTangent(1).normalize();
  w.head.visible = grow >= 1;
  w.head.position.copy(b).addScaledVector(tan, -0.22); // 뾰족한 끝이 배열 판에 닿게
  w.head.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), tan);
  w.label.visible = grow >= 1 && w.label.userData.first === true;
  w.label.position.copy(curve.getPoint(0.86)).add(new THREE.Vector3(0, 0.4, 0));
}

// ── 무대 ─────────────────────────────────────────────────────────────

export function CharacterStage({
  input,
  animKey,
  durationMs,
  reducedMotion = false,
  onArrowHover,
}: {
  input: CharacterStageInput;
  animKey: unknown;
  durationMs: number;
  reducedMotion?: boolean;
  /** 보라색 "가리킴" 화살표 위에 마우스가 올라오면 무대 안 좌표(px), 벗어나면 null */
  onArrowHover?: (at: { x: number; y: number } | null) => void;
}) {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef(input);
  const calmRef = useRef(reducedMotion);
  const arrowHoverRef = useRef(onArrowHover);
  arrowHoverRef.current = onArrowHover;
  const animRef = useRef({ start: 0, duration: durationMs });
  const [failed, setFailed] = useState(false);

  inputRef.current = input;
  calmRef.current = reducedMotion;
  useEffect(() => {
    animRef.current = { start: performance.now(), duration: durationMs };
  }, [animKey, durationMs]);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
    } catch {
      setFailed(true);
      return;
    }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.0;
    host.appendChild(renderer.domElement);

    const dk = isDarkTheme();
    const stageBg = dk ? STAGE_DARK.background : C.background;
    const scene = new THREE.Scene();
    scene.background = new THREE.Color(stageBg);
    scene.fog = new THREE.Fog(stageBg, 24, 52);
    const pmrem = new THREE.PMREMGenerator(renderer);
    const envTex = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
    scene.environment = envTex;
    scene.environmentIntensity = 0.6;
    scene.add(new THREE.HemisphereLight("#ffffff", dk ? STAGE_DARK.ground : "#e6d9ee", 0.7));
    const sun = new THREE.DirectionalLight("#ffffff", 1.5);
    sun.castShadow = true;
    sun.shadow.mapSize.set(2048, 2048);
    Object.assign(sun.shadow.camera, { left: -14, right: 14, top: 14, bottom: -14 });
    sun.shadow.radius = 6;
    sun.shadow.bias = -0.0005;
    scene.add(sun, sun.target);
    const floor = new THREE.Mesh(new THREE.PlaneGeometry(200, 200), new THREE.MeshStandardMaterial({ color: dk ? STAGE_DARK.floor : C.floor, roughness: 1 }));
    floor.rotation.x = -Math.PI / 2;
    floor.receiveShadow = true;
    scene.add(floor);

    const camera = new THREE.PerspectiveCamera(34, 1, 0.1, 200);
    const camPos = new THREE.Vector3(0, 6, 11);
    const camLook = new THREE.Vector3(0, 0.6, 0);
    const lookCur = camLook.clone();
    let firstFrame = true;

    const resize = () => {
      const w = host.clientWidth || 1;
      const h = host.clientHeight || 1;
      renderer.setSize(w, h, false);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
    };
    resize();
    const ro = new ResizeObserver(resize);
    ro.observe(host);

    const cells = new Map<string, Char>();
    const robots = new Map<string, Char>();
    const panels = new Map<string, { g: THREE.Group; board: THREE.Mesh; seats: THREE.Mesh[]; label: THREE.Sprite; topFlag: THREE.Sprite }>();
    const wires = new Map<string, Wire>();
    const signs = new Map<string, THREE.Sprite>();
    const seatGeo = new THREE.BoxGeometry(1, 1, 1);
    const seatMat = mat(dk ? STAGE_DARK.shelf : C.shelf, { roughness: 0.6, clearcoat: 0.2 });
    const freshSeat = mat(C.fresh, { roughness: 0.6, clearcoat: 0.2 });
    const boardMat = mat(dk ? STAGE_DARK.panel : C.panel, { roughness: 0.7, clearcoat: 0.2 });
    const jellyBase = new THREE.Color(C.jelly);
    const jellyFresh = new THREE.Color(C.fresh);
    const jellyCur = new THREE.Color(C.cur);
    const clock = new THREE.Clock();
    let raf = 0;
    let seedN = 0;

    // ── 오류 장면 소품 (한 번만 만든다) ──
    const ERR = "#d2402e";
    const ghostMat = new THREE.MeshStandardMaterial({ color: ERR, transparent: true, opacity: 0.38, roughness: 0.5, depthWrite: false });
    const ghostLine = new THREE.MeshBasicMaterial({ color: ERR, wireframe: true, transparent: true, opacity: 0.55 });
    const ghostCell = new THREE.Group(); // 없는 칸 — 빨간 반투명 선반 + 빈 젤리 윤곽
    const ghostSeat = new THREE.Mesh(seatGeo, ghostMat);
    ghostSeat.scale.set(1.1, 0.24, 1.15);
    ghostSeat.position.y = 0.12;
    const ghostBlob = new THREE.Mesh(blobGeo(), ghostLine);
    ghostBlob.scale.set(0.95, 0.95, 0.82);
    ghostBlob.position.y = 0.24;
    const ghostLabel = pill("✕ 없는 칸", "#ffffff", ERR);
    ghostLabel.scale.set(1.5, 0.36, 1);
    ghostLabel.position.y = 1.55;
    ghostCell.add(ghostSeat, ghostBlob, ghostLabel);
    const rangeLabel = pill("", "#ffffff", ERR); // "칸은 0~3번까지" — 판 위
    rangeLabel.scale.set(1.9, 0.34, 1);
    const banner = new THREE.Sprite(new THREE.SpriteMaterial({ depthWrite: false, toneMapped: false })); // 무대 맨 위 "⚠ 오류: …"
    banner.scale.set(4.4, 0.62, 1);
    const errBg = new THREE.Color(dk ? STAGE_DARK.err : "#fbe6e6");
    const calmBg = new THREE.Color(stageBg);

    const draw = ({ before, after, motion, marks, scale, error, pause }: CharacterStageInput, p: number, t: number) => {
      const calm = calmRef.current;
      const used = { c: new Set<string>(), r: new Set<string>(), p: new Set<string>(), w: new Set<string>(), s: new Set<string>() };
      let minX = -2.5;
      let maxX = 2.5;
      let minZ = 0;
      let maxZ = 0;
      let maxY = 1.5;
      const extend = (x: number, z: number, r = 0.8, y = 1.5) => {
        minX = Math.min(minX, x - r);
        maxX = Math.max(maxX, x + r);
        minZ = Math.min(minZ, z);
        maxZ = Math.max(maxZ, z);
        maxY = Math.max(maxY, y);
      };
      const add = (o: THREE.Object3D) => {
        if (o.parent) return;
        // 글자(값·이름·태그)는 캐릭터나 판 뒤에 가려지지 않게 늘 맨 위에 그린다
        o.traverse(x => {
          if (x instanceof THREE.Sprite) {
            x.material.depthTest = false;
            x.renderOrder = 10;
          }
        });
        scene.add(o);
      };
      const rowAnchor = new Map<string, THREE.Vector3>(); // 관이 닿는 판 왼쪽 끝

      // 배치 — 겹치지 않게: 배열은 앞에서 뒤로 줄을 세우고, 키가 큰 스택 탑은 배열·로봇 줄의 오른쪽 옆으로 뺀다.
      // (스택을 앞에 두면 뒤에 있는 로봇과 배열을 가린다)
      const arrRows = after.rows.filter(r => !isStackRow(r));
      const stackRows = after.rows.filter(isStackRow);
      const widthOf = (row: Row) => {
        const len = Math.max(row.cells.length, scale.maxLen.get(row.objectId) ?? 0, 1);
        const unit = len > 9 ? 9 / len : 1;
        return Math.max(1.6, row.cells.length * SP * unit + 0.4);
      };
      const botCount = after.vars.length + after.rows.reduce((k, r) => k + r.names.length, 0);
      const botSpan = (Math.min(botCount, BOT_ROW) - 1 + (botCount > BOT_ROW ? 0.5 : 0)) * VAR_GAP + 1;
      const leftW = Math.max(arrRows.length ? Math.max(...arrRows.map(widthOf)) : 0, after.vars.length || arrRows.length ? botSpan : 0);
      const placeOf = (row: Row) => {
        const a = arrRows.indexOf(row);
        if (a >= 0) return { ox: 0, z: -a * ROW_GAP };
        const k = stackRows.indexOf(row);
        return leftW > 0 ? { ox: leftW / 2 + 1.5 + k * 2.4, z: 0 } : { ox: (k - (stackRows.length - 1) / 2) * 2.6, z: 0 };
      };

      // 오류 단계에서 짚을 대상이 있으면 나머지를 흐리게 한다 (변화 강조와 같은 방식)
      const errTarget = error?.target;
      const errFocus = !!errTarget && (!!errTarget.objectId || !!errTarget.varName);
      const anyChange = errFocus || marks.sets.length + marks.swaps.length + marks.inserts.length + marks.changedVars.size + marks.addedVars.size > 0;
      let ghostUsed = false;
      let rangeUsed = false;
      // 오류 순간 — 모두 깜짝 놀라 한 번 몸을 떤다 (동작 줄이기면 생략)
      const shiver = error && !calm && p < 1 ? Math.sin(p * 70) * 0.05 * (1 - p) : 0;
      const focus: THREE.Vector3[] = []; // 이번 단계에서 바뀐 곳 — 카메라가 살짝 다가간다
      const activeRows = new Set<string>();

      after.rows.forEach(row => {
        const stack = isStackRow(row);
        const { ox, z } = placeOf(row);
        const len = Math.max(row.cells.length, scale.maxLen.get(row.objectId) ?? 0, 1);
        const unit = !stack && len > 9 ? 9 / len : 1;
        const sp = SP * unit;
        const n = row.cells.length;
        const xOf = (i: number) => ox + (stack ? 0 : (i - (n - 1) / 2) * sp);
        const yOf = (i: number) => (stack ? 0.24 + i * 0.98 : 0.24);
        const prevRow = before.rows.find(x => x.objectId === row.objectId);
        const swaps = motion.swaps.filter(m => m.objectId === row.objectId);
        const sets = new Set(motion.sets.filter(m => m.objectId === row.objectId).map(m => m.index));
        const grows = new Set(motion.inserts.filter(m => m.objectId === row.objectId).flatMap(m => Array.from({ length: m.count }, (_, k) => m.index + k)));
        const tagSwap = new Set(marks.swaps.filter(m => m.objectId === row.objectId).flatMap(m => [m.i, m.k]));
        const tagSet = new Set(marks.sets.filter(m => m.objectId === row.objectId).map(m => m.index));
        const tagNew = new Set(marks.inserts.filter(m => m.objectId === row.objectId).flatMap(m => Array.from({ length: m.count }, (_, k) => m.index + k)));

        // 판·선반
        let pn = panels.get(row.objectId);
        if (!pn) {
          const g = new THREE.Group();
          const board = new THREE.Mesh(seatGeo, boardMat);
          board.receiveShadow = true;
          g.add(board);
          const label = nameSprite("", "#5b3a8c");
          g.add(label);
          const topFlag = pill("top ▶", "#ffffff", C.wire);
          topFlag.scale.set(0.8, 0.3, 1);
          g.add(topFlag);
          pn = { g, board, seats: [], label, topFlag };
          panels.set(row.objectId, pn);
        }
        add(pn.g);
        used.p.add(row.objectId);
        pn.g.position.set(ox, 0, z);
        const width = stack ? 1.5 : Math.max(1.6, n * sp + 0.4);
        const height = stack ? Math.max(1.4, n * 0.98 + 0.6) : 1.3;
        pn.board.scale.set(width, height, 0.08);
        pn.board.position.set(stack ? 0 : 0, height / 2, -0.75);
        const caption = (stack ? "스택" : "배열") + (row.names.length ? ` · ${row.names.join(", ")}` : "") + (row.hidden ? `  +${row.hidden}칸` : "") + (n === 0 ? "  (비어 있음)" : "");
        if (pn.label.userData.text !== caption) {
          pn.label.userData.text = caption;
          setSpriteText(pn.label, caption, "#5b3a8c");
        }
        pn.label.scale.set(1.1, 0.33, 1);
        // 판 이름표는 캐릭터 태그와 겹치지 않게 판 왼쪽 옆 아래에 단다
        pn.label.position.set(-width / 2 - 0.62, 0.35, 0.1);
        pn.topFlag.visible = stack && n > 0;
        pn.topFlag.position.set(-1.05, yOf(Math.max(0, n - 1)) + 0.45, 0.2);
        while (pn.seats.length < (stack ? 1 : n)) {
          const s = new THREE.Mesh(seatGeo, seatMat);
          s.receiveShadow = true;
          s.castShadow = true;
          pn.g.add(s);
          pn.seats.push(s);
        }
        pn.seats.forEach((s, i) => {
          s.visible = stack ? i === 0 : i < n;
          if (stack) {
            s.scale.set(1.3, 0.24, 1.2);
            s.position.set(0, 0.12, 0);
            s.material = seatMat;
          } else {
            s.scale.set(sp * 0.9, 0.24, 1.15);
            s.position.set(xOf(i) - ox, 0.12, 0);
            s.material = tagNew.has(i) ? freshSeat : seatMat;
          }
        });
        rowAnchor.set(row.objectId, new THREE.Vector3(ox + (stack ? -0.45 : -width / 2 + 0.35), height + 0.05, z - 0.75));
        extend(ox - width / 2 - 1.2, z, 0.4, height + 0.6);
        extend(ox + width / 2, z, 0.4, height + 0.6);

        // 원소 캐릭터
        row.cells.forEach((cell, i) => {
          const key = `${row.objectId}:${stack ? "s" : "a"}:${i}`;
          used.c.add(key);
          let c = cells.get(key);
          if (!c) {
            c = stack ? makePenguin(++seedN) : makeJelly(++seedN, i);
            cells.set(key, c);
          }
          add(c.root);
          let shown = cell;
          let x = xOf(i);
          let y = yOf(i);
          let cz = z;
          let sy = calm ? 1 : breathe(t, c.seed);
          let spin = 0;
          const sw = swaps.find(m => m.i === i || m.k === i);
          if (sw && prevRow && p < 1) {
            // 교환 — 한 친구는 위로, 다른 친구는 앞으로 크게 돌아 서로의 자리로 간다
            const other = sw.i === i ? sw.k : sw.i;
            shown = prevRow.cells[i] ?? cell;
            const e = inOut(p);
            x = lerp(xOf(i), xOf(other), e);
            if (i < other) y += 0.9 * bump(p);
            else cz += 0.95 * bump(p);
            sy = p < 0.15 ? 1 + p * 1.2 : p > 0.82 ? 1 - Math.sin(((p - 0.82) / 0.18) * Math.PI) * 0.18 : 1 + bump(p) * 0.06;
          } else if (sets.has(i) && p < 1) {
            // 값 바뀜 — 꾹 눌렸다가 폴짝 뛰며 새 값을 든다
            if (prevRow?.cells[i] && p < 0.5) shown = prevRow.cells[i];
            sy = p < 0.35 ? 1 - 0.3 * bump(p / 0.7) : 1 + 0.08 * bump((p - 0.35) / 0.65);
            y += p > 0.35 ? 0.45 * bump((p - 0.35) / 0.65) : 0;
          } else if (grows.has(i) && stack && p < 1) {
            // 스택 push — 위에서 떨어져 내려와 쌓인다
            y += (1 - ease(p)) * 1.6;
          }
          if (grows.has(i) && p < 1 && !stack) spin = 0;
          const isNew = tagNew.has(i);
          const isSwap = tagSwap.has(i);
          const isSet = tagSet.has(i);
          c.root.position.set(x, y, cz);
          c.root.rotation.y = spin;
          const size = (stack ? 0.78 : JELLY) * unit;
          const pop = grows.has(i) ? backOut(p * 1.3) : 1;
          c.root.scale.setScalar(Math.max(0.001, size * pop));
          setSquash(c, sy);
          if (c.tint) c.tint.color.copy(isNew ? jellyFresh : isSwap || isSet ? jellyCur : jellyBase);
          if (c.flippers && (sets.has(i) || grows.has(i)) && p < 1) c.flippers[1].rotation.z = 0.35 + Math.sin(p * Math.PI * 4) * 0.8 * (1 - p);
          else if (c.flippers) c.flippers[1].rotation.z = 0.35;
          setValue(c, shown.text);
          const swapWith = marks.swaps.find(m => m.objectId === row.objectId && (m.i === i || m.k === i));
          const diff = marks.diffs.get(`${row.objectId}:${i}`);
          if (isNew) setTag(c, "신규", TAG.fresh);
          else if (isSwap && swapWith) setTag(c, `↔ ${swapWith.i === i ? swapWith.k : swapWith.i}번과 교환`, TAG.swap);
          else if (isSet) setTag(c, diff ? `${diff.from} → ${diff.to}` : "변경", TAG.change);
          else setTag(c, "");
          const errHere = errTarget?.objectId === row.objectId;
          const active = isNew || isSwap || isSet || errHere;
          setDim(c, anyChange && !active ? 1 : 0, calm);
          if (shiver) c.root.position.x += shiver * (i % 2 ? 1 : -1);
          if (active) {
            focus.push(new THREE.Vector3(xOf(i), 0, z));
            activeRows.add(row.objectId);
          }
          c.tag.position.set(stack ? 1.15 : 0, stack ? 0.55 : c.top + 0.32, 0);
          if (c.extra) c.extra.position.set(0, -0.06 / size, 0.7 / size);
          idle(c, t, calm);
          extend(x, cz, 0.6 * unit, y + 1.4);
        });

        // 없는 칸 — 오류가 이 배열의 범위 밖 칸을 찾았을 때, 그 자리에 빨간 빈 칸을 세운다
        if (errTarget?.objectId === row.objectId && !stack) {
          const len = errTarget.length ?? n;
          const idx = errTarget.index;
          const out = idx === undefined || idx < 0 || idx >= len;
          if (out) {
            // 너무 멀리 떨어진 번호는 바로 옆에 세우고 번호만 적는다 (무대가 끝없이 넓어지지 않게)
            const slot = idx === undefined ? n : idx < 0 ? -1 : Math.min(idx, n + 2);
            ghostCell.position.set(xOf(slot), 0, z);
            ghostCell.scale.setScalar(unit);
            const lift = calm ? 0 : Math.sin(t * 3) * 0.06;
            ghostBlob.position.y = 0.24 + lift;
            setPill(ghostLabel, idx === undefined ? "✕ 범위 밖 칸" : `✕ ${idx}번 칸 없음`, "#ffffff", ERR);
            add(ghostCell);
            ghostUsed = true;
            focus.push(new THREE.Vector3(xOf(slot), 0, z));
            extend(xOf(slot), z, 0.8, 2);
          }
          setPill(rangeLabel, len === 0 ? "빈 배열 · 칸 없음" : `있는 칸: 0 ~ ${len - 1}번`, "#ffffff", ERR);
          rangeLabel.position.set(ox, 0.05, z + 1.15); // 칸 번호 바로 앞 — 위쪽 로봇 이름표와 겹치지 않게
          add(rangeLabel);
          rangeUsed = true;
          focus.push(new THREE.Vector3(ox, 0, z));
        }
      });

      // 변수 로봇 — 배열 뒤 한 줄 (가리키는 배열은 관으로 잇는다)
      const backZ = after.rows.length ? -(Math.max(1, arrRows.length) - 1) * ROW_GAP - 3.4 : 0;
      type Bot = { key: string; name: string; text: string; num: number | null; ref?: string; ghost?: boolean };
      // 배열을 가리키는 로봇을 왼쪽에 먼저 세운다 — 화살표가 판 왼쪽 끝에 닿으므로 서로 덜 엇갈린다
      const bots: Bot[] = [
        ...after.rows.flatMap(row => row.names.map(name => ({ key: `${after.frameId}:${name}`, name, text: `[${row.cells.length + row.hidden}칸]`, num: null, ref: row.objectId }))),
        ...after.vars.map(v => ({ key: v.key, name: v.name, text: v.text, num: v.num })),
      ];
      // 없는 이름 오류 — 그 이름의 로봇이 무대에 없으면, 빨간 투명 로봇(빈자리)을 세워 "없다"를 보여 준다
      if (errTarget?.varName && !bots.some(b => b.name === errTarget.varName))
        bots.push({ key: `__ghost:${errTarget.varName}`, name: errTarget.varName, text: "?", num: null, ghost: true });
      // 로봇이 많으면 한 줄에 BOT_ROW명씩 여러 줄로 세운다. 뒷줄은 반 칸 비켜 서서 앞줄 로봇 사이로 보인다.
      const spotOf = (list: Bot[], key: string, zz: number) => {
        const i = list.findIndex(b => b.key === key);
        if (i < 0) return null;
        const line = Math.floor(i / BOT_ROW);
        const inLine = Math.min(BOT_ROW, list.length - line * BOT_ROW);
        const col = i % BOT_ROW;
        return { x: (col - (inLine - 1) / 2) * VAR_GAP + (line % 2 ? VAR_GAP / 2 : 0), z: zz - line * BOT_LINE_GAP };
      };
      const beforeBots: Bot[] = [
        ...before.rows.flatMap(row => row.names.map(name => ({ key: `${before.frameId}:${name}`, name, text: "", num: null, ref: row.objectId }))),
        ...before.vars.map(v => ({ key: v.key, name: v.name, text: v.text, num: v.num })),
      ];
      const beforeZ = before.rows.length ? -(Math.max(1, before.rows.filter(r => !isStackRow(r)).length) - 1) * ROW_GAP - 3.4 : 0;
      for (const b of bots) {
        used.r.add(b.key);
        let c = robots.get(b.key);
        if (!c) {
          c = makeRobot(++seedN, b.name);
          if (b.ghost)
            c.root.traverse(o => {
              const m = o as THREE.Mesh;
              if (m.isMesh) m.material = ghostMat;
            });
          robots.set(b.key, c);
        }
        add(c.root);
        renamePlate(c, b.name);
        const prev = before.vars.find(q => q.key === b.key);
        const existed = beforeBots.some(q => q.key === b.key);
        const changing = !b.ref && motion.changedVars.has(b.key) && !!prev && prev.text !== b.text;
        const to = spotOf(bots, b.key, backZ)!;
        const from = (existed && spotOf(beforeBots, b.key, beforeZ)) || to;
        const walk = ease(p * 1.4);
        const x = lerp(from.x, to.x, walk);
        const zz = lerp(from.z, to.z, walk);
        c.root.position.set(x, changing ? 0.5 * bump(p) : 0, zz);
        c.root.scale.setScalar(Math.max(0.001, ROBOT * (existed || p >= 1 ? 1 : backOut(p * 1.5))));
        setSquash(c, changing ? 1 - 0.22 * bump(p * 2) : 1);
        const changedNow = !b.ref && marks.changedVars.has(b.key);
        const addedNow = !b.ref && marks.addedVars.has(b.key);
        setValue(c, changing && p < 0.5 ? prev!.text : b.text, changedNow);
        const vdiff = marks.diffs.get(b.key);
        if (addedNow) setTag(c, `새 변수 = ${b.text}`, TAG.fresh);
        else if (changedNow) setTag(c, vdiff ? `${vdiff.from} → ${vdiff.to}` : "변경", TAG.change);
        else setTag(c, "");
        if (b.ghost) setTag(c, "✕ 아직 없는 이름", ERR);
        const botActive = changedNow || addedNow || !!b.ghost || (!!b.ref && (activeRows.has(b.ref) || errTarget?.objectId === b.ref));
        if (!b.ghost) setDim(c, anyChange && !botActive ? 1 : 0, calm);
        if (b.ghost) focus.push(new THREE.Vector3(x, 0, zz));
        if (shiver && !b.ghost) c.root.position.x += shiver;
        if (changedNow || addedNow) focus.push(new THREE.Vector3(x, 0, zz));
        c.tag.position.set(0, 2.05, 0);
        idle(c, t, calm);
        extend(x, zz, 0.8, 2.2);

        if (b.ref) {
          const end = rowAnchor.get(b.ref);
          if (end) {
            used.w.add(b.key);
            let w = wires.get(b.key);
            if (!w) {
              const label = pill("가리킴", "#ffffff", ARROW);
              label.scale.set(0.9, 0.36, 1);
              w = { key: b.key, tube: new THREE.Mesh(new THREE.BufferGeometry(), wireMat), head: new THREE.Mesh(new THREE.ConeGeometry(0.2, 0.44, 18), wireMat), label };
              w.tube.castShadow = true;
              wires.set(b.key, w);
            }
            add(w.tube);
            add(w.head);
            add(w.label);
            const start = new THREE.Vector3(x, 0.9 * ROBOT, zz + 0.3);
            // 같은 배열을 여러 변수가 가리키면 "가리킴" 글자는 첫 화살표에만 단다 (겹치지 않게)
            w.label.userData.first = bots.find(o => o.ref === b.ref)?.key === b.key;
            if (w.label.userData.sigFirst !== w.label.userData.first) {
              w.label.userData.sigFirst = w.label.userData.first;
              w.tube.userData.sig = "";
            }
            setWire(w, start, end, existed ? 1 : ease(p * 1.2));
          }
        }
      }

      // 표지판 — 배열이 아닌 객체 (딕셔너리·구조체·객체)
      after.signs.forEach((sg, k) => {
        const text = `${sg.names.join(" = ")} → ${sg.text}`;
        let s = signs.get(sg.objectId);
        if (!s) {
          s = makeSign(text);
          signs.set(sg.objectId, s);
        }
        (s.material as THREE.SpriteMaterial).map = signTexture(text);
        add(s);
        used.s.add(sg.objectId);
        s.position.set(0, 2.9 + k * 0.5, backZ - 0.6);
      });

      if (!ghostUsed) ghostCell.removeFromParent();
      if (!rangeUsed) rangeLabel.removeFromParent();
      // 무대 맨 위 오류 띠 + 붉은 배경 — "여기서 멈췄다"를 한눈에
      if (error || pause) {
        (banner.material as THREE.SpriteMaterial).map = error
          ? textTexture(`⚠ ${error.title}`, { color: "#ffffff", bg: ERR, pill: true, w: 1024, h: 144, weight: 800 })
          : textTexture(`✎ ${pause}`, { color: "#ffffff", bg: "#7b4a80", pill: true, w: 1024, h: 144, weight: 800 });
        (banner.material as THREE.SpriteMaterial).needsUpdate = true;
        banner.position.set((minX + maxX) / 2, maxY + 1.1, (minZ + maxZ) / 2);
        add(banner);
        maxY += 0.8;
      } else banner.removeFromParent();
      (scene.background as THREE.Color).lerp(error ? errBg : calmBg, calm ? 1 : 0.08);
      (scene.fog as THREE.Fog).color.copy(scene.background as THREE.Color);

      for (const [k, c] of cells) if (!used.c.has(k)) c.root.removeFromParent();
      for (const [k, c] of robots) if (!used.r.has(k)) c.root.removeFromParent();
      for (const [k, pn] of panels) if (!used.p.has(k)) pn.g.removeFromParent();
      for (const [k, w] of wires) if (!used.w.has(k)) (w.tube.removeFromParent(), w.head.removeFromParent(), w.label.removeFromParent());
      for (const [k, s] of signs) if (!used.s.has(k)) s.removeFromParent();

      // 카메라 — 무대 전체가 들어오게 부드럽게 따라간다
      const cx = (minX + maxX) / 2;
      const cz = (minZ + maxZ) / 2;
      const fov = (camera.fov * Math.PI) / 180;
      const fitW = (maxX - minX + 1) / 2 / Math.tan(fov / 2) / camera.aspect;
      const fitD = (maxZ - minZ + 2 + maxY * 0.6) / 2 / Math.tan(fov / 2);
      let d = Math.max(6.5, fitW * 1.1, fitD * 1.05);
      let fx = cx;
      let fz = cz;
      if (focus.length) {
        // 바뀐 곳 쪽으로 30% 옮기고 조금 다가간다 — 무대가 화면 밖으로 나가지 않을 만큼만
        const mx = focus.reduce((a, v) => a + v.x, 0) / focus.length;
        const mz = focus.reduce((a, v) => a + v.z, 0) / focus.length;
        fx = lerp(cx, mx, 0.3);
        fz = lerp(cz, mz, 0.3);
        d *= 0.9;
      }
      camPos.set(fx, d * 0.56, fz + d * 0.88);
      camLook.set(fx, 0.7, fz - 0.2);
      if (firstFrame) {
        camera.position.copy(camPos);
        lookCur.copy(camLook);
      } else {
        camera.position.lerp(camPos, calm ? 1 : 0.06);
        lookCur.lerp(camLook, calm ? 1 : 0.06);
      }
      firstFrame = false;
      if (motion.crash && !calm) camera.position.x += Math.sin(p * 60) * 0.06 * (1 - p);
      camera.lookAt(lookCur);
      sun.position.set(cx + 4, 10, cz + 6);
      sun.target.position.set(cx, 0, cz);
    };

    const frame = () => {
      raf = requestAnimationFrame(frame);
      const { start, duration } = animRef.current;
      const p = duration <= 0 ? 1 : Math.min(1, (performance.now() - start) / duration);
      draw(inputRef.current, p, clock.getElapsedTime());
      renderer.render(scene, camera);
    };
    frame();

    // 화살표에 마우스를 대면 설명을 띄운다 — 화살표 곡선을 화면에 투영해 커서와의 거리로 잰다
    const probe = new THREE.Vector3();
    const segDist = (px: number, py: number, ax: number, ay: number, bx: number, by: number) => {
      const dx = bx - ax, dy = by - ay;
      const len = dx * dx + dy * dy;
      const t = len ? Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / len)) : 0;
      return Math.hypot(px - (ax + t * dx), py - (ay + t * dy));
    };
    let overArrow = false;
    const onPointerMove = (e: PointerEvent) => {
      const r = host.getBoundingClientRect();
      const px = e.clientX - r.left;
      const py = e.clientY - r.top;
      let best = Infinity;
      for (const w of wires.values()) {
        const curve = w.tube.userData.curve as THREE.Curve<THREE.Vector3> | undefined;
        if (!curve || !w.tube.parent || !w.head.visible) continue;
        let ax = 0, ay = 0;
        for (let i = 0; i <= 24; i++) {
          probe.copy(curve.getPoint(i / 24)).project(camera);
          const sx = ((probe.x + 1) / 2) * r.width;
          const sy = ((1 - probe.y) / 2) * r.height;
          if (i) best = Math.min(best, segDist(px, py, ax, ay, sx, sy));
          ax = sx;
          ay = sy;
        }
      }
      const hit = best < 14;
      if (hit !== overArrow) host.style.cursor = hit ? "help" : "";
      if (hit || overArrow) arrowHoverRef.current?.(hit ? { x: px, y: py } : null);
      overArrow = hit;
    };
    const onPointerLeave = () => {
      if (!overArrow) return;
      overArrow = false;
      host.style.cursor = "";
      arrowHoverRef.current?.(null);
    };
    host.addEventListener("pointermove", onPointerMove);
    host.addEventListener("pointerleave", onPointerLeave);

    return () => {
      host.removeEventListener("pointermove", onPointerMove);
      host.removeEventListener("pointerleave", onPointerLeave);
      cancelAnimationFrame(raf);
      ro.disconnect();
      scene.traverse(o => {
        const m = o as THREE.Mesh;
        if (m.geometry && m.geometry !== blob) m.geometry.dispose();
      });
      envTex.dispose();
      pmrem.dispose();
      renderer.dispose();
      renderer.domElement.remove();
    };
  }, []);

  if (failed) return <div className="vz-stage__fallback">이 기기에서는 3D 무대를 쓸 수 없어요. 아래 변수 표로 상태를 확인해 주세요.</div>;
  return <div className="vz-stage" ref={hostRef} />;
}
