import { useEffect, useMemo, useRef, useState } from 'react'
import Editor, { type OnMount } from '@monaco-editor/react'
import { Play, Terminal } from 'lucide-react'
import Stage from './components/Stage'
import PlayerBar from './components/PlayerBar'
import Inspector from './components/Inspector'
import { preflight, type PreflightIssue } from './trace/preflight'
import { runTrace, warmUp, type TraceStage } from './trace/tracerClient'
import type { SyntaxErrorInfo, TraceEvent } from './trace/types'
import { buildSnapshots, type Snapshot } from './trace/snapshots'
import { buildScreenplay } from './screenplay/ruleDirector'
import { buildDigest } from './digest/buildDigest'
import { generateScreenplayWithSalvage } from './director/llmDirector'
import { makeGeminiCall, geminiApiKey, GEMINI_MODEL } from './director/gemini'
import type { Screenplay } from './screenplay/types'
import { expandScreenplay, type PlaybackStep } from './player/expand'
import { buildStage } from './film/buildStage'
import { layoutStage, type StageLayout } from './film/layout'
import { choreograph } from './film/choreograph'
import { decorateShots } from './film/decorate'
import type { Shot, StagePlan } from './film/types'
import WorldStage from './film/WorldStage'
import { SyntaxScene } from './ui/SyntaxScene'
import { applyGrammarPacing } from './film/presets'
import { useFilm } from './film/useFilm'
import { Nav } from './ui/Chrome'
import { useSettings, prefersStill } from './settings/store'
import './ui/app.css'

type MonacoApi = Parameters<OnMount>[1]

type LoadingStage = TraceStage
const stageLabels: Record<LoadingStage, string> = {
  'python-loading': 'Python 환경 준비 중…',
  executing: '코드 실행·기록 중…',
  building: '설명 준비 중…',
}

type DirectorMode = 'rule' | 'ai' | 'ai-partial' | 'ai-fallback'

const primitiveLabels: Record<string, string> = {
  variables: '변수',
  sequence: '시퀀스',
  callStack: '호출 스택',
  objectGraph: '객체 참조',
  generic: '변수 표',
}

type RunArtifacts = {
  steps: PlaybackStep[]
  snaps: Snapshot[]
  screenplay: Screenplay
  clipped: boolean
  error?: string
  syntaxError?: SyntaxErrorInfo
  directorMode: DirectorMode
  /** 저장된 연출을 그대로 쓴 실행인가 — 방금 생성한 것과 같아 보이면 그것도 화면의 거짓말이다 */
  directorCached?: boolean
  plan: StagePlan
  layout: StageLayout
  shots: Shot[]
  /** AI staging 힌트가 오면 필름을 재구축해야 하므로 원본 이벤트를 쥐고 있는다 */
  events: TraceEvent[]
}

/* Pyodide 내부 프레임은 학습자에게 잡음이다 — 사용자 코드부터의 꼬리만 남긴다.
   내용을 바꾸는 게 아니라 우리 런타임의 배관을 걷어내는 것. */
const tidyError = (err: string) => {
  const lines = err.trim().split('\n')
  const userIdx = lines.findIndex(l => l.includes('File "<user>"'))
  if (userIdx >= 0) return lines.slice(userIdx).join('\n')
  return lines.length > 3 ? lines.slice(-3).join('\n') : err
}

const EMPTY_PLAN: StagePlan = {
  objects: [], variables: [], frames: [],
  slotCount: 0, maxStackDepth: 0, maxListLength: 0, leadObjectId: null,
}

