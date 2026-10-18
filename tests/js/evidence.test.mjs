import test from "node:test";
import assert from "node:assert/strict";
import { receiptFor, checks, checkSummary, preferredCheck, recordKey, readerKey, replayCandidates,
  savedDataStatus, transcriptLabel, PASS_SCOPE, retainedData, workspaceTitle, sourceLabel } from "../../src/rw/static/model.mjs";
import { formatText, flagText } from "../../src/rw/static/explanations.mjs";

const obligation = { obligation_hash: "check-1", tuple: {
  plan_hash: "plan-1", service: "cart", release_id: "cart-1.4", deployment_id: "cart", route_id: "read-cart",
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

test("saved-data tile never shows a pass over evidence gaps, but failures still dominate", () => {
  const verification = { disposition: "BOUNDED_PASS", obligations: [obligation], receipts: [receipt("PASS")], gaps: [] };
  assert.equal(savedDataStatus(verification, "cart"), "PASS");
  for (const kind of ["COVERAGE_INCOMPLETE", "WRITER_UNKNOWN", "FORMAT_UNKNOWN"]) {
    const incomplete = { ...verification, disposition: "NEEDS_EVIDENCE", gaps: [{ kind }] };
    assert.equal(savedDataStatus(incomplete, "cart"), "UNKNOWN");
    assert.equal(savedDataStatus({ ...incomplete, receipts: [receipt("FAIL")] }, "cart"), "FAIL");
  }
  assert.equal(savedDataStatus({ ...verification, disposition: "NEEDS_EVIDENCE" }, "cart"), "UNKNOWN");
  assert.equal(savedDataStatus({ ...verification, gaps: [{ kind: "OTHER_GAP" }] }, "cart"), "UNKNOWN");
  assert.equal(savedDataStatus({ ...verification, receipts: [] }, "cart"), "UNKNOWN");
  assert.equal(savedDataStatus(verification, "absent-service"), "UNKNOWN");
});

test("recording labels include model, origin and ID without pretending unknown metadata is live", () => {
  const recording = { outcome: "proposal", model: "provider:model-a", live: true, file_name: "a.json", mtime: "2026-10-17T10:00:00Z" };
  const label = transcriptLabel(recording);
  assert(label.startsWith("Version proposal · provider:model-a · Recorded live model"));
  assert(label.includes("a.json"));
  assert(!label.includes("Invalid Date"));
  assert(transcriptLabel({ ...recording, live: false }).includes("Recorded non-live response"));
  assert(transcriptLabel({ outcome: "question", replay_path: "q.json" }).includes("Unknown model · Unknown origin · Unknown recording time · q.json"));
  assert(transcriptLabel({ ...recording, answer: "Keep Checkout", mtime: "invalid" }).startsWith("Answer: Keep Checkout"));
  assert(transcriptLabel({ ...recording, mtime: "invalid" }).includes("Unknown recording time"));
  assert(PASS_SCOPE.includes("readable (bytes and shape) only"));
});

test("retained-data summary and titles use arbitrary snapshot/store/format identities", () => {
  const context = { snapshot: "warehouse-27", environment: "warehouse-test", stores: [
    { name: "fulfillment-events", coverage: "COMPLETE", records: [
      { record_id: "order-71", format: "event/v7", writer: { service: "ingester", version: "9.2" } },
    ] },
  ] };
  const summary = retainedData(context);
  assert.equal(summary.title, "Retained data · fulfillment-events");
  assert.equal(summary.records[0].store, "fulfillment-events");
  assert.deepEqual(summary.formats, ["event/v7"]);
  assert.equal(summary.coverage, "COMPLETE");
  assert.equal(summary.unknownFormats, 0);
  assert.equal(summary.storeCount, 1);
  assert.equal(workspaceTitle(context), "Rollback review · warehouse-27");
  assert.equal(workspaceTitle(context, { report: { verification: { disposition: "NEEDS_EVIDENCE" } } }),
    "Rollback review · warehouse-27 · Can't confirm: data missing");
  assert.equal(sourceLabel(context), "warehouse-test");
  assert.equal(sourceLabel({ ...context, data_origin: "synthetic_fixture" }), "Synthetic fixture");
  assert.equal(formatText("event/v7"), "event/v7");
  assert.equal(formatText("cart/v2"), "cart/v2", "existing format IDs do not receive invented aliases either");
  assert.equal(flagText("ingester", "compact_events", false), "compact_events: Off");
  assert.equal(flagText("cart", "basket_v2", true), "basket_v2: On");
  assert.equal(flagText("ingester", "compact_events", null), "compact_events: Unknown");
});

test("retained summary preserves unknown facts, store identity and partial inventories", () => {
  const summary = retainedData({ stores: [
    { name: "first", coverage: "COMPLETE", records: [{ record_id: "same", format: "event/v7" }] },
    { name: "second", coverage: "PARTIAL", records: [{ record_id: "same", format: null }, { format: "UNKNOWN" }] },
  ] });
  assert.equal(summary.title, "Retained data · 2 stores");
  assert.equal(summary.coverage, "PARTIAL");
  assert.equal(summary.records.length, 3);
  assert.equal(summary.records[0].store, "first");
  assert.equal(summary.records[1].store, "second");
  assert.equal(summary.unknownFormats, 2);
  assert.equal(retainedData({ stores: [] }).coverage, "UNKNOWN");
  assert.equal(retainedData(null).title, "Retained data");
  assert.equal(formatText(null), "Unknown format");
  assert.equal(sourceLabel(null), "Data source unavailable");
});
