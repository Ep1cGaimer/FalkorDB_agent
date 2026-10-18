"""Build the deterministic repository used by evals/repo_questions/round2/synthetic.json.

Usage: python evals/repo_questions/round2/build_round2_synthetic.py <target_dir>

Independent of rw.repo: plain `git` only, fixed identity and dates, so commit shas are reproducible.
Written for round 2 (after round-1 results were seen); deliberately different content from the
round-1 builders and from the test-only fixture in tests/repo/test_s23_round2.py.

History on `main` (annotated tags in brackets):
  C1 initial: ship/limits.py constants, ship/errors.py, ship/quote.py, ship/fmt.py   [v1.0.0]
  C2 raise MAX_WEIGHT_KG to 35, add "fedex" carrier, add ship/track.py               [v1.1.0]
  FX reject negative weights in check_weight (#3)                                     (untagged)
  DC docs: README                                                                     (untagged)
  C3 changelog for 1.2.0                                                              [v1.2.0]
  C4 git mv ship/fmt.py -> ship/labels.py (+ new function short), delete ship/track.py [v1.3.0]
  C5 drop the negative-weight check again (hand edit, not a git revert)               [v1.4.0]
"""
import os
import subprocess
import sys
from pathlib import Path

LIMITS_V1 = ('MAX_WEIGHT_KG = 30\n'
             'CARRIERS = ("dhl", "ups")\n'
             'RETRY_DELAYS = [1, 2, 4]\n'
             'TIMEOUT_S = 2 * 5\n')
LIMITS_V11 = LIMITS_V1.replace("= 30", "= 35").replace('("dhl", "ups")', '("dhl", "ups", "fedex")')
ERRORS = ("class ShipError(Exception):\n    pass\n\n\n"
          "class OverweightError(ShipError):\n    pass\n")
QUOTE_HEAD = ("from ship.errors import OverweightError, ShipError\n"
              "from ship.limits import CARRIERS, MAX_WEIGHT_KG\n\n\n"
              "def check_weight(kg):\n")
QUOTE_FIX = '    if kg < 0:\n        raise ValueError("negative weight")\n'
QUOTE_TAIL = ("    if kg > MAX_WEIGHT_KG:\n        raise OverweightError(kg)\n    return kg\n\n\n"
              "def quote(carrier, kg):\n    if carrier not in CARRIERS:\n"
              '        raise ShipError("unknown carrier")\n    return check_weight(kg) * 2\n')
QUOTE_V1 = QUOTE_HEAD + QUOTE_TAIL
QUOTE_FIXED = QUOTE_HEAD + QUOTE_FIX + QUOTE_TAIL
FMT = "def label(text):\n    return text.upper()\n"
LABELS = FMT + "\n\ndef short(text):\n    return text[:8]\n"
TRACK = "def track(code):\n    if not code:\n        raise KeyError(code)\n    return code\n"
CL = "# Changelog\n\n"
S100 = "## 1.0.0\n- first release\n"
S110 = "## 1.1.0\n- max weight 35 kg, fedex carrier, tracking\n\n"
S120 = "## 1.2.0\n- reject negative weights (#3)\n\n"
S130 = "## 1.3.0\n- rename ship/fmt.py to ship/labels.py, add short(); remove tracking\n\n"
S140 = "## 1.4.0\n- simplify check_weight\n\n"


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


def _commit(repo: Path, date: str, msg: str) -> str:
    _git(repo, date, "add", "-A")
    _git(repo, date, "commit", "-q", "-m", msg)
    return _git(repo, date, "rev-parse", "HEAD")


def build(target: Path) -> dict:
    """Returns {"path": Path, "fix": sha, "drop_fix": sha}."""
    target = Path(target)
    target.mkdir(parents=True, exist_ok=False)
    d = lambda day: f"2024-06-{day:02d}T00:00:00+00:00"  # noqa: E731
    _git(target, d(1), "init", "-q")
    _write(target, {"ship/__init__.py": "", "ship/limits.py": LIMITS_V1, "ship/errors.py": ERRORS,
                    "ship/quote.py": QUOTE_V1, "ship/fmt.py": FMT, "CHANGELOG.md": CL + S100})
    _commit(target, d(1), "first release")
    _git(target, d(1), "tag", "-a", "v1.0.0", "-m", "release v1.0.0")
    _write(target, {"ship/limits.py": LIMITS_V11, "ship/track.py": TRACK, "CHANGELOG.md": CL + S110 + S100})
    _commit(target, d(10), "heavier parcels, fedex, tracking")
    _git(target, d(10), "tag", "-a", "v1.1.0", "-m", "release v1.1.0")
    _write(target, {"ship/quote.py": QUOTE_FIXED})
    fix = _commit(target, d(15), "reject negative weights (#3)")
    _write(target, {"README.md": "# ship\n"})
    _commit(target, d(18), "docs: README")
    _write(target, {"CHANGELOG.md": CL + S120 + S110 + S100})
    _commit(target, d(20), "changelog 1.2.0")
    _git(target, d(20), "tag", "-a", "v1.2.0", "-m", "release v1.2.0")
    _git(target, d(25), "mv", "ship/fmt.py", "ship/labels.py")
    (target / "ship/track.py").unlink()
    _write(target, {"ship/labels.py": LABELS, "CHANGELOG.md": CL + S130 + S120 + S110 + S100})
    _commit(target, d(25), "rename fmt to labels, add short, drop tracking")
    _git(target, d(25), "tag", "-a", "v1.3.0", "-m", "release v1.3.0")
    _write(target, {"ship/quote.py": QUOTE_V1, "CHANGELOG.md": CL + S140 + S130 + S120 + S110 + S100})
    drop = _commit(target, d(28), "simplify check_weight")
    _git(target, d(28), "tag", "-a", "v1.4.0", "-m", "release v1.4.0")
    return {"path": target, "fix": fix, "drop_fix": drop}


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    for k, v in build(Path(sys.argv[1])).items():
        print(k, v)
