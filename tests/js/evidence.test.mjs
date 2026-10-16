import test from "node:test";
import assert from "node:assert/strict";
import { receiptFor, checks, checkSummary, preferredCheck, recordKey, readerKey, replayCandidates } from "../../src/rw/static/model.mjs";

const obligation = { obligation_hash: "check-1", tuple: {
  plan_hash: "plan-1", release_id: "cart-1.4", deployment_id: "cart", route_id: "read-cart",
  store_id: "cart-cache", batch_id: "batch-1", record_id: "cart-2002", payload_hash: "bytes-1",
} };
const receipt = (result, overrides = {}) => ({ obligation_hash: "check-1", tuple: { ...obligation.tuple }, result, ...overrides });

test("a hash match with a different payload or plan cannot display a passing check", () => {
  for (const changed of [{ payload_hash: "other-bytes" }, { plan_hash: "other-plan" }, { route_id: "other-route" }]) {
    assert.equal(receiptFor(obligation, [receipt("PASS", { tuple: { ...obligation.tuple, ...changed } })]).result, "INAPPLICABLE");
  }
  assert.equal(receiptFor(obligation, []).result, "MISSING");
});

test("only applicable receipts participate in FAIL > PASS > UNKNOWN precedence", () => {
  const invalidFail = receipt("FAIL", { tuple: { ...obligation.tuple, payload_hash: "other-bytes" } });
  assert.equal(receiptFor(obligation, [receipt("UNKNOWN"), receipt("PASS"), invalidFail]).result, "PASS");
  assert.equal(receiptFor(obligation, [receipt("PASS"), receipt("FAIL")]).result, "FAIL");
  assert.equal(receiptFor(obligation, [receipt("UNKNOWN")]).result, "UNKNOWN");
});

test("matrix identities distinguish routes and stores even when display labels collide", () => {
  const route = { ...obligation, tuple: { ...obligation.tuple, route_id: "pricing-route" } };
  const record = { ...obligation, tuple: { ...obligation.tuple, store_id: "other-cache", batch_id: "batch-2" } };
  assert.notEqual(readerKey(obligation), readerKey(route));
  assert.notEqual(recordKey(obligation), recordKey(record));
});

test("summary preserves unresolved checks and does not infer a plan disposition", () => {
  const verification = { obligations: [obligation], receipts: [receipt("UNKNOWN")], gaps: [{ kind: "RECEIPT_UNKNOWN" }] };
  assert.deepEqual(checkSummary(verification), { total: 1, passed: 0, failed: 0, unresolved: 1, gaps: 1 });
  assert.equal(checks(verification)[0].result, "UNKNOWN");
  assert.equal(preferredCheck(verification, null).obligation, obligation);
  assert.equal(preferredCheck({ obligations: [], receipts: [], gaps: [] }), null);
});

test("alternative replay choices are exact-request proposals that have not been used", () => {
  const transcripts = [
    { replay_path: "used", request_text: "R", outcome: "proposal" },
    { replay_path: "next", request_text: "R", outcome: "proposal" },
    { replay_path: "question", request_text: "R", outcome: "question" },
    { replay_path: "unrelated", request_text: "other request", outcome: "proposal" },
  ];
  assert.deepEqual(replayCandidates(transcripts, "R", ["used"]).map(t => t.replay_path), ["next"]);
});
