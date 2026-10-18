"""Export a pinned, source-only corpus without checkout or repository execution.

This is evaluation infrastructure, not an answer oracle or a token estimator.
Only explicit immutable roots and path rules are accepted. Output is deterministic
JSONL containing complete tree membership, raw commit/tag objects, and each
included regular-file blob once. No questions, scoring files, or provider keys
are read. An exporter receipt is not an acceptance-gate result.
"""
from __future__ import annotations

import argparse
import base64
import fnmatch
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from rw.repo.git import GitRepo  # noqa: E402


def canonical(value: object) -> bytes:
    # ASCII escaping preserves even non-UTF8 Git paths via surrogateescape.
    return (json.dumps(value, sort_keys=True, ensure_ascii=True,
                       separators=(",", ":"), allow_nan=False) + "\n").encode("ascii")


def encoded(data: bytes) -> dict:
    try:
        return {"encoding": "utf-8", "content": data.decode("utf-8")}
    except UnicodeDecodeError:
        return {"encoding": "base64", "content": base64.b64encode(data).decode("ascii")}


def object_id(kind: str, data: bytes, algorithm: str) -> str:
    return hashlib.new(algorithm, f"{kind} {len(data)}\0".encode() + data).hexdigest()


def validate_spec(spec: dict, algorithm: str) -> dict:
    required = {"schema", "repository", "roots", "include", "exclude"}
    if set(spec) != required or spec["schema"] != "source-corpus-spec/v1":
        raise ValueError("spec requires exactly schema, repository, roots, include, exclude")
    if not isinstance(spec["repository"], str) or not spec["repository"].strip():
        raise ValueError("repository must be a nonempty public identifier")
    length = {"sha1": 40, "sha256": 64}.get(algorithm)
    if length is None:
        raise ValueError("unsupported Git object format")
    roots = spec["roots"]
    if not isinstance(roots, list) or not roots or any(
        not isinstance(x, str) or not re.fullmatch(f"[0-9a-f]{{{length}}}", x) for x in roots
    ):
        raise ValueError("roots must be nonempty full immutable commit object IDs")
    for key in ("include", "exclude"):
        if not isinstance(spec[key], list) or any(
            not isinstance(x, str) or not x or "\0" in x for x in spec[key]
        ):
            raise ValueError(f"{key} must be a list of nonempty path patterns")
    if not spec["include"]:
        raise ValueError("include rules cannot be empty")
    return {**spec, "roots": sorted(set(roots)), "include": sorted(set(spec["include"])),
            "exclude": sorted(set(spec["exclude"]))}


def classification(path: str, mode: str, kind: str, spec: dict) -> str:
    # Never dereference symlinks, descend into submodules, or treat their IDs as blobs.
    if mode == "040000" and kind == "tree":
        return "directory_metadata"
    if mode == "120000":
        return "symlink_not_followed"
    if mode == "160000" or kind == "commit":
        return "submodule_not_fetched"
    if kind != "blob" or mode not in {"100644", "100755"}:
        return "unsupported_mode"
    if any(fnmatch.fnmatchcase(path, p) for p in spec["exclude"]):
        return "excluded_by_rule"
    if not any(fnmatch.fnmatchcase(path, p) for p in spec["include"]):
        return "outside_include_rules"
    return "included"


