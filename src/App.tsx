import { useEffect, useMemo, useRef, useState } from 'react'
import Editor, { type OnMount } from '@monaco-editor/react'
import { Activity, Cpu, Film, Play, Terminal, Zap } from 'lucide-react'
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
import { usePlayback } from './player/usePlayback'
import './App.css'
import './stage.css'

type MonacoApi = Parameters<OnMount>[1]

type LoadingStage = TraceStage | 'directing'
const stageLabels: Record<LoadingStage, string> = {
  'python-loading': 'Python 환경 준비 중…',
  executing: '코드 실행·기록 중…',
  building: '설명 준비 중…',
  directing: 'AI 연출 생성 중…',
}

type DirectorMode = 'rule' | 'ai' | 'ai-fallback'

type RunArtifacts = {
  steps: PlaybackStep[]
  snaps: Snapshot[]
  screenplay: Screenplay
  clipped: boolean
  error?: string
  directorMode: DirectorMode
}

function App() {
  const [code, setCode] = useState<string>('')
  const [issues, setIssues] = useState<PreflightIssue[]>([])
  const [loading, setLoading] = useState<LoadingStage | null>(null)
  const [run, setRun] = useState<RunArtifacts | null>(null)
  const editorRef = useRef<Parameters<OnMount>[0] | null>(null)
  const monacoRef = useRef<MonacoApi | null>(null)
  const decorationRef = useRef<ReturnType<Parameters<OnMount>[0]['createDecorationsCollection']> | null>(null)

  const steps = run?.steps ?? []
  const { index, playing, speed, play, pause, seek, setSpeed } = usePlayback(steps)

  const bySeq = useMemo(() => new Map((run?.snaps ?? []).map(s => [s.seq, s])), [run])
  const currentStep = steps[index]
  const currentSnap = currentStep ? bySeq.get(currentStep.seq) : undefined

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
    decorationRef.current = editor.createDecorationsCollection()
  }

  const executeRun = async () => {
    const found = preflight(code)
    setIssues(found)
    if (found.some(i => i.level === 'block')) return

    setLoading('python-loading')
    setRun(null)
    try {
      const result = await runTrace(code, s => setLoading(s))
      const snaps = buildSnapshots(result.events)

      let screenplay: Screenplay
      let directorMode: DirectorMode = 'rule'
      if (geminiApiKey && result.events.length > 0) {
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
      setRun({ steps: expanded, snaps, screenplay, clipped: result.clipped, error: result.error, directorMode })
      setLoading(null)
      if (expanded.length > 0) setTimeout(play, 50)
    } catch (err) {
      setLoading(null)
      setRun({ steps: [], snaps: [], screenplay: { chapters: [] }, clipped: false, error: String(err), directorMode: 'rule' })
    }
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <div className="brand">
          <div className="brand-mark">
            <Activity size={21} strokeWidth={2.2} />
          </div>
          <div>
            <h1>TraceLens</h1>
            <span>실제 실행 기반 코드 무비</span>
          </div>
        </div>
        <div className="session-strip" aria-label="session status">
          <span className="status-pill">
            <Cpu size={15} />
            {run?.directorMode === 'ai' ? 'AI 연출' : run?.directorMode === 'ai-fallback' ? '규칙 폴백(AI 실패)' : '규칙 연출'}
          </span>
          <span className="status-pill accent">
            <Film size={15} />
            {steps.length ? `${index + 1}/${steps.length}` : 'idle'}
          </span>
          <span className="status-pill event">
            <Zap size={15} />
            {currentStep?.primitive ?? '-'}
          </span>
        </div>
      </header>

      <section className="workbench">
        <section className="left-panel" aria-label="code input">
          <div className="panel-toolbar">
            <button className="run-button" type="button" onClick={executeRun} disabled={loading !== null || !code.trim()}>
              <Play size={17} fill="currentColor" />
              Run
            </button>
          </div>

          {issues.map(i => (
            <div key={i.code} className={`issue-banner ${i.level}`}>{i.message}</div>
          ))}
          {run?.clipped && (
            <div className="issue-banner warn">실행이 길어 여기까지 시각화했어요.</div>
          )}
          {run?.error && (
            <div className="issue-banner block">실행 결과: {run.error}</div>
          )}

          <div className="editor-wrap">
            <Editor
              defaultLanguage="python"
              language="python"
              theme="vs-dark"
              value={code}
              onChange={value => setCode(value ?? '')}
              onMount={handleEditorMount}
              options={{
                minimap: { enabled: false },
                fontSize: 14,
                fontFamily: 'JetBrains Mono, Consolas, monospace',
                lineHeight: 22,
                scrollBeyondLastLine: false,
                smoothScrolling: true,
                padding: { top: 14, bottom: 14 },
                glyphMargin: true,
                automaticLayout: true,
              }}
            />
          </div>

          <div className="console-panel">
            <div className="subhead">
              <Terminal size={16} />
              <span>Console Output</span>
            </div>
            <pre>{currentSnap?.stdout || '아직 출력이 없습니다'}</pre>
          </div>
        </section>

        <section className="right-panel" aria-label="visualization output">
          <div className="stage-header">
            <div>
              <span className="eyebrow">실행 무비</span>
              <h2>{run ? run.screenplay.chapters[currentStep?.chapterIndex ?? 0]?.title ?? '' : '대기 중'}</h2>
            </div>
          </div>

          <div style={{ position: 'relative', flex: 1, minHeight: 320 }}>
            <Stage snapshot={currentSnap} step={currentStep} />
            {loading && (
              <div className="loading-overlay">
                <div className="spinner" />
                <span>{stageLabels[loading]}</span>
              </div>
            )}
          </div>

          <div className="narration-bar" aria-live="polite">
            <span className="chapter-tag">
              {run?.screenplay.chapters[currentStep?.chapterIndex ?? 0]?.title ?? '자막'}
            </span>
            <span key={index}>{currentStep?.narration ?? 'Run을 누르면 설명이 시작됩니다'}</span>
          </div>

          {run && steps.length > 0 && (
            <PlayerBar
              steps={steps}
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
      </section>
    </main>
  )
}

export default App
