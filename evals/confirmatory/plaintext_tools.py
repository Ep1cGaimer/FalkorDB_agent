"""Iterative plaintext/history tools over one hashed source-only export.

The baseline can search, follow source spans, inspect commits and diffs, and
compare ancestry. It has no graph, oracle, filesystem read, checkout, shell, or
network tool. Loading the explicitly supplied export is its only filesystem I/O.
This module makes no quality, efficiency, or acceptance claim.
"""
from __future__ import annotations

import base64
import codecs
import difflib
import hashlib
import json
import re
from pathlib import Path

from .corpus_export import canonical, classification, object_id, validate_spec
from .tool_budget import ToolBudgetExceeded, bounded_tool, checkpoint  # public exception for callers


class CorpusError(ValueError):
    pass


def lf_lines(text):
    """Physical source lines: LF only; preserve CR and all Unicode separators."""
    start = 0
    while start < len(text):
        end = text.find("\n", start)
        end = len(text) if end < 0 else end + 1
        yield text[start:end]
        start = end


def decoded_object(row):
    raw = PlaintextTools._raw(row)
    headers = raw.split(b"\n\n", 1)[0].split(b"\n")
    names = [x[9:] for x in headers if x.startswith(b"encoding ")]
    try:
        if len(names) > 1 or (names and len(names[0]) > 128):
            raise ValueError("invalid encoding header")
        name = names[0].decode("ascii") if names else "utf-8"
        codec = codecs.lookup(name)
        if not codec._is_text_encoding:
            raise ValueError("not a text encoding")
        return {"decoded_text": raw.decode(name, "strict"), "text_encoding": name,
                "text_gap": None}
    except (LookupError, UnicodeError, ValueError, TypeError):
        return {"decoded_text": None, "text_encoding": "unsupported_or_invalid",
                "text_gap": "raw_object_text_not_decodable; inspect retained raw bytes"}


def flattened_tree_id(entries: list[dict], algorithm: str) -> str:
    """Reconstruct raw nested Git tree hashes from complete flattened membership."""
    root = {}
    for entry in entries:
        parts = entry["path"].split("/")
        if any(p in {"", ".", ".."} for p in parts):
            raise CorpusError("invalid tree path")
        node = root
        for part in parts[:-1]:
            node = node.setdefault(part, {})
            if not isinstance(node, dict):
                raise CorpusError("tree path collision")
        if entry["type"] == "tree" and entry["mode"] == "040000":
            previous = node.setdefault(parts[-1], {})
            if not isinstance(previous, dict):
                raise CorpusError("tree path collision")
            continue
        if parts[-1] in node:
            raise CorpusError("duplicate tree path")
        node[parts[-1]] = (entry["mode"], entry["oid"])

    def tree_hash(node):
        content = bytearray()
        # Git compares a directory name as though followed by '/'.
        for name, value in sorted(node.items(), key=lambda pair:
                                  pair[0].encode("utf8", "surrogateescape") +
                                  (b"/" if isinstance(pair[1], dict) else b"")):
            mode, oid = ("40000", tree_hash(value)) if isinstance(value, dict) else value
            content.extend(mode.lstrip("0").encode("ascii") + b" " +
                           name.encode("utf8", "surrogateescape") + b"\0" + bytes.fromhex(oid))
        return object_id("tree", bytes(content), algorithm)
    return tree_hash(root)


