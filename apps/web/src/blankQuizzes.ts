// 빈칸 채우기 실습 문제 (예시 세트) — 교수자 문제 연결 전까지 쓰는 기본 문제.
// 틀 문법은 visualizer/blanks.ts 참고: `[[빈칸]]` 하나가 빈칸 하나다. 정답은 화면에 싣지 않는다.
export type BlankQuiz = {
  id: string; title: string; description: string;
  /** 문제 유형 — blank: 빈칸 채우기(기본), full: 처음부터 직접 작성 (출력 비교로 채점) */
  kind?: "blank" | "full";
  /** blank: 빈칸이 있는 코드 틀 · full: 처음에 놓아 주는 시작 코드 */
  template: string;
  /** 빈칸을 바르게 채웠을 때의 출력 — 채점은 이 출력과 비교한다 (빈칸 글자를 비교하지 않는다) */
  expected: string;
  example_input?: string;
  requirements?: string[];
  available_helpers?: string[];
  hint_steps?: number;
  /** 로컬 예제용 답지. 실제 수업에서는 최종 제출 후 서버에서 별도로 받아요 */
  answers?: string[];
  /** full 문제의 단계별 힌트 (1단계 → 2단계 …) — 개수는 문제마다 달라요. 없으면 기본 힌트 3개를 써요. */
  hints?: string[];
};
export type QuizLanguage = "Python" | "Java" | "C";

