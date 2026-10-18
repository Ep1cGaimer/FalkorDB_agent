"""S2/S3 round 3 — dotted-suffix symbol resolution, a function-level changes contract, constant
literal flags, revision discipline for non-adjacent pairs / history, and PRESENT for intact fixes.

Needs FalkorDB at 127.0.0.1:6379. Written after round-2 results (only failure categories read).
Everything runs on one deterministic test-only repo built here (`r3`), different from the round-3
eval builder (evals/repo_questions/round3/build_round3_synthetic.py) and from earlier fixtures.

Interface pinned here (additions on top of tests/repo/test_s23_round2.py's contract):

(1) Symbol resolution (every route that takes a symbol: raises, dependencies, history, locate).
    A name resolves, in order, to: the exact qualname; else the unique symbol whose qualname ends
    with the name on DOTTED-COMPONENT boundaries (qualname == name or qualname.endswith("." + name);
    so "Signer.unsign" matches "lib.crypto.Signer.unsign" but NOT "lib.crypto.TimedSigner.unsign").
    Several matches -> Gap(kind="ambiguous_symbol") whose detail lists every candidate qualname,
    no findings, facts == {}. No match -> Gap(kind="unknown_symbol"), facts == {}.
    facts["symbol"] is always the full resolved qualname.

(2) "What changed between <A> and <B>?" facts:
      from, to
      added / removed / modified : sorted FUNCTION and METHOD qualnames only (never modules,
          classes, constants), excluding symbols in test files. Functions of a deleted file are
          "removed"; functions of an added file are "added". In a renamed file, symbols are matched
          by their module-relative name, so an unchanged function that only moved with its file is
          in none of the three lists (it is reported under the new module name if added/modified).
      classes_added / classes_removed / classes_modified : class qualnames, same rules.
      deleted_files : paths present at A, absent at B, and not the old side of a rename.
      added_files   : paths absent at A, present at B, not the new side of a rename.
      renamed       : [{"old": path, "new": path, "similarity": int percent 0..100}].
      tests_changed : sorted paths of changed (added/modified/deleted/renamed-new) test files
          (a path segment "tests"/"test" or a file named test_*.py / *_test.py).
    Every citation (findings and RepoFindings.citations) is at A or B, whatever the requested
    revision is and however many tags lie between A and B.

(3) "What is the value of <SYM>?" facts add:
      is_plain_literal: bool  — True iff ast.literal_eval accepts the rhs.
      evaluated: bool         — True iff "value" is present (never True for a non-literal; source
                                is never executed).
    Plain literal: value, expression, is_plain_literal=True, evaluated=True.
    Non-literal (e.g. `10 * 1024`): expression, is_plain_literal=False, evaluated=False, no "value",
    Gap(kind="non_literal_value").

(4) History ("When did <SYM> appear/disappear?"): RepoFindings.citations (top level) contains only
    the requested revision's commit; labelled per-revision entries may cite their own revision in
    their own Finding.citations, but those are not promoted to the top-level list.

(5) "Is fix <sha> present?": when the fix commit is an ancestor of the revision and every non-blank
    line the fix added is present in the corresponding file at the revision (even if no longer
    contiguous, e.g. a comment was inserted between two added lines), state == "PRESENT".
"""
import json
import subprocess
import uuid
from pathlib import Path

import pytest

from .conftest import git as _git, write as _write

# ---------------------------------------------------------------- test-only `r3` repo

ERRORS = ("class BadSignature(Exception):\n    pass\n\n\n"
          "class SignatureExpired(BadSignature):\n    pass\n")
CONFIG = ('TIMEOUT = 30\n'
          'CHUNK = 10 * 1024\n'
          'NAMES = ("a", "b")\n'
          'OFFSET = -1\n'
          '\n\n'
          'class Settings:\n'
          '    retries = 3\n'
          '    backoff = TIMEOUT / 2\n')
