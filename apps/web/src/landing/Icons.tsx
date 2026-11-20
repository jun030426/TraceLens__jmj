/**
 * [공용 그림] 랜딩 아이콘 — 이모지·기호(📄 ▶ ✓ ↗ ↓ ❚❚) 대신 쓰는 선 아이콘
 * - 모두 같은 선 굵기(1.75)이고 글자 색(currentColor)과 글자 크기(1em)를 따라가요.
 * - 장식용이라 화면 읽기 프로그램에는 읽히지 않아요(aria-hidden).
 */

import type { ReactNode } from 'react'

type IconProps = { size?: number | string; className?: string }

function Svg({ size = '1em', className, children }: IconProps & { children: ReactNode }) {
  return (
    <svg
      className={`ln-icon${className ? ` ${className}` : ''}`}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.75}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {children}
    </svg>
  )
}

/** 문서 */
export function IconDoc(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" />
      <path d="M14 3v5h5M9 13h6M9 17h4" />
    </Svg>
  )
}

/** 재생 (back 이면 왼쪽을 향해요) */
export function IconPlay({ back, ...props }: IconProps & { back?: boolean }) {
  return (
    <Svg {...props}>
      <path d={back ? 'M17 5.5v13L6.5 12z' : 'M7 5.5v13L17.5 12z'} fill="currentColor" />
    </Svg>
  )
}

/** 일시정지 */
export function IconPause(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M8.5 5.5v13M15.5 5.5v13" strokeWidth={3} />
    </Svg>
  )
}

/** 체크 */
export function IconCheck(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M5 12.5l4.5 4.5L19 7.5" />
    </Svg>
  )
}

/** 오른쪽 위 화살표 */
export function IconArrowUpRight(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M7 17L17 7M8.5 7H17v8.5" />
    </Svg>
  )
}