export const BLANK_QUIZZES: Record<QuizLanguage, BlankQuiz[]> = {
  Python: [
    {
      id: "py-bubble",
      answers: ["n - 1 - i", "nums[j], nums[j + 1] = nums[j + 1], nums[j]"],
      expected: "[1, 2, 4, 5]",
      title: "버블 정렬 완성하기",
      description: "이웃한 두 수를 비교해 큰 수를 뒤로 보내는 버블 정렬이에요. 안쪽 반복의 범위와, 순서가 틀렸을 때 두 칸을 바꾸는 코드를 채워 보세요.",
      template: [
        "nums = [5, 2, 4, 1]",
        "n = len(nums)",
        "for i in range(n - 1):",
        "    for j in range([[빈칸]]):",
        "        if nums[j] > nums[j + 1]:",
        "            [[빈칸]]",
        "print(nums)",
      ].join("\n"),
    },
    {
      id: "py-average",
      answers: ["0", "total + s"],
      expected: "83.25",
      title: "점수 평균 구하기",
      description: "점수를 모두 더한 뒤 개수로 나눠 평균을 구해요. 합계를 처음에 얼마로 두어야 할지, 반복마다 합계가 어떻게 바뀌어야 할지 채워 보세요.",
      template: [
        "scores = [80, 95, 70, 88]",
        "total = [[빈칸]]",
        "for s in scores:",
        "    total = [[빈칸]]",
        "average = total / len(scores)",
        "print(average)",
      ].join("\n"),
    },
    {
      id: "py-max",
      kind: "full",
      /** 단계별 힌트 — 1단계부터 하나씩 열려요 (개수는 문제마다 달라요) */
      hints: [
        "가장 큰 수를 기억해 둘 변수 하나를 먼저 만들어요. 처음 값은 리스트의 첫 번째 수(nums[0])로 두면 안전해요.",
        "for 문으로 nums의 수를 하나씩 꺼내 보세요. 꺼낸 수를 n처럼 이름 붙여 두면 다음 단계가 쉬워요.",
        "꺼낸 수가 지금까지 기억한 수보다 크면(if) 기억한 값을 그 수로 바꿔요.",
        "반복이 끝난 뒤(들여쓰기 밖에서) 기억한 값을 print로 출력해요.",
      ],
      expected: "9",
      answers: ["nums = [3, 9, 2, 7]\n# 여기에 가장 큰 수를 찾는 코드를 쓰세요\nbiggest = nums[0]\nfor n in nums:\n    if n > biggest:\n        biggest = n\nprint(biggest)"],
      title: "가장 큰 수 찾기",
      description: "nums에서 가장 큰 수를 찾아 출력하는 코드를 처음부터 직접 써 보세요. max() 함수는 쓰지 않아요.",
      template: [
        "nums = [3, 9, 2, 7]",
        "# 여기에 가장 큰 수를 찾는 코드를 쓰세요",
        "",
      ].join("\n"),
    },
    {
      id: "py-even-sum",
      kind: "full",
      /** 단계별 힌트 — 1단계부터 하나씩 열려요 (개수는 문제마다 달라요) */
      hints: [
        "합을 모을 변수를 0으로 먼저 만들어요.",
        "range(1, n + 1)로 1부터 n까지 돌아요. 끝 값에 + 1을 붙여야 n까지 들어가요.",
        "i % 2 == 0이면 짝수예요. 짝수일 때만 합 변수에 더하고, 반복이 끝나면 출력해요.",
      ],
      expected: "30",
      answers: ["n = 10\n# 여기에 1부터 n까지 짝수의 합을 구하는 코드를 쓰세요\ntotal = 0\nfor i in range(1, n + 1):\n    if i % 2 == 0:\n        total += i\nprint(total)"],
      title: "짝수의 합 구하기",
      description: "1부터 n까지의 수 중 짝수만 모두 더해 출력하는 코드를 직접 써 보세요.",
      template: [
        "n = 10",
        "# 여기에 1부터 n까지 짝수의 합을 구하는 코드를 쓰세요",
        "",
      ].join("\n"),
    },
  ],
  Java: [
    {
      id: "java-bubble",
      answers: ["nums.length - 1 - i", "nums[j + 1] = t;"],
      expected: "[1, 2, 4, 5]",
      title: "버블 정렬 완성하기",
      description: "이웃한 두 수를 비교해 큰 수를 뒤로 보내요. 안쪽 반복의 끝과, 두 칸을 바꾸는 마지막 한 줄을 채워 보세요.",
      template: [
        "public class Main {",
        "    public static void main(String[] args) {",
        "        int[] nums = {5, 2, 4, 1};",
        "        for (int i = 0; i < nums.length - 1; i++) {",
        "            for (int j = 0; j < [[빈칸]]; j++) {",
        "                if (nums[j] > nums[j + 1]) {",
        "                    int t = nums[j];",
        "                    nums[j] = nums[j + 1];",
        "                    [[빈칸]]",
        "                }",
        "            }",
        "        }",
        "        System.out.println(java.util.Arrays.toString(nums));",
        "    }",
        "}",
      ].join("\n"),
    },
    {
      id: "java-average",
      answers: ["0", "total + s"],
      expected: "83.25",
      title: "점수 평균 구하기",
      description: "점수를 모두 더한 뒤 개수로 나눠 평균을 구해요. 합계의 시작값과 반복마다 더하는 코드를 채워 보세요.",
      template: [
        "public class Main {",
        "    public static void main(String[] args) {",
        "        int[] scores = {80, 95, 70, 88};",
        "        int total = [[빈칸]];",
        "        for (int s : scores) {",
        "            total = [[빈칸]];",
        "        }",
        "        System.out.println((double) total / scores.length);",
        "    }",
        "}",
      ].join("\n"),
    },
    {
      id: "java-max",
      kind: "full",
      /** 단계별 힌트 — 1단계부터 하나씩 열려요 (개수는 문제마다 달라요) */
      hints: [
        "main 안에서 가장 큰 수를 기억할 int 변수를 만들고 nums[0]으로 시작해요.",
        "for (int n : nums) 형태로 배열의 수를 하나씩 꺼내 보세요.",
        "꺼낸 수가 기억한 수보다 크면(if) 기억한 값을 바꿔요. 중괄호 { } 짝을 꼭 맞춰요.",
        "반복이 끝난 뒤 System.out.println으로 기억한 값을 출력해요.",
      ],
      expected: "9",
      answers: ["public class Main {\n    public static void main(String[] args) {\n        int[] nums = {3, 9, 2, 7};\n        // 여기에 가장 큰 수를 찾는 코드를 쓰세요\n        int biggest = nums[0];\n        for (int n : nums) {\n            if (n > biggest) biggest = n;\n        }\n        System.out.println(biggest);\n    }\n}"],
      title: "가장 큰 수 찾기",
      description: "nums에서 가장 큰 수를 찾아 출력하는 코드를 직접 써 보세요.",
      template: [
        "public class Main {",
        "    public static void main(String[] args) {",
        "        int[] nums = {3, 9, 2, 7};",
        "        // 여기에 가장 큰 수를 찾는 코드를 쓰세요",
        "",
        "    }",
        "}",
      ].join("\n"),
    },
    {
      id: "java-even-sum",
      kind: "full",
      /** 단계별 힌트 — 1단계부터 하나씩 열려요 (개수는 문제마다 달라요) */
      hints: [
        "합을 모을 int 변수를 0으로 먼저 만들어요.",
        "for (int i = 1; i <= n; i++)로 1부터 n까지 돌아요. <= 를 써야 n까지 들어가요.",
        "i % 2 == 0이면 짝수예요. 짝수일 때만 더하고, 반복이 끝나면 System.out.println으로 출력해요.",
      ],
      expected: "30",
      answers: ["public class Main {\n    public static void main(String[] args) {\n        int n = 10;\n        // 여기에 1부터 n까지 짝수의 합을 구하는 코드를 쓰세요\n        int total = 0;\n        for (int i = 1; i <= n; i++) {\n            if (i % 2 == 0) total += i;\n        }\n        System.out.println(total);\n    }\n}"],
      title: "짝수의 합 구하기",
      description: "1부터 n까지의 수 중 짝수만 모두 더해 출력하는 코드를 직접 써 보세요.",
      template: [
        "public class Main {",
        "    public static void main(String[] args) {",
        "        int n = 10;",
        "        // 여기에 1부터 n까지 짝수의 합을 구하는 코드를 쓰세요",
        "",
        "    }",
        "}",
      ].join("\n"),
    },
  ],
  C: [
    {
      id: "c-bubble",
      answers: ["3 - i", "nums[j + 1] = t;"],
      expected: "1 2 4 5",
      title: "버블 정렬 완성하기",
      description: "이웃한 두 수를 비교해 큰 수를 뒤로 보내요. 안쪽 반복의 끝과, 두 칸을 바꾸는 마지막 한 줄을 채워 보세요.",
      template: [
        "#include <stdio.h>",
        "",
        "int main(void) {",
        "    int nums[4] = {5, 2, 4, 1};",
        "    for (int i = 0; i < 3; i++) {",
        "        for (int j = 0; j < [[빈칸]]; j++) {",
        "            if (nums[j] > nums[j + 1]) {",
        "                int t = nums[j];",
        "                nums[j] = nums[j + 1];",
        "                [[빈칸]]",
        "            }",
        "        }",
        "    }",
        "    printf(\"%d %d %d %d\\n\", nums[0], nums[1], nums[2], nums[3]);",
        "    return 0;",
        "}",
      ].join("\n"),
    },
    {
      id: "c-average",
      answers: ["0", "total + scores[i]"],
      expected: "83.25",
      title: "점수 평균 구하기",
      description: "점수를 모두 더한 뒤 개수로 나눠 평균을 구해요. 합계의 시작값과 반복마다 더하는 코드를 채워 보세요.",
      template: [
        "#include <stdio.h>",
        "",
        "int main(void) {",
        "    int scores[4] = {80, 95, 70, 88};",
        "    int total = [[빈칸]];",
        "    for (int i = 0; i < 4; i++) {",
        "        total = [[빈칸]];",
        "    }",
        "    printf(\"%.2f\\n\", total / 4.0);",
        "    return 0;",
        "}",
      ].join("\n"),
    },
    {
      id: "c-max",
      kind: "full",
      /** 단계별 힌트 — 1단계부터 하나씩 열려요 (개수는 문제마다 달라요) */
      hints: [
        "main 안에서 가장 큰 수를 기억할 int 변수를 만들고 nums[0]으로 시작해요.",
        "for (int i = 1; i < 4; i++)로 배열의 나머지 칸을 하나씩 살펴봐요.",
        "nums[i]가 기억한 수보다 크면(if) 기억한 값을 바꿔요. 줄 끝 세미콜론(;)을 잊지 마세요.",
        "반복이 끝난 뒤 printf(\"%d\\n\", ...)로 기억한 값을 출력해요.",
      ],
      expected: "9",
      answers: ["#include <stdio.h>\n\nint main(void) {\n    int nums[4] = {3, 9, 2, 7};\n    /* 여기에 가장 큰 수를 찾는 코드를 쓰세요 */\n    int biggest = nums[0];\n    for (int i = 1; i < 4; i++) {\n        if (nums[i] > biggest) biggest = nums[i];\n    }\n    printf(\"%d\\n\", biggest);\n    return 0;\n}"],
      title: "가장 큰 수 찾기",
      description: "nums에서 가장 큰 수를 찾아 출력하는 코드를 직접 써 보세요.",
      template: [
        "#include <stdio.h>",
        "",
        "int main(void) {",
        "    int nums[4] = {3, 9, 2, 7};",
        "    /* 여기에 가장 큰 수를 찾는 코드를 쓰세요 */",
        "",
        "    return 0;",
        "}",
      ].join("\n"),
    },
    {
      id: "c-even-sum",
      kind: "full",
      /** 단계별 힌트 — 1단계부터 하나씩 열려요 (개수는 문제마다 달라요) */
      hints: [
        "합을 모을 int 변수를 0으로 먼저 만들어요.",
        "for (int i = 1; i <= n; i++)로 1부터 n까지 돌아요. <= 를 써야 n까지 들어가요.",
        "i % 2 == 0이면 짝수예요. 짝수일 때만 더하고, 반복이 끝나면 printf로 출력해요.",
      ],
      expected: "30",
      answers: ["#include <stdio.h>\n\nint main(void) {\n    int n = 10;\n    /* 여기에 1부터 n까지 짝수의 합을 구하는 코드를 쓰세요 */\n    int total = 0;\n    for (int i = 1; i <= n; i++) {\n        if (i % 2 == 0) total += i;\n    }\n    printf(\"%d\\n\", total);\n    return 0;\n}"],
      title: "짝수의 합 구하기",
      description: "1부터 n까지의 수 중 짝수만 모두 더해 출력하는 코드를 직접 써 보세요.",
      template: [
        "#include <stdio.h>",
        "",
        "int main(void) {",
        "    int n = 10;",
        "    /* 여기에 1부터 n까지 짝수의 합을 구하는 코드를 쓰세요 */",
        "",
        "    return 0;",
        "}",
      ].join("\n"),
    },
  ],
};