SIGNER_V1 = ("from lib.errors import BadSignature, SignatureExpired\n\n\n"
             "class Signer:\n"
             "    def unsign(self, value):\n"
             "        if not value:\n"
             "            raise BadSignature(\"empty\")\n"
             "        return value\n\n"
             "    def sign(self, value):\n"
             "        return value\n")
TIMED = ("\n\nclass TimedSigner(Signer):\n"
         "    def unsign(self, value):\n"
         "        raise SignatureExpired(\"old\")\n")
MODULE_UNSIGN = "\n\ndef unsign(value):\n    raise TypeError(\"module-level\")\n"
CRYPTO_V1 = SIGNER_V1 + TIMED + MODULE_UNSIGN

VERIFY_HEAD = "\n    def verify(self, value, sig=None):\n"
FIX_A = "        if sig is None:\n"
FIX_B = "            raise BadSignature(\"missing\")\n"
FIX_COMMENT = "            # a missing signature is never valid\n"
VERIFY_TAIL = "        return self.sign(value) == sig\n"
SIGN_V2 = "    def sign(self, value):\n        return value + b\".sig\"\n"
VERIFIER_V1 = "\n\nclass Verifier:\n    def check(self, s):\n        return s.verify(1)\n"
VERIFIER_V2 = "\n\nclass Verifier:\n    def check(self, s):\n        return bool(s.verify(1))\n"
ROTATE = "\n\ndef rotate(key):\n    return key[::-1]\n"


def _crypto(verify_body: str, verifier: str = VERIFIER_V1, extra: str = "") -> str:
    signer = SIGNER_V1.replace("    def sign(self, value):\n        return value\n", SIGN_V2)
    return signer + VERIFY_HEAD + verify_body + VERIFY_TAIL + TIMED + verifier + extra


HTTP = ("class Adapter:\n"
        "    def send(self, req):\n"
        "        if req is None:\n"
        "            raise ConnectionError(\"no request\")\n"
        "        return connect(req)\n\n\n"
        "def connect(req):\n"
        "    return req\n")
COMPAT = ("class Adapter:\n"
          "    def send(self, req):\n"
          "        raise NotImplementedError\n")
LEGACY = ("class LegacyThing:\n    def run(self):\n        return 1\n\n\n"
          "def go():\n    return LegacyThing().run()\n")
OLD_UTIL = ("def helper(x):\n    \"\"\"Shared helper kept across the rename.\"\"\"\n"
            "    total = x + 1\n    total = total * 2\n    return total\n")
UTIL_NEW = OLD_UTIL + "\n\ndef extra(y):\n    return helper(y)\n"
TESTS_V1 = "from lib.crypto import Signer\n\n\ndef test_sign():\n    assert Signer().sign(b\"a\")\n"
CL_FIX = "- reject a missing signature in Signer.verify (#5)\n"


