import { el, icon, button, panel, details, hash } from "./dom.mjs";
import { checks, preferredCheck, recordKey, readerKey, displayStatus } from "./model.mjs";
import { buildGraph, renderGraph, clusterRecords, clusterTarget, CUT_KINDS } from "./graph.mjs";
import { formatText } from "./explanations.mjs";

export const releaseLabel = (inv, id) => inv?.release_labels?.[id] || id || "Unknown release";
export const badge = (status, label = displayStatus(status)) => el("span", { class: `badge ${status || ""}` },
  ["FAIL", "BLOCKED", "NEEDS_EVIDENCE"].includes(status) ? icon("alert") : ["PASS", "BOUNDED_PASS"].includes(status) ? icon("check") : null, label);

export function sourcesView(citations, inv) {
  if (!citations?.length) return el("p", { class: "small muted" }, "No source citations were returned for this proposal.");
  return el("div", {}, citations.map(c => el("blockquote", { class: "quote" },
    el("p", {}, `“${c.quote}”`),
    el("footer", {}, releaseLabel(inv, c.release_id), " · ", c.kind || "Source excerpt"),
    details("Source identity", el("p", { class: "small mono subtle" }, c.excerpt_id, " · ", hash(c.content_hash))))));
}

const cutKey = (s, planHash) => `${s.inv?.id}|${planHash}`;
const json = v => { try { return JSON.stringify(v); } catch { return String(v); } };

function queryItem(q, extra) {
  return el("li", { class: "query-item" }, el("div", { class: "row" }, el("strong", { class: "mono" }, q.name),
    el("span", { class: "tiny muted" }, `${q.rows} row${q.rows === 1 ? "" : "s"}`),
    q.truncated ? el("span", { class: "badge UNKNOWN" }, "truncated at cap") : null, extra),
    q.complete === false ? el("p", { class: "small error-text" }, "Lineage incomplete: ",
      q.gaps?.length ? q.gaps.map(g => `${g.batch_id}: ${g.reason}`).join("; ") : "query cap reached") : null,
    q.params && Object.keys(q.params).length ? el("p", { class: "tiny muted mono query-params" }, "params: ", json(q.params)) : null,
    q.cypher ? el("pre", { class: "code-block query-cypher" }, q.cypher) : null);
}

function ablationBox(s, actions, planHash) {
  const key = cutKey(s, planHash), results = s.ablation?.[key] || {};
  const row = (id, title) => {
    const r = results[id];
    return el("div", { class: "ablation-row" }, el("div", { class: "row" },
      button(title, () => actions.ablate(planHash, id), { variant: "secondary", disabled: r === "loading" || !!s.busy, "data-ablate": id }),
      r === "loading" ? el("span", { class: "spinner" }) : null,
      r && r !== "loading" && !r.error ? button(s.cutShown === id ? "Restore edges" : "Show cut in graph", () => actions.showCut(s.cutShown === id ? null : id),
        { variant: "link" }) : null),
      r?.error ? el("p", { class: "small error-text" }, r.error)
        : r && r !== "loading" ? el("p", { class: "small mono ablation-result" },
          `removed ${r.removed.join(", ")} (${r.edges_deleted} edges) → ${r.disposition} · ${r.obligations} obligations · ${r.failures_found} failures · ${r.witness_paths} witness paths · ${r.origins_found} origins`,
          r.gap_kinds?.length ? ` · gaps: ${r.gap_kinds.join(", ")}` : "") : null);
  };
  return el("div", { class: "drawer-section" }, el("h3", {}, "Cut the relationships"),
    el("p", { class: "tiny muted" }, "Re-run on a disposable copy of the graph; the real graph is untouched."),
    row("DERIVED_FROM", "Cut DERIVED_FROM"), row("READER_LINKS", "Cut reader/store/record links"));
}

export function queriesDrawer(s, actions, attempt, originsData) {
  const calls = attempt.grounding?.tool_calls || [], queries = attempt.report?.queries || [];
  const planHash = attempt.plan_hash;
  const node = el("details", { class: "disclosure queries-drawer", id: "queries-drawer", open: !!s.drawerOpen,
    ontoggle: e => actions.setDrawerOpen(e.target.open) },
    el("summary", {}, `What FalkorDB was asked · ${calls.length} agent lookups · ${queries.length} checker queries`, icon("down")),
    el("div", { class: "drawer-body" },
      el("div", { class: "drawer-section" }, el("h3", {}, "Agent graph lookups"),
        calls.length ? el("ul", { class: "query-list" }, calls.map(c => el("li", { class: "query-item" },
          el("div", { class: "row" }, el("strong", { class: "mono" }, c.name), el("span", { class: "tiny muted" }, c.error ? "error" : `${c.rows ?? "?"} rows`)),
          el("p", { class: "tiny muted mono query-params" }, json(c.args)), c.error ? el("p", { class: "tiny error-text" }, String(c.error)) : null)))
          : el("p", { class: "small muted" }, "No graph lookups were recorded for this attempt.")),
      el("div", { class: "drawer-section" }, el("h3", {}, "Checker queries"),
        queries.length ? el("ul", { class: "query-list" }, queries.map(q => queryItem(q))) : el("p", { class: "small muted" }, "No queries were recorded.")),
      originsData?.query ? el("div", { class: "drawer-section" }, el("h3", {}, "Origin lineage query"),
        el("ul", { class: "query-list" }, queryItem(originsData.query))) : null,
      planHash ? ablationBox(s, actions, planHash) : null));
  return node;
}

