"""Independent source/Git inventory. Never imports or executes corpus code."""
import ast
import hashlib
import json
import pathlib
import subprocess
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[2]
BASE = ROOT / "artifacts/confirmatory"
REPOS = {
    "requests": (ROOT / "artifacts/repos/requests", ["v2.10.0", "v2.20.0", "v2.31.0", "v2.32.3", "v2.32.5"]),
    "click": (BASE / "repos/click", ["6.7", "7.1.2", "8.1.7", "8.2.1", "8.3.0"]),
}

def git(repo, *args):
    return subprocess.check_output(["git", f"--git-dir={REPOS[repo][0]}", *args])

def source_path(path):
    roots = ("requests/", "src/requests/", "click/", "src/click/")
    return path.endswith(".py") and path.startswith(roots) and not path.startswith("requests/packages/")

def included(path):
    return source_path(path) or path in ("HISTORY.rst", "HISTORY.md", "CHANGES.rst", "CHANGES.md", "CHANGELOG.rst", "CHANGELOG.md", "pyproject.toml", "setup.py", "setup.cfg")

def main():
    manifest = {"version": "draft-v1", "status": "DRAFT", "created_at": datetime.now(timezone.utc).isoformat(), "author": "Independent Codex AI evaluator; no human review asserted", "repositories": {}}
    for repo, (repo_path, refs) in REPOS.items():
        snapshots = []
        for ref in refs:
            sha = git(repo, "rev-parse", f"{ref}^{{commit}}").decode().strip()
            tree = git(repo, "ls-tree", "-r", "--long", sha).decode().splitlines()
            files = []
            symbols = []
            for item in tree:
                left, path = item.split("\t", 1)
                mode, typ, blob, size = left.split()
                if not included(path):
                    continue
                raw = git(repo, "cat-file", "blob", blob)
                files.append({"path": path, "git_blob": blob, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(), "lines": len(raw.splitlines()), "python_production": source_path(path)})
                if source_path(path):
                    try:
                        parsed = ast.parse(raw)
                    except (SyntaxError, UnicodeError) as exc:
                        symbols.append({"path": path, "parse_error": str(exc)})
                        continue
                    def walk(node, prefix=""):
                        for child in ast.iter_child_nodes(node):
                            if isinstance(child, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                                qualname = prefix + child.name
                                symbols.append({"path": path, "qualname": qualname, "line": child.lineno, "end": child.end_lineno, "kind": type(child).__name__})
                                walk(child, qualname + ".")
                            else:
                                walk(child, prefix)
                    walk(parsed)
            snapshots.append({"ref": ref, "commit": sha, "tree": git(repo, "rev-parse", f"{sha}^{{tree}}").decode().strip(), "tracked_files": len(tree), "included_files": files, "included_bytes": sum(f["bytes"] for f in files), "symbols": len([s for s in symbols if "qualname" in s]), "parse_gaps": [s for s in symbols if "parse_error" in s]})
            out = BASE / "sealed" / f"{repo}-{ref}-symbols.json"
            out.write_text(json.dumps(symbols, indent=2) + "\n")
        shas = [s["commit"] for s in snapshots]
        commits = git(repo, "rev-list", "--parents", *shas)
        tags = git(repo, "for-each-ref", "--format=%(refname) %(objectname) %(*objectname)", "refs/tags")
        (BASE / "provenance" / f"{repo}-parents.txt").write_bytes(commits)
        (BASE / "provenance" / f"{repo}-tags.txt").write_bytes(tags)
        manifest["repositories"][repo] = {"origin": git(repo, "remote", "get-url", "origin").decode().strip(), "bare_path": str(repo_path.relative_to(ROOT)), "ancestry_commit_count": len(commits.splitlines()), "available_tag_count": len(tags.splitlines()), "snapshots": snapshots}
    out = ROOT / "evals/confirmatory/corpus.draft-v1.json"
    out.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(json.dumps({r: {"commits": m["ancestry_commit_count"], "tags": m["available_tag_count"], "snapshots": [{"ref": s["ref"], "files": len(s["included_files"]), "bytes": s["included_bytes"], "symbols": s["symbols"], "parse_gaps": len(s["parse_gaps"])} for s in m["snapshots"]]} for r,m in manifest["repositories"].items()}, indent=2))

if __name__ == "__main__":
    main()
