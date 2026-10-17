import { test } from 'node:test';
import assert from 'node:assert/strict';
import { investigationFromSearch, loadInvestigation, adoptInvestigation } from '../../src/rw/static/handoff.mjs';
import { investigationView } from '../../src/rw/static/views.mjs';
import { usedReplays } from '../../src/rw/static/model.mjs';

const id = 'a'.repeat(32);
const inv = { id, original_request_text: 'Original <script>evil</script>', request_text: 'Answered request', mode: 'replay',
  snapshot_id: 'snapshot:snap-001', transcript: '/private/saved.json', attempts: [
    { grounding: { model: 'replay:first.json' }, transcript: '/private/first.json' }, { grounding: { model: 'replay:saved.json' }, transcript: 'C:\\local\\saved.json' }], answered: true };

test('handoff loads and refreshes with GET only, selects latest and keeps request and replay labels', async () => {
  const calls = [], priorFetch = globalThis.fetch;
  globalThis.fetch = async (path, options) => { calls.push({ path, method: options.method }); return { ok: true, json: async () => inv }; };
  try {
    const state = { inv: null, attemptIndex: 0, selected: 'old', form: {} };
    adoptInvestigation(state, await loadInvestigation(investigationFromSearch('?investigation=' + id)));
    assert.equal(state.inv, inv); assert.equal(state.attemptIndex, 1); assert.equal(state.selected, null);
    assert.equal(state.form.request, inv.original_request_text); assert.equal(state.form.mode, 'replay');
    assert.equal(state.form.snapshot, 'snap-001'); assert.equal(state.form.replay, 'saved.json');
    assert.deepEqual(usedReplays(inv), ['first.json', 'saved.json']);
    adoptInvestigation(state, await loadInvestigation(state.inv.id));
    assert.deepEqual(calls, Array(2).fill({ method: 'GET', path: '/api/investigations/' + id }));
  } finally { globalThis.fetch = priorFetch; }
});

test('invalid and encoded routes never fetch; missing link makes no call', async () => {
  const priorFetch = globalThis.fetch;
  globalThis.fetch = () => assert.fail('invalid links must not fetch');
  try {
    assert.equal(investigationFromSearch(''), null);
    for (const value of ['bad', 'A'.repeat(32), '../api', '%2Fapi', 'a'.repeat(31), '']) {
      assert.throws(() => investigationFromSearch('?investigation=' + value), /Invalid investigation/);
      await assert.rejects(loadInvestigation(value), /Invalid investigation/);
    }
  } finally { globalThis.fetch = priorFetch; }
});

test('unknown or expired ID has recovery guidance', async () => {
  const priorFetch = globalThis.fetch;
  globalThis.fetch = async () => ({ ok: false, status: 404, json: async () => ({ detail: 'not found' }) });
  try { await assert.rejects(loadInvestigation(id), /lost when the API restarted.*Start a new/); }
  finally { globalThis.fetch = priorFetch; }
});

// Minimal DOM for exercising the shipped view's text and click bindings in Node.
class TestNode {
  constructor(tag, text = '') { this.tag = tag; this.text = text; this.children = []; this.attrs = {}; this.events = {}; }
  append(...children) { this.children.push(...children); }
  prepend(child) { this.children.unshift(child); }
  setAttribute(key, value) { this.attrs[key] = value; }
  addEventListener(name, fn) { this.events[name] = fn; }
  get childElementCount() { return this.children.filter(n => n.tag !== '#text').length; }
  get textContent() { return this.text + this.children.map(n => n.textContent).join(''); }
}
const walk = node => [node, ...node.children.flatMap(walk)];

test('module view displays the full selected plan hash, confirms that attempt and exposes earlier clarification', () => {
  const priorNode = globalThis.Node, priorDocument = globalThis.document;
  globalThis.Node = TestNode;
  globalThis.document = { createElement: tag => new TestNode(tag), createElementNS: (_, tag) => new TestNode(tag),
    createTextNode: text => new TestNode('#text', text) };
  try {
    const confirmed = [], selected = [];
    const actions = { confirm: attempt => confirmed.push(attempt.plan_hash), selectAttempt: index => selected.push(index) };
    for (const hash of ['sha256:' + 'a'.repeat(64), 'sha256:' + 'b'.repeat(64)]) {
      const attempt = { plan_hash: hash, report: null, plan: { fleet: [], label: 'candidate 1' },
        grounding: { result: { rationale: 'Grounded proposal' } }, validation_errors: [] };
      const state = { inv: { ...inv, attempts: [{ clarification: { question: 'Which?' } }, attempt] },
        attemptIndex: 1, form: {}, contexts: [] };
      const nodes = investigationView(state, actions).flat(Infinity).filter(Boolean).flatMap(walk);
      assert(nodes.some(n => n.textContent.includes('Exact plan hash: ' + hash)));
      nodes.find(n => n.attrs.id === 'confirm-button').events.click();
      assert.equal(confirmed.at(-1), hash);
      nodes.find(n => n.tag === 'button' && n.textContent === 'Attempt 1').events.click();
      assert.equal(selected.at(-1), 0);
    }
  } finally { globalThis.Node = priorNode; globalThis.document = priorDocument; }
});
