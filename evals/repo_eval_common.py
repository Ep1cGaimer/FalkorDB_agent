"""Shared helpers for the E2 (evals/repo_history_eval.py) and E4 (evals/repo_benefit.py) runners:
question sets, read-only git on the clones, citation checks, evidence overlap and the rule-based
answer check declared in evals/repo_eval_keys.json. No repository code is imported or executed."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
QDIR = ROOT / "evals" / "repo_questions"
CFG_DIR = ROOT / "evals" / "repo_eval_configs"
KEYS_PATH = ROOT / "evals" / "repo_eval_keys.json"
THRESHOLD = ROOT / "evals" / "repo_benefit_threshold.json"

# question-set name -> (question file, config file, graph, clone)
SETS = {
    "synthetic-history": ("synthetic_history.json", CFG_DIR / "synthetic-history.json",
                          "rw_repo_synthetic-history", ROOT / "artifacts" / "question_repos" / "synthetic-history"),
    "branchy-history": ("branchy_history.json", CFG_DIR / "branchy-history.json",
                        "rw_repo_branchy-history", ROOT / "artifacts" / "question_repos" / "branchy-history"),
    "requests": ("requests.json", ROOT / "evals" / "repo_onboarding" / "configs" / "requests.json",
                 "rw_repo_requests", ROOT / "artifacts" / "repos" / "requests"),
    "itsdangerous": ("itsdangerous.json", CFG_DIR / "itsdangerous.json",
                     "rw_repo_itsdangerous", ROOT / "artifacts" / "repos" / "itsdangerous"),
}
IGNORED_GAPS = {"runtime_unverified", "history_sampled", "truncated"}


def sha256_file(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_questions(name: str) -> dict:
    return json.loads((QDIR / SETS[name][0]).read_text(encoding="utf-8"))


def load_keys() -> dict:
    return json.loads(KEYS_PATH.read_text(encoding="utf-8"))


def rel(p: Path) -> str:
    try:
        return Path(p).resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(p)


class Clone:
    """Read-only git access (rev-parse, show, grep, log, ls-tree, cat-file) with small caches."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._sha: dict[str, str | None] = {}
        self._lines: dict[tuple[str, str], int | None] = {}

    def run(self, *args: str, check: bool = False) -> subprocess.CompletedProcess:
        assert args[0] in {"rev-parse", "show", "grep", "log", "ls-tree", "cat-file", "tag", "merge-base"}
        from rw.repo.git import GitRepo
        raw = GitRepo(self.path)._proc(*args)
        result = subprocess.CompletedProcess(raw.args, raw.returncode,
            raw.stdout.decode("utf-8", "replace"), raw.stderr.decode("utf-8", "replace"))
        if check:
            result.check_returncode()
        return result

    def sha(self, rev) -> str | None:
        if not isinstance(rev, str) or not rev or rev.startswith("-"):
            return None
        if rev not in self._sha:
            r = self.run("rev-parse", "--verify", "-q", f"{rev}^{{commit}}")
            self._sha[rev] = r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else None
        return self._sha[rev]

    def show(self, sha: str, path: str) -> str | None:
        r = self.run("show", f"{sha}:{path}")
        return r.stdout if r.returncode == 0 else None

    def nlines(self, sha: str, path: str) -> int | None:
        key = (sha, path)
        if key not in self._lines:
            text = self.show(sha, path)
            from rw.repo.source import source_lines
            self._lines[key] = None if text is None else len(source_lines(text))
        return self._lines[key]


def expected_citations(q: dict) -> list[dict]:
    return [{"path": c["path"], "start_line": c["start_line"], "end_line": c["end_line"],
             "revision": c.get("revision") or q.get("revision")} for c in q.get("expected_citations", [])]


def allowed_shas(clone: Clone, q: dict) -> set[str]:
    """Requested revision, compare revision and the revisions named by the expected citations."""
    revs = {q.get("revision"), q.get("compare_revision")} | {c["revision"] for c in expected_citations(q)}
    return {s for s in (clone.sha(r) for r in revs if r) if s}


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def check_citation(clone: Clone, c: dict, allowed: set[str], default_rev: str | None) -> dict:
    """{path, start_line, end_line, revision, resolved_sha, valid, requested_revision_match, why}.
    valid: revision resolves in the requested repo, path exists there, 1 <= start <= end <= file length."""
    path = str(c.get("path") or "").strip().removeprefix("./")
    path = path.replace("\\", "/")
    start, end = _int(c.get("start_line")), _int(c.get("end_line"))
    if start is not None and end is None:
        end = start
    rev = c.get("revision") or c.get("commit") or default_rev
    out = {"path": path, "start_line": start, "end_line": end, "revision": rev}
    sha = clone.sha(str(rev)) if rev else None
    out["resolved_sha"] = sha
    why = None
    if sha is None:
        why = "revision does not resolve"
    elif not path:
        why = "no path"
    else:
        n = clone.nlines(sha, path)
        if n is None:
            why = "path absent at revision"
        elif start is None or end is None or not (1 <= start <= end <= max(n, 1)):
            why = f"span {start}-{end} outside file of {n} lines"
    out["valid"] = why is None
    out["requested_revision_match"] = bool(sha and sha in allowed)
    out["why"] = why
    return out


