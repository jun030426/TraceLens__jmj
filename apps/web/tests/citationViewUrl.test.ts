import { test } from "node:test";
import assert from "node:assert/strict";
import { citationViewUrl } from "../src/sourceLabels.ts";
import type { Citation, Material } from "../src/api.ts";

const handout: Material = {
  id: "deck", title: "자료구조", kind: "lecture", week: 1, visibility: "public",
  revision: 1, internal_use: "none", view_url: "/materials/deck/view",
  version: { id: "v1", status: "ready", filename: "강의.pptx", error_code: null },
};
const cite: Citation = { material_id: "deck", version_id: "v1", locator: { slide: 4 }, title: "자료구조", excerpt: "" };

test("PPT 슬라이드와 PDF 쪽 번호는 학생용 열람 주소에 그대로 전달한다", () => {
  assert.equal(citationViewUrl(cite, [handout]), "/materials/deck/view?version_id=v1&page=4");
  assert.equal(citationViewUrl({ ...cite, locator: { page: 7 } }, [handout]), "/materials/deck/view?version_id=v1&page=7");
});

test("페이지가 없는 출처는 문단 번호를 페이지로 사용하지 않는다", () => {
  for (const locator of [{ paragraph: 3 }, { table: 6 }, { slide: 0 }, { page: -1 }, {}]) {
    assert.equal(citationViewUrl({ ...cite, locator }, [handout]), "/materials/deck/view?version_id=v1");
  }
});

test("학생 열람 목록에 없거나 교체된 버전의 출처는 링크로 만들지 않는다", () => {
  assert.equal(citationViewUrl(cite, []), null);
  assert.equal(citationViewUrl({ ...cite, version_id: "old" }, [handout]), null);
  assert.equal(citationViewUrl(cite, [{ ...handout, view_url: undefined }]), null);
});