export function witnessPanel(inv, attempt, selected, actions, s = {}) {
  const v = attempt.report.verification;
  const check = preferredCheck(v, selected);
  if (!check) return null;
  const { obligation: ob, receipt, result } = check, t = ob.tuple;
  const originsData = s.origins?.[cutKey(s, attempt.plan_hash)];
  const originsOk = originsData && originsData !== "loading" && !originsData.error ? originsData : null;
  const graph = buildGraph(attempt.report, originsOk, { label: id => releaseLabel(inv, id) });
  const cutKinds = s.cutShown ? CUT_KINDS[s.cutShown] : [];
  const selectedCluster = graph.clusters.find(c => c.id === s.cluster);
  const svg = renderGraph(graph, { filter: s.cluster, faded: cutKinds,
    onCluster: c => actions.selectCluster(c.id, clusterTarget(c)) });
  const error = receipt && [receipt.error_type, receipt.message].filter(Boolean).join(": ");
  const legend = el("div", { class: "tg-legend tiny muted" },
    el("span", { class: "key FAIL" }, "reader failed"), el("span", { class: "key PASS" }, "all passed"),
    el("span", { class: "key NONE" }, "unresolved / no read"), el("span", { class: "key DERIVED" }, "derived from"),
    el("span", {}, "Select a record cluster to filter the checks below."));
  const detail = selectedCluster ? (() => {
    const { shown, hidden } = clusterRecords(selectedCluster);
    return el("div", { class: "cluster-detail" }, el("div", { class: "row between" },
      el("strong", { class: "small" }, `${selectedCluster.records.length} rows in this cluster`),
      button("Clear filter", () => actions.selectCluster(null, null), { variant: "link" })),
      el("div", { class: "chip-list" }, shown.map(r => el("button", { type: "button", class: `rec-chip ${r.outcome}`,
        onclick: () => actions.inspect(r.failHashes[0] || r.hashes[0]) }, r.record_id)),
        hidden ? el("span", { class: "tiny muted" }, `+${hidden} more (filter applies to the checks below)`) : null));
  })() : null;
  const callout = graph.callout ? el("div", { class: "root-callout", role: "note" }, icon("alert"), el("p", {}, graph.callout.text)) : null;
  const loadingNote = originsData === "loading" ? el("p", { class: "tiny muted" }, "Loading record lineage…") : null;
  const title = v.disposition === "BLOCKED" ? "Why this is blocked — FalkorDB path"
    : v.disposition === "BOUNDED_PASS" ? "Verified reads — FalkorDB path" : "Incomplete evidence — FalkorDB path";
  return panel(title, "The evidence subgraph the checker walked: plan, readers, stores, records and their writers.",
    [el("div", { class: "map-scroll" }, el("div", { class: "tgraph-wrap" }, svg)), legend, callout, loadingNote, detail,
      el("button", { class: `map-record ${result}`, type: "button", onclick: () => actions.inspect(ob.obligation_hash),
        "aria-label": `Inspect ${t.record_id}, ${displayStatus(result)}` },
      el("span", { class: "tiny muted" }, icon("file"), " Selected read · ", releaseLabel(inv, t.release_id), " · ", displayStatus(result)),
      el("strong", {}, t.record_id), el("small", {}, formatText(t.format_id))),
      result === "FAIL" && error ? el("div", { class: "evidence-error mono" }, error) : null,
      queriesDrawer(s, actions, attempt, originsOk),
      el("div", { class: "panel-footer" }, el("span", {}, t.record_id, " · ", displayStatus(result)),
        button("View read result", () => actions.inspect(ob.obligation_hash), { variant: "link", symbol: "file" }))], badge(null, "FalkorDB path"));
}

