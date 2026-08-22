import { useEffect, useState } from 'react'
import App from './App.tsx'
import Landing from './routes/Landing'
import About from './routes/About'
import Help from './routes/Help'
import Settings from './routes/Settings'
import NotFound from './routes/NotFound'
import { Page } from './ui/Chrome'
import { ROUTES, usePath, useSurfaceFlag } from './router'
import { prefersStill, useSettings } from './settings/store'

/** 어느 화면을 그릴지 정하는 곳. main.tsx는 붙이기만 한다 — 진입점이 라우팅까지 들고 있으면
    그 파일은 컴포넌트를 정의하면서 아무것도 내보내지 않게 되어 fast refresh가 꺼진다. */
export default function Root() {
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