class PlaintextTools:
    def __init__(self, export_dir: Path):
        receipt = json.loads((export_dir / "receipt.json").read_bytes())
        data = (export_dir / "corpus.jsonl").read_bytes()
        self.corpus_hash = hashlib.sha256(data).hexdigest()
        if receipt.get("status") != "COMPLETE" or receipt.get("corpus_sha256") != self.corpus_hash:
            raise CorpusError("export incomplete or corpus hash mismatch")
        self.commits, self.trees, self.blobs, self.refs = {}, {}, {}, {}
        self.ref_records = {}
        rows = iter(data.splitlines())
        header = json.loads(next(rows))
        if header.get("schema") != "source-corpus/v1" or header.get("kind") != "header":
            raise CorpusError("unsupported corpus serialization")
        self.repository = header["spec"]["repository"]
        self.algorithm = header["object_format"]
        self.spec = validate_spec(header["spec"], self.algorithm)
        if hashlib.sha256(canonical(self.spec)).hexdigest() != receipt.get("spec_sha256"):
            raise CorpusError("corpus specification hash mismatch")
        for line in rows:
            row = json.loads(line)
            kind = row.get("kind")
            if kind in {"commit", "blob"}:
                raw = self._raw(row)
                if object_id(kind, raw, self.algorithm) != row["oid"] or len(raw) != row["bytes"]:
                    raise CorpusError("object digest or size mismatch")
                if kind == "blob" and hashlib.sha256(raw).hexdigest() != row["sha256"]:
                    raise CorpusError("blob SHA256 mismatch")
            if kind == "commit":
                headers = raw.split(b"\n\n", 1)[0].splitlines()
                trees = [x[5:].decode("ascii") for x in headers if x.startswith(b"tree ")]
                parents = [x[7:].decode("ascii") for x in headers if x.startswith(b"parent ")]
                if trees != [row["tree"]] or parents != row["parents"]:
                    raise CorpusError("commit metadata disagrees with immutable object")
                self._insert(self.commits, row["oid"], row)
            elif kind == "tree":
                if flattened_tree_id(row["entries"], self.algorithm) != row["oid"]:
                    raise CorpusError("historical file membership disagrees with immutable tree")
                entries = {e["path"]: e for e in row["entries"]}
                if any(e["coverage"] != classification(e["path"], e["mode"], e["type"], self.spec)
                       for e in row["entries"]):
                    raise CorpusError("file coverage disagrees with declared corpus rules")
                if len(entries) != len(row["entries"]):
                    raise CorpusError("duplicate tree path")
                self._insert(self.trees, row["oid"], entries)
            elif kind == "blob":
                self._insert(self.blobs, row["oid"], row)
            elif kind == "ref":
                current = row["oid"]
                for tag in row["tag_chain"]:
                    raw = self._raw(tag)
                    if tag["oid"] != current or object_id("tag", raw, self.algorithm) != current:
                        raise CorpusError("tag chain disagrees with immutable object")
                    headers = raw.split(b"\n\n", 1)[0].split(b"\n")
                    current = next(x[7:].decode("ascii") for x in headers if x.startswith(b"object "))
                if current != row["target"]:
                    raise CorpusError("tag target disagrees with immutable chain")
                self._insert(self.refs, row["name"], row["target"])
                self._insert(self.ref_records, row["name"], row)
            else:
                raise CorpusError("unknown corpus record")
        for row in self.commits.values():
            if row["tree"] not in self.trees or any(p not in self.commits for p in row["parents"]):
                raise CorpusError("missing historical tree or parent")
        if any(target not in self.commits for target in self.refs.values()):
            raise CorpusError("ref target outside declared corpus")
        reachable, pending = set(), list(self.spec["roots"])
        while pending:
            sha = pending.pop()
            if sha in reachable:
                continue
            if sha not in self.commits:
                raise CorpusError("declared root or ancestor absent from corpus")
            reachable.add(sha)
            pending.extend(self.commits[sha]["parents"])
        if reachable != set(self.commits):
            raise CorpusError("unreachable extra commits outside declared roots")
        for entries in self.trees.values():
            for e in entries.values():
                if e["coverage"] == "included" and e["oid"] not in self.blobs:
                    raise CorpusError("missing included source blob")

    @staticmethod
    def _insert(mapping, key, value):
        if key in mapping:
            raise CorpusError("duplicate logical record")
        mapping[key] = value

    @staticmethod
    def _raw(row):
        if row["encoding"] == "utf-8":
            return row["content"].encode("utf-8")
        if row["encoding"] == "base64":
            return base64.b64decode(row["content"], validate=True)
        raise CorpusError("unknown content encoding")

    @bounded_tool
    def resolve(self, revision: str) -> str:
        if not isinstance(revision, str) or not revision:
            raise CorpusError("revision required")
        checkpoint(work_units=len(self.commits) if re.fullmatch("[0-9a-f]{7,64}", revision) else 1)
        candidates = {self.refs[r] for r in (revision, "refs/tags/" + revision, "refs/heads/" + revision)
                      if r in self.refs}
        if revision in self.commits:
            candidates.add(revision)
        elif re.fullmatch("[0-9a-f]{7,64}", revision):
            candidates.update(s for s in self.commits if s.startswith(revision))
        if len(candidates) != 1:
            raise CorpusError("missing or ambiguous revision in pinned corpus")
        return candidates.pop()

    def _tree(self, revision):
        sha = self.resolve(revision)
        return sha, self.trees[self.commits[sha]["tree"]]

    def _page(self, items, *, scope, limit, cursor):
        if type(limit) is not int or not 1 <= limit <= 100:
            raise CorpusError("limit must be an integer from 1 to 100")
        binding = hashlib.sha256(canonical([self.corpus_hash, scope])).hexdigest()
        offset = 0
        if cursor is not None:
            try:
                if not isinstance(cursor, str) or len(cursor) > 1024:
                    raise ValueError()
                value = json.loads(base64.b64decode(cursor, altchars=b"-_", validate=True))
                offset = value["offset"]
                if value["binding"] != binding or type(offset) is not int or not 0 <= offset < len(items):
                    raise ValueError()
            except (ValueError, TypeError, KeyError):
                raise CorpusError("invalid cursor for corpus/revision/query") from None
        end = offset + limit
        next_cursor = base64.urlsafe_b64encode(canonical({"binding": binding, "offset": end})).decode() if end < len(items) else None
        return {"repository": self.repository, "corpus_sha256": self.corpus_hash,
                "items": items[offset:end], "total": len(items), "next_cursor": next_cursor,
                "truncated": next_cursor is not None, "complete": next_cursor is None}

    @bounded_tool
    def list_files(self, revision: str, *, prefix: str = "", limit: int = 20, cursor=None):
        sha, entries = self._tree(revision)
        checkpoint(work_units=len(entries))
        items = [{**e, **({"content_hash": self.blobs[e["oid"]]["sha256"]}
                         if e["coverage"] == "included" else {})}
                 for p, e in sorted(entries.items()) if p.startswith(prefix) and e["type"] != "tree"]
        return {"commit": sha, **self._page(items, scope=["files", sha, prefix], limit=limit, cursor=cursor)}

    def _source(self, entries, path):
        if path not in entries:
            raise CorpusError("path absent at selected revision")
        entry = entries[path]
        if entry["coverage"] != "included":
            raise CorpusError("source unavailable: " + entry["coverage"])
        blob = self.blobs[entry["oid"]]
        if blob["encoding"] != "utf-8":
            raise CorpusError("source unavailable: non-UTF8 content")
        return blob

    def _citation(self, sha, path, blob, start, end):
        return {"repository": self.repository, "commit": sha, "path": path,
                "start_line": start, "end_line": end, "content_hash": blob["sha256"],
                "git_blob": blob["oid"], "provenance": "raw Git source; no parsed dependency inference"}

    @bounded_tool
    def read_file(self, revision: str, path: str, *, start: int = 1, end: int | None = None):
        sha, entries = self._tree(revision)
        if end is None and type(start) is int:
            end = start + 99
        if type(start) is not int or type(end) is not int or start < 1 or end < start or end - start >= 200:
            raise CorpusError("read spans require 1-based inclusive lines, at most 200 per call")
        blob = self._source(entries, path)
        checkpoint(source_bytes=blob["bytes"])
        lines = []
        for line in lf_lines(blob["content"]):
            checkpoint()
            lines.append(line)
        if not lines and start == 1:
            return {"citation": {"proof_type": "file_membership", "repository": self.repository,
                                 "commit": sha, "path": path, "git_blob": blob["oid"],
                                 "content_hash": blob["sha256"]},
                    "content": "", "total_lines": 0, "next_line": None, "complete_file": True}
        if start > len(lines):
            raise CorpusError("start line beyond source (including empty file)")
        actual_end = min(end, len(lines))
        return {"citation": self._citation(sha, path, blob, start, actual_end),
                "content": "".join(lines[start - 1:actual_end]), "total_lines": len(lines),
                "next_line": actual_end + 1 if actual_end < len(lines) else None,
                "complete_file": start == 1 and actual_end == len(lines)}

    @bounded_tool
    def search(self, revision: str, text: str, *, prefix: str = "", case_sensitive: bool = False,
               limit: int = 20, cursor=None):
        if not isinstance(text, str) or not 1 <= len(text) <= 512 or type(case_sensitive) is not bool:
            raise CorpusError("search requires a literal 1..512-character string and boolean case_sensitive")
        sha, entries = self._tree(revision)
        needle = text if case_sensitive else text.casefold()
        items, gaps = [], []
        for path, entry in sorted(entries.items()):
            checkpoint()
            if not path.startswith(prefix) or entry["type"] == "tree":
                continue
            if entry["coverage"] != "included":
                gaps.append({"path": path, "reason": entry["coverage"]})
                continue
            blob = self.blobs[entry["oid"]]
            checkpoint(source_bytes=blob["bytes"])
            if blob["encoding"] != "utf-8":
                gaps.append({"path": path, "reason": "non-UTF8 content"})
                continue
            for number, line in enumerate(lf_lines(blob["content"]), 1):
                checkpoint()
                if needle in (line if case_sensitive else line.casefold()):
                    items.append({"citation": self._citation(sha, path, blob, number, number), "content": line})
        result = self._page(items, scope=["search", sha, text, prefix, case_sensitive], limit=limit, cursor=cursor)
        return {"commit": sha, **result, "coverage_gaps": gaps,
                "absence_scope": "literal matches in included UTF8 source only; missing matches do not prove absent relationships"}

    def _history(self, sha):
        # Iterative DFS: all reachable commits in child-before-parent topological
        # order, independent of authored timestamps and recursion depth.
        seen, order, stack = set(), [], [(sha, False)]
        while stack:
            checkpoint()
            current, expanded = stack.pop()
            if expanded:
                order.append(current)
            elif current not in seen:
                seen.add(current)
                stack.append((current, True))
                stack.extend((p, False) for p in reversed(self.commits[current]["parents"]))
        return list(reversed(order))

    @bounded_tool
    def show_commit(self, revision: str):
        sha = self.resolve(revision)
        row = self.commits[sha]
        checkpoint(source_bytes=row["bytes"])
        return {"repository": self.repository, **row, **decoded_object(row),
                "provenance": "raw Git commit object"}

    @bounded_tool
    def log(self, revision: str, *, text: str = "", limit: int = 20, cursor=None):
        sha = self.resolve(revision)
        rows, gaps = [], []
        for s in self._history(sha):
            item = self.show_commit(s)
            if item["text_gap"]:
                gaps.append({"oid": s, "reason": item["text_gap"]})
            if not text or (item["decoded_text"] is not None and text.casefold() in item["decoded_text"].casefold()):
                rows.append(item)
        page = self._page(rows, scope=["log", sha, text], limit=limit, cursor=cursor)
        if gaps:
            page.update(complete=False)
        return {"commit": sha, **page, "coverage_gaps": gaps}

    @bounded_tool
    def show_ref(self, name: str):
        if name not in self.ref_records:
            raise CorpusError("exact ref name absent from pinned corpus")
        row = self.ref_records[name]
        chain = []
        for tag in row["tag_chain"]:
            checkpoint(source_bytes=len(self._raw(tag)))
            chain.append({**tag, **decoded_object(tag)})
        return {"repository": self.repository, **row, "tag_chain": chain}

    @bounded_tool
    def list_refs(self, *, text: str = "", limit: int = 20, cursor=None):
        rows, gaps = [], []
        for name in sorted(self.ref_records):
            checkpoint()
            row = self.show_ref(name)
            tags = row["tag_chain"]
            gaps.extend({"oid": tag["oid"], "reason": tag["text_gap"]} for tag in tags if tag["text_gap"])
            if text.casefold() in name.casefold() or any(
                tag["decoded_text"] is not None and text.casefold() in tag["decoded_text"].casefold()
                for tag in tags
            ):
                rows.append(row)
        page = self._page(rows, scope=["refs", text], limit=limit, cursor=cursor)
        if gaps:
            page.update(complete=False)
        return {**page, "coverage_gaps": gaps}

    @bounded_tool
    def is_ancestor(self, ancestor: str, descendant: str):
        a, b = self.resolve(ancestor), self.resolve(descendant)
        return {"repository": self.repository, "ancestor": a, "descendant": b,
                "is_ancestor": a in self._history(b), "complete_ancestry": True,
                "limitation": "Ancestry alone does not establish that a fix is present"}

    @bounded_tool
    def diff(self, old: str, new: str, path: str):
        a, before = self._tree(old)
        b, after = self._tree(new)
        if path not in before and path not in after:
            raise CorpusError("path absent from both selected trees")
        old_blob = self._source(before, path) if path in before else None
        new_blob = self._source(after, path) if path in after else None
        old_text = old_blob["content"] if old_blob else ""
        new_text = new_blob["content"] if new_blob else ""
        checkpoint(source_bytes=(old_blob["bytes"] if old_blob else 0) +
                   (new_blob["bytes"] if new_blob else 0))
        patch_lines = []
        before_lines, after_lines = list(lf_lines(old_text)), list(lf_lines(new_text))
        checkpoint(work_units=len(before_lines) + len(after_lines))
        for line in difflib.unified_diff(before_lines, after_lines,
                                         fromfile=a + ":" + path, tofile=b + ":" + path):
            checkpoint()
            patch_lines.append(line if line.endswith("\n") else line + "\n\\ No newline at end of file\n")
        return {"repository": self.repository, "old_commit": a, "new_commit": b, "path": path,
                "old_blob": old_blob["oid"] if old_blob else None,
                "new_blob": new_blob["oid"] if new_blob else None,
                "old_content_hash": old_blob["sha256"] if old_blob else None,
                "new_content_hash": new_blob["sha256"] if new_blob else None,
                "patch": "".join(patch_lines),
                "rename_identity": "not inferred; inspect other paths and commits",
                "provenance": "deterministic text diff of raw pinned Git blobs"}