/* 에디터도 같은 세계를 쓴다 — 페이지와 다른 명도로 튀지 않게 토큰 값으로 테마를 정의한다 */
function defineEditorTheme(monaco: MonacoApi) {
  monaco.editor.defineTheme('tracelens', {
    base: 'vs',
    inherit: true,
    rules: [
      { token: 'comment', foreground: '8a877c', fontStyle: 'italic' },
      { token: 'keyword', foreground: '16409f' },
      { token: 'string', foreground: '0f7b3e' },
      { token: 'number', foreground: 'bd2b1c' },
    ],
    colors: {
      'editor.background': '#ffffff',
      'editor.foreground': '#1a1a17',
      'editorLineNumber.foreground': '#a8a49a',
      'editorLineNumber.activeForeground': '#55534c',
      'editor.lineHighlightBackground': '#faf9f6',
      'editor.lineHighlightBorder': '#00000000',
      'editorIndentGuide.background1': '#eceae4',
      'editorCursor.foreground': '#1b57e0',
      'editor.selectionBackground': '#dbe4fb',
      'editorWidget.background': '#ffffff',
      'editorWidget.border': '#e4e2dc',
      'scrollbarSlider.background': '#e4e2dc99',
      'scrollbarSlider.hoverBackground': '#cfccc3',
    },
  })
}

