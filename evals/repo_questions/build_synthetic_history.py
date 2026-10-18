"""Build the deterministic synthetic repository used by evals/repo_questions/synthetic_history.json.

Usage: python evals/repo_questions/build_synthetic_history.py <target_dir>

Independent of rw.repo: plain `git` only, fixed author/committer identity and dates, so commit shas
are reproducible. Tags (annotated): v1.0.0, v1.1.0, v1.2.0, v1.3.0, all on `main`.
"""
import os
import subprocess
import sys
from pathlib import Path

CHANGELOG_HEAD = "# Changelog\n\n"
SEC_100 = "## 1.0.0\n- first release\n"
SEC_110 = "## 1.1.0\n- fix rounding of taxed totals (#7)\n\n"
SEC_120 = "## 1.2.0\n- add team plan to rates\n- add billing/discount.py with discounted()\n\n"
SEC_130 = "## 1.3.0\n- update VAT rate to 25%\n\n"

RELEASES = [
    ("v1.0.0", "2024-03-01T00:00:00+00:00", "first release", {
        "billing/__init__.py": "",
        "billing/rates.py": 'def base_rate(plan):\n    return {"free": 0, "pro": 10}[plan]\n',
        "billing/tax.py": "def apply_tax(amount):\n    return amount * 1.2\n",
        "billing/invoice.py": ("from billing.rates import base_rate\nfrom billing.tax import apply_tax\n\n\n"
                               "def total(plan):\n    return apply_tax(base_rate(plan))\n"),
        "billing/cli.py": ("import click\nfrom billing.invoice import total\n\n\n"
                           "def main(plan):\n    return total(plan)\n"),
        "CHANGELOG.md": CHANGELOG_HEAD + SEC_100,
    }, []),
    ("v1.1.0", "2024-03-10T00:00:00+00:00", "fix tax rounding (#7)", {
        "billing/tax.py": ("def round_cents(value):\n    return round(value, 2)\n\n\n"
                           "def apply_tax(amount):\n    return round_cents(amount * 1.2)\n"),
        "CHANGELOG.md": CHANGELOG_HEAD + SEC_110 + SEC_100,
    }, []),
    ("v1.2.0", "2024-03-20T00:00:00+00:00", "add team plan and discounts", {
        "billing/rates.py": 'def base_rate(plan):\n    return {"free": 0, "pro": 10, "team": 25}[plan]\n',
        "billing/discount.py": ("from billing.rates import base_rate\n\n\n"
                                "def discounted(plan, pct):\n    return base_rate(plan) * (1 - pct)\n"),
        "CHANGELOG.md": CHANGELOG_HEAD + SEC_120 + SEC_110 + SEC_100,
    }, []),
    ("v1.3.0", "2024-04-01T00:00:00+00:00", "update VAT rate", {
        "billing/tax.py": "def apply_tax(amount):\n    return amount * 1.25\n",
        "CHANGELOG.md": CHANGELOG_HEAD + SEC_130 + SEC_120 + SEC_110 + SEC_100,
    }, []),
]


def _git(repo: Path, date: str, *args: str) -> None:
    env = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0",
           "GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date}
    subprocess.run(["git", "-c", "user.name=eval", "-c", "user.email=eval@example.com",
                    "-c", "core.autocrlf=false", "-c", "init.defaultBranch=main",
                    "-c", "commit.gpgsign=false", "-c", "tag.gpgsign=false", "-C", str(repo), *args],
                   env=env, check=True, capture_output=True)


def build(target: Path) -> Path:
    target = Path(target)
    target.mkdir(parents=True, exist_ok=False)
    _git(target, RELEASES[0][1], "init", "-q")
    for tag, date, msg, files, deletions in RELEASES:
        for rel, text in files.items():
            p = target / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(text.encode("utf-8"))
        for rel in deletions:
            (target / rel).unlink()
        _git(target, date, "add", "-A")
        _git(target, date, "commit", "-q", "-m", msg)
        _git(target, date, "tag", "-a", tag, "-m", f"release {tag}")
    return target


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    print(build(Path(sys.argv[1])))
