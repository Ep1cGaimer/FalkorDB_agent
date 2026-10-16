// Node test for the pure replay matcher extracted from src/rw/static/index.html.
// Run directly with `node --test tests/js/replay_matcher.test.mjs`, or through
// tests/test_ui_matcher.py which skips when node is missing.
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import test from "node:test";
import assert from "node:assert/strict";

const here = dirname(fileURLToPath(import.meta.url));
const html = readFileSync(join(here, "..", "..", "src", "rw", "static", "index.html"), "utf8");

const START = "/* --- replay matcher";
const END = "/* --- end replay matcher --- */";
const start = html.indexOf(START);
const end = html.indexOf(END);
assert.ok(start >= 0 && end > start, "index.html contains the replay matcher markers");

const { withAnswer, replayMatches } =
  new Function(`${html.slice(start, end)}\nreturn { withAnswer, replayMatches };`)();

test("withAnswer mirrors pipeline.with_answer", () => {
  assert.equal(withAnswer("R", "Q", "A"), "R\n\nAgent asked: Q\nOperator answered: A");
});

test("only the transcript bound to the exact answer matches", () => {
  const transcripts = [
    { replay_path: "a.json", request_text: "R\n\nAgent asked: Q\nOperator answered: A" },
    { replay_path: "b.json", request_text: "R\n\nAgent asked: Q\nOperator answered: B" },
    { replay_path: "c.json", request_text: "R" },
  ];
  assert.deepEqual(replayMatches(transcripts, "R", "Q", "A").map(t => t.replay_path), ["a.json"]);
  // surrounding whitespace in the typed answer is trimmed, exactly like sendAnswer
  assert.deepEqual(replayMatches(transcripts, "R", "Q", "  A  ").map(t => t.replay_path), ["a.json"]);
  // a partial answer matches nothing (the picker must not offer an unrelated run)
  assert.deepEqual(replayMatches(transcripts, "R", "Q", "").map(t => t.replay_path), []);
  assert.deepEqual(replayMatches(transcripts, "R", "Q", "B").map(t => t.replay_path), ["b.json"]);
});
