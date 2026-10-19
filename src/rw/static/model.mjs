export const PASS_SCOPE = "Safe for saved data means every checked record was readable (bytes and shape) only for the modeled records checked here. This does not establish behavioral compatibility, production safety or application-level correctness.";

export function retainedData(context) {
  const stores = context?.stores || [];
  const records = stores.flatMap(store => (store.records || []).map(record => ({ ...record, store: store.name || null })));
  const formats = [...new Set(records.map(r => r.format).filter(f => f && f !== "UNKNOWN"))].sort();
  const coverage = stores.length && stores.every(s => s.coverage === "COMPLETE") ? "COMPLETE"
    : stores.some(s => s.coverage === "PARTIAL") ? "PARTIAL" : "UNKNOWN";
  return { records, formats, coverage, storeCount: stores.length,
    unknownFormats: records.filter(r => !r.format || r.format === "UNKNOWN").length,
    title: stores.length === 1 && stores[0].name ? `Retained data · ${stores[0].name}`
      : stores.length ? `Retained data · ${stores.length} stores` : "Retained data" };
}
export const workspaceTitle = (context, attempt) => ["Rollback review", context?.snapshot,
  attempt?.report?.verification?.disposition ? displayStatus(attempt.report.verification.disposition) : null].filter(Boolean).join(" · ");
export const sourceLabel = context => context?.data_origin === "synthetic_fixture" ? "Synthetic fixture"
  : context?.environment || "Data source unavailable";

export const withAnswer = (request, question, answer) => `${request}\n\nAgent asked: ${question}\nOperator answered: ${answer}`;
export const replayMatches = (transcripts, requestText, question, answer) => {
  const bound = withAnswer(requestText, question, String(answer ?? "").trim());
  return (transcripts || []).filter(t => t.request_text === bound);
};
export function recordedAnswers(transcripts, requestText, question) {
  const prefix = withAnswer(requestText, question, "");
  return transcripts.filter(t => t.request_text.startsWith(prefix) && t.outcome === "proposal")
    .map(t => ({ ...t, answer: t.request_text.slice(prefix.length) }))
    .filter(t => t.answer && t.answer === t.answer.trim());
}
export const disposition = attempt => attempt?.report?.verification.disposition || null;
export const displayStatus = value => ({
  BLOCKED: "Unsafe: breaks saved data", NEEDS_EVIDENCE: "Can't confirm: data missing", BOUNDED_PASS: "Safe for saved data",
  PASS: "Passed", FAIL: "Failed", UNKNOWN: "Unresolved", MISSING: "No receipt",
  INAPPLICABLE: "Inapplicable", COMPLETE: "Complete", PARTIAL: "Partial",
})[value] || value || "Not checked";
export const shortHash = value => String(value || "").replace(/^sha256:/, "").slice(0, 8);
export const recordKey = obligation => `${obligation.tuple.store_id}|${obligation.tuple.batch_id}`;
export const readerKey = obligation => `${obligation.tuple.deployment_id}|${obligation.tuple.release_id}|${obligation.tuple.route_id}`;

function sameTuple(left, right) {
  if (!left || !right) return false;
  const keys = Object.keys(left);
  return keys.length === Object.keys(right).length && keys.every(key => left[key] === right[key]);
}

// Display follows the server's applicability and FAIL > PASS > UNKNOWN precedence.
// The UI never computes the plan disposition or grants eligibility.
export function receiptFor(obligation, receipts = []) {
  const candidates = receipts.filter(r => r.obligation_hash === obligation.obligation_hash);
  const bound = candidates.filter(r => sameTuple(r.tuple, obligation.tuple));
  for (const result of ["FAIL", "PASS", "UNKNOWN"]) {
    const receipt = bound.find(r => r.result === result);
    if (receipt) return { result, receipt };
  }
  return { result: candidates.length ? "INAPPLICABLE" : "MISSING", receipt: null };
}
export function checks(verification) {
  return (verification?.obligations || []).map(obligation => ({
    obligation, ...receiptFor(obligation, verification.receipts),
  }));
}
export function checkSummary(verification) {
  const rows = checks(verification);
  return { total: rows.length, passed: rows.filter(r => r.result === "PASS").length,
    failed: rows.filter(r => r.result === "FAIL").length,
    unresolved: rows.filter(r => !["PASS", "FAIL"].includes(r.result)).length,
    gaps: verification?.gaps?.length || 0 };
}
export function savedDataStatus(verification, service) {
  const rows = checks(verification).filter(r => r.obligation.tuple.service === service);
  if (rows.some(r => r.result === "FAIL")) return "FAIL";
  if (verification?.disposition === "NEEDS_EVIDENCE" || verification?.gaps?.length) return "UNKNOWN";
  return rows.length && rows.every(r => r.result === "PASS") ? "PASS" : "UNKNOWN";
}
export function transcriptLabel(t) {
  const kind = t.answer ? `Answer: ${t.answer}` : t.outcome === "question" ? "Clarification" : "Version proposal";
  const origin = t.live === true ? "Recorded live model" : t.live === false ? "Recorded non-live response" : "Unknown origin";
  const date = t.mtime ? new Date(t.mtime) : null;
  const recordedAt = date && Number.isFinite(date.getTime()) ? date.toLocaleString() : "Unknown recording time";
  return `${kind} · ${t.model || "Unknown model"} · ${origin} · ${recordedAt} · ${t.file_name || t.replay_path || "Unknown recording"}`;
}
export function preferredCheck(verification, selected) {
  const rows = checks(verification);
  return rows.find(r => r.obligation.obligation_hash === selected)
    || rows.find(r => r.result === "FAIL")
    || rows.find(r => r.result !== "PASS") || rows[0] || null;
}
export function replayCandidates(transcripts, request, used = []) {
  return transcripts.filter(t => t.request_text === request && ["proposal", "question"].includes(t.outcome)
    && !used.includes(t.replay_path));
}
export function usedReplays(inv) {
  return (inv?.attempts || []).map(a => {
    const model = a.grounding.model || "";
    return model.startsWith("replay:") ? model.slice(7) : null;
  }).filter(Boolean);
}
