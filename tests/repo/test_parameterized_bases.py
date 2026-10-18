"""Subscripted base origins are static inferences, not runtime inheritance proofs."""
from rw.repo.adapters.python import PythonAdapter
from rw.repo.config import RepoConfig
from rw.repo.index import index_repository
from rw.repo.query import RepoQuery


def test_parameterized_origins_are_marked_inferred_and_plain_bases_stay_parsed():
    source = b"from .base import Parent\nclass Plain(Parent): pass\nclass Typed(Parent[str]): pass\n"
    result = PythonAdapter().extract("pkg/child.py", source)
    edges = {(r.source, r.target, r.provenance) for r in result.relations if r.kind == "INHERITS"}
    assert edges == {("pkg.child.Plain", "pkg.base.Parent", "parsed"),
                     ("pkg.child.Typed", "pkg.base.Parent", "inferred")}


def test_parameterized_origin_produces_source_cited_second_hop_without_execution(
    make_repo, tmp_path, graph_name,
):
    marker = tmp_path / "must-never-execute"
    repo = make_repo(files={
        "pkg/base.py": f"class Parent:\n    def __class_getitem__(cls, item):\n        open({str(marker)!r}, 'w').write('executed')\n        return cls\n",
        "pkg/child.py": "from .base import Parent\nclass Typed(Parent[str]): pass\nclass Leaf(Typed): pass\n",
    })
    cfg = RepoConfig(name="parameterized", path=repo, revisions=["v1.0.0"])
    index_repository(cfg, graph_name)
    page = RepoQuery(graph_name, cfg.name).dependencies("v1.0.0", "pkg.child.Leaf", hops=2)
    expected = next((e for e in page.items if e.target == "pkg.base.Parent"), None)
    assert expected is not None and expected.hops == 2
    assert expected.provenance == "inferred" and expected.target_citation.path == "pkg/base.py"
    assert not marker.exists()


def test_arbitrary_base_factories_are_not_reported_as_inheritance_origins():
    result = PythonAdapter().extract("pkg/unknown.py", b"class Dynamic(make_base()[str]): pass\n")
    assert not [r for r in result.relations if r.kind == "INHERITS"]
    assert any("call" in limit.lower() and "base" in limit.lower() for limit in result.limits)