def _build_r3(repo: Path) -> dict:
    repo.mkdir(parents=True)
    _git(repo, "init", "-q")

    def commit(files, msg, day, tag=None, deletions=(), mv=None):
        date = f"2024-09-{day:02d}T00:00:00+00:00"
        if mv:
            _git(repo, "mv", *mv)
        for rel, text in files.items():
            _write(repo, rel, text)
        for rel in deletions:
            (repo / rel).unlink()
        _git(repo, "add", "-A", date=date)
        _git(repo, "commit", "-q", "-m", msg, date=date)
        if tag:
            _git(repo, "tag", "-a", tag, "-m", f"release {tag}", date=date)
        return _git(repo, "rev-parse", "HEAD")

    commit({"lib/__init__.py": "", "lib/errors.py": ERRORS, "lib/config.py": CONFIG,
            "lib/crypto.py": CRYPTO_V1, "lib/http.py": HTTP, "lib/compat.py": COMPAT,
            "lib/legacy.py": LEGACY, "lib/old_util.py": OLD_UTIL,
            "CHANGELOG.md": "# Changelog\n\n## 1.0.0\n- first\n"}, "initial", 1, "v1.0.0")
    # v1.1.0: Signer.verify + Verifier added, Signer.sign modified, module unsign removed,
    # legacy.py deleted, old_util.py -> util_new.py (+extra), a test file added, TIMEOUT changed.
    commit({"lib/crypto.py": _crypto(""), "lib/util_new.py": UTIL_NEW,
            "lib/config.py": CONFIG.replace("TIMEOUT = 30", "TIMEOUT = 45"),
            "tests/test_crypto.py": TESTS_V1,
            "CHANGELOG.md": "# Changelog\n\n## 1.1.0\n- verify\n\n## 1.0.0\n- first\n"},
           "verify, drop legacy, rename util", 3, "v1.1.0", deletions=["lib/legacy.py"],
           mv=("lib/old_util.py", "lib/util_new.py"))
    fix = commit({"lib/crypto.py": _crypto(FIX_A + FIX_B),
                  "CHANGELOG.md": "# Changelog\n\n## 1.1.0\n- verify\n" + CL_FIX + "\n## 1.0.0\n- first\n"},
                 "fix: reject missing signature (#5)", 5)
    commit({"lib/crypto.py": _crypto(FIX_A + FIX_B, VERIFIER_V2, ROTATE),
            "tests/test_crypto.py": TESTS_V1 + "\n\ndef test_rotate():\n    assert True\n"},
           "rotate, verifier tweak", 7, "v1.2.0")
    # v1.3.0: a comment line is inserted BETWEEN the two lines the fix added; the fix stays intact.
    commit({"lib/crypto.py": _crypto(FIX_A + FIX_COMMENT + FIX_B, VERIFIER_V2, ROTATE),
            "CHANGELOG.md": "# Changelog\n\n## 1.3.0\n- comment\n\n## 1.1.0\n- verify\n" + CL_FIX
                            + "\n## 1.0.0\n- first\n"}, "document the check", 9, "v1.3.0")
    # v1.4.0: the check is removed by hand (no git revert).
    commit({"lib/crypto.py": _crypto("", VERIFIER_V2, ROTATE)}, "drop the check", 11, "v1.4.0")
    tags = ("v1.0.0", "v1.1.0", "v1.2.0", "v1.3.0", "v1.4.0")
    shas = {t: _git(repo, "rev-parse", f"{t}^{{commit}}") for t in tags}
    return {"path": repo, "fix": fix, "shas": shas}


@pytest.fixture(scope="module")
def r3(tmp_path_factory):
    from rw.repo.config import load_config
    from rw.repo.index import index_repository
    tmp = tmp_path_factory.mktemp("r3")
    info = _build_r3(tmp / "r3")
    cfg_dir = tmp / "repos"
    cfg_dir.mkdir()
    cfg_path = cfg_dir / "r3.json"
    cfg_path.write_text(json.dumps({"name": "r3", "path": str(info["path"]),
                                    "tag_pattern": r"^v\d+\.\d+\.\d+$", "languages": ["python"]}),
                        encoding="utf-8")
    graph = f"rw_test_repo_{uuid.uuid4().hex[:12]}"
    assert index_repository(load_config(cfg_path), graph_name=graph).status == "COMPLETE"
    yield {**info, "name": "r3", "config": cfg_path, "graph": graph}
    try:
        from rw import graph as G
        G.connect().select_graph(graph).delete()
    except Exception:
        pass


# ---------------------------------------------------------------- helpers

def ask(env, rev, question):
    from rw.repo.investigate import investigate
    return investigate(env["name"], rev, question, graph_name=env["graph"], config=env["config"])


def _span(env, c) -> str:
    text = subprocess.run(["git", "-C", str(env["path"]), "show", f"{c.commit}:{c.path}"],
                          capture_output=True, check=True).stdout.decode("utf-8")
    lines = text.splitlines()
    assert 1 <= c.start_line <= c.end_line <= max(len(lines), 1), c
    return "\n".join(lines[c.start_line - 1:c.end_line])


