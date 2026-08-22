import { useCallback, type MouseEvent, type ReactNode } from 'react'
import { navigate, usePath } from '../router'

/** 내부 이동 링크 — 라우팅 로직(router.ts)과 한 파일에 두면 그 파일이 "상수·훅·컴포넌트"를
    한꺼번에 내보내게 되어 fast refresh가 꺼진다. 컴포넌트는 컴포넌트끼리 산다. */
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
