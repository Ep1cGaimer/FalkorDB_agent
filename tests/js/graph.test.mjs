import test from "node:test";
import assert from "node:assert/strict";
import { buildGraph, layoutGraph, clusterRecords, clusterTarget, CUT_KINDS } from "../../src/rw/static/graph.mjs";

// Synthetic report: 4 fleet services (one reads nothing), 2 stores, a failing and a passing cluster.
const svc = { cart: "cart", acct: "accounting", web: "web", chk: "checkout" };
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
};
const origins = { origins: ["ledger-1", "ledger-2", "ledger-3"].map(r => ({ record_id: r, chain: [r, "orders-1@5"],
  origin_record: "orders-1@5", origin_release_id: "release:checkout:3", origin_service: "checkout", origin_version: "3.2.0", hops: 1 })) };
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

test("services without obligations collapse into one grey node", () => {
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
  const split = { origins: [origins.origins[0], { ...origins.origins[1], origin_release_id: "release:other:1" }] };
  assert.equal(buildGraph(report, split, { label }).callout, null);
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