def overlaps(cit: dict, exp: dict, clone: Clone) -> bool:
    if not cit.get("valid") or not cit.get("requested_revision_match"):
        return False
    if cit.get("path") != exp["path"] or not cit.get("resolved_sha"):
        return False
    if cit["resolved_sha"] != clone.sha(exp["revision"]):
        return False
    s, e = cit.get("start_line"), cit.get("end_line")
    if s is None or e is None:
        return False
    return s <= exp["end_line"] and exp["start_line"] <= e


def evidence_scores(cits: list[dict], q: dict, clone: Clone) -> tuple[float | None, float | None]:
    """(recall, precision); empty answerable retrieval earns zeros, not an omitted denominator."""
    exp = expected_citations(q)
    recall = (sum(any(overlaps(c, x, clone) for c in cits) for x in exp) / len(exp)) if exp else None
    precision = (sum(any(overlaps(c, x, clone) for x in exp) for c in cits) / len(cits)) if cits else (0.0 if exp else None)
    return recall, precision


def fabricated(cits: list[dict]) -> list[dict]:
    return [c for c in cits if not c["valid"] or not c["requested_revision_match"]]


def answer_check(q: dict, text: str, cits: list[dict], keys: dict, *, structural: dict | None = None
                 ) -> tuple[bool, str]:
    """Rule-based answer check (evals/repo_eval_keys.json `answer_rule`). Returns (correct, decision)."""
    text = text or ""
    cat = q["category"]
    key = keys["keys"].get(q["id"], {})
    wrong = [c for c in cits if not c["requested_revision_match"]]
    if cat == "ambiguous":
        if structural is not None:
            ok = bool(structural.get("unresolved") or "ambiguous_symbol" in structural.get("gap_kinds", []))
            return ok, "structural: unresolved/ambiguous_symbol gap" + ("" if ok else " absent")
        if re.search(keys["CLARIFY"], text, re.I):
            return True, "asks for clarification (CLARIFY matched)"
        named = [c for c in key.get("candidates", []) if re.search(c, text, re.I)]
        ok = len(named) >= 2
        return ok, f"candidates named: {len(named)} of {len(key.get('candidates', []))}"
    if cat == "missing_evidence":
        fab = fabricated(cits)
        if structural is not None:
            gaps = [g for g in structural.get("gap_kinds", []) if g not in IGNORED_GAPS]
            ok = bool((gaps or structural.get("unresolved")) and not fab)
            return ok, f"structural: gaps={gaps} unresolved={bool(structural.get('unresolved'))} fabricated={len(fab)}"
        absent = bool(re.search(keys["ABSENCE"], text, re.I))
        return absent and not fab, f"absence reported={absent}, fabricated citations={len(fab)}"
    missing = [g for g in key.get("required", []) if not any(re.search(a, text, re.I) for a in g)]
    ok = not missing and not wrong
    why = []
    if missing:
        why.append("missing required facts: " + "; ".join("|".join(g) for g in missing))
    if wrong:
        why.append(f"{len(wrong)} citation(s) at a wrong revision")
    return ok, "all required facts present, no wrong-revision citation" if ok else " / ".join(why)


def grounded(q: dict, correct: bool, recall, cits: list[dict]) -> bool:
    if fabricated(cits):
        return False
    if q["category"] in ("missing_evidence", "ambiguous") and not q.get("expected_citations"):
        return correct and not fabricated(cits)
    return bool(correct and recall == 1.0)


def failed_task(repo: str, q: dict, error: str) -> dict:
    """Keep failed attempts in quality denominators; unavailable measurements remain explicit."""
    applicable = bool(expected_citations(q))
    return {"repo": repo, "question_id": q["id"], "category": q["category"],
            "revision": q.get("revision"), "contestant": "deterministic_retrieval",
            "answer": "", "answer_correct": False, "grounded_answer_correct": False,
            "answer_decision": error, "error": error, "evidence_recall": 0.0 if applicable else None,
            "evidence_precision": 0.0 if applicable else None, "citations": [],
            "citation_validity": None, "wrong_revision": False, "wrong_revision_citations": 0,
            "fabricated_citations": 0, "tokens": 0, "tool_calls": 0, "latency_s": None,
            "context_limit": False, "budget_exhausted": False, "infra_error": True}


def macro_mean(tasks: list[dict], metric: str) -> float | None:
    """Average repeats within each distinct question before averaging questions."""
    groups: dict[tuple, list[float]] = {}
    for t in tasks:
        if t.get(metric) is not None:
            groups.setdefault((t["repo"], t["question_id"]), []).append(float(t[metric]))
    means = [sum(values) / len(values) for values in groups.values()]
    return round(sum(means) / len(means), 4) if means else None


def manifest_for(name: str, revs: set[str]) -> dict:
    clone = Clone(SETS[name][3])
    m = {r: clone.sha(r) for r in sorted(revs) if r and clone.sha(r)}
    return {"repo": name, "path": rel(SETS[name][3]), "revisions": m}


def question_revs(q: dict) -> set[str]:
    return ({q.get("revision"), q.get("compare_revision")} | {c["revision"] for c in expected_citations(q)}) - {None}
