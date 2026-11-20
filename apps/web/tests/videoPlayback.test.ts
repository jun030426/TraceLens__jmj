import assert from "node:assert/strict";
import test from "node:test";
import { videoPlayback } from "../src/videoPlayback.ts";

Object.defineProperty(globalThis, "location", { value: { href: "https://lerny.example/lecture" }, configurable: true });
class Media extends EventTarget {
  src = "/api/v1/concept-videos/sample/file";
  currentTime = 0; duration = 54; paused = true; ended = false;
  error: MediaError | null = null;
  loads = 0; plays = 0;
  fire(name: string) { this.dispatchEvent(new Event(name)); }
  load() { this.loads++; this.error = null; this.paused = true; this.currentTime = 0; this.fire("timeupdate"); this.fire("pause"); }
  async play() { this.plays++; this.paused = false; this.fire("play"); }
  fail(code = 2) { this.error = { code } as MediaError; this.fire("error"); }
}
const setup = () => {
  const media = new Media(); let message = "";
  const control = videoPlayback(media, media.src, value => { message = value; });
  return { media, control, message: () => message };
};

test("expired network request refreshes authenticated endpoint and resumes at saved position", async () => {
  const { media, control, message } = setup();
  await media.play(); media.currentTime = 23; media.fire("timeupdate");
  media.fail();
  assert.equal(media.loads, 1);
  assert.equal(new URL(media.src).origin, "https://lerny.example");
  assert.equal(new URL(media.src).pathname, "/api/v1/concept-videos/sample/file");
  assert.ok(new URL(media.src).searchParams.get("playback_retry"));
  media.fire("loadedmetadata");
  assert.equal(media.currentTime, 23); assert.equal(media.plays, 2);
  media.fire("playing"); assert.equal(message(), ""); control.dispose();
});

test("persistent failure stops retrying; explicit retry keeps position and uses a fresh request", async () => {
  const { media, control, message } = setup();
  await media.play(); media.currentTime = 31; media.fire("timeupdate");
  media.fail(4); const first = media.src;
  media.fail(4); media.fail(4);
  assert.equal(media.loads, 1); assert.ok(message());
  control.retry(); assert.equal(media.loads, 2); assert.notEqual(media.src, first);
  media.fire("loadedmetadata"); assert.equal(media.currentTime, 31);
  media.fire("playing"); assert.equal(message(), ""); control.dispose();
});

test("a paused video stays paused after automatic recovery", async () => {
  const { media, control } = setup();
  await media.play(); media.currentTime = 17; media.fire("timeupdate");
  media.paused = true; media.fire("pause"); media.fail(); media.fire("loadedmetadata");
  assert.equal(media.currentTime, 17); assert.equal(media.plays, 1); control.dispose();
});

test("list refresh leaves healthy playback alone and retries a failed player", async () => {
  const { media, control } = setup();
  await media.play(); control.retryIfFailed(); assert.equal(media.loads, 0);
  media.fail(3); assert.equal(media.loads, 0);
  control.retryIfFailed(); assert.equal(media.loads, 1); control.dispose();
});

test("successful native playback clears the previous error", () => {
  const { media, control, message } = setup();
  media.fail(3); assert.ok(message()); media.error = null; media.fire("playing");
  assert.equal(message(), ""); control.dispose();
});

test("unmounted player cannot reload or report errors", () => {
  const { media, control, message } = setup(); control.dispose();
  media.fail(); control.retry(); control.retryIfFailed();
  assert.equal(media.loads, 0); assert.equal(message(), "");
});