def all_citations(res):
    return list(res.citations) + [c for f in res.findings for c in f.citations]


def gap(res, kind):
    return next((g for g in res.gaps if g.kind == kind), None)


def assert_clean_gap(res, kind):
    assert gap(res, kind) is not None, [(g.kind, g.detail) for g in res.gaps]
    assert res.facts == {} and res.findings == [] and res.citations == []


# ---------------------------------------------------------------- (1) dotted-suffix resolution

@pytest.mark.parametrize("name,qual,exc", [
    ("Signer.unsign", "lib.crypto.Signer.unsign", ["BadSignature"]),
    ("TimedSigner.unsign", "lib.crypto.TimedSigner.unsign", ["SignatureExpired"]),
    ("crypto.Signer.unsign", "lib.crypto.Signer.unsign", ["BadSignature"]),
    ("http.Adapter.send", "lib.http.Adapter.send", ["ConnectionError"]),
    ("compat.Adapter.send", "lib.compat.Adapter.send", ["NotImplementedError"]),
])
def test_partially_dotted_name_resolves_on_component_boundaries(r3, name, qual, exc):
    sha = r3["shas"]["v1.0.0"]
    res = ask(r3, "v1.0.0", f"Which exceptions does {name} raise?")
    assert res.unresolved in (None, "")
    assert gap(res, "ambiguous_symbol") is None, gap(res, "ambiguous_symbol")
    assert res.facts.get("symbol") == qual
    assert res.facts.get("exceptions") == exc
    assert all(c.commit == sha for c in all_citations(res))
    assert "def " in _span(r3, res.findings[0].citations[0])


def test_ambiguous_partial_name_lists_every_candidate(r3):
    res = ask(r3, "v1.0.0", "What exceptions does Adapter.send raise?")
    assert_clean_gap(res, "ambiguous_symbol")
    detail = gap(res, "ambiguous_symbol").detail
    assert "lib.http.Adapter.send" in detail and "lib.compat.Adapter.send" in detail


def test_bare_last_component_still_ambiguous(r3):
    res = ask(r3, "v1.0.0", "Which exceptions does unsign raise?")
    assert_clean_gap(res, "ambiguous_symbol")
    detail = gap(res, "ambiguous_symbol").detail
    for q in ("lib.crypto.Signer.unsign", "lib.crypto.TimedSigner.unsign", "lib.crypto.unsign"):
        assert q in detail


def test_partial_name_with_wrong_prefix_is_unknown(r3):
    res = ask(r3, "v1.0.0", "Which exceptions does Nope.unsign raise?")
    assert_clean_gap(res, "unknown_symbol")


def test_partial_name_on_dependencies_and_history_routes(r3):
    res = ask(r3, "v1.0.0", "What does http.Adapter.send call?")
    assert res.facts.get("symbol") == "lib.http.Adapter.send"
    assert "lib.http.connect" in res.facts.get("targets", [])
    res = ask(r3, "v1.3.0", "When did Signer.verify appear?")
    assert res.facts.get("symbol") == "lib.crypto.Signer.verify"
    assert res.facts.get("first_present_revision") == "v1.1.0"
    assert res.facts.get("present_at_requested") is True


# ---------------------------------------------------------------- (2) changes contract

FUNCS_10_11 = {
    "added": ["lib.crypto.Signer.verify", "lib.crypto.Verifier.check", "lib.util_new.extra"],
    "removed": ["lib.crypto.unsign", "lib.legacy.LegacyThing.run", "lib.legacy.go"],
    "modified": ["lib.crypto.Signer.sign"],
}


def _changes(r3, a, b, at):
    res = ask(r3, at, f"What changed between {a} and {b}?")
    assert res.unresolved in (None, "")
    return res, res.facts


