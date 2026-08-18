import { StrictMode, useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import './ui/ui.css'
import App from './App.tsx'
import Landing from './routes/Landing'
import About from './routes/About'
import Help from './routes/Help'
import Settings from './routes/Settings'
import { Page } from './ui/Chrome'
import { Link, ROUTES, usePath, useSurfaceFlag } from './router'
import { prefersStill, useSettings } from './settings/store'

function NotFound() {
  return (
    <main className="tl-shell tl-lead" style={{ paddingBottom: '22vh' }}>
      <h1 className="tl-h1">이 주소에는 아무것도 없습니다</h1>
      <p className="tl-lede" style={{ marginTop: 14 }}>주소를 잘못 입력했거나, 없어진 페이지입니다.</p>
      <div className="tl-actions" style={{ marginTop: 24 }}>
        <Link to={ROUTES.landing} className="tl-btn">
          처음으로
        </Link>
        <Link to={ROUTES.app} className="tl-btn tl-btn--quiet">
          실행 화면으로
        </Link>
      </div>
    </main>
  )
}

function Root() {
  const path = usePath()
  const settings = useSettings()
  useSurfaceFlag(path)

  const [osStill, setOsStill] = useState(false)
  useEffect(() => {
    if (!window.matchMedia) return
    const mq = window.matchMedia('(prefers-reduced-motion: reduce)')
    const sync = () => setOsStill(mq.matches)
    sync()
    mq.addEventListener('change', sync)
    return () => mq.removeEventListener('change', sync)
  }, [])

  const still = osStill || prefersStill(settings)

  useEffect(() => {
    document.documentElement.dataset.still = still ? 'true' : 'false'
  }, [still])

  if (path === ROUTES.app) {
    return <App />
  }

  const page =
    path === ROUTES.landing ? (
      <Landing still={still} />
    ) : path === ROUTES.about ? (
      <About />
    ) : path === ROUTES.help ? (
      <Help />
    ) : path === ROUTES.settings ? (
      <Settings />
    ) : (
      <NotFound />
    )

  return <Page still={still}>{page}</Page>
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <Root />
  </StrictMode>,
)
