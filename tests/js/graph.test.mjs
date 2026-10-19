import test from "node:test";
import assert from "node:assert/strict";
import { buildGraph, layoutGraph, clusterRecords, clusterTarget, CUT_KINDS } from "../../src/rw/static/graph.mjs";

// Synthetic report: 4 fleet services (three proven to read nothing), 2 stores, failing and passing clusters.
const relOf = s => `release:${s}:1`;
function ob(service, store, recId, batch, format, writer, route = `route-${service}`) {
  const hash = `h-${service}-${recId}`;
  const tuple = { plan_hash: "p", service, release_id: relOf(service), deployment_id: service, route_id: route,
    store_id: `store:${store}`, batch_id: batch, record_id: recId, format_id: `format:${format}`, payload_hash: "x" };
  return { obligation_hash: hash, tuple, writer_release_id: writer, reader_entry: "read()", witness_path: [
    { label: "ReaderRoute", id: route, display: `${service}.read` }] };
}
const obs = [
  ...["ledger-1", "ledger-2", "ledger-3"].map(r => ob("cart", "ledger", r, `b-${r}`, "ledger/v2", "release:accounting:3")),
  ob("cart", "orders", "orders-1@5", "b-o1", "orders/v3", "release:checkout:3"),
  ...["ledger-9"].map(r => ob("cart", "ledger", r, `b-${r}`, "ledger/v1", "release:accounting:2")),
];
const receipts = obs.map(o => ({ obligation_hash: o.obligation_hash, tuple: { ...o.tuple },
  result: o.tuple.format_id === "format:ledger/v2" ? "FAIL" : "PASS" }));
const report = {
  plan: { label: "Rollback cart", fleet: [
    { service: "cart", changed: true, proposed_version: "1.0" }, { service: "accounting", changed: false },
    { service: "web", changed: false }, { service: "checkout", changed: false }] },
  verification: { obligations: obs, receipts },
  no_state_read_services: ["accounting", "checkout", "web"],
};
const origins = { query: { complete: true, truncated: false, gaps: [] },
  origins: ["ledger-1", "ledger-2", "ledger-3"].map(r => ({ batch_id: `b-${r}`, record_id: r,
    store_id: "store:ledger", chain: [r, "orders-1@5"], origin_batch_id: "b-o1", origin_store_id: "store:orders",
    origin_record: "orders-1@5", origin_release_id: "release:checkout:3", origin_service: "checkout",
    origin_version: "3.2.0", hops: 1, lineage_complete: true })) };
const label = id => id.replace(/^release:/, "").replace(":", " v");

test("clusters group rows by store, format, writer and outcome", () => {
  const g = buildGraph(report, origins, { label });
  assert.equal(g.clusters.length, 3);
  const bad = g.clusters.find(c => c.outcome === "FAIL");
  assert.equal(bad.records.length, 3);
  assert.equal(g.nodes.find(n => n.id === bad.id).failCount, 3);
  const col = g.columns.find(c => c.name === "Record clusters");
  assert.equal(col.count, 3); assert.equal(col.extra, "5 records");
});

test("edges are red only where the reader failed, green when all passed", () => {
  const g = buildGraph(report, origins, { label });
  const byId = new Map(g.nodes.map(n => [n.id, n]));
  for (const e of g.edges.filter(e => e.kind === "IN_STORE" || e.kind === "WRITTEN_BY")) {
    const cluster = byId.get(e.kind === "IN_STORE" ? e.to : e.from);
    assert.equal(e.status, cluster.outcome, `${e.id} follows its cluster outcome`);
  }
  assert.ok(g.edges.some(e => e.status === "FAIL") && g.edges.some(e => e.status === "PASS"));
  assert.ok(g.edges.filter(e => e.status === "FAIL").every(e => e.kind !== "DERIVED_FROM"));
});

test("only proven no-state-read services collapse into one grey node", () => {
  const g = buildGraph(report, origins, { label });
  const stateless = g.nodes.filter(n => n.type === "stateless");
  assert.equal(stateless.length, 1);
  assert.deepEqual(stateless[0].services, ["accounting", "checkout", "web"]);
  assert.match(stateless[0].title, /3 services read/);
  assert.equal(g.nodes.filter(n => n.type === "deployment").length, 1);
});

test("derived-from edges and root callout come from origins", () => {
  const g = buildGraph(report, origins, { label });
  const derived = g.edges.filter(e => e.kind === "DERIVED_FROM");
  assert.equal(derived.length, 1);
  assert.equal(derived[0].status, "DERIVED"); assert.equal(derived[0].count, 3);
  assert.equal(g.callout.text, "These 3 ledger rows were produced from orders written by checkout 3.2.0 — 1 hop away.");
  assert.ok(g.nodes.some(n => n.type === "origin" && n.column === 7));
});

test("no callout when the origin service is itself changed, or origins are absent or diverge", () => {
  const changedReport = { ...report, plan: { ...report.plan, fleet: report.plan.fleet.map(f => f.service === "checkout" ? { ...f, changed: true } : f) } };
  assert.equal(buildGraph(changedReport, origins, { label }).callout, null);
  const none = buildGraph(report, null, { label });
  assert.equal(none.callout, null); assert.ok(!none.nodes.some(n => n.type === "origin"));
  assert.equal(none.columns.some(c => c.name === "Origin writers"), false);
  const split = { ...origins, origins: origins.origins.map((o, i) => i === 1 ? { ...o, origin_release_id: "release:other:1" } : o) };
  assert.equal(buildGraph(report, split, { label }).callout, null);
});

