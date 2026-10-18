// Traversal graph of a plan's evidence subgraph. buildGraph/layoutGraph are pure (no DOM) so they can be
// unit tested; renderGraph draws the result as data-driven SVG. Nothing here hard-codes fixture names.
import { checks } from "./model.mjs";

export const COLUMNS = ["Plan", "Deployments", "Reader releases", "Reader routes", "State stores", "Record clusters", "Writer releases", "Origin writers"];
export const CUT_KINDS = {
  DERIVED_FROM: ["DERIVED_FROM"],
  READER_LINKS: ["EXECUTES_ROUTE", "READS_FROM", "IN_STORE"],
};
const MAX_RECORDS_SHOWN = 24;
const aggregate = list => list.some(x => x === "FAIL") ? "FAIL" : list.length && list.every(x => x === "PASS") ? "PASS" : "UNKNOWN";
const bare = (value, prefix) => String(value ?? "").replace(new RegExp(`^${prefix}:`), "");
const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;

export function buildGraph(report, origins, options = {}) {
  const label = options.label || (id => id);
  const rows = checks(report?.verification);
  const fleet = report?.plan?.fleet || [];
  const changed = new Set(fleet.filter(f => f.changed).map(f => f.service));
  const nodes = new Map(), edges = new Map();
  const addNode = (id, column, props) => { if (!nodes.has(id)) nodes.set(id, { id, column, ...props }); return nodes.get(id); };
  const addEdge = (from, to, kind, status, props = {}) => {
    const id = `${kind}|${from}|${to}`;
    const found = edges.get(id);
    if (found) found.statuses.push(status); else edges.set(id, { id, from, to, kind, statuses: [status], ...props });
  };

  const planId = "plan";
  addNode(planId, 0, { type: "plan", title: report?.plan?.label || "Plan", subtitle: "proposed fleet" });

  // Record outcome across every reader that must read it (FAIL > PASS > unresolved).
  const records = new Map();
  for (const r of rows) {
    const t = r.obligation.tuple, key = `${t.store_id}|${t.batch_id}`;
    const rec = records.get(key) || { key, record_id: t.record_id, store_id: t.store_id, format_id: t.format_id,
      writer: r.obligation.writer_release_id || null, results: [], hashes: [], failHashes: [] };
    rec.results.push(r.result); rec.hashes.push(r.obligation.obligation_hash);
    if (r.result === "FAIL") rec.failHashes.push(r.obligation.obligation_hash);
    records.set(key, rec);
  }
  for (const rec of records.values()) rec.outcome = aggregate(rec.results);
  const storeOfRecord = new Map([...records.values()].map(r => [r.record_id, bare(r.store_id, "store")]));

  const serviceHasReads = new Set(rows.map(r => r.obligation.tuple.service));
  const statelessServices = [...new Set(fleet.map(f => f.service))].filter(x => !serviceHasReads.has(x)).sort();
  if (statelessServices.length) {
    addNode("stateless", 1, { type: "stateless", title: `${plural(statelessServices.length, "service")} read`, subtitle: "no retained state",
      tooltip: statelessServices.join(", "), services: statelessServices });
    addEdge(planId, "stateless", "HAS_DEPLOYMENT", null);
  }

  for (const r of rows) {
    const ob = r.obligation, t = ob.tuple;
    const dep = `dep:${t.deployment_id || t.service}`, rel = `rel:${t.release_id}`, route = `route:${t.release_id}|${t.route_id}`, store = `store:${t.store_id}`;
    const hop = ob.witness_path?.find(h => h.label === "ReaderRoute");
    addNode(dep, 1, { type: "deployment", title: t.service, subtitle: "deployment" });
    addNode(rel, 2, { type: "release", title: label(t.release_id), subtitle: "reader release", service: t.service });
    addNode(route, 3, { type: "route", title: hop?.display || ob.reader_entry || t.route_id, subtitle: "reader route" });
    addNode(store, 4, { type: "store", title: bare(t.store_id, "store"), subtitle: "state store" });
    addEdge(planId, dep, "HAS_DEPLOYMENT", r.result); addEdge(dep, rel, "RUNS", r.result);
    addEdge(rel, route, "EXECUTES_ROUTE", r.result); addEdge(route, store, "READS_FROM", r.result);
  }

  const clusters = new Map();
  for (const rec of records.values()) {
    const ck = `${rec.store_id}|${rec.format_id}|${rec.writer}|${rec.outcome}`;
    const c = clusters.get(ck) || { id: `cluster:${ck}`, store_id: rec.store_id, format_id: rec.format_id, writer: rec.writer, outcome: rec.outcome, records: [] };
    c.records.push(rec); clusters.set(ck, c);
  }
  const writerId = w => w ? `writer:${w}` : "writer:unknown";
  for (const c of clusters.values()) {
    const fmt = bare(c.format_id, "format"), store = bare(c.store_id, "store");
    const fails = c.records.filter(r => r.outcome === "FAIL").length;
    addNode(c.id, 5, { type: "cluster", title: plural(c.records.length, "row"), subtitle: `${store} · ${fmt}`,
      cluster: c, outcome: c.outcome, failCount: fails, byLine: c.writer ? `by ${label(c.writer)}` : "writer unknown" });
    addEdge(`store:${c.store_id}`, c.id, "IN_STORE", c.outcome);
    addNode(writerId(c.writer), 6, { type: "writer", title: c.writer ? label(c.writer) : "Unknown writer", subtitle: "writer release" });
    addEdge(c.id, writerId(c.writer), "WRITTEN_BY", c.outcome);
  }

  // Lineage: only failing records with a chain longer than 0 add the origin column.
  const byRecord = new Map((origins?.origins || []).map(o => [o.record_id, o]));
  const derived = [];
  for (const c of clusters.values()) {
    const groups = new Map();
    for (const rec of c.records) {
      const o = byRecord.get(rec.record_id);
      if (rec.outcome !== "FAIL" || !o || !(o.hops > 0) || !o.origin_release_id) continue;
      derived.push({ rec, o });
      groups.set(o.origin_release_id, [...(groups.get(o.origin_release_id) || []), o]);
    }
    for (const [rid, list] of groups) {
      const sample = list[0], oid = `origin:${rid}`;
      addNode(oid, 7, { type: "origin", title: `${sample.origin_service || label(rid)}${sample.origin_version ? ` ${sample.origin_version}` : ""}`,
        subtitle: "origin writer", service: sample.origin_service, release_id: rid });
      addEdge(c.id, oid, "DERIVED_FROM", "DERIVED", { label: "derived from", count: list.length });
    }
  }

  let callout = null;
  const origin = new Set(derived.map(d => d.o.origin_release_id));
  if (derived.length && origin.size === 1) {
    const o = derived[0].o;
    if (!changed.has(o.origin_service)) {
      const stores = [...new Set(derived.map(d => bare(d.rec.store_id, "store")))].sort();
      const hops = Math.max(...derived.map(d => d.o.hops));
      const originStore = storeOfRecord.get(o.origin_record) || /^[A-Za-z][\w]*?(?=-\d)/.exec(o.origin_record || "")?.[0] || "records";
      const who = `${o.origin_service}${o.origin_version ? ` ${o.origin_version}` : ""}`;
      callout = { count: derived.length, stores, origin_service: o.origin_service, origin_version: o.origin_version, hops,
        origin_release_id: o.origin_release_id, origin_store: originStore,
        text: `These ${derived.length} ${stores.join("/")} rows were produced from ${originStore} written by ${who} — ${plural(hops, "hop")} away.` };
    }
  }

  const edgeList = [...edges.values()].map(e => ({ ...e,
    status: e.kind === "DERIVED_FROM" ? "DERIVED" : e.statuses.every(x => x === null) ? null : aggregate(e.statuses.filter(Boolean)) }));
  const columns = COLUMNS.map((name, column) => {
    const inCol = [...nodes.values()].filter(n => n.column === column);
    let count = inCol.length;
    if (column === 1) count = fleet.length || inCol.length;
    if (column === 5) return { name, column, count, extra: `${plural(records.size, "record")}` };
    return { name, column, count };
  }).filter(c => c.column <= 6 || c.count > 0);
  return { nodes: [...nodes.values()], edges: edgeList, columns, callout, clusters: [...clusters.values()], records, statelessServices };
}

