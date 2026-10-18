"""Build the deterministic branchy repository used by evals/repo_questions/branchy_history.json
and by tests/repo/test_s3_revisions.py (fixture `make_branchy_repo`).

Usage: python evals/repo_questions/build_branchy_history.py <target_dir>

Independent of rw.repo: plain `git` only, fixed identity and dates, so commit shas are reproducible.

History (annotated tags in brackets):
  main:   C0 initial [v1.0.0]
          F  "validate amounts" (parse_amount rejects negatives)          -- the fix
          (branch feature/report from F: adds svc/report.py)
          D  README tweak on main
          M  merge feature/report into main (--no-ff, parents [D, feature tip]) [v1.1.0]
          RV git revert F                                                  [v2.0.0]
          RA git revert RV (re-applies F's exact lines)                    [v2.1.0]
          X  modify the fix (new condition/message), git mv svc/helpers.py -> svc/tools.py
             with a small edit, delete svc/legacy.py                       [v2.2.0]
  release-1.x    from v1.0.0: "prepare 1.0.1" (VERSION), cherry-pick -x F [v1.0.1]
  release-legacy from v1.0.0: hand-written, NOT equivalent backport        [v1.0.2]
"""
import os
import subprocess
import sys
from pathlib import Path

VALIDATE_V1 = (
    "def parse_amount(text):\n"          # 1
    "    value = int(text)\n"            # 2
    "    return value\n"                 # 3
)
VALIDATE_FIX = (
    "def parse_amount(text):\n"          # 1
    "    value = int(text)\n"            # 2
    "    if value < 0:\n"                # 3
    "        raise ValueError(\"negative amount\")\n"  # 4
    "    return value\n"                 # 5
)
VALIDATE_LEGACY_BACKPORT = (
    "def parse_amount(text):\n"          # 1
    "    value = int(text)\n"            # 2
    "    if value <= 0:\n"               # 3
    "        raise ValueError(\"bad amount\")\n"  # 4
    "    return value\n"                 # 5
)
VALIDATE_MODIFIED = (
    "def parse_amount(text):\n"          # 1
    "    value = int(text.strip())\n"    # 2
    "    if value < -100:\n"             # 3
    "        raise ValueError(\"amount too small\")\n"  # 4
    "    return value\n"                 # 5
)
HELPERS = (
    "def slugify(text):\n"               # 1
    "    return text.lower().replace(\" \", \"-\")\n"  # 2
    "\n"
    "\n"
    "def titlecase(text):\n"             # 5
    "    return text.title()\n"          # 6
    "\n"
    "\n"
    "def shout(text):\n"                 # 9
    "    return text.upper() + \"!\"\n"  # 10
)
TOOLS = HELPERS.replace("+ \"!\"", "+ \"!!\"")
LEGACY = "def old_api(x):\n    return x * 2\n"
REPORT = (
    "from svc.validate import parse_amount\n"  # 1
    "\n"
    "\n"
    "def summarize(rows):\n"             # 4
    "    return sum(parse_amount(r) for r in rows)\n"  # 5
)
BASE_FILES = {
    "svc/__init__.py": "",
    "svc/validate.py": VALIDATE_V1,
    "svc/helpers.py": HELPERS,
    "svc/legacy.py": LEGACY,
    "README.md": "# Branchy\n",
}


def _git(repo: Path, date: str, *args: str) -> str:
    env = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0",
           "GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date}
    out = subprocess.run(["git", "-c", "user.name=eval", "-c", "user.email=eval@example.com",
                          "-c", "core.autocrlf=false", "-c", "init.defaultBranch=main",
                          "-c", "commit.gpgsign=false", "-c", "tag.gpgsign=false",
                          "-C", str(repo), *args],
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


def _tag(repo: Path, date: str, tag: str) -> None:
    _git(repo, date, "tag", "-a", tag, "-m", f"release {tag}")


def build(target: Path) -> dict:
    """Build the repo; returns {"path": Path, "fix": sha, "revert": sha, "reapply": sha,
    "merge": sha, "pick": sha, "legacy_backport": sha, "feature_tip": sha, "readme": sha,
    "modify": sha}."""
    target = Path(target)
    target.mkdir(parents=True, exist_ok=False)
    d = lambda day: f"2024-05-{day:02d}T00:00:00+00:00"  # noqa: E731
    _git(target, d(1), "init", "-q")
    _write(target, BASE_FILES)
    _commit(target, d(1), "initial")
    _tag(target, d(1), "v1.0.0")

    _write(target, {"svc/validate.py": VALIDATE_FIX})
    fix = _commit(target, d(2), "validate amounts: reject negatives")

    _git(target, d(3), "checkout", "-q", "-b", "feature/report")
    _write(target, {"svc/report.py": REPORT})
    feature_tip = _commit(target, d(3), "add report summary")
    _git(target, d(4), "checkout", "-q", "main")
    _write(target, {"README.md": "# Branchy\n\nAmounts are validated.\n"})
    readme = _commit(target, d(4), "docs: mention validation")
    _git(target, d(5), "merge", "-q", "--no-ff", "-m", "Merge branch 'feature/report'", "feature/report")
    merge = _git(target, d(5), "rev-parse", "HEAD")
    _tag(target, d(5), "v1.1.0")

    _git(target, d(6), "revert", "--no-edit", fix)
    revert = _git(target, d(6), "rev-parse", "HEAD")
    _tag(target, d(6), "v2.0.0")
    _git(target, d(7), "revert", "--no-edit", revert)
    reapply = _git(target, d(7), "rev-parse", "HEAD")
    _tag(target, d(7), "v2.1.0")

    _git(target, d(8), "mv", "svc/helpers.py", "svc/tools.py")
    _write(target, {"svc/tools.py": TOOLS, "svc/validate.py": VALIDATE_MODIFIED})
    (target / "svc/legacy.py").unlink()
    modify = _commit(target, d(8), "loosen validation, rename helpers to tools, drop legacy")
    _tag(target, d(8), "v2.2.0")

    _git(target, d(9), "checkout", "-q", "-b", "release-1.x", "v1.0.0")
    _write(target, {"VERSION": "1.0.1\n"})
    _commit(target, d(9), "prepare 1.0.1")
    _git(target, d(10), "cherry-pick", "-x", fix)
    pick = _git(target, d(10), "rev-parse", "HEAD")
    _tag(target, d(10), "v1.0.1")

    _git(target, d(11), "checkout", "-q", "-b", "release-legacy", "v1.0.0")
    _write(target, {"svc/validate.py": VALIDATE_LEGACY_BACKPORT})
    legacy_backport = _commit(target, d(11), "backport amount validation (adapted)")
    _tag(target, d(11), "v1.0.2")
    _git(target, d(12), "checkout", "-q", "main")
    return {"path": target, "fix": fix, "revert": revert, "reapply": reapply, "merge": merge,
            "pick": pick, "legacy_backport": legacy_backport, "feature_tip": feature_tip,
            "readme": readme, "modify": modify}


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    for k, v in build(Path(sys.argv[1])).items():
        print(k, v)
