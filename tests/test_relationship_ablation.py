import pytest
from types import SimpleNamespace
from evals.relationship_ablation import run_case, mutate


@pytest.mark.parametrize('case,disposition', [('A', 'BLOCKED'), ('B', 'BOUNDED_PASS')])
def test_real_ablation(case, disposition, tmp_path):
    evidence = run_case(case, tmp_path, port=6379)
    assert len(evidence['removed_edges']) == 2
    assert evidence['before']['nodes'] == evidence['after']['nodes']
    assert evidence['before'] == evidence['restored_structure']
    assert len(evidence['paths_before']) == 4 and not evidence['paths_after']
    assert len(evidence['inventory_after']) == 2 and all(not r['in_store'] for r in evidence['inventory_after'])
    assert evidence['intact']['verification']['disposition'] == disposition
    assert evidence['ablated']['verification']['disposition'] == 'NEEDS_EVIDENCE'
    assert evidence['restored']['verification']['disposition'] == disposition
    assert evidence['cleanup'] == 'verified_absent'


def test_mutation_refuses_unowned_graph():
    with pytest.raises(ValueError, match='owned'):
        mutate(SimpleNamespace(graph_name='rw_fixture_shop', snapshot_id='snapshot:snap-001', g=None), [])
