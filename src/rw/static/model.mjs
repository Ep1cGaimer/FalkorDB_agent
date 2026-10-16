export const DEFAULT_REQUEST = "Roll cart back to the build it ran before the basket rollout, but keep the receipt correction.";
export const PASS_SCOPE = "Passing means the tested versions could read the saved records checked here. This does not establish production safety or verify receipt totals.";

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
  BLOCKED: "Blocked", NEEDS_EVIDENCE: "Needs evidence", BOUNDED_PASS: "Bounded pass",
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
    gaps: verification?.gaps.length || 0 };
}
export function preferredCheck(verification, selected) {
  const rows = checks(verification);
  return rows.find(r => r.obligation.obligation_hash === selected)
    || rows.find(r => r.result === "FAIL")
    || rows.find(r => r.result !== "PASS") || rows[0] || null;
}
export function replayCandidates(transcripts, request, used = []) {
  return transcripts.filter(t => t.request_text === request && t.outcome === "proposal" && !used.includes(t.replay_path));
}
export function usedReplays(inv) {
  return (inv?.attempts || []).map(a => {
    const model = a.grounding.model || "";
    return model.startsWith("replay:") ? model.slice(7) : null;
  }).filter(Boolean);
}
