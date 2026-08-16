import { useEffect, useMemo, useRef, useState } from 'react'
import Editor, { type OnMount } from '@monaco-editor/react'
import { Play, Terminal } from 'lucide-react'
import Stage from './components/Stage'
import PlayerBar from './components/PlayerBar'
import Inspector from './components/Inspector'
import { preflight, type PreflightIssue } from './trace/preflight'
import { runTrace, warmUp, type TraceStage } from './trace/tracerClient'
import { buildSnapshots, type Snapshot } from './trace/snapshots'
import { buildScreenplay } from './screenplay/ruleDirector'
import { buildDigest } from './digest/buildDigest'
import { generateScreenplay } from './director/llmDirector'
import { makeGeminiCall, geminiApiKey } from './director/gemini'
import type { Screenplay } from './screenplay/types'
import { expandScreenplay, type PlaybackStep } from './player/expand'
import { buildStage } from './film/buildStage'
import { layoutStage, type StageLayout } from './film/layout'
import { choreograph } from './film/choreograph'
import type { Shot, StagePlan } from './film/types'
import WorldStage from './film/WorldStage'
import { useFilm } from './film/useFilm'
import { Nav } from './ui/Chrome'
import { useSettings } from './settings/store'
import './ui/app.css'

type MonacoApi = Parameters<OnMount>[1]

type LoadingStage = TraceStage | 'directing'
const stageLabels: Record<LoadingStage, string> = {
  'python-loading': 'Python 환경 준비 중…',
  executing: '코드 실행·기록 중…',
  building: '설명 준비 중…',
  directing: 'AI 연출 생성 중…',
}

type DirectorMode = 'rule' | 'ai' | 'ai-fallback'

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
  directorMode: DirectorMode
  plan: StagePlan
  layout: StageLayout
  shots: Shot[]
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
  const editorRef = useRef<Parameters<OnMount>[0] | null>(null)
  const monacoRef = useRef<MonacoApi | null>(null)
  const decorationRef = useRef<ReturnType<Parameters<OnMount>[0]['createDecorationsCollection']> | null>(null)

  const settings = useSettings()
  const steps = run?.steps ?? []
  const shots = useMemo(() => run?.shots ?? [], [run])
  const { index, playing, speed, play, pause, seek, setSpeed, register } = useFilm(shots)
  const film = { index, playing, speed, play, pause, seek, setSpeed, register }

  // 설정의 기본 배속은 시작 값이다 — 재생 중 바꾼 값을 덮어쓰지 않도록 설정이 바뀔 때만 적용한다
  useEffect(() => { setSpeed(settings.speed) }, [settings.speed, setSpeed])

  const bySeq = useMemo(() => new Map((run?.snaps ?? []).map(s => [s.seq, s])), [run])

  // 샷과 스텝은 개수가 다르다 — 샷마다 "그 seq를 넘지 않는 마지막 스텝"의 자막·챕터를 물려준다.
  // 그래야 진행바·자막·인스펙터가 전부 같은 축(샷)에서 움직인다.
  const shotSteps = useMemo<PlaybackStep[]>(() => {
    let cursor = 0
    let carried: PlaybackStep | undefined
    return shots.map(sh => {
      while (cursor < steps.length && steps[cursor].seq <= sh.seq) carried = steps[cursor++]
      return {
        seq: sh.seq,
        chapterIndex: carried?.chapterIndex ?? 0,
        primitive: carried?.primitive ?? 'variables',
        focus: carried?.focus ?? [],
        narration: sh.timelapse ? `같은 반복이 계속됩니다 (총 ${sh.timelapse}회 더)` : carried?.narration ?? '',
        durationMs: sh.durationMs,
      }
    })
  }, [shots, steps])

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

    setLoading('python-loading')
    setRun(null)
    try {
      const result = await runTrace(code, s => setLoading(s), {
        maxEvents: settings.maxEvents,
        timeoutMs: settings.timeoutMs,
      })
      const snaps = buildSnapshots(result.events)

      let screenplay: Screenplay
      let directorMode: DirectorMode = 'rule'
      if (settings.aiDirector && geminiApiKey && result.events.length > 0) {
        setLoading('directing')
        try {
          screenplay = await generateScreenplay(code, buildDigest(result.events), makeGeminiCall(geminiApiKey))
          directorMode = 'ai'
        } catch {
          screenplay = buildScreenplay(result.events)
          directorMode = 'ai-fallback'
        }
      } else {
        screenplay = buildScreenplay(result.events)
      }

      const expanded = expandScreenplay(screenplay, snaps)
      // 무대는 AI와 무관하게 트레이스에서 계산된다 — 콘티가 없어도 영화는 나온다
      const plan = buildStage(result.events)
      const layout = layoutStage(plan)
      const filmShots = choreograph(result.events, plan)
      setRun({
        steps: expanded, snaps, screenplay, clipped: result.clipped, error: result.error, directorMode,
        plan, layout, shots: filmShots,
      })
      setLoading(null)
      if (filmShots.length > 0 && settings.autoplay) setTimeout(play, 120)
    } catch (err) {
      setLoading(null)
      setRun({
        steps: [], snaps: [], screenplay: { chapters: [] }, clipped: false, error: String(err), directorMode: 'rule',
        plan: EMPTY_PLAN, layout: layoutStage(EMPTY_PLAN), shots: [],
      })
    }
  }

  const executeRunRef = useRef<() => void>(() => {})
  useEffect(() => {
    executeRunRef.current = executeRun
  })

  const directorLabel =
    run?.directorMode === 'ai' ? 'AI 연출' : run?.directorMode === 'ai-fallback' ? '규칙 폴백' : '규칙 연출'

  return (
    <div className="tl tl-app">
      <Nav
        trailing={
          <div className="tl-status" aria-label="실행 상태">
            {run && (
              <span className={`tl-tag ${run.directorMode === 'ai' ? 'tl-tag--info' : ''}`}>{directorLabel}</span>
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
          {run?.error && <div className="issue-banner block">실행 결과: {run.error}</div>}

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
