/**
 * 오로라 배경 — Aceternity UI 의 Aurora Background 를 이 프로젝트에 맞게 옮겼어요 (11/18).
 * 맥북 장면("흩어진 배움이," + 도는 네모)의 배경에 깔아요 (MacScene.tsx).
 * 원본과 다른 점 (이 프로젝트에 Tailwind · shadcn 이 없어서):
 *  · Tailwind 클래스 · animate-aurora 대신 같은 값의 CSS 를 landing/lerny-aurora.css 에 썼어요 (.aur-*).
 *  · cn(clsx + tailwind-merge) 대신 클래스 이름을 공백으로 이어 붙여요.
 *  · 다크 모드는 .dark 클래스가 아니라 이 프로젝트의 :root[data-theme="dark"] 를 따라요.
 *  · 원본은 <main> + 화면 높이(100vh) 칸이지만, 여기서는 이미 있는 장면 칸 안에 깔리는 배경 층만 써요 (layer).
 */
import type { CSSProperties, HTMLAttributes, ReactNode } from 'react'
import './lerny-aurora.css'

const cn = (...c: (string | undefined | false)[]) => c.filter(Boolean).join(' ')

const AURORA_VARS = {
  '--aurora': 'repeating-linear-gradient(100deg,#3b82f6 10%,#a5b4fc 15%,#93c5fd 20%,#ddd6fe 25%,#60a5fa 30%)',
  '--dark-gradient': 'repeating-linear-gradient(100deg,#000 0%,#000 7%,transparent 10%,transparent 12%,#000 16%)',
  '--white-gradient': 'repeating-linear-gradient(100deg,#fff 0%,#fff 7%,transparent 10%,transparent 12%,#fff 16%)',
  '--blue-300': '#93c5fd',
  '--blue-400': '#60a5fa',
  '--blue-500': '#3b82f6',
  '--indigo-300': '#a5b4fc',
  '--violet-200': '#ddd6fe',
  '--black': '#000',
  '--white': '#fff',
  '--transparent': 'transparent',
} as CSSProperties

/** 오로라 빛 층만 — 감싼 칸을 꽉 채워요 (position: absolute; inset: 0) */
export function AuroraLayer({ showRadialGradient = true, className }: { showRadialGradient?: boolean; className?: string }) {
  return (
    <div className={cn('aur-clip', className)} style={AURORA_VARS} aria-hidden="true">
      <div className={cn('aur-light', showRadialGradient && 'is-radial')} />
    </div>
  )
}

interface AuroraBackgroundProps extends HTMLAttributes<HTMLDivElement> {
  children: ReactNode
  showRadialGradient?: boolean
}

/** 원본과 같은 모양의 칸 (화면 높이, 가운데 정렬) — 다른 곳에서 통째로 쓸 때 */
export const AuroraBackground = ({ className, children, showRadialGradient = true, ...props }: AuroraBackgroundProps) => {
  return (
    <div className={cn('aur-box', className)} {...props}>
      <AuroraLayer showRadialGradient={showRadialGradient} />
      {children}
    </div>
  )
}
