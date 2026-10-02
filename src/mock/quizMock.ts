/**
 * [임시 데이터] 교수자 퀴즈 현황용 퀴즈 · 응시 기록 (mock)
 * - api/quizApi.ts 의 fetchCourseQuizData 가 지금은 이 값을 돌려줘요.
 * TODO(백엔드): API 가 준비되면 이 파일은 지워도 돼요.
 */

import type { Quiz, QuizAttempt } from '../types/quiz'

export const MOCK_QUIZZES: Quiz[] = [
  {
    id: 101,
    courseId: 1,
    title: '퀴즈 1 · 좌표계와 변환',
    week: 2,
    questions: [
      {
        id: 'q101-1',
        concept: '변환 행렬',
        text: '2D 회전 행렬에서 cosθ가 들어가는 위치로 옳은 것은?',
        choices: ['대각 성분', '비대각 성분', '이동 성분', '마지막 행'],
        answer: 0,
      },
      {
        id: 'q101-2',
        concept: '변환 행렬',
        text: '동차 좌표를 쓰는 가장 큰 이유는?',
        choices: ['색 표현', '이동을 행렬 곱으로 표현', '메모리 절약', '정밀도 향상'],
        answer: 1,
      },
      {
        id: 'q101-3',
        concept: '좌표계',
        text: '월드 좌표 → 뷰 좌표 변환을 담당하는 행렬은?',
        choices: ['모델 행렬', '뷰 행렬', '투영 행렬', '뷰포트 행렬'],
        answer: 1,
      },
      {
        id: 'q101-4',
        concept: '변환 행렬',
        text: '변환 순서를 바꾸면 결과가 달라지는 이유는?',
        choices: [
          '행렬 곱은 교환법칙이 성립하지 않아서',
          '부동소수점 오차',
          '좌표계가 달라서',
          '결과는 같다',
        ],
        answer: 0,
      },
    ],
  },
  {
    id: 102,
    courseId: 1,
    title: '퀴즈 2 · 투영과 래스터화',
    week: 4,
    questions: [
      {
        id: 'q102-1',
        concept: '투영',
        text: '원근 투영에서 멀리 있는 물체가 작게 보이는 이유는?',
        choices: ['z로 나누기 때문', '조명 감쇠', '텍스처 축소', '클리핑'],
        answer: 0,
      },
      {
        id: 'q102-2',
        concept: '투영',
        text: '직교 투영의 특징으로 옳은 것은?',
        choices: [
          '소실점이 생긴다',
          '평행선이 평행하게 유지된다',
          '시야각이 필요하다',
          '깊이가 사라진다',
        ],
        answer: 1,
      },
      {
        id: 'q102-3',
        concept: '래스터화',
        text: '삼각형 내부 판정에 주로 쓰는 방법은?',
        choices: ['레이 트레이싱', '에지 함수', '스캔 정렬', '깊이 버퍼'],
        answer: 1,
      },
      {
        id: 'q102-4',
        concept: '래스터화',
        text: 'Z-버퍼가 해결하는 문제는?',
        choices: ['앨리어싱', '가시성(가림)', '조명', '텍스처 왜곡'],
        answer: 1,
      },
      {
        id: 'q102-5',
        concept: '투영',
        text: 'NDC 좌표의 범위(OpenGL 기준)는?',
        choices: ['0 ~ 1', '-1 ~ 1', '0 ~ 화면 크기', '-∞ ~ ∞'],
        answer: 1,
      },
    ],
  },
  {
    id: 103,
    courseId: 1,
    title: '퀴즈 3 · 셰이딩',
    week: 5,
    questions: [
      {
        id: 'q103-1',
        concept: '셰이딩',
        text: '퐁 셰이딩은 무엇을 보간하나?',
        choices: ['색', '법선 벡터', '텍스처 좌표만', '깊이'],
        answer: 1,
      },
      {
        id: 'q103-2',
        concept: '조명 모델',
        text: '정반사(specular) 항에 영향을 주는 값은?',
        choices: ['광택 지수', '주변광 세기', '텍스처 크기', '뷰포트 크기'],
        answer: 0,
      },
      {
        id: 'q103-3',
        concept: '조명 모델',
        text: '난반사(diffuse)는 어떤 두 벡터의 내적으로 구하나?',
        choices: ['법선 · 빛 방향', '시선 · 반사', '법선 · 시선', '빛 · 반사'],
        answer: 0,
      },
      {
        id: 'q103-4',
        concept: '셰이딩',
        text: '구로 셰이딩에서 하이라이트가 사라지기 쉬운 이유는?',
        choices: [
          '정점에서만 조명을 계산해서',
          '법선이 없어서',
          '텍스처가 없어서',
          '깊이 테스트 때문',
        ],
        answer: 0,
      },
    ],
  },
  {
    id: 501,
    courseId: 5,
    title: '퀴즈 1 · 게임 루프',
    week: 3,
    questions: [
      {
        id: 'q501-1',
        concept: '게임 루프',
        text: '고정 시간 간격(fixed timestep)을 쓰는 이유는?',
        choices: ['물리 계산 안정성', '그래픽 품질', '메모리 절약', '입력 지연 증가'],
        answer: 0,
      },
      {
        id: 'q501-2',
        concept: '게임 루프',
        text: 'deltaTime 을 곱하는 이유는?',
        choices: ['프레임과 무관한 이동 속도', '렌더링 품질', '충돌 정확도', '사운드 동기화'],
        answer: 0,
      },
      {
        id: 'q501-3',
        concept: '컴포넌트',
        text: '컴포넌트 기반 설계의 장점은?',
        choices: ['상속 계층 단순화', '실행 속도 무조건 향상', '메모리 0', '네트워크 불필요'],
        answer: 0,
      },
    ],
  },
]

