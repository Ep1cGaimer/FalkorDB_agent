// Test the same module imported by the browser; no source extraction or eval.
// Run directly with `node --test tests/js/replay_matcher.test.mjs`, or through
// tests/test_ui_matcher.py which skips when node is missing.
import test from "node:test";
import assert from "node:assert/strict";
import { withAnswer, replayMatches, recordedAnswers } from "../../src/rw/static/model.mjs";

test("withAnswer mirrors pipeline.with_answer", () => {
  assert.equal(withAnswer("R", "Q", "A"), "R\n\nAgent asked: Q\nOperator answered: A");
});

test("recorded answers come only from the exact current request and question", () => {
  const transcripts = [
    { replay_path: "match", request_text: withAnswer("R", "Q", "Keep Checkout"), outcome: "proposal" },
    { replay_path: "other-request", request_text: withAnswer("R2", "Q", "Wrong"), outcome: "proposal" },
    { replay_path: "other-question", request_text: withAnswer("R", "Q2", "Wrong"), outcome: "proposal" },
    { replay_path: "empty", request_text: withAnswer("R", "Q", ""), outcome: "proposal" },
    { replay_path: "question", request_text: withAnswer("R", "Q", "Wrong"), outcome: "question" },
  ];
  assert.deepEqual(recordedAnswers(transcripts, "R", "Q").map(t => [t.replay_path, t.answer]), [["match", "Keep Checkout"]]);
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
