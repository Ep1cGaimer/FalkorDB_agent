"""Common raw-corpus/reference guard for generated answers from either arm.

Checks immutable identity, physical source spans and retrieval membership only.
It reads no oracle and performs no claim/relevance/answer-quality scoring. Source
metadata anchors are not proof that every claim made about that span is supported.
"""
from __future__ import annotations

import time


SOURCE_FIELDS = {"repository", "commit", "path", "start_line", "end_line", "content_hash"}
SOURCE_OPTIONAL = {"proof_type", "git_blob", "provenance"}


class ReferenceError(ValueError):
    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


class CitationGuard:
    version = "reference-integrity-v1"

    def __init__(self, raw):
        self.raw = raw
        self.tags = {tag["oid"]: tag for ref in raw.ref_records.values() for tag in ref["tag_chain"]}

    def _file(self, value):
        if value.get("repository") != self.raw.repository:
            raise ReferenceError("WRONG_REPOSITORY")
        commit, path = value.get("commit"), value.get("path")
        if not isinstance(commit, str) or commit not in self.raw.commits:
            raise ReferenceError("UNKNOWN_REVISION")
        entry = self.raw.trees[self.raw.commits[commit]["tree"]].get(path) if isinstance(path, str) else None
        if entry is None or entry["coverage"] != "included":
            raise ReferenceError("SOURCE_OUTSIDE_CORPUS")
        blob = self.raw.blobs[entry["oid"]]
        if value.get("content_hash") != blob["sha256"] or (
            "git_blob" in value and value["git_blob"] != entry["oid"]
        ):
            raise ReferenceError("CONTENT_HASH_MISMATCH")
        return entry, blob

    def _source(self, value, *, strict=False):
        if not SOURCE_FIELDS <= set(value) or (strict and set(value) - SOURCE_FIELDS - SOURCE_OPTIONAL):
            raise ReferenceError("INVALID_SOURCE_REFERENCE_FIELDS")
        _, blob = self._file(value)
        start, end = value["start_line"], value["end_line"]
        if blob["encoding"] != "utf-8":
            raise ReferenceError("SOURCE_UNDECODABLE")
        text = blob["content"]
        lines = text.count("\n") + (1 if text and not text.endswith("\n") else 0)
        if type(start) is not int or type(end) is not int or not 1 <= start <= end <= lines:
            raise ReferenceError("INVALID_SOURCE_SPAN")
        return (value["repository"], value["commit"], value["path"], value["content_hash"]), (start, end)

    def _membership(self, value):
        if set(value) != {"proof_type", "repository", "commit", "path", "git_blob", "content_hash"}:
            raise ReferenceError("INVALID_FILE_MEMBERSHIP_REFERENCE")
        entry, blob = self._file(value)
        if value["git_blob"] != entry["oid"]:
            raise ReferenceError("CONTENT_HASH_MISMATCH")
        return self.raw.repository, value["commit"], value["path"], entry["oid"], blob["sha256"]

    def _object(self, value):
        kind, oid = value.get("object_type"), value.get("oid")
        if value.get("repository") != self.raw.repository:
            raise ReferenceError("WRONG_REPOSITORY")
        if set(value) != {"proof_type", "repository", "object_type", "oid"} or (
            not isinstance(kind, str) or kind not in {"commit", "tag"} or not isinstance(oid, str)
        ):
            raise ReferenceError("INVALID_GIT_OBJECT_REFERENCE")
        if oid not in (self.raw.commits if kind == "commit" else self.tags):
            raise ReferenceError("UNKNOWN_GIT_OBJECT")
        return kind, oid

    def _diff(self, value, *, strict=False):
        fields = {"repository", "old_commit", "new_commit", "path", "old_content_hash", "new_content_hash"}
        if value.get("repository") != self.raw.repository:
            raise ReferenceError("WRONG_REPOSITORY")
        if not fields <= set(value) or (strict and set(value) != fields | {"proof_type"}):
            raise ReferenceError("INVALID_DIFF_REFERENCE")
        identities = []
        found = False
        for prefix in ("old", "new"):
            sha = value[prefix + "_commit"]
            if not isinstance(sha, str) or sha not in self.raw.commits:
                raise ReferenceError("UNKNOWN_REVISION")
            path = value["path"]
            entry = self.raw.trees[self.raw.commits[sha]["tree"]].get(path) if isinstance(path, str) else None
            if entry is not None:
                found = True
                if entry["coverage"] != "included":
                    raise ReferenceError("SOURCE_OUTSIDE_CORPUS")
            expected = self.raw.blobs[entry["oid"]]["sha256"] if entry else None
            if value[prefix + "_content_hash"] != expected:
                raise ReferenceError("CONTENT_HASH_MISMATCH")
            identities.append(expected)
        if not found:
            raise ReferenceError("SOURCE_OUTSIDE_CORPUS")
        return (self.raw.repository, value["old_commit"], value["new_commit"], value["path"], *identities)

    def _ancestry(self, value, check, *, strict=False):
        if value.get("repository") != self.raw.repository:
            raise ReferenceError("WRONG_REPOSITORY")
        if strict and set(value) != {"proof_type", "repository", "ancestor", "descendant", "is_ancestor"}:
            raise ReferenceError("INVALID_ANCESTRY_REFERENCE")
        a, b = value.get("ancestor"), value.get("descendant")
        if any(not isinstance(x, str) or x not in self.raw.commits for x in (a, b)):
            raise ReferenceError("UNKNOWN_REVISION")
        if type(value.get("is_ancestor")) is not bool:
            raise ReferenceError("INVALID_ANCESTRY_REFERENCE")
        seen, stack = set(), [b]
        while stack:
            check()
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            if current == a:
                break
            stack.extend(self.raw.commits[current]["parents"])
        if (a in seen) != value["is_ancestor"]:
            raise ReferenceError("ANCESTRY_RESULT_MISMATCH")
        return self.raw.repository, a, b, value["is_ancestor"]

    def verify(self, citations, tool_trace, *, deadline=None, clock=time.monotonic,
               max_records=100000, max_citations=100):
        deadline = min(deadline, clock() + 10) if deadline is not None else clock() + 10
        report = {"schema": self.version, "valid": False, "references_checked": 0,
                  "material_claim_grounding": "UNSCORED", "answer_quality": "UNSCORED", "errors": []}
        records = 0
        def check():
            nonlocal records
            if clock() >= deadline:
                raise ReferenceError("VALIDATION_DEADLINE_EXHAUSTED")
            records += 1
            if records > max_records:
                raise ReferenceError("VALIDATION_WORK_EXHAUSTED")
        spans, objects, diffs, ancestry, refs, memberships = {}, set(), set(), set(), set(), set()
        try:
            check()
            if not isinstance(citations, list) or len(citations) > max_citations:
                raise ReferenceError("INVALID_CITATION_LIST")
            for event in tool_trace:
                check()
                response = event.get("response", {})
                if response.get("status") != "OK":
                    continue
                result, tool = response.get("result"), event.get("tool")
                if isinstance(result, dict):
                    if tool == "diff":
                        diffs.add(self._diff(result))
                    elif tool == "is_ancestor" and result.get("complete_ancestry") is True:
                        ancestry.add(self._ancestry(result, check))
                    elif tool == "list_files":
                        sha = result.get("commit")
                        if sha in self.raw.commits:
                            tree = self.raw.trees[self.raw.commits[sha]["tree"]]
                            for item in result.get("items", []):
                                entry = tree.get(item.get("path"))
                                if entry and entry["coverage"] == "included" and entry["oid"] == item.get("oid") and (
                                    item.get("content_hash") == self.raw.blobs[entry["oid"]]["sha256"]
                                ):
                                    memberships.add((self.raw.repository, sha, item["path"], entry["oid"],
                                                     self.raw.blobs[entry["oid"]]["sha256"]))
                # Only returned JSON structures count. Arguments, failed calls,
                # source text and model text are never reparsed as evidence.
                stack = [result]
                while stack:
                    check()
                    value = stack.pop()
                    if isinstance(value, list):
                        stack.extend(value)
                    elif isinstance(value, dict):
                        if value.get("proof_type") == "file_membership":
                            memberships.add(self._membership(value))
                        if SOURCE_FIELDS <= set(value):
                            key, span = self._source(value)
                            spans.setdefault(key, []).append(span)
                        if value.get("kind") == "commit":
                            raw = self.raw.commits.get(value.get("oid"))
                            if raw and all(value.get(k) == raw[k] for k in ("content", "encoding", "parents", "tree")):
                                objects.add(("commit", value["oid"]))
                        if value.get("kind") == "ref":
                            raw = self.raw.ref_records.get(value.get("name"))
                            if raw and value.get("oid") == raw["oid"] and value.get("target") == raw["target"]:
                                refs.add((self.raw.repository, raw["name"], raw["oid"], raw["target"]))
                                for tag in value.get("tag_chain", []):
                                    known = self.tags.get(tag.get("oid"))
                                    if known and all(tag.get(k) == known[k] for k in ("content", "encoding")):
                                        objects.add(("tag", tag["oid"]))
                        stack.extend(value.values())
        except (ReferenceError, TypeError, KeyError, ValueError) as exc:
            report["errors"].append({"index": None, "reason": exc.reason if isinstance(exc, ReferenceError) else "MALFORMED_RETURNED_EVIDENCE"})
            return report
        for index, citation in enumerate(citations):
            try:
                check()
                if not isinstance(citation, dict):
                    raise ReferenceError("INVALID_CITATION_OBJECT")
                kind = citation.get("proof_type", "source")
                if kind == "source":
                    key, (start, end) = self._source(citation, strict=True)
                    frontier = start
                    for a, b in sorted(spans.get(key, [])):
                        if a > frontier:
                            break
                        if b >= frontier:
                            frontier = b + 1
                        if frontier > end:
                            break
                    if frontier <= end:
                        raise ReferenceError("SOURCE_SPAN_NOT_RETRIEVED")
                elif kind == "git_object":
                    if self._object(citation) not in objects:
                        raise ReferenceError("GIT_OBJECT_NOT_RETRIEVED")
                elif kind == "diff":
                    if self._diff(citation, strict=True) not in diffs:
                        raise ReferenceError("DIFF_NOT_RETRIEVED")
                elif kind == "ancestry":
                    if self._ancestry(citation, check, strict=True) not in ancestry:
                        raise ReferenceError("ANCESTRY_PROOF_NOT_RETRIEVED")
                elif kind == "ref":
                    if set(citation) != {"proof_type", "repository", "name", "oid", "target"} or any(
                        not isinstance(citation.get(k), str) for k in ("repository", "name", "oid", "target")
                    ):
                        raise ReferenceError("INVALID_REF_REFERENCE")
                    identity = tuple(citation.get(k) for k in ("repository", "name", "oid", "target"))
                    if identity not in refs:
                        raise ReferenceError("REF_PROOF_NOT_RETRIEVED")
                elif kind == "file_membership":
                    if self._membership(citation) not in memberships:
                        raise ReferenceError("FILE_MEMBERSHIP_NOT_RETRIEVED")
                else:
                    raise ReferenceError("UNSUPPORTED_CITATION_TYPE")
                report["references_checked"] += 1
            except (ReferenceError, TypeError, KeyError, ValueError) as exc:
                report["errors"].append({"index": index, "reason": exc.reason if isinstance(exc, ReferenceError) else "MALFORMED_CITATION"})
        report["valid"] = not report["errors"]
        return report