export function matrixPanel(inv, attempt, selected, actions, recordFilter = null) {
  const rows = checks(attempt.report.verification).filter(r => !recordFilter || recordFilter.has(recordKey(r.obligation)));
  if (!rows.length) return panel("Reader checks", "No reader–record checks were derived.",
    el("div", { class: "panel-body small muted" }, "Review the evidence gaps before considering any action."));
  const readers = [...new Map(rows.map(r => [readerKey(r.obligation), r.obligation])).values()];
  const records = [...new Map(rows.map(r => [recordKey(r.obligation), r.obligation])).values()];
  const selectedHash = preferredCheck(attempt.report.verification, selected)?.obligation.obligation_hash;
  const head = el("tr", {}, el("th", { scope: "col" }, "Software version / reader"), records.map(ob => el("th", { scope: "col" },
    el("span", { class: "table-primary" }, ob.tuple.record_id), el("span", { class: "table-secondary" }, formatText(ob.tuple.format_id)))));
  const body = readers.map(reader => el("tr", {}, el("th", { scope: "row" },
    el("span", { class: "table-primary" }, releaseLabel(inv, reader.tuple.release_id)),
    el("span", { class: "table-secondary" }, reader.reader_entry)), records.map(record => {
      const row = rows.find(r => readerKey(r.obligation) === readerKey(reader) && recordKey(r.obligation) === recordKey(record));
      if (!row) return el("td", {}, el("span", { class: "muted", title: "No modeled reader–record check in this plan" }, "—"));
      const ob = row.obligation;
      return el("td", {}, el("button", {
        class: `matrix-cell ${row.result}${selectedHash === ob.obligation_hash ? " selected" : ""}`,
        type: "button", "aria-label": `${releaseLabel(inv, ob.tuple.release_id)} reading ${ob.tuple.record_id}: ${displayStatus(row.result)}`,
        "aria-pressed": String(selectedHash === ob.obligation_hash), onclick: () => actions.inspect(ob.obligation_hash),
      }, icon(row.result === "PASS" ? "check" : "alert"), displayStatus(row.result)));
    })));
  return panel("Saved-data compatibility", "Rows are software readers; columns are retained records. Select a result to see the recorded check.",
    el("div", { class: "table-scroll" }, el("table", { class: "matrix" }, el("thead", {}, head), el("tbody", {}, body))),
    badge(null, recordFilter ? `${rows.length} checks · filtered` : `${rows.length} checks`));
}

export function gapsPanel(verification) {
  if (!verification.gaps.length) return null;
  const meanings = {
    COVERAGE_INCOMPLETE: "Some saved records may be missing from this snapshot. Passing checks on the listed records cannot cover those that are unlisted.",
    WRITER_UNKNOWN: "The inventory does not establish which software version created this record.",
    FORMAT_UNKNOWN: "The inventory does not establish the data format this record was saved in.",
    RECEIPT_UNKNOWN: "The test ran, but a reliable result could not be established.",
    RECEIPT_MISSING: "A required saved-data check has no recorded result.",
    RECEIPT_INAPPLICABLE: "The recorded result does not belong to this exact version, record and configuration.",
  };
  return panel("Evidence still needed", "These facts are missing, even if some saved-data checks passed.",
    el("div", { class: "panel-body" }, el("ul", { class: "gap-list" }, verification.gaps.map(g => el("li", {},
      el("strong", {}, g.kind.replaceAll("_", " ").toLowerCase().replace(/^./, x => x.toUpperCase())),
      el("p", {}, meanings[g.kind] || g.detail),
      details("Technical details", meanings[g.kind] ? el("p", { class: "small subtle" }, g.detail) : null,
        el("p", { class: "mono" }, g.subject)))))), badge("NEEDS_EVIDENCE", `${verification.gaps.length} gaps`));
}

export function receiptInspector(inv, attempt, selected) {
  const check = preferredCheck(attempt.report.verification, selected);
  if (!check) return el("p", { class: "small muted" }, "No check is available.");
  const { obligation: ob, receipt: r, result } = check;
  const kv = (name, value) => [el("dt", {}, name), el("dd", {}, value)];
  return el("div", {}, el("div", { class: "receipt-header" }, badge(result), el("span", { class: "tiny muted" }, "Recorded read result")),
    el("h3", { class: "receipt-heading" }, ob.tuple.record_id),
    el("p", { class: "small muted" }, `${releaseLabel(inv, ob.tuple.release_id)} · ${ob.reader_entry}`),
    el("p", { class: "explanation-intro" }, "A reader is the code that opens saved data. This is the recorded result of running that reader on this record's stored bytes."),
    !r ? el("div", { class: "callout", style: "margin-top:18px" }, result === "INAPPLICABLE"
      ? "A receipt exists, but it does not match this check's full bound identity. It cannot establish a result."
      : "No applicable receipt exists for this check. It remains unresolved.") : null,
    r?.error_type || r?.message ? el("div", { class: "receipt-error mono" }, [r.error_type, r.message].filter(Boolean).join(": ")) : null,
    el("dl", { class: "receipt-kv" },
      kv("Data format", formatText(ob.tuple.format_id)), kv("Stored in", ob.tuple.store_id.replace(/^store:/, "")),
      kv("Saved by version", releaseLabel(inv, ob.writer_release_id))),
    r ? details("Technical test output", el("p", { class: "small muted" }, "Process exit code: ", r.harness_exit === null ? "No exit result" : r.harness_exit),
      el("pre", { class: "code-block" }, r.stdout_excerpt || "No output captured.")) : null,
    details("Full bound check identity", r ? el("p", { class: "small muted" }, "Executed ", r.executed_at) : null,
      el("pre", { class: "code-block" }, JSON.stringify(ob.tuple, null, 2))));
}
