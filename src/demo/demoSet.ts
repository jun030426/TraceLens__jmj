import type { TraceEvent } from '../trace/types'

/* 파일럿 설문용 데모 묶음.
   목적은 "이 코드가 무엇을 하는 코드인가"가 아니라
   "메모리에서 어떤 순서로 진행되는가"만 영상으로 전달되는지 확인하는 것이다.
   그래서 제목에 코드의 의도를 쓰지 않는다 — 답을 미리 알려주면 실험이 무너진다. */

export type DemoFixture = { id: string; code: string; events: TraceEvent[]; clipped: boolean }

const modules = import.meta.glob('../fixtures/demo/*.json', { eager: true }) as Record<
  string,
  { default: DemoFixture }
>

const byId = new Map<string, DemoFixture>()
for (const m of Object.values(modules)) byId.set(m.default.id, m.default)

export type DemoMeta = {
  id: string
  /** 참가자에게 보이는 이름 — 답을 흘리지 않는 중립적 번호·라벨 */
  label: string
  /** 팀 내부용: 이 영상이 보여주려는 메모리 사건 (참가자에게 노출 금지) */
  internalGoal: string
  /** 층화: 우리가 잘하는 유형인지 어려운 유형인지 */
  tier: 'core' | 'mid'
}

const META: DemoMeta[] = [
  { id: 'fill', label: '영상 1', internalGoal: '리스트 칸이 하나씩 차오르는 순서', tier: 'core' },
  { id: 'alias', label: '영상 2', internalGoal: '두 이름이 같은 상자를 가리킴 — 한쪽을 바꾸면 둘 다 바뀜', tier: 'core' },
  { id: 'copy-vs-alias', label: '영상 3', internalGoal: '별칭은 끈이 한 상자로, 복사는 새 상자로 감', tier: 'mid' },
  { id: 'call', label: '영상 4', internalGoal: '함수 프레임이 들어왔다 나가고, 지역 변수는 그 안에서만 산다', tier: 'core' },
  { id: 'recursion', label: '영상 5', internalGoal: '프레임이 깊이 쌓였다가 역순으로 풀린다', tier: 'mid' },
  { id: 'dict-fill', label: '영상 6', internalGoal: 'dict에 키가 하나씩 채워지는 순서', tier: 'mid' },
]

export type Demo = DemoMeta & { fixture: DemoFixture }

export const demos: Demo[] = META.flatMap(meta => {
  const fixture = byId.get(meta.id)
  return fixture ? [{ ...meta, fixture }] : []
})

/** 참가자에게 던지는 질문 — 자기보고가 아니라 서술을 받는다 */
export const PILOT_QUESTION = '방금 본 영상에서 무슨 일이 순서대로 일어났나요? 두세 문장으로 적어주세요.'
