/**
 * [공용 훅] 서버에서 데이터를 받아올 때 쓰는 훅 — 로딩 중 / 오류 / 데이터 상태를 한 번에 관리
 * - 학생 퀴즈 목록(QuizList), 교수자 퀴즈 현황(ProfessorQuizStats)에서 사용
 *
 * @example const { data, loading, error, reload } = useApiData(() => getMyQuizzes(), [])
 * @param fetcher 데이터를 돌려주는 async 함수 (api/ 폴더의 함수)
 * @param deps    이 값이 바뀌면 다시 불러와요 (useEffect 의존성과 같아요)
 */

import { useCallback, useEffect, useState, type DependencyList } from 'react'

export function useApiData<T>(fetcher: () => Promise<T>, deps: DependencyList) {
  const [data, setData] = useState<T | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [reloadKey, setReloadKey] = useState(0)

  // eslint-disable-next-line react-hooks/exhaustive-deps
  const load = useCallback(fetcher, deps)

  useEffect(() => {
    let cancelled = false // 응답 오기 전에 페이지를 벗어나거나 값이 바뀌면 결과를 버려요
    setLoading(true)
    setError(null)
    load()
      .then((result) => !cancelled && setData(result))
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : '데이터를 불러오지 못했어요.')
      })
      .finally(() => !cancelled && setLoading(false))
    return () => {
      cancelled = true
    }
  }, [load, reloadKey])

  /** 다시 불러오기 */
  const reload = useCallback(() => setReloadKey((k) => k + 1), [])

  return { data, setData, loading, error, reload }
}
