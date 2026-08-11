export const samples = [
  {
    id: 'aliasing',
    label: '얕은 복사 함정',
    description: 'b = a 는 복사가 아니다 — 같은 객체를 가리키는 별칭',
    code: `team_a = ["kim", "lee"]
team_b = team_a
team_b.append("park")
print(team_a)
`,
  },
  {
    id: 'loop',
    label: '루프 합계',
    description: '반복문이 접히며 빨리감기되는 예제',
    code: `total = 0
for i in range(5):
    total += i
print(total)
`,
  },
  {
    id: 'recursion',
    label: '재귀 팩토리얼',
    description: '호출 스택이 쌓였다 줄어드는 예제',
    code: `def fact(n):
    if n <= 1:
        return 1
    return n * fact(n - 1)

print(fact(4))
`,
  },
  {
    id: 'crash',
    label: '예외 데모',
    description: '터지는 순간까지 재생 — 에러도 콘텐츠',
    code: `arr = [1, 2, 3]
print(arr[5])
`,
  },
] as const

export const defaultCode = samples[0].code
