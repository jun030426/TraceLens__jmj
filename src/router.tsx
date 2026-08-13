import { useCallback, useEffect, useSyncExternalStore, type MouseEvent, type ReactNode } from 'react'

export const ROUTES = {
  landing: '/',
  app: '/app',
  about: '/about',
  help: '/help',
  settings: '/settings',
  demo: '/demo',
} as const

export type RoutePath = (typeof ROUTES)[keyof typeof ROUTES]

const listeners = new Set<() => void>()

function emit() {
  for (const l of listeners) l()
}

function subscribe(listener: () => void) {
  listeners.add(listener)
  window.addEventListener('popstate', emit)
  return () => {
    listeners.delete(listener)
    if (listeners.size === 0) window.removeEventListener('popstate', emit)
  }
}

function readPath(): string {
  if (typeof window === 'undefined') return ROUTES.landing
  const p = window.location.pathname.replace(/\/+$/, '')
  return p === '' ? ROUTES.landing : p
}

export function navigate(to: string, replace = false) {
  if (readPath() === to) return
  window.history[replace ? 'replaceState' : 'pushState']({}, '', to)
  emit()
  window.scrollTo({ top: 0, behavior: 'instant' as ScrollBehavior })
}

export function usePath(): string {
  return useSyncExternalStore(subscribe, readPath, () => ROUTES.landing)
}

/** 라우트가 바뀌면 문서에 표면 종류를 기록한다 — 전역 배경색이 그것을 따른다. */
export function useSurfaceFlag(path: string) {
  useEffect(() => {
    document.documentElement.dataset.surface = path === ROUTES.app ? 'app' : 'site'
  }, [path])
}

export function Link({
  to,
  children,
  className,
  ...rest
}: { to: string; children: ReactNode; className?: string } & Omit<
  React.AnchorHTMLAttributes<HTMLAnchorElement>,
  'href'
>) {
  const path = usePath()
  const onClick = useCallback(
    (e: MouseEvent<HTMLAnchorElement>) => {
      if (e.defaultPrevented || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button !== 0) return
      e.preventDefault()
      navigate(to)
    },
    [to],
  )
  return (
    <a href={to} onClick={onClick} className={className} aria-current={path === to ? 'page' : undefined} {...rest}>
      {children}
    </a>
  )
}
