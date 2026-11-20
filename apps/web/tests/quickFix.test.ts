// 풀코딩 실행 전 간단 문법 자동수정 — 줄 끝에 빠진 콜론·괄호·세미콜론만 붙여요
import { test } from "node:test";
import assert from "node:assert/strict";
// A valid literal/comment must never be rewritten by a line-level suggestion.
test("여러 줄 문자열·주석·명시적 이어쓰기는 원문을 보존해요", () => {
  for (const [language, code] of [
    ["Python", 's = """hello\nprint(x\n"""'],
    ["Python", "s = '''hello\nif x\n  keep me\n'''"],
    ["Python", 'value = "hello\\\nprint(x"'],
    ["C", '/* explanation\nprint(x\n*/\nint x = 1;'],
    ["Java", 'String s = """\nprint(x\n""";'],
  ] as const) assert.deepEqual(quickFix(code, language), { code, fixes: [] });
});
import { quickFix } from "../src/quickFix.ts";
import { BLANK_QUIZZES } from "../src/blankQuizzes.ts";

test("Python: 블록 줄 끝 콜론과 닫는 괄호를 붙여요", () => {
  const r = quickFix("nums = [3, 9]\nbiggest = nums[0]\nfor n in nums\n    if (n > biggest\n        biggest = n\nprint(biggest", "Python");
  assert.equal(r.code, "nums = [3, 9]\nbiggest = nums[0]\nfor n in nums:\n    if (n > biggest):\n        biggest = n\nprint(biggest)");
  assert.deepEqual(r.fixes.map(f => [f.line, f.add]), [[3, ":"], [4, "):"], [6, ")"]]);
  assert.match(r.fixes[0].message, /콜론\(:\)이/);
  assert.match(r.fixes[1].message, /닫는 괄호 \)와 콜론\(:\)이/);
});

test("Python: else·def·while도 고치고, 이미 맞는 코드는 그대로 둬요", () => {
  assert.equal(quickFix("def f(x)\n    return x\nif x:\n    pass\nelse\n    pass", "Python").code, "def f(x):\n    return x\nif x:\n    pass\nelse:\n    pass");
  for (const ok of ["if a[1:2]:\n    pass", "x = {\n    'a': 1,\n}\nprint(x)", "y = foo(\n    1,\n    2)\n", "print('if x')", "if x: print(x)", "s = 'for ('\n"]) {
    const r = quickFix(ok, "Python");
    assert.equal(r.fixes.length, 0, ok);
    assert.equal(r.code, ok);
  }
});

test("Python: 주석이 붙은 줄·들여쓴 다음 줄이 없는 블록 줄은 건드리지 않아요", () => {
  assert.equal(quickFix("if x  # 비교\n    pass", "Python").fixes.length, 0);
  assert.equal(quickFix("if x\nprint(1)", "Python").fixes.length, 0);
});

test("Java·C: 문장 끝 세미콜론과 닫는 괄호를 붙여요", () => {
  const java = "public class Main {\n    public static void main(String[] args) {\n        int total = 0\n        for (int i = 1; i <= 10; i++) {\n            total += i\n        }\n        System.out.println(total\n    }\n}";
  const r = quickFix(java, "Java");
  assert.deepEqual(r.fixes.map(f => [f.line, f.add]), [[3, ";"], [5, ";"], [7, ");"]]);
  const c = "#include <stdio.h>\n\nint main(void)\n{\n    int n = 10\n    printf(\"%d\\n\", n);\n    return 0\n}";
  assert.deepEqual(quickFix(c, "C").fixes.map(f => [f.line, f.add]), [[5, ";"], [7, ";"]]);
});

test("모든 실습 모범 답안은 고칠 게 없어요", () => {
  for (const [lang, quizzes] of Object.entries(BLANK_QUIZZES)) for (const q of quizzes) {
    if (q.kind !== "full" || !q.answers?.[0]) continue;
    const r = quickFix(q.answers[0], lang as "Python" | "Java" | "C");
    assert.deepEqual(r.fixes, [], `${q.id}`);
  }
});

test("고친 줄은 학생이 친 줄로 시작해요 (회색 따라쓰기와 맞아요)", () => {
  const src = "for n in nums\n    print(n";
  const r = quickFix(src, "Python");
  src.split("\n").forEach((line, i) => assert.ok(r.code.split("\n")[i].startsWith(line)));
});