def test_changes_lists_functions_and_methods_only(r3):
    res, fx = _changes(r3, "v1.0.0", "v1.1.0", "v1.1.0")
    for k, want in FUNCS_10_11.items():
        assert fx[k] == sorted(want), (k, fx[k])


def test_changes_separates_classes(r3):
    _, fx = _changes(r3, "v1.0.0", "v1.1.0", "v1.1.0")
    assert "lib.crypto.Verifier" in fx["classes_added"]
    assert "lib.legacy.LegacyThing" in fx["classes_removed"]
    assert "classes_modified" in fx
    for k in ("added", "removed", "modified"):
        assert not {"lib.crypto.Verifier", "lib.legacy.LegacyThing", "lib.crypto.Signer"} & set(fx[k])


def test_changes_files_rename_similarity_and_tests(r3):
    _, fx = _changes(r3, "v1.0.0", "v1.1.0", "v1.1.0")
    assert fx["deleted_files"] == ["lib/legacy.py"]
    assert "tests/test_crypto.py" in fx["tests_changed"]
    assert "tests/test_crypto.py" not in fx.get("added_files", [])
    assert len(fx["renamed"]) == 1
    r = fx["renamed"][0]
    assert (r["old"], r["new"]) == ("lib/old_util.py", "lib/util_new.py")
    assert isinstance(r["similarity"], int) and 50 <= r["similarity"] <= 100
    for k in ("added", "removed", "modified"):
        assert not any(q.startswith("tests.") for q in fx[k]), fx[k]
        assert "lib.util_new.helper" not in fx[k] and "lib.old_util.helper" not in fx[k]
        assert "lib.config" not in fx[k] and "lib.config.TIMEOUT" not in fx[k]


def test_changes_non_adjacent_pair_cites_only_endpoints(r3):
    s = r3["shas"]
    res, fx = _changes(r3, "v1.0.0", "v1.2.0", "v1.3.0")
    assert fx["added"] == sorted(FUNCS_10_11["added"] + ["lib.crypto.rotate"])
    assert fx["removed"] == sorted(FUNCS_10_11["removed"])
    assert "lib.crypto.Signer.sign" in fx["modified"]
    assert "lib.crypto.Verifier.check" not in fx["modified"]  # absent at A -> added, not modified
    assert fx["deleted_files"] == ["lib/legacy.py"]
    cits = all_citations(res)
    assert cits
    allowed = {s["v1.0.0"], s["v1.2.0"]}
    for c in cits:
        assert c.commit in allowed, (c, "intermediate/requested revisions must not be cited")


def test_changes_pair_with_requested_after_both(r3):
    s = r3["shas"]
    res, fx = _changes(r3, "v1.1.0", "v1.2.0", "v1.4.0")
    assert "lib.crypto.rotate" in fx["added"]
    assert "lib.crypto.Verifier.check" in fx["modified"]
    assert "lib.crypto.Signer.verify" in fx["modified"]
    assert fx["tests_changed"] == ["tests/test_crypto.py"]
    assert not any(q.startswith("tests.") for q in fx["added"])
    assert fx["deleted_files"] == [] and fx["renamed"] == []
    for c in all_citations(res):
        assert c.commit in {s["v1.1.0"], s["v1.2.0"]}, c


def test_changes_facts_json_serialisable(r3):
    res, _ = _changes(r3, "v1.0.0", "v1.1.0", "v1.1.0")
    d = res.to_dict()
    json.dumps(d)
    for k in ("added", "removed", "modified", "classes_added", "classes_removed", "classes_modified",
              "deleted_files", "renamed", "tests_changed"):
        assert k in d["facts"], k


# ---------------------------------------------------------------- (3) constant literal flags

@pytest.mark.parametrize("name,value", [
    ("TIMEOUT", 30), ("NAMES", ["a", "b"]), ("OFFSET", -1), ("Settings.retries", 3)])
