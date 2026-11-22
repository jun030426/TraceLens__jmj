// 실행 장면 화면 — 계약(VisualizationScreenProps)만 받아 그린다.
// 최종 모습은 늘 current로 다시 그리고, 순방향 한 단계 이동(next·tick)에서만 previous → current와 current.events로 움직임을 연출한다.
// 단계 선택은 controls로만 한다 (화면이 따로 타이머로 단계를 넘기지 않는다).
import { lazy, Suspense, useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { createPortal } from "react-dom";
import type { TraceValue } from "../pythonTrace";
import type { Observation, Recording, VisualizationEvent, VisualizationScreenProps } from "./contracts";
import { EMPTY_SCENE, motionOf, NO_MOTION, scaleOf, sceneOf, valueText } from "./screen/sceneModel";
import { explainError } from "./screen/errorModel";
import { explainLine } from "./screen/lineExplain";
import { circled, showBlanks } from "../visualizer/blanks";
import { VIZ_LINE_WORD, vizLineOf } from "./vizLine";
import "./visualization.css";
import { useTheme } from "../theme";

// three.js 무대는 시각화 탭을 열 때만 불러온다 — 설계서 캐릭터(젤리·로봇·펭귄) 무대
const CharacterStage = lazy(() => import("./screen/CharacterStage").then(m => ({ default: m.CharacterStage })));

const SPEEDS = [
  { label: "느리게", ms: 2000 },
  { label: "보통", ms: 1000 },
  { label: "빠르게", ms: 500 },
];

const LANG_NAME = { python: "Python", java: "Java", c: "C" } as const;

function arrayName(e: Extract<VisualizationEvent, { target: unknown }>) {
  const names = e.target.bindings.length ? e.target.bindings : e.target.previousBindings;
  return names.length ? names.map(b => b.name).join(" = ") : "안쪽 배열";
}

/** 이번 단계에서 확인된 변화를 한두 문장으로 — 이벤트에 있는 사실만 말한다 */
function captionOf(cur: Observation, recording: Recording): string {
  const t = (v: TraceValue | undefined) => valueText(v, cur.objects);
  const lines: string[] = [];
  for (const e of cur.events) {
    if (e.type === "array.swap") lines.push(`${arrayName(e)}[${e.indices[0]}]와 [${e.indices[1]}]가 자리를 바꿨어요 (${t(e.before[0])} ↔ ${t(e.before[1])})`);
    else if (e.type === "array.set") lines.push(`${arrayName(e)}[${e.index}] 값이 ${t(e.before)} → ${t(e.after)}로 바뀌었어요`);
    else if (e.type === "array.insert") lines.push(`${arrayName(e)}의 ${e.index}번 자리에 ${e.values.map(t).join(", ")}이(가) 들어왔어요`);
    else if (e.type === "array.remove") lines.push(`${arrayName(e)}의 ${e.index}번 자리에서 ${e.values.map(v => valueText(v, recording.steps[Math.max(0, cur.index - 1)].objects)).join(", ")}이(가) 빠졌어요`);
    else if (e.type === "array.snapshot") {
      if (e.reason === "first-observation") lines.push(`${arrayName(e)} 배열이 나타났어요 (${e.after?.items?.length ?? 0}칸)`);
      else if (e.reason !== "left-observation") lines.push(`${arrayName(e)} 배열이 여러 곳 바뀌었어요`);
    } else if (e.type === "variable.change" && e.change.kind !== "removed")
      lines.push(e.change.kind === "added" ? `${e.change.name} = ${t(e.change.after)}` : `${e.change.name}: ${t(e.change.before)} → ${t(e.change.after)}`);
  }
  const top = cur.frames[cur.frames.length - 1];
  if (cur.event === "exception") return `여기서 멈췄어요 — ${cur.error ? explainError(cur.error, sceneOf(cur)).title : "오류가 났어요"}`;
  if (cur.event === "call" && top) lines.unshift(cur.frames.length === 1 ? "실행을 시작해요" : `${top.name}() 안으로 들어갔어요`);
  if (cur.event === "return" && top) lines.unshift(top.name === "<module>" || top.name === "main" && cur.frames.length === 1 ? "프로그램이 끝나요" : cur.returned ? `${top.name}()가 ${t(cur.returned)}을(를) 돌려줘요` : `${top.name}()가 끝나요`);
  if (lines.length === 0) return cur.causedByLine ? `${cur.causedByLine}번째 줄을 실행했어요. 값은 그대로예요.` : cur.nextLine ? `프로그램을 시작해요. ${cur.nextLine}번째 줄부터 차례로 실행해요.` : "실행을 시작해요.";
  return lines.slice(0, 2).join(" · ") + (lines.length > 2 ? ` 외 ${lines.length - 2}개` : "");
}

export function VisualizationScreen(props: VisualizationScreenProps) {
  const [theme] = useTheme();
  const { recording, current, previous, playback, controls, canNext, canPrevious, reducedMotion } = props;
  const scale = useMemo(() => scaleOf(recording), [recording]);
  const forward = playback.transition.kind === "next" || playback.transition.kind === "tick";
  const animate = forward && !!previous && !reducedMotion;
  const after = useMemo(() => sceneOf(current), [current]);
  // 오류 단계 — 바로 알리지 않고, 재생이 그 단계에 닿았을 때 무대와 코드에서 "어디서·왜"를 보여 준다
  const error = useMemo(() => (current?.event === "exception" && current.error ? explainError(current.error, after) : null), [current, after]);
  const errorStep = useMemo(() => recording.steps.findIndex(s => s.event === "exception"), [recording]);
  const errLine = error ? current?.causedByLine ?? current?.nextLine ?? null : null;
  // 빈칸 채우기 — 기록은 안 채운 빈칸 줄 직전에서 끝난다. 마지막 단계에서 "여기서 멈췄어요"를 보여 준다
  const blankStop = recording.blankStop && current && current.index === recording.steps.length - 1 ? recording.blankStop : null;
  const viz = vizLineOf(recording, current);
  // 실행 줄 주석 — "▶ 다음 N번째 줄" 옆에 그 줄이 하는 일을 코드 주석처럼
  // 설명 문장 — 방금 실행한 줄의 뜻 + 바뀐 값
  const said = useMemo(() => (current && !error ? explainLine(recording.source, current, previous) : null), [recording.source, current, previous, error]);
  const facts = current ? captionOf(current, recording) : "";
  const factsShown = !!facts && !/번째 줄을 실행했어요\. 값은 그대로예요\.$/.test(facts) && facts !== "실행을 시작해요.";
  const before = useMemo(() => (animate ? sceneOf(previous) : after), [animate, previous, after]);
  const marks = useMemo(() => (current ? motionOf(current.events, current) : NO_MOTION), [current]);
  const motion = animate ? marks : NO_MOTION;
  // 움직임은 단계 간격의 85%까지 (최대 1.7초) — 너무 빨리 끝나 무엇이 바뀌었는지 놓치지 않게
  const durationMs = animate ? Math.min(1700, playback.intervalMs * 0.85) : 0;
  const lines = useMemo(() => recording.source.split("\n"), [recording.source]);
  // 코드 칸은 지금 줄(오류 줄)이 보이도록 스스로 스크롤한다 — 페이지 전체는 움직이지 않게 목록만 굴린다
  const codeRef = useRef<HTMLOListElement | null>(null);
  // 실습 페이지: 왼쪽 코드 밑에 변수 표를 띄울 자리
  const [varSlot, setVarSlot] = useState<HTMLElement | null>(null);
  const [arrowTip, setArrowTip] = useState<{ x: number; y: number } | null>(null);
  useEffect(() => { setVarSlot(document.getElementById("practice-vartable-slot")); }, []);
  useEffect(() => {
    const box = codeRef.current;
    const li = box?.querySelector<HTMLElement>("li.is-error, li.is-next, li.is-ran");
    if (!box || !li) return;
    const top = li.offsetTop - box.offsetTop;
    if (top < box.scrollTop || top + li.offsetHeight > box.scrollTop + box.clientHeight) box.scrollTop = Math.max(0, top - box.clientHeight / 2);
  }, [current]);
  const total = recording.steps.length;

  const onKey = (e: KeyboardEvent) => {
    if (e.target instanceof HTMLInputElement || e.target instanceof HTMLButtonElement) return;
    if (e.key === "ArrowRight") controls.next();
    else if (e.key === "ArrowLeft") controls.previous();
    else if (e.key === "Home") controls.restart();
    else if (e.key === " ") (playback.playing ? controls.pause : controls.play)();
    else return;
    e.preventDefault();
  };

  if (!current) return <section className="vz-screen" aria-label="실행 장면"><p className="vz-screen__caption">실행 기록 없음</p></section>;
  const stack = current.frames.map(f => f.name);
  return (
    <section className="vz-screen" aria-label="실행 장면" tabIndex={0} onKeyDown={onKey}>
      <div className="vz-screen__main">
        <div className="vz-screen__stage">
          <Suspense fallback={<div className="vz-stage__fallback">3D 무대를 준비하고 있어요…</div>}>
            <CharacterStage
              key={theme /* 다크 · 밝은 모드가 바뀌면 무대 색도 새로 */}
              input={{ before: before ?? EMPTY_SCENE, after, motion, marks, scale, error }}
              animKey={playback.transition.revision}
              durationMs={durationMs}
              reducedMotion={reducedMotion}
              onArrowHover={setArrowTip}
            />
          </Suspense>
          {stack.length > 1 && (
            <ol className="vz-screen__stack" aria-label="함수 호출">
              {stack.map((f, i) => <li key={i}>{f}</li>)}
            </ol>
          )}
          {error && <div className="vz-screen__badge is-stop">⚠ 오류 장면</div>}
          {/* 보라색 화살표 설명 — 화살표에 마우스를 댈 때만 그 자리에 띄운다 */}
          {arrowTip && after.rows.some(r => r.names.length > 0) && (
            <p
              className={`vz-screen__legend is-tip${arrowTip.y < 110 ? " is-below" : ""}`}
              role="tooltip"
              style={{ left: `clamp(150px, ${arrowTip.x}px, calc(100% - 150px))`, top: arrowTip.y }}
            >
              <span className="vz-screen__arrow" aria-hidden="true">➜</span>
              보라색 화살표: 로봇(변수)이 그 배열을 <b>가리킨다</b>는 뜻이에요. 값을 복사한 게 아니라 배열이 있는 곳을 알고 있어요.
            </p>
          )}
          {viz && (
            <div className={`vz-screen__where is-${viz.kind}`} aria-live="polite">
              코드 <b>{viz.line}번째 줄</b> · {VIZ_LINE_WORD[viz.kind]}
              <span className="vz-screen__where-step">{viz.step}/{viz.total}단계</span>
            </div>
          )}
        </div>
        <ol className="vz-screen__code" ref={codeRef} aria-label={`${LANG_NAME[recording.language]} 코드`}>
          {lines.map((text, i) => {
            const n = i + 1;
            const bad = errLine === n;
            const hole = blankStop?.line === n;
            const ran = !bad && current.causedByLine === n;
            const next = !bad && !hole && current.nextLine === n;
            return (
              <li key={n} className={`${ran ? "is-ran" : ""} ${next ? "is-next" : ""} ${bad ? "is-error" : ""} ${hole ? "is-blank" : ""}`} aria-current={next || bad || hole ? "step" : undefined}>
                <span className="vz-screen__ln">{n}</span>
                <span className="vz-screen__mark" aria-label={bad ? "여기서 오류" : hole ? "빈칸 앞에서 멈춤" : ran ? "방금 실행" : next ? "다음에 실행" : undefined}>{bad ? "✕" : hole ? "？" : ran ? "✓" : next ? "▶" : ""}</span>
                <code>{showBlanks(text) || " "}</code>
                {bad && <span className="vz-screen__errtag">여기서 멈춤</span>}
                {hole && <span className="vz-screen__blanktag">빈칸 {circled(blankStop!.blank)} · 여기서 멈춤</span>}
              </li>
            );
          })}
        </ol>
      </div>
      {/* 오류 설명 카드 — 무대 밖(아래)에 둬서 캐릭터를 가리지 않는다 */}
      {error && (
        <div className="vz-screen__error" role="status">
          <p className="vz-screen__error-title">
            <span aria-hidden="true">⚠</span> {errLine ? `${errLine}번째 줄에서 멈췄어요 · ` : ""}{error.title}
          </p>
          {errLine && <code className="vz-screen__error-code">{showBlanks(lines[errLine - 1] ?? "").trim()}</code>}
          <p><b>왜?</b> {error.why}</p>
          <p><b>이렇게 확인해 봐요</b> {error.hint}</p>
          <p className="vz-screen__error-raw">원래 오류 문구: {error.raw}</p>
        </div>
      )}
      {/* 빈칸 앞에서 멈춘 장면 — 오류가 아니라 "여기부터는 학생이 채울 차례" */}
      {blankStop && (
        <div className="vz-screen__blank" role="status">
          <p className="vz-screen__blank-title">
            <span aria-hidden="true">✎</span> {blankStop.line}번째 줄의 빈칸 {circled(blankStop.blank)} 앞에서 멈췄어요
          </p>
          <code className="vz-screen__blank-code">{showBlanks(lines[blankStop.line - 1] ?? "").trim()}</code>
          <p>지금 무대는 이 줄을 실행하기 <b>바로 전</b> 모습이에요. 변수와 배열의 값을 보고 빈칸에 무엇이 들어가야 할지 생각해 보세요. 채우고 실행하면 다음 빈칸까지 이어서 보여 줘요.</p>
        </div>
      )}
      {/* 줄 번호 0(실행 시작 직전 단계)은 "줄 없음" — `0 && …`은 화면에 0을 찍으므로 불리언으로 바꿔 검사한다 */}
      {/* 시각화 아래 '다음 n번째 줄' 안내는 헷갈려서 뺐어요 (11-14) */}
      {/* 설명 — 첫 줄은 "방금 실행한 줄이 한 일"을 말로, 둘째 줄은 그 결과 바뀐 값(사실) */}
      <div className="vz-screen__caption" aria-live="polite">
        <p className="vz-screen__say">
          <span className="vz-screen__step">{current.index + 1}단계</span>
          {blankStop ? `빈칸 ${circled(blankStop.blank)} 앞까지 실행했어요. 빈칸을 채우면 이어서 볼 수 있어요.`
            : said ? <><span className="vz-screen__sayline">{said.line}번째 줄</span>{said.text}</>
            : facts}
        </p>
        {!blankStop && said?.detail && said.detail !== said.text && <p className={`vz-screen__detail is-${said.kind}`}>값으로 보면 <code>{said.detail}</code>{said.kind === "cond-true" || said.kind === "loop-in" ? " → 참" : said.kind === "cond-false" || said.kind === "loop-out" ? " → 거짓" : ""}</p>}
        {!blankStop && said && factsShown && <p className="vz-screen__facts"><mark>바뀐 값 · {facts}</mark></p>}
      </div>
      <div className="vz-screen__controls">
        <button type="button" onClick={controls.restart} disabled={!canPrevious} aria-label="처음으로">⟲</button>
        <button type="button" onClick={controls.previous} disabled={!canPrevious} aria-label="이전 단계">‹</button>
        <button type="button" className="is-primary" onClick={playback.playing ? controls.pause : controls.play} disabled={total <= 1} aria-label={playback.playing ? "일시정지" : "재생"}>
          {playback.playing ? "❚❚" : "▶"}
        </button>
        <button type="button" onClick={controls.next} disabled={!canNext} aria-label="다음 단계">›</button>
        {errorStep >= 0 && playback.index !== errorStep && (
          <button type="button" className="vz-screen__tojump" onClick={() => controls.seek(errorStep)} aria-label={`${errorStep + 1}단계 오류 장면으로 이동`}>
            ⚠ 오류 장면
          </button>
        )}
        <input
          type="range"
          min={0}
          max={Math.max(0, total - 1)}
          value={playback.index}
          onChange={e => controls.seek(Number(e.target.value))}
          aria-label="단계 이동"
          style={{ ["--vz-progress" as string]: `${total > 1 ? (playback.index / (total - 1)) * 100 : 100}%` }}
        />
        <span className="vz-screen__count">{playback.index + 1}/{total}</span>
        <div className="vz-screen__speed" role="group" aria-label="재생 속도">
          {SPEEDS.map(s => (
            <button key={s.ms} type="button" aria-pressed={playback.intervalMs === s.ms} onClick={() => controls.setIntervalMs(s.ms)}>{s.label}</button>
          ))}
        </div>
      </div>
      {/* 실습 페이지에서는 변수 표를 왼쪽 코드 밑 자리(practice-vartable-slot)에 띄운다. 그 자리가 없으면 원래처럼 무대 아래 접힌 표 */}
      {varSlot ? createPortal(
        <div className="vz-host vz-host--vartable">
          <details className="vz-screen__state" open>
            <summary>변수 표 · {current.index + 1}단계</summary>
            {current.frames.map(f => (
              <table key={f.id}>
                <caption>{f.name}</caption>
                <tbody>
                  {f.variables.length === 0 ? <tr><td colSpan={2}>(변수 없음)</td></tr> : f.variables.map(v => (
                    <tr key={v.name}><th scope="row">{v.name}</th><td>{fullText(v.value, current)}</td></tr>
                  ))}
                </tbody>
              </table>
            ))}
            {current.stdout && <pre className="vz-screen__stdout" aria-label="지금까지의 출력">{current.stdout}</pre>}
          </details>
        </div>,
        varSlot,
      ) : (
      <details className="vz-screen__state">
        <summary>변수 표로 보기</summary>
        {current.frames.map(f => (
          <table key={f.id}>
            <caption>{f.name}</caption>
            <tbody>
              {f.variables.length === 0 ? <tr><td colSpan={2}>(변수 없음)</td></tr> : f.variables.map(v => (
                <tr key={v.name}><th scope="row">{v.name}</th><td>{fullText(v.value, current)}</td></tr>
              ))}
            </tbody>
          </table>
        ))}
        {current.stdout && <pre className="vz-screen__stdout" aria-label="지금까지의 출력">{current.stdout}</pre>}
      </details>
      )}
    </section>
  );
}

/** 표에 쓰는 긴 표현 — 배열은 원소까지, 객체는 키까지 한 단계만 펼친다 */
function fullText(v: TraceValue, cur: Observation): string {
  if (v.kind !== "reference") return valueText(v, cur.objects);
  const o = v.object_id ? cur.objects[v.object_id] : undefined;
  if (!o) return "→ ? (찾을 수 없는 참조)";
  if (o.unsupported) return `${o.type} (표시할 수 없는 값)`;
  const more = o.truncated || (o.length !== undefined && o.items && o.length > o.items.length) ? ", …" : "";
  if (o.items) return `[${o.items.map(x => valueText(x, cur.objects)).join(", ")}${more}]`;
  if (o.entries) return `${o.type} { ${o.entries.map(([k, x]) => `${k}: ${valueText(x, cur.objects)}`).join(", ")}${more} }`;
  return o.type;
}
