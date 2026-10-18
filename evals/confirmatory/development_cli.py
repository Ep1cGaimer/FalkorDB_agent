"""Run one unscored development question against an explicit shared corpus.

No automatic retry, baseline verdict, holdout execution or scoring. Confirmatory
IDs are rejected by public_task. Auth uses GEMINI_API_KEY, never a CLI key value.
"""
from __future__ import annotations

import argparse
import json
import os
import ssl
from pathlib import Path

import httpx

from .gemini_meter import GeminiAPI, Journal, MeteredModel, ModelLimits
from .investigation_runner import public_task, run_development_question
from .plaintext_tools import PlaintextTools, lf_lines
from .citation_guard import CitationGuard
from .tool_budget import bounded_tool


def plaintext_capabilities(tools):
    descriptions = {
        "search": {"description": "Literal included-source search; physical line citations, coverage gaps and follow-up cursor.",
                   "arguments": {"revision": "required string", "text": "required literal string",
                    "prefix": "optional repository path prefix", "case_sensitive": "optional boolean",
                    "limit": "optional integer 1..100", "cursor": "optional next_cursor"}},
        "read_file": {"description": "Read up to200 physical LF source lines at an explicit revision; content labels each physical line as NUMBER | text. Labels are display metadata, not source bytes. Exact citation and follow-up next_line. Empty files return membership proof without source lines.",
                      "arguments": {"revision": "required string", "path": "required repository-relative path",
                                    "start": "optional 1-based integer; follow next_line for later pages",
                                    "end": "optional inclusive integer; defaults to start+99; span at most200 lines"}},
        "list_files": {"description": "Discover raw tree files and inclusion/exclusion metadata at an explicit revision; included entries expose oid and content_hash for membership references.",
                       "arguments": {"revision": "required string", "prefix": "optional path prefix",
                                     "limit": "optional integer 1..100", "cursor": "optional next_cursor"}},
        "show_commit": {"description": "Inspect immutable commit object, ordered parents and decoded text.",
                        "arguments": {"revision": "required string"}},
        "log": {"description": "Search decoded commit text across complete ancestry, child before parent, with bounded pages.",
                "arguments": {"revision": "required string", "text": "optional literal text",
                              "limit": "optional integer 1..100", "cursor": "optional next_cursor"}},
        "is_ancestor": {"description": "Check raw commit ancestry; ancestry does not establish current fix presence.",
                        "arguments": {"ancestor": "required revision string", "descendant": "required revision string"}},
        "diff": {"description": "Text patch with exact raw-blob identities for one path between two revisions; no rename inference.",
                 "arguments": {"old": "required revision string", "new": "required revision string", "path": "required path"}},
        "list_refs": {"description": "Discover/search ref names and annotated tag messages with bounded pages.",
                      "arguments": {"text": "optional literal text", "limit": "optional integer 1..100", "cursor": "optional next_cursor"}},
        "show_ref": {"description": "Inspect exact ref name, immutable target and full validated nested tag objects.",
                     "arguments": {"name": "required full ref name e.g. refs/tags/release"}},
    }
    capabilities = {name: getattr(tools, name) for name in descriptions}
    @bounded_tool
    def numbered_read(*args, **kwargs):
        value = tools.read_file(*args, **kwargs)
        if not isinstance(value, dict) or not value.get("content"):
            return value
        start = value["citation"]["start_line"]
        return {**value, "content": "".join(f"{number} | {line}" for number, line in
                    enumerate(lf_lines(value["content"]), start)),
                "content_format": "physical-LF-numbered; labels are metadata; content_hash identifies original raw source"}
    capabilities["read_file"] = numbered_read
    return capabilities, descriptions


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--export", type=Path, required=True)
    parser.add_argument("--task", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", required=True, help="explicit models/<model> resource")
    parser.add_argument("--arm", choices=["plaintext", "graph"], default="plaintext")
    parser.add_argument("--graph", help="existing graph name; graph arm never indexes or mutates")
    parser.add_argument("--decision-protocol", choices=["json", "native"], default="json",
                        help="explicit planner transport; no automatic protocol/model fallback")
    parser.add_argument("--tls-max12", action="store_true", help="recorded local TLS workaround, certificate checks remain enabled")
    args = parser.parse_args()
    if any("sealed" in path.resolve().parts for path in (args.task, args.export, args.output)):
        raise ValueError("sealed evaluator paths are outside development runner permissions")
    if args.task.stat().st_size > 16384:
        raise ValueError("development task file too large")
    task = public_task(json.loads(args.task.read_bytes()))
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise ValueError("GEMINI_API_KEY required in process environment")
    tools = PlaintextTools(args.export)
    if task["repository"] != tools.repository:
        raise ValueError("task and export repository identities differ")
    journal = Journal(args.output)
    journal.append("corpus_loaded", sha256=tools.corpus_hash, commits=len(tools.commits),
                   included_blobs=len(tools.blobs), tls_max12=args.tls_max12, arm=args.arm)
    context = ssl.create_default_context()
    if args.tls_max12:
        context.maximum_version = ssl.TLSVersion.TLSv1_2
    with httpx.Client(verify=context, follow_redirects=False) as client:
        api = GeminiAPI(args.model, key, client=client)
        def create_model(capabilities, descriptions):
            return MeteredModel(api, journal, ModelLimits(), generation={"responseMimeType": "application/json"},
                native_decision_tools=sorted(capabilities) if args.decision_protocol == "native" else None,
                native_tool_descriptions=descriptions if args.decision_protocol == "native" else None,
                reserve_final_answer=True)
        if args.arm == "graph":
            if not args.graph:
                raise ValueError("explicit existing --graph required for graph arm")
            from .graph_tools import GraphTools
            trace = []
            arm = GraphTools(tools, args.graph, trace=trace)
            capabilities, descriptions = arm.capabilities()
            model = create_model(capabilities, descriptions)
            result = run_development_question(task, capabilities, descriptions, model,
                                               readiness=arm.prepare, audit_trace=trace,
                                               citation_guard=CitationGuard(tools),
                                               corpus_context={"corpus_sha256": tools.corpus_hash, "spec": tools.spec})
        else:
            if args.graph:
                raise ValueError("--graph is only valid for graph arm")
            capabilities, descriptions = plaintext_capabilities(tools)
            model = create_model(capabilities, descriptions)
            result = run_development_question(task, capabilities, descriptions, model,
                                               citation_guard=CitationGuard(tools),
                                               corpus_context={"corpus_sha256": tools.corpus_hash, "spec": tools.spec})
    print(json.dumps({"status": result["status"], "failure": result["failure"],
                      "answer_generated": result["answer"] is not None, "scored": False,
                      "model_usage": result["model_usage"]}, sort_keys=True))
    return 0 if result["status"] == "COMPLETE_UNSCORED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
