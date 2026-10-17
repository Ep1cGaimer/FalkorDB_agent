"""Remove only owned snapshot IN_STORE edges, retaining raw records and all node properties."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'src'))
from rw import graph as G
from rw.contracts import FleetEntry, GroundingProposal, ScopeConfirmation, h
from rw.pipeline import Session
from evals.flat_grounding import source_catalog
from evals.run_comparison import source_hashes, write_json

_OWNED = {}


def structure(graph):
    nodes = graph.ro_query('MATCH (n) RETURN id(n), labels(n), properties(n)').result_set
    edges = graph.ro_query('MATCH (a)-[e]->(b) RETURN a.id, type(e), b.id, properties(e)').result_set
    key = lambda x: json.dumps(x, sort_keys=True)
    return {'nodes': sorted(nodes, key=key), 'edges': sorted(edges, key=key)}


def mutate(session, edges, restore=False):
    if session.graph_name not in _OWNED or _OWNED[session.graph_name] is not session.g or session.snapshot_id != 'snapshot:snap-001':
        raise ValueError('mutation requires an owned disposable snap-001 graph')
    if len(edges) != 2 or any(e[1] != 'IN_STORE' or e[3] for e in edges):
        raise ValueError('expected exactly two property-free IN_STORE edges')
    for batch, _, store, _ in edges:
        if restore:
            query = ('MATCH (b:Batch {id:$batch, snapshot_id:$snapshot, store_id:$store}), '
                     '(s:StateStore {id:$store}) MERGE (b)-[:IN_STORE]->(s)')
        else:
            query = ('MATCH (b:Batch {id:$batch, snapshot_id:$snapshot, store_id:$store})'
                     '-[e:IN_STORE]->(s:StateStore {id:$store}) DELETE e')
        session.g.query(query, {'batch': batch, 'store': store, 'snapshot': session.snapshot_id})


def comparable(report):
    """Only receipt nonce/time varies; obligation tuples and witnesses remain exact."""
    v = report['verification']
    return {'plan_hash': report['plan_hash'], 'obligations': v['obligations'],
            'receipts': sorted([{'tuple': r['tuple'], 'result': r['result'], 'obligation_hash': r['obligation_hash']}
                                for r in v['receipts']], key=lambda x: x['obligation_hash']),
            'gaps': v['gaps'], 'disposition': v['disposition']}


def run_case(case, out, port=6382):
    if case not in ('A', 'B'):
        raise ValueError('ablation supports fixed A/B fleets')
    name = 'rw_issue22_ablation_' + uuid.uuid4().hex
    session = None
    graph_owned = False
    result = {'case': case, 'capability_lost': 'connected reader-record obligation enumeration and witness paths'}
    fixture_before = {k: v for k, v in source_hashes().items() if k.startswith('fixtures/')}
    try:
        db = G.connect(port=port)
        if name in db.list_graphs():
            raise ValueError('disposable namespace already exists')
        graph_owned = True
        session = Session(graph_name=name, port=port)
        _OWNED[name] = session.g
        releases = source_catalog()['releases']
        cart_version = '1.4' if case == 'A' else '1.5'
        chosen = [r for r in releases if (r['service'], r['version']) in (('cart', cart_version), ('checkout', '2.1'))]
        proposal = GroundingProposal(changes=[FleetEntry(service=r['service'], release_id=r['release_id'],
            flags={'basket_v2': False} if case == 'B' and r['service'] == 'cart' else {}) for r in chosen],
            citations=[], rationale='deterministic relationship ablation')
        plan, errors = session.plan_from_proposal(proposal, 'deterministic relationship ablation', origin='fixture')
        if errors or plan is None:
            raise ValueError(errors)
        confirmation = ScopeConfirmation(plan_hash=plan.plan_hash(), confirmed_by='evaluation-scope',
                                         confirmed_at='2026-10-18T00:00:00Z')
        intact = session.verify(plan, confirmation)
        before = structure(session.g)
        batches = {row[0] for row in session.g.ro_query(
            'MATCH (b:Batch {snapshot_id:$snapshot}) RETURN b.id', {'snapshot': session.snapshot_id}).result_set}
        removed = [e for e in before['edges'] if e[0] in batches and e[1] == 'IN_STORE']
        inventory_before = G.store_inventory(session.g, session.snapshot_id, 'store:cart-cache')[1]
        paths_before = G.obligation_paths(session.g, plan.plan_id(), session.snapshot_id)[0]
        mutate(session, removed)
        after = structure(session.g)
        if before['nodes'] != after['nodes'] or after['edges'] != [e for e in before['edges'] if e not in removed]:
            raise AssertionError('ablation changed more than the selected edges')
        inventory_after = G.store_inventory(session.g, session.snapshot_id, 'store:cart-cache')[1]
        paths_after = G.obligation_paths(session.g, plan.plan_id(), session.snapshot_id)[0]
        if [{k: v for k, v in r.items() if k != 'in_store'} for r in inventory_before] != [
                {k: v for k, v in r.items() if k != 'in_store'} for r in inventory_after]:
            raise AssertionError('raw inventory changed')
        ablated = session.verify(plan, confirmation)
        if len(paths_before) != 4 or paths_after or ablated['verification']['disposition'] != 'NEEDS_EVIDENCE':
            raise AssertionError('expected loss of four connected pairs with fail-closed disposition')
        if ablated['verification']['obligations'] or not ablated['verification']['gaps']:
            raise AssertionError('missing relationship evidence was silently accepted')
        mutate(session, removed, restore=True)
        restored_state = structure(session.g)
        if before != restored_state:
            raise AssertionError('restore did not recover exact graph structure')
        restored = session.verify(plan, confirmation)
        if comparable(intact) != comparable(restored):
            raise AssertionError('restored evidence differs beyond receipt time/nonce')
        fixture_after = {k: v for k, v in source_hashes().items() if k.startswith('fixtures/')}
        if fixture_before != fixture_after:
            raise AssertionError('fixture bytes changed')
        result.update(intact=intact, ablated=ablated, restored=restored,
                      before=before, after=after, restored_structure=restored_state,
                      node_digest=h(before['nodes']), removed_edges=removed,
                      inventory_before=inventory_before, inventory_after=inventory_after,
                      paths_before=paths_before, paths_after=paths_after,
                      fixture_hashes=fixture_before, fixtures_unchanged=True)
    finally:
        original_error = sys.exc_info()[0] is not None
        cleanup_error = None
        try:
            if graph_owned:
                db = session.db if session else G.connect(port=port)
                if name in db.list_graphs():
                    db.select_graph(name).delete()
                if name in db.list_graphs():
                    raise RuntimeError('owned graph cleanup failed')
                result['cleanup'] = 'verified_absent'
        except Exception as exc:
            cleanup_error = exc
            result['cleanup'] = {'error_category': type(exc).__name__}
        finally:
            _OWNED.pop(name, None)
            write_json(Path(out) / f'{case}.json', result)
        if cleanup_error and not original_error:
            raise cleanup_error
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--db-port', type=int, default=6382)
    args = parser.parse_args(argv)
    for case in ('A', 'B'):
        result = run_case(case, args.out, args.db_port)
        print(case, result['intact']['verification']['disposition'], '-> NEEDS_EVIDENCE ->',
              result['restored']['verification']['disposition'])
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