/** 하루에 푸는 실습 문제 수 */
export const DAILY_PRACTICE_COUNT = 2;

/** 한국 시간 기준 날짜 번호 — 날마다 1씩 늘어난다 */
const kstDay = (now = Date.now()) => Math.floor((now + 9 * 3600_000) / 86_400_000);

/** 오늘의 실습 문제 — 빈칸 문제 하나와 직접 작성 문제 하나를 날마다 한 칸씩 돌려 가며 고른다 (같은 날엔 늘 같은 문제) */
export function todaysQuizzes(language: QuizLanguage, day = kstDay()): BlankQuiz[] {
  const all = BLANK_QUIZZES[language];
  const pick = (list: BlankQuiz[]) => list.length ? [list[((day % list.length) + list.length) % list.length]] : [];
  const mixed = [...pick(all.filter(q => q.kind !== "full")), ...pick(all.filter(q => q.kind === "full"))];
  if (mixed.length >= DAILY_PRACTICE_COUNT) return mixed.slice(0, DAILY_PRACTICE_COUNT);
  const start = ((day % all.length) + all.length) % all.length;
  return all.length <= DAILY_PRACTICE_COUNT ? all : Array.from({ length: DAILY_PRACTICE_COUNT }, (_, k) => all[(start + k) % all.length]);
}