// Barycenter sweeps: each node moves toward the mean normalized position of its neighbours in the
// adjacent column; the collapsed stateless node stays pinned at the top of its column.
function orderColumns(graph, cols, byCol) {
  const norm = () => { const m = new Map(); for (const list of byCol.values()) list.forEach((n, i) => m.set(n.id, (i + 0.5) / list.length)); return m; };
  const sweep = (c, neighbourCol) => {
    const list = byCol.get(c), rank = norm(), keep = new Map(list.map((n, i) => [n.id, i]));
    const bary = n => {
      const ys = graph.edges.map(e => e.from === n.id ? e.to : e.to === n.id ? e.from : null)
        .filter(id => id && graph.nodes.find(x => x.id === id)?.column === neighbourCol).map(id => rank.get(id));
      return ys.length ? ys.reduce((a, b) => a + b, 0) / ys.length : null;
    };
    const scored = list.map(n => ({ n, b: n.type === "stateless" ? -1 : bary(n) ?? (keep.get(n.id) + 0.5) / list.length }));
    scored.sort((x, y) => x.b - y.b || keep.get(x.n.id) - keep.get(y.n.id));
    byCol.set(c, scored.map(s => s.n));
  };
  for (let pass = 0; pass < 3; pass++) {
    for (let i = 1; i < cols.length; i++) sweep(cols[i], cols[i - 1]);
    for (let i = cols.length - 2; i >= 1; i--) sweep(cols[i], cols[i + 1]);
  }
  for (let i = 1; i < cols.length; i++) sweep(cols[i], cols[i - 1]);
}