def test_plain_literal_flags(r3, name, value):
    res = ask(r3, "v1.0.0", f"What is the value of {name}?")
    fx = res.facts
    got = list(fx["value"]) if isinstance(fx.get("value"), tuple) else fx.get("value")
    assert got == value
    assert fx.get("is_plain_literal") is True
    assert fx.get("evaluated") is True
    assert "expression" in fx
    assert gap(res, "non_literal_value") is None


@pytest.mark.parametrize("name,expr", [("CHUNK", "10 * 1024"), ("Settings.backoff", "TIMEOUT / 2")])
def test_non_literal_flags(r3, name, expr):
    sha = r3["shas"]["v1.0.0"]
    res = ask(r3, "v1.0.0", f"What is the value of {name}?")
    fx = res.facts
    assert "value" not in fx
    assert fx.get("expression") == expr
    assert fx.get("is_plain_literal") is False
    assert fx.get("evaluated") is False
    assert gap(res, "non_literal_value") is not None
    assert res.citations and all(c.commit == sha for c in res.citations)
    assert expr in _span(r3, res.citations[0])


# ---------------------------------------------------------------- (4) history discipline

@pytest.mark.parametrize("question", ["When did lib.crypto.unsign disappear?",
                                      "When did lib.crypto.Verifier.check appear?",
                                      "When did lib.crypto.rotate appear?"])
def test_history_top_level_citations_only_at_requested(r3, question):
    sha = r3["shas"]["v1.3.0"]
    res = ask(r3, "v1.3.0", question)
    assert res.unresolved in (None, "")
    for c in res.citations:
        assert c.commit == sha, (question, c)
    for f in res.findings:
        if getattr(f, "revision", None) is None:
            assert all(c.commit == sha for c in f.citations), (question, f)


def test_history_present_symbol_headline_cites_requested(r3):
    sha = r3["shas"]["v1.3.0"]
    res = ask(r3, "v1.3.0", "When did lib.crypto.Verifier.check appear?")
    assert res.facts["first_present_revision"] == "v1.1.0"
    assert res.citations and all(c.commit == sha for c in res.citations)
    assert "def check" in _span(r3, res.citations[0])


def test_history_disappeared_symbol(r3):
    res = ask(r3, "v1.3.0", "When did lib.crypto.unsign disappear?")
    fx = res.facts
    assert fx["first_present_revision"] == "v1.0.0"
    assert fx["first_absent_revision"] == "v1.1.0"
    assert fx["present_at_requested"] is False
    assert res.citations == []


# ---------------------------------------------------------------- (5) intact fix is PRESENT

def test_fix_present_when_contiguous(r3):
    res = ask(r3, "v1.2.0", f"Is fix {r3['fix'][:10]} present?")
    assert res.facts["state"] == "PRESENT"
    assert res.facts["first_tag_containing"] == "v1.2.0"


def test_fix_present_when_added_lines_no_longer_contiguous(r3):
    sha = r3["shas"]["v1.3.0"]
    res = ask(r3, "v1.3.0", f"Is fix {r3['fix'][:10]} present?")
    fx = res.facts
    assert fx["state"] == "PRESENT", (fx, [(g.kind, g.detail) for g in res.gaps])
    assert fx["fix_commit"] == r3["fix"]
    assert fx["first_tag_containing"] == "v1.2.0"
    assert all(c.commit == sha for c in all_citations(res))
    assert any('raise BadSignature("missing")' in _span(r3, c) for c in res.citations)
    assert gap(res, "CHANGE_IDENTITY_UNKNOWN") is None


def test_fix_absent_after_hand_removal(r3):
    res = ask(r3, "v1.4.0", f"Is fix {r3['fix']} present?")
    assert res.facts["state"] != "PRESENT"  # ABSENT or UNCERTAIN; never PRESENT
    assert res.facts["first_tag_containing"] == "v1.2.0"


def test_fix_absent_before_it_landed(r3):
    res = ask(r3, "v1.1.0", f"Is fix {r3['fix']} present?")
    assert res.facts["state"] == "ABSENT"
