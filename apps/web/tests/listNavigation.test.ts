import assert from "node:assert/strict";
import test from "node:test";
import { listPage, matchesSearch } from "../src/listNavigation.ts";

test("all items remain reachable and a narrower result cannot leave a blank stale page", () => {
  const items = Array.from({length: 63}, (_,id) => ({id}));
  const seen = Array.from({length: 8}, (_,page) => listPage(items,page,8).items).flat();
  assert.deepEqual(seen,items);
  assert.equal(new Set(seen.map(item => item.id)).size,63);
  assert.deepEqual(listPage(items.slice(0,2),7,8).items,items.slice(0,2));
  assert.deepEqual(listPage([],7,8),{page:0,pages:1,items:[]});
});

test("course search combines subject and teacher and handles whitespace and case", () => {
  assert.equal(matchesSearch("  자료구조   KIM ","자료구조와 알고리즘","Prof. Kim"),true);
  assert.equal(matchesSearch("자료구조 Lee","자료구조와 알고리즘","Prof. Kim"),false);
  assert.equal(matchesSearch("",undefined,"분반"),true);
});
