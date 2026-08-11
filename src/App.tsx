import { useEffect, useMemo, useRef, useState } from 'react'
import Editor, { type OnMount } from '@monaco-editor/react'
import {
  Activity,
  Braces,
  ChevronLeft,
  ChevronRight,
  Cpu,
  Gauge,
  Layers3,
  Pause,
  Play,
  RotateCcw,
  Terminal,
  Workflow,
  Zap,
} from 'lucide-react'
import PixiStage from './PixiStage'
import {
  algorithmPresets,
  buildPreviewTrace,
  sampleCode,
  type TraceFrame,
} from './tracing'
import './App.css'

type MonacoApi = Parameters<OnMount>[1]

const speedOptions = [
  { label: '0.5x', value: 0.5 },
  { label: '1x', value: 1 },
  { label: '1.25x', value: 1.25 },
  { label: '1.5x', value: 1.5 },
  { label: '2x', value: 2 },
  { label: '3x', value: 3 },
  { label: 'CPU', value: 'cpu' },
] as const

type PlaybackSpeed = (typeof speedOptions)[number]['value']

const baseStepDelayMs = 1000
const speedToDelay = (speed: PlaybackSpeed) =>
  speed === 'cpu' ? 45 : Math.max(220, baseStepDelayMs / speed)

function App() {
  const [code, setCode] = useState(sampleCode)
  const [trace, setTrace] = useState<TraceFrame[]>(() => buildPreviewTrace(sampleCode))
  const [currentIndex, setCurrentIndex] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeed] = useState<PlaybackSpeed>(0.5)
  const editorRef = useRef<Parameters<OnMount>[0] | null>(null)
  const monacoRef = useRef<MonacoApi | null>(null)
  const decorationRef = useRef<ReturnType<Parameters<OnMount>[0]['createDecorationsCollection']> | null>(
    null,
  )

  const currentFrame = trace[currentIndex]
  const currentArray = currentFrame?.structures[0]
  const activePreset = algorithmPresets.find((preset) => preset.code === code)?.id
  const consoleLines = useMemo(
    () =>
      trace
        .slice(0, currentIndex + 1)
        .filter((frame) => frame.stdout)
        .map((frame) => `[${frame.seq}] ${frame.stdout}`),
    [trace, currentIndex],
  )

  useEffect(() => {
    if (!playing) {
      return
    }

    const timer = window.setInterval(() => {
      setCurrentIndex((index) => {
        if (index >= trace.length - 1) {
          setPlaying(false)
          return index
        }

        return index + 1
      })
    }, speedToDelay(speed))

    return () => window.clearInterval(timer)
  }, [playing, speed, trace.length])

  useEffect(() => {
    const editor = editorRef.current
    const monaco = monacoRef.current
    const decorations = decorationRef.current

    if (!editor || !monaco || !decorations || !currentFrame) {
      return
    }

    decorations.set([
      {
        range: new monaco.Range(currentFrame.currentLine, 1, currentFrame.currentLine, 1),
        options: {
          isWholeLine: true,
          className: 'current-line-highlight',
          glyphMarginClassName: 'current-line-glyph',
        },
      },
    ])
    editor.revealLineInCenterIfOutsideViewport(currentFrame.currentLine)
  }, [currentFrame])

  const handleEditorMount: OnMount = (editor, monaco) => {
    editorRef.current = editor
    monacoRef.current = monaco
    decorationRef.current = editor.createDecorationsCollection()
  }

  const runTrace = () => {
    const nextTrace = buildPreviewTrace(code)
    setTrace(nextTrace)
    setCurrentIndex(0)
    setPlaying(true)
  }

  const loadPreset = (presetCode: string) => {
    const nextTrace = buildPreviewTrace(presetCode)
    setCode(presetCode)
    setTrace(nextTrace)
    setCurrentIndex(0)
    setPlaying(false)
  }

  const resetTrace = () => {
    setPlaying(false)
    setCurrentIndex(0)
  }

  const goPrevious = () => {
    setPlaying(false)
    setCurrentIndex((index) => Math.max(0, index - 1))
  }

  const goNext = () => {
    setPlaying(false)
    setCurrentIndex((index) => Math.min(trace.length - 1, index + 1))
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
            <span>Python Auto Trace Sandbox</span>
          </div>
        </div>

        <div className="session-strip" aria-label="session status">
          <span className="status-pill">
            <Cpu size={15} />
            frontend preview
          </span>
          <span className="status-pill accent">
            <Gauge size={15} />
            {currentIndex + 1}/{trace.length}
          </span>
          <span className="status-pill event">
            <Zap size={15} />
            {currentFrame?.event.name ?? 'idle'}
          </span>
          <span className="status-pill algorithm">
            <Workflow size={15} />
            {currentFrame?.algorithm.label ?? 'Unknown'}
          </span>
        </div>
      </header>

      <section className="workbench">
        <section className="left-panel" aria-label="code input">
          <div className="panel-toolbar">
            <label className="selector-label" htmlFor="language">
              Language
            </label>
            <select id="language" defaultValue="python" aria-label="language selector">
              <option value="python">Python</option>
            </select>
            <div className="preset-strip" aria-label="algorithm presets">
              {algorithmPresets.map((preset) => (
                <button
                  className={activePreset === preset.id ? 'preset-button active' : 'preset-button'}
                  key={preset.id}
                  type="button"
                  title={preset.description}
                  onClick={() => loadPreset(preset.code)}
                >
                  <Workflow size={14} />
                  {preset.label}
                </button>
              ))}
            </div>
            <button className="run-button" type="button" onClick={runTrace}>
              <Play size={17} fill="currentColor" />
              Run Visualization
            </button>
          </div>

          <div className="editor-wrap">
            <Editor
              defaultLanguage="python"
              language="python"
              theme="vs-dark"
              value={code}
              onChange={(value) => setCode(value ?? '')}
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
            <pre>
              {consoleLines.length > 0
                ? consoleLines.join('\n')
                : 'waiting for trace output...'}
            </pre>
          </div>
        </section>

        <section className="right-panel" aria-label="visualization output">
          <div className="stage-header">
            <div>
              <span className="eyebrow">{currentFrame?.algorithm.label ?? 'PixiJS Stage'}</span>
              <h2>
                {currentArray?.id ?? 'array'} {currentArray?.view ?? 'state'}
              </h2>
            </div>
            <div className="event-chip">{currentFrame?.event.label ?? 'idle'}</div>
          </div>

          <PixiStage frame={currentFrame} />

          <div className="playback">
            <button type="button" onClick={resetTrace} title="Reset trace" aria-label="Reset trace">
              <RotateCcw size={18} />
            </button>
            <button
              type="button"
              onClick={goPrevious}
              title="Previous step"
              aria-label="Previous step"
            >
              <ChevronLeft size={20} />
            </button>
            <button
              className="primary-control"
              type="button"
              onClick={() => setPlaying((value) => !value)}
              title={playing ? 'Pause' : 'Play'}
              aria-label={playing ? 'Pause' : 'Play'}
            >
              {playing ? <Pause size={20} fill="currentColor" /> : <Play size={20} fill="currentColor" />}
            </button>
            <button type="button" onClick={goNext} title="Next step" aria-label="Next step">
              <ChevronRight size={20} />
            </button>
            <div className="speed-control" aria-label="playback speed">
              <span>Speed</span>
              <div className="speed-options">
                {speedOptions.map((option) => (
                  <button
                    className={[
                      'speed-button',
                      speed === option.value ? 'active' : '',
                      option.value === 'cpu' ? 'cpu' : '',
                    ].join(' ')}
                    key={option.label}
                    type="button"
                    aria-pressed={speed === option.value}
                    onClick={() => setSpeed(option.value)}
                  >
                    {option.label}
                  </button>
                ))}
              </div>
            </div>
          </div>

          <div className="inspectors">
            <section className="inspector" aria-label="variables">
              <div className="subhead">
                <Braces size={16} />
                <span>Variables</span>
              </div>
              <div className="variable-list">
                {currentFrame?.variables.map((variable) => (
                  <div className="variable-row" key={`${variable.name}-${variable.type}`}>
                    <span>{variable.name}</span>
                    <strong>{String(variable.value)}</strong>
                    <small>{variable.type}</small>
                  </div>
                ))}
              </div>
            </section>

            <section className="inspector" aria-label="call stack">
              <div className="subhead">
                <Layers3 size={16} />
                <span>Call Stack</span>
              </div>
              <div className="stack-list">
                {currentFrame?.callStack.map((stackFrame) => (
                  <span key={stackFrame}>{stackFrame}</span>
                ))}
              </div>
            </section>

            <section className="inspector compact" aria-label="step controls">
              <div className="subhead">
                <StepIcon />
                <span>Step</span>
              </div>
              <strong className="step-number">{currentFrame?.seq ?? 0}</strong>
              <small>{currentFrame?.compressedRepeat ? `${currentFrame.compressedRepeat} repeats` : 'live diff'}</small>
            </section>
          </div>
        </section>
      </section>
    </main>
  )
}

function StepIcon() {
  return (
    <span className="step-icon" aria-hidden="true">
      <ChevronLeft size={13} />
      <ChevronRight size={13} />
    </span>
  )
}

export default App
