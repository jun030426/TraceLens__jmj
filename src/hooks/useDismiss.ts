/**
 * [공용 훅] 열린 메뉴·창 닫기 — ESC 키 / (선택) 바깥 클릭
 * - 헤더 프로필 메뉴, 수강 신청 확인 창, 강의 추가 모달에서 사용
 */

import { useEffect, type RefObject } from 'react'

/**
 * @param open    지금 열려 있는지 (닫혀 있으면 아무것도 안 함)
 * @param onClose 닫을 때 실행할 함수
 * @param ref     넘기면 이 요소 바깥을 클릭했을 때도 닫힘
 */
export function useDismiss(
  open: boolean,
  onClose: () => void,
  ref?: RefObject<HTMLElement | null>,
) {
  useEffect(() => {
    if (!open) return

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    const handleClickOutside = (e: MouseEvent) => {
      if (ref?.current && !ref.current.contains(e.target as Node)) onClose()
    }

    document.addEventListener('keydown', handleKeyDown)
    if (ref) document.addEventListener('mousedown', handleClickOutside)
    return () => {
      document.removeEventListener('keydown', handleKeyDown)
      document.removeEventListener('mousedown', handleClickOutside)
    }
  }, [open, onClose, ref])
}