// Pure layout: column x, evenly spaced y; cubic Bezier paths between node borders.
export function layoutGraph(graph, { width = 1280, nodeW = 124 } = {}) {
  const cols = graph.columns.map(c => c.column);
  const gap = cols.length > 1 ? (width - 24 - nodeW) / (cols.length - 1) : 0;
  const colX = new Map(cols.map((c, i) => [c, 12 + i * gap]));
  const heightOf = n => n.type === "cluster" ? 62 : 44;
  const byCol = new Map(cols.map(c => [c, graph.nodes.filter(n => n.column === c)
    .sort((a, b) => (a.outcome === "FAIL" ? 0 : 1) - (b.outcome === "FAIL" ? 0 : 1) || a.title.localeCompare(b.title))]));
  orderColumns(graph, cols, byCol);
  const tallest = Math.max(1, ...[...byCol.values()].map(list => list.reduce((sum, n) => sum + heightOf(n) + 12, 0)));
  const height = Math.max(240, tallest + 56);
  const pos = new Map();
  for (const [c, list] of byCol) {
    const total = list.reduce((sum, n) => sum + heightOf(n), 0), space = (height - 40 - total) / (list.length + 1);
    let y = 40 + space;
    for (const n of list) { pos.set(n.id, { x: colX.get(c), y, w: nodeW, h: heightOf(n) }); y += heightOf(n) + space; }
  }
  const paths = graph.edges.map(e => {
    const a = pos.get(e.from), b = pos.get(e.to);
    if (!a || !b) return null;
    const x1 = a.x + a.w, y1 = a.y + a.h / 2, x2 = b.x, y2 = b.y + b.h / 2, dx = Math.max(20, (x2 - x1) / 2);
    return { ...e, d: `M${x1.toFixed(1)} ${y1.toFixed(1)} C${(x1 + dx).toFixed(1)} ${y1.toFixed(1)} ${(x2 - dx).toFixed(1)} ${y2.toFixed(1)} ${x2.toFixed(1)} ${y2.toFixed(1)}`,
      mx: (x1 + x2) / 2, my: (y1 + y2) / 2 };
  }).filter(Boolean);
  return { width, height, pos, paths, colX };
}

// Bounded record list for an expanded cluster; failing rows first.
export function clusterRecords(cluster, limit = MAX_RECORDS_SHOWN) {
  const sorted = [...cluster.records].sort((a, b) => (a.outcome === "FAIL" ? 0 : 1) - (b.outcome === "FAIL" ? 0 : 1) || a.record_id.localeCompare(b.record_id));
  return { shown: sorted.slice(0, limit), hidden: Math.max(0, sorted.length - limit) };
}
export const clusterTarget = cluster => {
  const rec = cluster.records.find(r => r.failHashes.length) || cluster.records[0];
  return rec?.failHashes[0] || rec?.hashes[0] || null;
};