def export_corpus(repo_path: Path, spec: dict, output: Path) -> dict:
    """Write a new export directory. Failed attempts remain there, never overwritten."""
    git = GitRepo(repo_path)
    algorithm = git._text("rev-parse", "--show-object-format").strip()
    spec = validate_spec(spec, algorithm)
    if git._text("rev-parse", "--is-shallow-repository").strip() != "false":
        raise ValueError("shallow history cannot establish the declared complete ancestor corpus")
    for root in spec["roots"]:
        if git.resolve(root) != root:
            raise ValueError("every root must identify a commit directly, not a tag object")
    output.mkdir(parents=True, exist_ok=False)
    (output / "spec.json").write_bytes(canonical(spec))
    receipt = {"schema": "source-corpus-export/v1", "status": "STARTED",
               "acceptance_validated": False, "tokens": None,
               "token_status": "PENDING_EXACT_MODEL_TOKENIZER",
               "spec_sha256": hashlib.sha256(canonical(spec)).hexdigest(),
               "object_format": algorithm,
               "serialization": "Canonical ASCII JSONL; unique flattened trees, raw commit/tag objects, included unique blobs",
               "path_rules": "fnmatchcase on repository-relative full paths; * may cross /; exclude wins",
               "limitations": ["No syntax, dependency, runtime, or answer-quality claim",
                               "Excluded-file content, symlink targets, and submodule content are unavailable",
                               "Byte counts are not model token counts"]}
    receipt_path = output / "receipt.json"
    receipt_path.write_bytes(canonical(receipt))
    try:
        counts = Counter()
        commits = sorted(set(git._text("rev-list", *spec["roots"], "--").split()))
        commit_set = set(commits)
        trees: set[str] = set()
        blobs: set[str] = set()
        digest = hashlib.sha256()
        byte_count = 0
        with (output / "corpus.jsonl").open("xb") as stream:
            def write(record):
                nonlocal byte_count
                data = canonical(record)
                stream.write(data)
                digest.update(data)
                byte_count += len(data)
                counts["records"] += 1

            write({"kind": "header", "schema": "source-corpus/v1", "spec": spec,
                   "object_format": algorithm})
            for sha in commits:
                raw = git._bytes("cat-file", "commit", sha)
                if object_id("commit", raw, algorithm) != sha:
                    raise ValueError("commit object hash mismatch")
                headers = raw.split(b"\n\n", 1)[0].splitlines()
                tree = next(x[5:].decode("ascii") for x in headers if x.startswith(b"tree "))
                parents = [x[7:].decode("ascii") for x in headers if x.startswith(b"parent ")]
                if any(p not in commit_set for p in parents):
                    raise ValueError("missing ancestor in declared complete corpus")
                trees.add(tree)
                write({"kind": "commit", "oid": sha, "tree": tree, "parents": parents,
                       "bytes": len(raw), **encoded(raw)})
                counts["raw_commit_bytes"] += len(raw)
            # Every historical path membership is retained, including repeated bytes
            # at different paths and paths excluded from content retrieval.
            for tree in sorted(trees):
                entries = []
                raw = git._bytes("ls-tree", "-r", "-t", "-z", "--full-tree", tree)
                for entry in raw.split(b"\0"):
                    if not entry:
                        continue
                    meta, path_bytes = entry.split(b"\t", 1)
                    mode, kind, oid = meta.decode("ascii").split()
                    path = path_bytes.decode("utf-8", "surrogateescape")
                    scope = classification(path, mode, kind, spec)
                    entries.append({"path": path, "mode": mode, "type": kind,
                                    "oid": oid, "coverage": scope})
                    counts[f"memberships/{scope}"] += 1
                    if scope == "included":
                        blobs.add(oid)
                write({"kind": "tree", "oid": tree,
                       "entries": sorted(entries, key=lambda x: x["path"])})
            for sha in sorted(blobs):
                raw = git.blob(sha)
                if object_id("blob", raw, algorithm) != sha:
                    raise ValueError("blob object hash mismatch")
                write({"kind": "blob", "oid": sha, "bytes": len(raw),
                       "sha256": hashlib.sha256(raw).hexdigest(), **encoded(raw)})
                counts["included_unique_blob_bytes"] += len(raw)
            # Freeze eligible ref names and raw annotated tags. Resolve object IDs,
            # never a ref a second time, so concurrent ref moves cannot mix targets.
            raw_refs = git._bytes("for-each-ref", "refs/heads", "refs/tags",
                                  "--format=%(refname)%00%(objectname)%00%(objecttype)")
            for line in raw_refs.splitlines():
                ref, oid_bytes, kind = line.split(b"\0")
                oid = oid_bytes.decode("ascii")
                tag_chain = []
                while kind == b"tag":
                    raw = git._bytes("cat-file", "tag", oid)
                    if object_id("tag", raw, algorithm) != oid:
                        raise ValueError("tag object hash mismatch")
                    tag_chain.append({"oid": oid, **encoded(raw)})
                    lines = raw.split(b"\n\n", 1)[0].splitlines()
                    oid = next(x[7:].decode("ascii") for x in lines if x.startswith(b"object "))
                    kind = next(x[5:] for x in lines if x.startswith(b"type "))
                if kind != b"commit":
                    counts["refs_not_commits"] += 1
                    continue
                target = oid
                if target not in commit_set:
                    counts["refs_outside_corpus"] += 1
                    continue
                write({"kind": "ref", "name": ref.decode("utf-8", "surrogateescape"),
                       "oid": oid_bytes.decode("ascii"), "target": target, "tag_chain": tag_chain})
                counts["included_refs"] += 1
        receipt.update(status="COMPLETE", corpus_sha256=digest.hexdigest(),
                       serialized_bytes=byte_count, commits=len(commits), unique_trees=len(trees),
                       included_unique_blobs=len(blobs), counts=dict(sorted(counts.items())))
        receipt_path.write_bytes(canonical(receipt))
        return receipt
    except BaseException as exc:
        receipt.update(status="FAILED", error_type=type(exc).__name__)
        receipt_path.write_bytes(canonical(receipt))
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    receipt = export_corpus(args.repo, json.loads(args.spec.read_text()), args.output)
    # Deliberately no source snippets on stdout.
    print(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    main()
