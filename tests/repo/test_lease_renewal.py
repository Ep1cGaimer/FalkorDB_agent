"""Real Redis WATCH races: renewal must survive; a replacement owner must fence writes."""
import pytest

from rw import graph as G
from rw.repo.adapters import ADAPTERS
from rw.repo.config import RepoConfig
from rw.repo.index import index_repository
from rw.repo.query import RepoQuery


@pytest.fixture
def publication(make_repo, graph_name):
    cfg = RepoConfig(name="renewal", path=make_repo(), revisions=["main"])
    index_repository(cfg, graph_name)
    return cfg, graph_name, G.connect()


def test_renewal_between_watch_and_exec_does_not_abort_owned_import(publication, monkeypatch):
    from redis.client import Pipeline
    cfg, name, db = publication
    key = f"rw:repo-import:{name}"
    original = Pipeline.execute
    conflicts = []
    def renew(self, *args, **kwargs):
        if self.watching and self.command_stack and len(conflicts) < 3:
            command = self.command_stack[0][0]
            if command[0].startswith("GRAPH.") and command[1] == name:
                owner = db.connection.get(key)
                assert owner
                db.connection.pexpire(key, 120000)
                assert db.connection.get(key) == owner
                conflicts.append(owner)
        return original(self, *args, **kwargs)
    monkeypatch.setattr(Pipeline, "execute", renew)
    report = index_repository(cfg, name, db=db)
    assert report.status == "COMPLETE" and len(conflicts) == 3
    assert len(set(conflicts)) == 1
    assert RepoQuery(name, cfg.name, db=db).symbols("main").items
    assert not db.connection.exists(key)


def test_owner_replaced_between_watch_and_exec_cannot_delete_symbols(publication, monkeypatch):
    from redis.client import Pipeline
    cfg, name, db = publication
    key = f"rw:repo-import:{name}"
    graph = db.select_graph(name)
    before = graph.ro_query("MATCH (s:Symbol) RETURN count(s)").result_set
    original = Pipeline.execute
    replaced = False
    def replace(self, *args, **kwargs):
        nonlocal replaced
        if self.watching and self.command_stack and not replaced:
            command = self.command_stack[0][0]
            if command[0].startswith("GRAPH.") and command[1] == name and "DETACH DELETE s" in command[2]:
                replaced = True
                db.connection.set(key, "successor-owner", xx=True, ex=120)
        return original(self, *args, **kwargs)
    try:
        with monkeypatch.context() as patch:
            patch.setattr(Pipeline, "execute", replace)
            patch.setattr(type(ADAPTERS["python"]), "version", "renewal-race")
            with pytest.raises(RuntimeError, match="lease"):
                index_repository(cfg, name, db=db)
        assert replaced
        assert graph.ro_query("MATCH (s:Symbol) RETURN count(s)").result_set == before
        assert db.connection.get(key) == "successor-owner"
        assert not RepoQuery(name, cfg.name, db=db).symbols("main").items
    finally:
        db.connection.delete(key)
    index_repository(cfg, name, db=db)
    assert RepoQuery(name, cfg.name, db=db).symbols("main").items