// ---- DOM rendering -------------------------------------------------------------------------------------
const NS = "http://www.w3.org/2000/svg";
function s(tag, attrs, text) {
  const n = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs || {})) if (v !== null && v !== undefined) n.setAttribute(k, String(v));
  if (text !== undefined && text !== null) n.textContent = text;
  return n;
}
const fit = (text, n) => String(text).length > n ? `${String(text).slice(0, n - 1)}…` : String(text);

export function renderGraph(graph, { filter = null, faded = [], onCluster } = {}) {
  const lay = layoutGraph(graph);
  const svg = s("svg", { class: "tgraph", viewBox: `0 0 ${lay.width} ${lay.height}`, role: "group",
    "aria-label": "Evidence subgraph: plan, deployments, readers, routes, stores, record clusters, writers" });
  const fadedSet = new Set(faded), index = new Map(graph.columns.map((c, i) => [c.column, i]));
  const delay = column => `${((index.get(column) ?? 0) * 0.19).toFixed(2)}s`;
  for (const c of graph.columns) {
    const head = s("text", { class: "tg-head", x: lay.colX.get(c.column) + 62, y: 16, "text-anchor": "middle", style: `animation-delay:${delay(c.column)}` });
    head.append(s("tspan", { class: "tg-head-n" }, String(c.count)), s("tspan", { dx: 4 }, c.extra ? c.name.toLowerCase() : c.name),
      ...(c.extra ? [s("tspan", { dx: 4 }, `· ${c.extra}`)] : []));
    svg.append(head);
  }
  const nodeColumn = new Map(graph.nodes.map(n => [n.id, n.column]));
  const rankOf = p => p.status === "FAIL" ? 2 : p.status === "DERIVED" ? 3 : 0;
  for (const p of [...lay.paths].sort((a, b) => rankOf(a) - rankOf(b))) {
    const cls = `tg-edge ${p.status || "NONE"}${fadedSet.has(p.kind) ? " cut" : ""}`;
    const g = s("g", { class: "tg-edge-g", style: `animation-delay:${delay(nodeColumn.get(p.to) ?? 0)}` });
    const path = s("path", { class: cls, d: p.d, "data-kind": p.kind,
      style: p.status === "FAIL" ? "stroke-width:2.6px" : p.status === "DERIVED" ? "stroke-width:2.8px" : null });
    path.append(s("title", {}, `${p.kind}${p.status && p.status !== "DERIVED" ? ` · ${p.status}` : ""}`));
    g.append(path);
    if (p.label) g.append(s("text", { class: "tg-edge-label", x: p.mx, y: p.my - 4, "text-anchor": "middle" }, `${p.label} · ${p.count}`));
    svg.append(g);
  }
  for (const n of graph.nodes) {
    const q = lay.pos.get(n.id);
    if (!q) continue;
    const isCluster = n.type === "cluster", on = isCluster && filter === n.id;
    const g = s("g", { class: `tg-node ${n.type}${n.outcome ? ` ${n.outcome}` : ""}${on ? " selected" : ""}`,
      transform: `translate(${q.x.toFixed(1)} ${q.y.toFixed(1)})`, style: `animation-delay:${delay(n.column)}`,
      ...(isCluster ? { tabindex: 0, role: "button", "aria-pressed": String(on), "data-cluster": n.id,
        "aria-label": `${n.title}, ${n.subtitle}, ${n.failCount} failing. Select to filter checks.` } : {}) });
    g.append(s("title", {}, n.tooltip || [n.title, n.subtitle, n.byLine].filter(Boolean).join(" · ")));
    g.append(s("rect", { width: q.w, height: q.h, rx: 7 }));
    g.append(s("text", { class: "tg-title", x: 8, y: 17 }, fit(n.title, 19)));
    g.append(s("text", { class: "tg-sub", x: 8, y: 30 }, fit(n.subtitle, 24)));
    if (isCluster) {
      g.append(s("text", { class: "tg-sub", x: 8, y: 42 }, fit(n.byLine, 24)));
      g.append(s("text", { class: `tg-fails ${n.failCount ? "FAIL" : ""}`, x: 8, y: 55 }, n.failCount ? `${n.failCount} FAIL` : n.outcome === "PASS" ? "all pass" : "unresolved"));
      if (onCluster) {
        g.addEventListener("click", () => onCluster(n.cluster));
        g.addEventListener("keydown", e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onCluster(n.cluster); } });
      }
    }
    svg.append(g);
  }
  return svg;
}
