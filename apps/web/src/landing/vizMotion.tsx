/** 랜딩 공용: 요소의 최초 화면 진입을 감지한다. */

import { useEffect, useState, type RefObject } from 'react'

/** 요소가 화면에 한 번이라도 들어왔는지 */
export function useInView(ref: RefObject<HTMLElement | null>, threshold = 0.2) {
  const [inView, setInView] = useState(false)
  useEffect(() => {
    const el = ref.current
    if (!el || inView) return
    if (typeof IntersectionObserver === 'undefined') {
      setInView(true)
      return
    }
    const io = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setInView(true)
          io.disconnect()
        }
      },
      { threshold },
    )
    io.observe(el)
    return () => io.disconnect()
  }, [ref, threshold, inView])
  return inView
}