test("missing obligations without stateless proof remain unresolved", () => {
  const unknown = { ...report, no_state_read_services: ["web"],
    verification: { obligations: [], receipts: [], gaps: [{ kind: "ROUTE_MISSING" }] } };
  const g = buildGraph(unknown, null);
  assert.deepEqual(g.statelessServices, ["web"]);
  assert.deepEqual(g.unresolvedServices, ["accounting", "cart", "checkout"]);
  assert.equal(g.nodes.find(n => n.type === "unresolved").subtitle, "reads unresolved");
  assert.equal(g.edges.find(e => e.to === "unresolved-services").status, "UNKNOWN");
  assert.deepEqual(buildGraph({ ...unknown, no_state_read_services: undefined }, null).statelessServices, []);
});

test("origins join by batch identity even when display record ids collide", () => {
  const copy = ob("cart", "archive", "ledger-1", "b-archive-ledger-1", "ledger/v2", "release:accounting:3");
  const colliding = { ...report, verification: { obligations: [...obs, copy],
    receipts: [...receipts, { obligation_hash: copy.obligation_hash, tuple: copy.tuple, result: "FAIL" }] } };
  const g = buildGraph(colliding, origins);
  const archiveCluster = g.clusters.find(c => c.store_id === "store:archive");
  assert.equal(g.edges.some(e => e.from === archiveCluster.id && e.kind === "DERIVED_FROM"), false);
  assert.equal(g.callout, null); // the additional failing batch has no origin evidence
  const noBatchIds = { ...origins, origins: origins.origins.map(o => ({ ...o, batch_id: undefined })) };
  assert.equal(buildGraph(report, noBatchIds).edges.some(e => e.kind === "DERIVED_FROM"), false);
});

test("all roots survive and mixed origin writers suppress a common-origin claim", () => {
  const extra = { ...origins.origins[0], origin_batch_id: "b-other", origin_record: "other",
    origin_release_id: "release:other:1", origin_service: "other" };
  const g = buildGraph(report, { ...origins, origins: [...origins.origins, extra] });
  assert.deepEqual(g.nodes.filter(n => n.type === "origin").map(n => n.release_id).sort(),
    ["release:checkout:3", "release:other:1"]);
  assert.deepEqual(g.edges.filter(e => e.kind === "DERIVED_FROM").map(e => e.count).sort(), [1, 3]);
  assert.equal(g.callout, null);
});

test("converging paths and multiple roots by one writer count each failing batch once", () => {
  const extra = { ...origins.origins[0], origin_batch_id: "b-other-order", origin_record: "another-order" };
  const duplicate = { ...origins.origins[0], hops: 2 };
  const g = buildGraph(report, { ...origins, origins: [...origins.origins, extra, duplicate] });
  assert.equal(g.edges.filter(e => e.kind === "DERIVED_FROM").length, 1);
  assert.equal(g.edges.find(e => e.kind === "DERIVED_FROM").count, 3);
  assert.equal(g.callout.count, 3);
  assert.equal(g.callout.hops, 2);
});

test("incomplete, truncated, missing and unknown lineage never make a common-origin claim", () => {
  const variants = [
    { ...origins, query: { ...origins.query, complete: false } },
    { ...origins, query: { ...origins.query, truncated: true } },
    { ...origins, query: { ...origins.query, gaps: [{ reason: "cycle" }] } },
    { ...origins, query: undefined },
    { ...origins, origins: origins.origins.slice(1) },
    ...[ { lineage_complete: false }, { origin_release_id: null, origin_service: null },
      { origin_batch_id: null }, { origin_store_id: null } ].map(change => ({ ...origins,
        origins: origins.origins.map((o, i) => i === 0 ? { ...o, ...change } : o) })),
    { ...origins, origins: [...origins.origins, { ...origins.origins[0], lineage_complete: false }] },
  ];
  for (const variant of variants) assert.equal(buildGraph(report, variant).callout, null);
  const unknownWriter = buildGraph(report, variants[6]);
  assert.ok(unknownWriter.nodes.some(n => n.type === "origin" && n.title === "Unknown writer"));
  assert.ok(buildGraph(report, variants[0]).edges.some(e => e.kind === "DERIVED_FROM"));
});

test("direct failing roots participate in the common-writer check", () => {
  const direct = obs.find(o => o.tuple.batch_id === "b-o1");
  const failingDirect = { ...report, verification: { obligations: obs,
    receipts: receipts.map(r => r.obligation_hash === direct.obligation_hash ? { ...r, result: "FAIL" } : r) } };
  const root = { ...origins.origins[0], batch_id: "b-o1", record_id: "orders-1@5", hops: 0,
    origin_release_id: "release:other:1", origin_service: "other" };
  assert.equal(buildGraph(failingDirect, { ...origins, origins: [...origins.origins, root] }).callout, null);
  const sameWriter = { ...root, origin_release_id: "release:checkout:3", origin_service: "checkout" };
  assert.equal(buildGraph(failingDirect, { ...origins, origins: [...origins.origins, sameWriter] }).callout.count, 3);
});

test("layout places every node inside the viewBox and bounds expanded records", () => {
  const g = buildGraph(report, origins, { label }), lay = layoutGraph(g);
  for (const n of g.nodes) {
    const p = lay.pos.get(n.id);
    assert.ok(p.x >= 0 && p.x + p.w <= lay.width && p.y >= 0 && p.y + p.h <= lay.height, n.id);
  }
  assert.equal(lay.paths.length, g.edges.length);
  const c = g.clusters.find(x => x.outcome === "FAIL");
  assert.equal(clusterRecords(c, 2).shown.length, 2); assert.equal(clusterRecords(c, 2).hidden, 1);
  assert.match(clusterTarget(c), /^h-cart-ledger/);
  assert.deepEqual(CUT_KINDS.DERIVED_FROM, ["DERIVED_FROM"]);
});
