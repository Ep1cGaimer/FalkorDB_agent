import { el, icon, button, panel, details, hash } from "./dom.mjs";
import { checks, preferredCheck, recordKey, readerKey, displayStatus, shortHash } from "./model.mjs";
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

function svgNode(tag, attrs, text) {
  const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [k, v] of Object.entries(attrs || {})) node.setAttribute(k, String(v));
  if (text) node.textContent = text;
  return node;
}

export function witnessPanel(inv, attempt, selected, actions) {
  const v = attempt.report.verification;
  const check = preferredCheck(v, selected);
  if (!check) return null;
  const { obligation: ob, receipt, result } = check, t = ob.tuple;
  const route = ob.witness_path.find(h => h.label === "ReaderRoute");
  const map = el("div", { class: "witness-map", "aria-label": "Selected reader and retained-record evidence path" });
  const markerId = `arrow-${shortHash(ob.obligation_hash)}`;
  const svg = svgNode("svg", { class: "map-connectors", viewBox: "0 0 720 236", preserveAspectRatio: "none", "aria-hidden": "true" });
  const defs = svgNode("defs");
  const marker = svgNode("marker", { id: markerId, markerWidth: 6, markerHeight: 6, refX: 5, refY: 3, orient: "auto", markerUnits: "strokeWidth" });
  marker.append(svgNode("path", { d: "M0,0 L6,3 L0,6", fill: "#b5c1d2" })); defs.append(marker); svg.append(defs);
  for (const d of ["M204 69 H264", "M516 69 H456", ...(ob.writer_release_id ? ["M608 113 V150"] : [])]) {
    svg.append(svgNode("path", { d, stroke: "#bac5d5", "stroke-width": 1.3, fill: "none", "marker-end": `url(#${markerId})` }));
  }
  for (const [x, y, text] of [[234, 53, "reads"], [486, 53, "in store"], ...(ob.writer_release_id ? [[648, 137, "written by"]] : [])]) {
    svg.append(svgNode("text", { x, y, fill: "#99a6b8", "font-size": 9, "text-anchor": "middle", "font-family": "Segoe UI, sans-serif" }, text));
  }
  const node = (cls, type, title, subtitle, symbol) => el("div", { class: `map-node ${cls}` },
    el("span", {}, icon(symbol), type), el("strong", {}, title), subtitle ? el("small", {}, subtitle) : null);
  map.append(svg,
    node("map-reader", "Reads saved data", releaseLabel(inv, t.release_id), route?.display || ob.reader_entry, "code"),
    node("map-store", "Shared storage", t.store_id.replace(/^store:/, ""), "Store on this modeled read path", "database"),
    el("button", { class: `map-node map-record ${result}`, type: "button", onclick: () => actions.inspect(ob.obligation_hash),
      "aria-label": `Inspect ${t.record_id}, ${displayStatus(result)}` },
      el("span", {}, icon("file"), "Retained record"), el("strong", {}, t.record_id), el("small", {}, formatText(t.format_id))),
    ob.writer_release_id ? node("map-writer", "Saved by version", releaseLabel(inv, ob.writer_release_id), null, "layers")
      : node("map-writer", "Saved by version", "Unknown", null, "info"));
  const error = receipt && [receipt.error_type, receipt.message].filter(Boolean).join(": ");
  return panel("Why this record matters", "How the proposed version can encounter this retained record.",
    [el("div", { class: "map-scroll" }, map),
      result === "FAIL" && error ? el("div", { class: "evidence-error mono" }, error) : null,
      el("div", { class: "panel-footer" }, el("span", {}, t.record_id, " · ", displayStatus(result)),
        button("View read result", () => actions.inspect(ob.obligation_hash), { variant: "link", symbol: "file" }))], badge(null, "FalkorDB path"));
}

export function matrixPanel(inv, attempt, selected, actions) {
  const rows = checks(attempt.report.verification);
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
    badge(null, `${rows.length} checks`));
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
