"""Build the deterministic repository used by evals/repo_questions/round3/synthetic.json.

Usage: python evals/repo_questions/round3/build_round3_synthetic.py <target_dir>

Independent of rw.repo: plain `git` only, fixed identity and dates, so commit shas are reproducible.
Written for round 3 (after round-2 results were seen); different content from the round-1/round-2
builders and from the test-only fixture in tests/repo/test_s23_round3.py.

History on `main` (annotated tags in brackets):
  C1 initial: inv/errors.py, inv/limits.py, inv/store.py, inv/report.py, inv/csvio.py      [v1.0.0]
  C2 Store.restock added, Store.release + Store.default_zone changed, MAX_ITEMS 100 -> 120,
     inv/report.py deleted, git mv inv/csvio.py -> inv/export.py (+ dump_lines),
     tests/test_store.py added                                                             [v1.1.0]
  FX reject non-positive quantities in Store.restock (#9): adds two lines               (untagged)
  C3 inv/ledger.py (Ledger.record) added, ColdStore.reserve changed, test added             [v1.2.0]
  C4 a comment inserted BETWEEN the two lines FX added; module function audit removed    [v1.3.0]
"""
import os
import subprocess
import sys
from pathlib import Path

ERRORS = ("class OutOfStock(Exception):\n    pass\n\n\n"
          "class TempError(Exception):\n    pass\n")
LIMITS_V1 = ('MAX_ITEMS = 100\n'
             'BATCH = 4 * 25\n'
             'ZONES = ("eu", "us")\n')
LIMITS_V11 = LIMITS_V1.replace("MAX_ITEMS = 100", "MAX_ITEMS = 120")

STORE_HEAD = ("from inv.errors import OutOfStock, TempError\n"
              "from inv.limits import MAX_ITEMS\n\n\n"
              "class Store:\n"
              "    default_zone = \"{zone}\"\n\n"
              "    def __init__(self):\n"
              "        self.items = {{}}\n\n"
              "    def reserve(self, sku, qty):\n"
              "        if self.items.get(sku, 0) < qty:\n"
              "            raise OutOfStock(sku)\n"
              "        self.items[sku] -= qty\n\n")
RELEASE_V1 = ("    def release(self, sku, qty):\n"
              "        self.items[sku] = self.items.get(sku, 0) + qty\n")
RELEASE_V2 = ("    def release(self, sku, qty):\n"
              "        self.items[sku] = min(MAX_ITEMS, self.items.get(sku, 0) + qty)\n")
RESTOCK_HEAD = "\n    def restock(self, sku, qty):\n"
FIX_A = "        if qty <= 0:\n"
FIX_COMMENT = "            # zero or negative restocks are always a caller bug\n"
FIX_B = "            raise ValueError(\"qty must be positive\")\n"
RESTOCK_TAIL = "        self.items[sku] = self.items.get(sku, 0) + qty\n"
COLD_V1 = ("\n\nclass ColdStore(Store):\n"
           "    def reserve(self, sku, qty):\n"
           "        if qty > 10:\n"
           "            raise TempError(sku)\n"
           "        return super().reserve(sku, qty)\n")
COLD_V2 = ("\n\nclass ColdStore(Store):\n"
           "    def reserve(self, sku, qty):\n"
           "        if qty > 10:\n"
           "            raise TempError(sku)\n"
           "        if sku not in self.items:\n"
           "            raise OutOfStock(sku)\n"
           "        return super().reserve(sku, qty)\n")
AUDIT = "\n\ndef audit(store):\n    return sorted(store.items)\n"


def store(zone="eu", release=RELEASE_V1, restock=None, cold=COLD_V1, audit=True):
    text = STORE_HEAD.format(zone=zone) + release
    if restock is not None:
        text += RESTOCK_HEAD + restock + RESTOCK_TAIL
    return text + cold + (AUDIT if audit else "")


REPORT = ("class Report:\n    def render(self, store):\n        return str(store.items)\n\n\n"
          "def summary(store):\n    return Report().render(store)\n")
CSVIO = ("import csv\n\n\n"
         "def dump(rows, fh):\n"
         "    \"\"\"Write rows as CSV; kept unchanged across the rename to export.py.\"\"\"\n"
         "    writer = csv.writer(fh)\n"
         "    for row in rows:\n"
         "        writer.writerow(row)\n")
