import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { buildFilm } from "../src/visualizer/buildFilm.ts";
import { judgedExpr, normalizeStmt, parseLoops, stripNoise } from "../src/visualizer/film/sourceRules.ts";

const fixture = (name: string) => JSON.parse(readFileSync(new URL(`./fixtures/${name}.trace.json`, import.meta.url), "utf8"));
const verbs = (film: ReturnType<typeof buildFilm>) => new Set(film.shots.flatMap(s => s.motions.map(m => m.v)));

test("Java·C 소스 줄에서 판단식과 대입을 읽는다", () => {
  assert.equal(judgedExpr("        if (arr[j] > arr[j + 1]) {", "java"), "arr[j] > arr[j + 1]");
  assert.equal(judgedExpr("} else if (n == 0) {", "c"), "n == 0");
  assert.equal(normalizeStmt("int t = arr[j];", "java"), "t = arr[j]");
  assert.equal(stripNoise('printf("// not comment"); // real', "c").includes("real"), false);
  assert.equal(stripNoise("x = a // 2", "python"), "x = a // 2");
});

test("중괄호 반복문의 몸통 범위를 찾고 한 줄 반복문은 건너뛴다", () => {
  const src = ["for (int i = 0; i < n; i++) {", "  total += i;", "}", "while (k > 0) k--;"];
  assert.deepEqual(parseLoops(src, "c"), [{ header: 1, end: 3, name: "i" }]);
});

test("Java 버블 정렬 기록은 비교·교환 장면이 있는 필름이 된다", () => {
  const { code, events } = fixture("java-bubble");
  const film = buildFilm(events, code, "java");
  assert.ok(film.shots.length > 0);
  assert.equal(film.chapterOf.length, film.shots.length);
  assert.ok(verbs(film).has("compare"));
});

test("C 연결 리스트 기록의 NULL 역참조는 오류 장면으로 끝난다", () => {
  const { code, events, error } = fixture("c-list");
  const film = buildFilm(events, code, "c", error ?? undefined);
  assert.ok(film.shots.length > 0);
  assert.ok(verbs(film).has("crashEnd"));
  assert.match(film.shots.at(-1)?.caption ?? "", /SIGSEGV/);
});

test("3D 무대: 샷마다 변수·배열 칸을 실제 값으로 읽고 인덱스 변수는 자기 배열을 가리킨다", async () => {
  const { buildWorld } = await import("../src/visualizer/stage3d/world.ts");
  const { code, events } = fixture("java-bubble");
  const film = buildFilm(events, code, "java");
  const world = buildWorld(film);
  assert.equal(world.beats.length, film.shots.length);
  assert.ok(Math.abs(world.total - film.shots.reduce((a, s) => a + s.durationMs / 1000, 0)) < 1e-9);
  const cmp = world.beats.find(b => b.shot.motions.some(m => m.v === "compare") && b.after.rows.length > 0);
  assert.ok(cmp, "배열을 비교하는 장면이 있어야 해요");
  const row = cmp.after.rows[0];
  assert.ok(row.cells.every(c => c.num !== null));
  assert.ok(cmp.after.vars.some(p => p.pointer === row.objectId));
  assert.ok(world.maxAbs.get(row.objectId)! > 0);
});