// 문항별 난이도(맞힐 확률 기준값) — 일부 개념이 취약하게 보이도록 설정한 임시 값
const DIFFICULTY: Record<string, number> = {
  'q101-1': 0.85,
  'q101-2': 0.5,
  'q101-3': 0.8,
  'q101-4': 0.6,
  'q102-1': 0.7,
  'q102-2': 0.75,
  'q102-3': 0.35,
  'q102-4': 0.8,
  'q102-5': 0.45,
  'q103-1': 0.4,
  'q103-2': 0.7,
  'q103-3': 0.85,
  'q103-4': 0.5,
  'q501-1': 0.55,
  'q501-2': 0.8,
  'q501-3': 0.7,
}

// 매번 같은 결과가 나오는 간단한 의사난수
function rand(seed: number) {
  let t = (seed + 0x6d2b79f5) | 0
  t = Math.imul(t ^ (t >>> 15), t | 1)
  t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
  return ((t ^ (t >>> 14)) >>> 0) / 4294967296
}

export function mockAttempts(quizzes: Quiz[], studentIds: number[]): QuizAttempt[] {
  const out: QuizAttempt[] = []
  quizzes.forEach((quiz) => {
    studentIds.forEach((sid) => {
      // 약 15% 는 미응시
      if (rand(quiz.id * 7919 + sid * 13) < 0.15) return
      const ability = (rand(sid * 104729) - 0.5) * 0.3 // 학생별 실력 차이
      const choices = quiz.questions.map((q, i) => {
        const r = rand(quiz.id * 1000 + sid * 31 + i)
        if (r < (DIFFICULTY[q.id] ?? 0.7) + ability) return q.answer
        // 오답: 많은 학생이 같은 오답(첫 번째 오답 보기)을 고르도록
        const wrongs = q.choices.map((_, k) => k).filter((k) => k !== q.answer)
        return rand(sid * 7 + i * 3 + quiz.id) < 0.65
          ? wrongs[0]
          : wrongs[(sid + i) % wrongs.length]
      })
      out.push({
        quizId: quiz.id,
        studentId: sid,
        choices,
        submittedAt: '2026.09.2' + ((sid + quiz.id) % 9),
      })
    })
  })
  return out
}
