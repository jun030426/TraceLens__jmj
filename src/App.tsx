import { useEffect, useMemo, useRef, useState } from 'react'
import Editor, { type OnMount } from '@monaco-editor/react'
import { Activity, Cpu, Film, Play, Terminal, Workflow, Zap } from 'lucide-react'
import Stage from './components/Stage'
import PlayerBar from './components/PlayerBar'
import Inspector from './components/Inspector'
import { preflight, type PreflightIssue } from './trace/preflight'
import { runTrace, warmUp, type TraceStage } from './trace/tracerClient'
import { buildSnapshots, type Snapshot } from './trace/snapshots'
import { buildScreenplay } from './screenplay/ruleDirector'
import type { Screenplay } from './screenplay/types'
import { expandScreenplay, type PlaybackStep } from './player/expand'
import { usePlayback } from './player/usePlayback'
import { samples, defaultCode } from './samples'
import './App.css'
import './stage.css'

type MonacoApi = Parameters<OnMount>[1]

const stageLabels: Record<TraceStage, string> = {
  'python-loading': 'Python 환경 준비 중…',
  executing: '코드 실행·기록 중…',
  building: '설명 준비 중…',
}

type RunArtifacts = {
  steps: PlaybackStep[]
  snaps: Snapshot[]
  screenplay: Screenplay
  clipped: boolean
  error?: string
}

function App() {
  const [code, setCode] = useState<string>(defaultCode)
  const [issues, setIssues] = useState<PreflightIssue[]>([])
  const [loading, setLoading] = useState<TraceStage | null>(null)
  const [run, setRun] = useState<RunArtifacts | null>(null)
  const editorRef = useRef<Parameters<OnMount>[0] | null>(null)
  const monacoRef = useRef<MonacoApi | null>(null)
  const decorationRef = useRef<ReturnType<Parameters<OnMount>[0]['createDecorationsCollection']> | null>(null)

  const steps = run?.steps ?? []
  const { index, playing, speed, play, pause, seek, setSpeed } = usePlayback(steps)

  const bySeq = useMemo(() => new Map((run?.snaps ?? []).map(s => [s.seq, s])), [run])
  const currentStep = steps[index]
  const currentSnap = currentStep ? bySeq.get(currentStep.seq) : undefined
  const activeSample = samples.find(s => s.code === code)?.id

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
      const screenplay = buildScreenplay(result.events)
      const expanded = expandScreenplay(screenplay, snaps)
      setRun({ steps: expanded, snaps, screenplay, clipped: result.clipped, error: result.error })
      setLoading(null)
      if (expanded.length > 0) setTimeout(play, 50)
    } catch (err) {
      setLoading(null)
      setRun({ steps: [], snaps: [], screenplay: { chapters: [] }, clipped: false, error: String(err) })
    }
  }

  const loadSample = (sampleCode: string) => {
    setCode(sampleCode)
    setIssues([])
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <div className="brand">
          <div className="brand-mark">
            <Activity size={21} strokeWidth={2.2} />
          </div>
          <div>
            <h1>Algo-Scope</h1>
            <span>실제 실행 기반 코드 무비</span>
          </div>
        </div>
        <div className="session-strip" aria-label="session status">
          <span className="status-pill">
            <Cpu size={15} />
            Slice 1 · rule-based
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
            <div className="preset-strip" aria-label="예제 코드">
              {samples.map(s => (
                <button
                  key={s.id}
                  className={activeSample === s.id ? 'preset-button active' : 'preset-button'}
                  type="button"
                  title={s.description}
                  onClick={() => loadSample(s.code)}
                >
                  <Workflow size={14} />
                  {s.label}
                </button>
              ))}
            </div>
            <button className="run-button" type="button" onClick={executeRun} disabled={loading !== null}>
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
