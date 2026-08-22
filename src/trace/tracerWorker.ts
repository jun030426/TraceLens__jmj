/// <reference lib="webworker" />
import tracerSource from './py/tracer.py?raw'

const PYODIDE_URL = 'https://cdn.jsdelivr.net/pyodide/v0.26.4/full/pyodide.mjs'
// pyodide 타입은 CDN 동적 로드라 any로 다룬다
let pyodidePromise: Promise<any> | null = null

async function getPyodide() {
  if (!pyodidePromise) {
    pyodidePromise = (async () => {
      const mod = await import(/* @vite-ignore */ PYODIDE_URL)
      const py = await mod.loadPyodide()
      py.runPython(tracerSource)
      return py
    })()
  }
  return pyodidePromise
}

// 페이지 진입 직후 선로딩 (콜드 스타트 흡수)
void getPyodide().catch(() => { pyodidePromise = null })

self.onmessage = async (e: MessageEvent<{ code: string; maxEvents: number }>) => {
  try {
    self.postMessage({ type: 'stage', stage: 'python-loading' })
    const py = await getPyodide()
    self.postMessage({ type: 'stage', stage: 'executing' })
    py.globals.set('js_emit', (s: string) => self.postMessage({ type: 'chunk', json: s }))
    py.globals.set('user_code', e.data.code)
    py.globals.set('max_events', e.data.maxEvents)
    py.runPython('run_traced(user_code, js_emit, max_events)')
  } catch (err) {
    self.postMessage({ type: 'fatal', message: String(err) })
  }
}