function App() {
  const [code, setCode] = useState<string>('')
  const [issues, setIssues] = useState<PreflightIssue[]>([])
  const [loading, setLoading] = useState<LoadingStage | null>(null)
  const [run, setRun] = useState<RunArtifacts | null>(null)
  const [aiPending, setAiPending] = useState(false)
  const runIdRef = useRef(0)
  // 복원은 seq 기준 — staging 재구축은 샷 수 자체가 달라질 수 있다
  const restoreRef = useRef<{ seq: number; playing: boolean } | null>(null)
  const editorRef = useRef<Parameters<OnMount>[0] | null>(null)
  const monacoRef = useRef<MonacoApi | null>(null)
  const decorationRef = useRef<ReturnType<Parameters<OnMount>[0]['createDecorationsCollection']> | null>(null)

  const settings = useSettings()
  const steps = useMemo(() => run?.steps ?? [], [run])
  // 연출 문법 완급(판단·행동 샷 늘림)은 데이터 단계에서 — 경계·자막·타임라인이 같은 배열을 본다
  const shots = useMemo(() => applyGrammarPacing(run?.shots ?? []), [run])
  const { index, playing, speed, play, pause, seek, setSpeed, register } = useFilm(shots)
  const film = { index, playing, speed, play, pause, seek, setSpeed, register }
  // AI 도착 시점의 재생 위치를 되살리기 위한 미러 — 비동기 콜백은 낡은 상태를 본다
  const indexRef = useRef(0)
  indexRef.current = index
  const playingRef = useRef(false)
  playingRef.current = playing

  // 설정의 기본 배속은 시작 값이다 — 재생 중 바꾼 값을 덮어쓰지 않도록 설정이 바뀔 때만 적용한다
  useEffect(() => { setSpeed(settings.speed) }, [settings.speed, setSpeed])

  const bySeq = useMemo(() => new Map((run?.snaps ?? []).map(s => [s.seq, s])), [run])

  // 샷과 스텝은 개수가 다르다 — 샷마다 "그 seq를 넘지 않는 마지막 스텝"의 자막·챕터를 물려준다.
  // 그래야 진행바·자막·인스펙터가 전부 같은 축(샷)에서 움직인다.
  // 자막 선택 — 화면과 원리적으로 일치하는 필름 자막이 기본. AI 연출이 접히지 않은
  // 장면에 붙인 문장('왜')은 그대로 둔다: 기계적 사실은 필름이, 의도는 AI가 말한다.
  const aiNarration = run?.directorMode === 'ai' || run?.directorMode === 'ai-partial'
  const shotSteps = useMemo<PlaybackStep[]>(() => {
    let cursor = 0
    let carried: PlaybackStep | undefined
    return shots.map(sh => {
      while (cursor < steps.length && steps[cursor].seq <= sh.seq) carried = steps[cursor++]
      const narration =
        aiNarration && carried && !carried.folded && !sh.timelapse
          ? carried.narration
          : (sh.caption ?? carried?.narration ?? '')
      return {
        seq: sh.seq,
        chapterIndex: carried?.chapterIndex ?? 0,
        primitive: carried?.primitive ?? 'variables',
        focus: carried?.focus ?? [],
        narration,
        durationMs: sh.durationMs,
      }
    })
  }, [shots, steps, aiNarration])

  const currentShot = shots[index]
  const currentStep = shotSteps[index]
  const currentSnap = currentShot ? bySeq.get(currentShot.seq) : undefined
  const chapterTitle = run?.screenplay.chapters[currentStep?.chapterIndex ?? 0]?.title

  useEffect(() => { warmUp() }, [])

  useEffect(() => {
    const editor = editorRef.current
    const monaco = monacoRef.current
    const decorations = decorationRef.current
    if (!editor || !monaco || !decorations || !currentSnap) return
    decorations.set([
      {
        range: new monaco.Range(currentSnap.line, 1, currentSnap.line, 1),
        options: {
          isWholeLine: true,
          className: 'current-line-highlight',
          glyphMarginClassName: 'current-line-glyph',
        },
      },
    ])
    editor.revealLineInCenterIfOutsideViewport(currentSnap.line)
  }, [currentSnap])

  const handleEditorMount: OnMount = (editor, monaco) => {
    editorRef.current = editor
    monacoRef.current = monaco
    defineEditorTheme(monaco)
    monaco.editor.setTheme('tracelens')
    decorationRef.current = editor.createDecorationsCollection()
    // 마운트 시점 클로저는 낡는다 — 항상 최신 executeRun을 부르도록 ref를 거친다
    editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.Enter, () => executeRunRef.current())
  }

  const executeRun = async () => {
    if (loading !== null || !code.trim()) return // 버튼 disabled를 우회하는 단축키 경로 가드
    const found = preflight(code)
    setIssues(found)
    if (found.some(i => i.level === 'block')) return

    const runId = ++runIdRef.current
    setLoading('python-loading')
    setRun(null)
    setAiPending(false)
    try {
      const result = await runTrace(code, s => setLoading(s), {
        maxEvents: settings.maxEvents,
        timeoutMs: settings.timeoutMs,
      })
      if (runId !== runIdRef.current) return
      const snaps = buildSnapshots(result.events)

      // 규칙 대본으로 즉시 완성한다 — AI는 재생을 막지 않는다
      const screenplay = buildScreenplay(result.events)
      // 무대는 AI와 무관하게 트레이스에서 계산된다 — 콘티가 없어도 영화는 나온다
      const plan = buildStage(result.events)
      const layout = layoutStage(plan)
      const filmShots = choreograph(result.events, plan, code)
      setRun({
        steps: expandScreenplay(screenplay, snaps), snaps, screenplay,
        clipped: result.clipped, error: result.error, syntaxError: result.syntaxError, directorMode: 'rule',
        plan, layout, shots: filmShots, events: result.events,
      })
      setLoading(null)
      // 모션 정지에서는 자동재생하지 않는다 — WorldStage가 이미 마지막 프레임으로 점프해 두는데,
      // play()가 progress(0)으로 되감으면 완성된 프레임이 빈 무대로 바뀐다
      if (filmShots.length > 0 && settings.autoplay && !prefersStill(settings)) setTimeout(play, 120)

      // AI 연출은 배경에서 — 도착하면 자막·챕터·완급이 좋아지고, 실패해도 영화는 이미 완성돼 있다
      if (settings.aiDirector && geminiApiKey && result.events.length > 0) {
        setAiPending(true)
        void (async () => {
          try {
            const ai = await generateScreenplayWithSalvage(
              code, buildDigest(result.events), makeGeminiCall(geminiApiKey), screenplay, GEMINI_MODEL,
            )
            if (runId !== runIdRef.current) return
            setRun(prev => {
              if (!prev) return prev
              restoreRef.current = { seq: prev.shots[indexRef.current]?.seq ?? 0, playing: playingRef.current }
              // AI의 표현 선택(staging) — 격자 구성이 실제로 달라질 때만 필름을 재구축한다.
              // 판정·좌표는 buildStage(도구)가 하고, AI는 이름을 골랐을 뿐이다.
              let nextPlan = prev.plan
              let nextLayout = prev.layout
              let baseShots = prev.shots
              if (ai.screenplay.staging) {
                const rebuilt = buildStage(prev.events, ai.screenplay.staging)
                const gridIds = (p: StagePlan) => p.objects.filter(o => o.grid).map(o => o.objectId).sort().join(',')
                if (gridIds(rebuilt) !== gridIds(prev.plan)) {
                  nextPlan = rebuilt
                  nextLayout = layoutStage(rebuilt)
                  baseShots = choreograph(prev.events, rebuilt, code)
                }
              }
              return {
                ...prev,
                screenplay: ai.screenplay,
                steps: expandScreenplay(ai.screenplay, snaps),
                plan: nextPlan,
                layout: nextLayout,
                shots: decorateShots(baseShots, ai.screenplay, nextPlan, nextLayout),
                directorMode: ai.mode,
                directorCached: !!ai.cached,
              }
            })
          } catch {
            if (runId === runIdRef.current) setRun(prev => (prev ? { ...prev, directorMode: 'ai-fallback' } : prev))
          } finally {
            if (runId === runIdRef.current) setAiPending(false)
          }
        })()
      }
    } catch (err) {
      if (runId !== runIdRef.current) return
      setLoading(null)
      setRun({
        steps: [], snaps: [], screenplay: { chapters: [] }, clipped: false, error: String(err), directorMode: 'rule',
        plan: EMPTY_PLAN, layout: layoutStage(EMPTY_PLAN), shots: [], events: [],
      })
    }
  }

  const executeRunRef = useRef<() => void>(() => {})
  useEffect(() => {
    executeRunRef.current = executeRun
  })

  // AI 장식·재구축이 샷을 갈아끼우면 타임라인이 다시 만들어진다 — 보던 자리로 되돌린다.
  // seq 기준이라 재구축으로 샷 수가 달라져도 유효하다.
  // 자식(WorldStage) effect가 먼저 돌아 타임라인을 등록해 두므로 여기서 seek이 가능하다.
  useEffect(() => {
    const restore = restoreRef.current
    if (!restore || !run) return
    restoreRef.current = null
    let idx = 0
    for (let k = 0; k < run.shots.length; k++) if (run.shots[k].seq <= restore.seq) idx = k
    if (idx > 0 || restore.playing) {
      seek(idx)
      if (restore.playing) play()
    }
  }, [run, seek, play])

  const directorLabel =
    run?.directorMode === 'ai' ? (run.directorCached ? 'AI 연출 · 캐시' : 'AI 연출')
    : run?.directorMode === 'ai-partial' ? (run.directorCached ? 'AI 연출·일부 보강 · 캐시' : 'AI 연출·일부 보강')
    : run?.directorMode === 'ai-fallback' ? '규칙 폴백'
    : '규칙 연출'

  return (
    <div className="tl tl-app">
      <Nav
        trailing={
          <div className="tl-status" aria-label="실행 상태">
            {aiPending && <span className="tl-tag">AI 연출 준비 중…</span>}
            {run && !aiPending && (
              <span
                className={`tl-tag ${run.directorMode === 'ai' || run.directorMode === 'ai-partial' ? 'tl-tag--info' : ''}`}
              >
                {directorLabel}
              </span>
            )}
            <span className="tl-tag">{steps.length ? `${index + 1} / ${steps.length}` : '대기'}</span>
          </div>
        }
      />

      <div className="tl-work">
        {/* ── 코드 ── */}
        <section className="tl-col tl-panel" aria-label="코드 입력">
          <div className="tl-panel__bar tl-runbar">
            <button className="tl-btn tl-btn--sm" type="button" onClick={executeRun} disabled={loading !== null || !code.trim()}>
              <Play size={13} fill="currentColor" />
              실행
            </button>
            <span className="tl-runbar__hint">
              {code.trim() ? '표준 라이브러리 중심 · 단일 파일 · Ctrl+Enter 실행' : '파이썬 코드를 붙여넣으세요'}
            </span>
          </div>

          {issues.map(i => (
            <div key={i.code} className={`issue-banner ${i.level}`}>
              {i.message}
            </div>
          ))}
          {run?.clipped && <div className="issue-banner warn">실행이 길어 여기까지 시각화했어요.</div>}
          {run?.error && !run.syntaxError && <div className="issue-banner block">실행 결과: {tidyError(run.error)}</div>}

          <div className="tl-editor">
            <Editor
              defaultLanguage="python"
              language="python"
              theme="tracelens"
              value={code}
              onChange={value => setCode(value ?? '')}
              onMount={handleEditorMount}
              options={{
                minimap: { enabled: false },
                fontSize: 13.5,
                fontFamily: 'JetBrains Mono, ui-monospace, Consolas, monospace',
                lineHeight: 22,
                scrollBeyondLastLine: false,
                smoothScrolling: true,
                padding: { top: 14, bottom: 14 },
                glyphMargin: true,
                automaticLayout: true,
                renderLineHighlight: 'none',
                overviewRulerLanes: 0,
              }}
            />
          </div>

          <div className="tl-console">
            <div className="tl-console__head">
              <Terminal size={13} />
              <span className="tl-label">콘솔 출력</span>
            </div>
            <pre className={currentSnap?.stdout ? undefined : 'is-empty'}>
              {currentSnap?.stdout || '아직 출력이 없습니다'}
            </pre>
          </div>
        </section>

        {/* ── 재생 ── */}
        <section className="tl-col tl-panel" aria-label="실행 시각화">
          <div className="tl-panel__bar">
            <span className="tl-label">{chapterTitle || '실행 기록'}</span>
            {currentShot?.timelapse ? (
              <span className="tl-tag">×{currentShot.timelapse}회 압축</span>
            ) : (
              currentStep && <span className="tl-tag">{primitiveLabels[currentStep.primitive] ?? currentStep.primitive}</span>
            )}
          </div>

          <div className="tl-stage">
            {run && shots.length > 0 ? (
              <WorldStage plan={run.plan} layout={run.layout} shots={shots} film={film} />
            ) : run?.syntaxError ? (
              /* 구문 오류 — 실행 0줄. 파서의 사실로 만든 장면이 무대를 받는다 */
              <SyntaxScene info={run.syntaxError} />
            ) : run?.error ? (
              /* 그 밖의 실행 전 죽음(환경 문제 등)은 정적 패널로 */
              <div className="stage-error" role="alert">
                <span className="tl-label">실행이 여기서 멈췄습니다</span>
                <code className="tl-mono">{tidyError(run.error)}</code>
              </div>
            ) : (
              <Stage snapshot={currentSnap} step={currentStep} />
            )}
            {loading && (
              <div className="loading-overlay">
                <div className="spinner" />
                <span>{stageLabels[loading]}</span>
              </div>
            )}
          </div>

          <div className="narration-bar" data-size={settings.captionSize} aria-live="polite">
            {chapterTitle && <span className="chapter-tag">{chapterTitle}</span>}
            <span key={index}>{currentStep?.narration ?? '실행을 누르면 설명이 시작됩니다'}</span>
          </div>

          {run && shotSteps.length > 0 && (
            <PlayerBar
              steps={shotSteps}
              screenplay={run.screenplay}
              index={index}
              playing={playing}
              speed={speed}
              onPlay={play}
              onPause={pause}
              onSeek={seek}
              onSpeed={setSpeed}
            />
          )}

          {!playing && currentSnap && <Inspector snapshot={currentSnap} />}
        </section>
      </div>
    </div>
  )
}

export default App