EXPORT = CSVIO + "\n\ndef dump_lines(rows):\n    return [\",\".join(map(str, r)) for r in rows]\n"
LEDGER = ("class Ledger:\n    def __init__(self):\n        self.entries = []\n\n"
          "    def record(self, sku, qty):\n        self.entries.append((sku, qty))\n")
TEST_STORE = "from inv.store import Store\n\n\ndef test_reserve():\n    assert Store().items == {}\n"
TEST_LEDGER = "from inv.ledger import Ledger\n\n\ndef test_record():\n    assert Ledger().entries == []\n"
CL = "# Changelog\n\n"
S100 = "## 1.0.0\n- first release\n"
S110 = "## 1.1.0\n- restock, csv export renamed, report removed\n\n"
S120 = "## 1.2.0\n- reject non-positive restocks (#9); ledger\n\n"
S130 = "## 1.3.0\n- document restock check; drop audit\n\n"


def _git(repo: Path, date: str, *args: str) -> str:
    env = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0",
           "GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date}
    out = subprocess.run(["git", "-c", "user.name=eval", "-c", "user.email=eval@example.com",
                          "-c", "core.autocrlf=false", "-c", "init.defaultBranch=main",
                          "-c", "commit.gpgsign=false", "-c", "tag.gpgsign=false", "-C", str(repo), *args],
                         env=env, check=True, capture_output=True, text=True)
    return out.stdout.strip()


def _write(repo: Path, files: dict) -> None:
    for rel, text in files.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(text.encode("utf-8"))


def _commit(repo: Path, date: str, msg: str, tag: str | None = None) -> str:
    _git(repo, date, "add", "-A")
    _git(repo, date, "commit", "-q", "-m", msg)
    if tag:
        _git(repo, date, "tag", "-a", tag, "-m", f"release {tag}")
    return _git(repo, date, "rev-parse", "HEAD")


def build(target: Path) -> dict:
    """Returns {"path": Path, "fix": sha}."""
    target = Path(target)
    target.mkdir(parents=True, exist_ok=False)
    d = lambda day: f"2024-10-{day:02d}T00:00:00+00:00"  # noqa: E731
    _git(target, d(1), "init", "-q")
    _write(target, {"inv/__init__.py": "", "inv/errors.py": ERRORS, "inv/limits.py": LIMITS_V1,
                    "inv/store.py": store(), "inv/report.py": REPORT, "inv/csvio.py": CSVIO,
                    "CHANGELOG.md": CL + S100})
    _commit(target, d(1), "first release", "v1.0.0")
    _git(target, d(6), "mv", "inv/csvio.py", "inv/export.py")
    (target / "inv/report.py").unlink()
    _write(target, {"inv/export.py": EXPORT, "inv/limits.py": LIMITS_V11,
                    "inv/store.py": store(zone="us", release=RELEASE_V2, restock=""),
                    "tests/test_store.py": TEST_STORE, "CHANGELOG.md": CL + S110 + S100})
    _commit(target, d(6), "restock, rename csvio to export, drop report", "v1.1.0")
    _write(target, {"inv/store.py": store(zone="us", release=RELEASE_V2, restock=FIX_A + FIX_B)})
    fix = _commit(target, d(9), "reject non-positive restock quantities (#9)")
    _write(target, {"inv/store.py": store(zone="us", release=RELEASE_V2, restock=FIX_A + FIX_B, cold=COLD_V2),
                    "inv/ledger.py": LEDGER, "tests/test_ledger.py": TEST_LEDGER,
                    "CHANGELOG.md": CL + S120 + S110 + S100})
    _commit(target, d(12), "ledger, cold store stock check", "v1.2.0")
    _write(target, {"inv/store.py": store(zone="us", release=RELEASE_V2, restock=FIX_A + FIX_COMMENT + FIX_B,
                                          cold=COLD_V2, audit=False),
                    "CHANGELOG.md": CL + S130 + S120 + S110 + S100})
    _commit(target, d(15), "document the restock check, drop audit", "v1.3.0")
    return {"path": target, "fix": fix}


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    for k, v in build(Path(sys.argv[1])).items():
        print(k, v)
