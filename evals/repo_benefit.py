"""E4 FalkorDB benefit (remquirements-v1.md E4), run exactly as pre-registered in
evals/repo_benefit_threshold.json: contestants graph_tools / plaintext_direct / plaintext_search,
Groq openai/gpt-oss-120b at temperature 0, identical instructions and budgets, 2 paired repeats with
contestant order shuffled per question by a recorded seed, scoring as in evals/repo_eval_keys.json
(rule-based, no LLM judge), verdict strictly from the declared PASS/FAIL/INCONCLUSIVE rules.

    PYTHONPATH=src .venv/Scripts/python.exe evals/repo_benefit.py [--seed N]
    PYTHONPATH=src .venv/Scripts/python.exe evals/repo_benefit.py --smoke --questions rq-01 --contestants graph_tools

Writes artifacts/repo_benefit/<timestamp>.json (+ artifacts/repo_benefit/traces/<timestamp>.json).
A checkpoint with every required key is rewritten after each task at
artifacts/repo_benefit/attempts/<timestamp>-checkpoint.json (status running -> complete, or crashed
with the error); smoke runs only ever write artifacts/repo_benefit/attempts/<timestamp>-smoke.json.

Implementation decisions not fixed by the declaration (recorded in the output under `scoring` and
`runner_decisions`):
* Token estimates before a call: the first call of a task uses ceil(len(json(messages + tools)) / 3);
  later calls use the previous call's actual prompt+completion tokens plus len(new tool output)/3.
  Estimates drive pacing (estimate + max_completion_tokens must fit the rolling 60 s window of 8000)
  and the per-task budget. Actual API usage replaces the estimate in the window and is what is reported.
* Per-task budget 7500 tokens over all calls: each call gets max_completion_tokens =
  min(1500, 7500 - used - estimated_prompt); a call that would get < 256 is not made and the task is
  budget_exhausted. A call is sent without tools plus FINAL_NUDGE (the model must answer) when it is turn 6,
  8 tool calls were made, or a further tool round would not fit (forecast: this prompt + 300
  completion + 1000 tool output + 600 to answer); that final call carries the question plus all tool
  results flattened as text (no tool-call turns). A task stopped by the budget is scored on its last text.
* Groq tool_use_failed (HTTP 400: the model called a non-existent tool): if the rejected generation
  holds an "answer" JSON it is taken as the final answer; otherwise one nudge listing the real tools
  is appended (counts as a turn); no token usage is reported by the API for rejected calls.
* plaintext_direct "relevant source files": the files named by the question's expected citations at
  their revisions (an oracle selection favouring the baseline); for questions without expected
  citations, every indexed source file at the question revision. Each file is numbered by line and
  followed by `git log --oneline -n 20 <rev> -- <path>`. CONTEXT_LIMIT (nothing truncated, scored
  incorrect with zero evidence) when the actual prompt_tokens reported by the API + 1500 > 7500 or the
  API rejects the request as too large (413); prompts estimated at len/4 + 1500 > 1.25 x 7500 are not
  sent at all.
* graph_tools wrappers return bounded JSON from RepoQuery/investigate; named symbol lookups also carry
  the definition text from the clone (<= 40 lines per item, <= 3 items) so citations can be checked by
  the model. plaintext_search tools are read-only git (grep, show, log, tag) with the same 6000-char cap.
* tokens of a CONTEXT_LIMIT task are 0 (no call is made); its estimated prompt size is recorded.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import re
import sys
import time
import traceback
from collections import deque
from pathlib import Path

import httpx

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from repo_eval_common import (KEYS_PATH, ROOT, SETS, THRESHOLD, Clone, allowed_shas, answer_check,  # noqa: E402
                              check_citation, evidence_scores, expected_citations, fabricated, grounded,
                              load_keys, load_questions, manifest_for, now_iso, question_revs, rel,
                              sha256_file, sha256_text, stamp)

OUT = ROOT / "artifacts" / "repo_benefit"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
DECL = json.loads(THRESHOLD.read_text(encoding="utf-8"))
B = DECL["budget"]
MODEL = DECL["model"]["name"]
TEMP = DECL["model"]["temperature"]
MAX_COMPLETION = DECL["model"]["max_completion_tokens_per_call"]
TPM = B["groq_tokens_per_minute_limit"]
TASK_BUDGET = B["max_total_tokens_per_task"]
MAX_REQ = B["max_tokens_per_request"]
MAX_TURNS = B["max_turns_per_task"]
MAX_TOOL_CALLS = B["max_tool_calls_per_task"]
MAX_OUT = B["max_tool_output_chars"]
COST_IN = DECL["cost_model"]["usd_per_million_input_tokens"]
COST_OUT = DECL["cost_model"]["usd_per_million_output_tokens"]
CONTESTANTS = [c["name"] for c in DECL["contestants"]]
REPOS = DECL["repos"]
MIN_COMPLETION = 256
CHARS_PER_TOKEN = 3          # conservative pre-call estimate (JSON of messages + tool schemas)
DIRECT_CHARS_PER_TOKEN = 4   # plain-text estimate for plaintext_direct (actual usage decides; see docstring)
DIRECT_SEND_SLACK = 1.25     # direct prompts estimated above 1.25 x budget are not sent (clearly over)
FORECAST_TURN_COMPLETION = 300
FORECAST_TOOL_OUTPUT = 1000
FORECAST_ANSWER = 600
TOOL_USE_HTTP_RETRIES = 0     # identical resend at temperature 0 repeats the same invalid generation
MAX_TOOL_NUDGES = 1
FINAL_NUDGE = ("No more tool calls are available for this task. Answer now from the evidence gathered so far, "
               "with ONLY the JSON object described in the instructions.")

SYSTEM = (DECL["instructions"] + "\n\n"
          "You are working on a local Git clone of the named repository. Revisions are tags, branches or "
          "commit shas of that repository. Use only the evidence available to you (tool results or the "
          "provided text); do not rely on memory of the project.\n"
          "Reply at the end with ONLY a JSON object:\n"
          '{"answer": "<your answer>", "citations": [{"path": "<repo-relative path>", "start_line": <int>, '
          '"end_line": <int>, "revision": "<tag, branch or sha>"}], "gap": <true if evidence is absent or the '
          'request is ambiguous, else false>}')
USER_TMPL = "Repository: {repo}\nRequested revision: {revision}{compare}\nQuestion: {question}"
PROMPT_ID = "repo_benefit/v1"
PROMPT_SHA = sha256_text(SYSTEM + "\n----\n" + USER_TMPL)


def est_tokens(obj) -> int:
    return math.ceil(len(json.dumps(obj, ensure_ascii=False)) / CHARS_PER_TOKEN)


def clip(s: str) -> str:
    if len(s) <= MAX_OUT:
        return s
    note = f"\n...[truncated: {len(s) - MAX_OUT + 80} more chars not shown]"
    return s[:MAX_OUT - len(note)] + note


# ---------------------------------------------------------------- Groq + pacing

class Pacer:
    def __init__(self):
        self.window: deque = deque()  # (t, tokens)
        self.total_wait = 0.0

    def _used(self, now):
        while self.window and now - self.window[0][0] >= 60:
            self.window.popleft()
        return sum(t for _, t in self.window)

    def wait_for(self, need: int) -> float:
        waited = 0.0
        while True:
            now = time.monotonic()
            if self._used(now) + need <= TPM or not self.window:
                break
            dt = max(0.5, 60 - (now - self.window[0][0]) + 0.2)
            time.sleep(dt)
            waited += dt
        self.total_wait += waited
        return waited

    def record(self, tokens: int):
        self.window.append((time.monotonic(), tokens))


class Groq:
    def __init__(self, key: str, pacer: Pacer):
        self.key, self.pacer = key, pacer
        self.consecutive_infra = 0

    def call(self, messages, tools, tool_choice, max_tokens, est: int | None = None) -> dict:
        body = {"model": MODEL, "temperature": TEMP, "max_completion_tokens": max_tokens, "messages": messages}
        if tools:
            body["tools"] = tools
            body["tool_choice"] = tool_choice
        if est is None:
            est = est_tokens(messages) + (est_tokens(tools) if tools else 0)
        rec = {"estimated_prompt_tokens": est, "max_completion_tokens": max_tokens, "pacing_wait_s": 0.0,
               "backoff_wait_s": 0.0, "http_attempts": 0}
        rec["pacing_wait_s"] += self.pacer.wait_for(est + max_tokens)
        for attempt in range(6):
            rec["http_attempts"] += 1
            t0 = time.perf_counter()
            try:
                r = httpx.post(GROQ_URL, json=body, headers={"Authorization": f"Bearer {self.key}"}, timeout=180)
            except httpx.HTTPError as exc:
                rec["latency_s"] = time.perf_counter() - t0
                rec["error"] = f"{type(exc).__name__}: {exc}"
                time.sleep(10)
                rec["backoff_wait_s"] += 10
                continue
            latency = time.perf_counter() - t0
            if r.status_code == 429 or r.status_code >= 500:
                wait = float(r.headers.get("retry-after") or 15 * (attempt + 1))
                rec["error"] = f"HTTP {r.status_code}: {r.text[:300]}"
                if wait > 900:
                    break
                self.pacer.record(est)  # be conservative: assume the attempt counted
                time.sleep(min(wait, 120) + 1)
                rec["backoff_wait_s"] += min(wait, 120) + 1
                continue
            rec["latency_s"] = latency
            if r.status_code == 400 and "tool_use_failed" in r.text and rec.get("tool_use_retries", 0) < TOOL_USE_HTTP_RETRIES:
                rec["tool_use_retries"] = rec.get("tool_use_retries", 0) + 1  # model emitted an invalid tool call
                rec.setdefault("rejected_generations", []).append(r.text[:500])
                self.pacer.record(est)
                rec["pacing_wait_s"] += self.pacer.wait_for(est + max_tokens)
                continue
            if r.status_code != 200:
                rec["error"] = f"HTTP {r.status_code}: {r.text[:500]}"
                rec["infra_error"] = r.status_code not in (400, 413)  # 400/413: request-level (e.g. too large)
                self.pacer.record(est)
                self.consecutive_infra += rec["infra_error"]
                return rec
            data = r.json()
            u = data.get("usage") or {}
            rec.update({"prompt_tokens": int(u.get("prompt_tokens") or 0),
                        "completion_tokens": int(u.get("completion_tokens") or 0),
                        "finish_reason": data["choices"][0].get("finish_reason"),
                        "message": data["choices"][0]["message"], "error": None, "infra_error": False})
            self.pacer.record(rec["prompt_tokens"] + rec["completion_tokens"])
            self.consecutive_infra = 0
            return rec
        rec["infra_error"] = True
        rec.setdefault("latency_s", 0.0)
        self.consecutive_infra += 1
        return rec


# ---------------------------------------------------------------- tools

def _fn(name, desc, props, required):
    return {"type": "function", "function": {"name": name, "description": desc, "parameters": {
        "type": "object", "properties": props, "required": required}}}


S = {"type": "string"}
I = {"type": "integer"}
GRAPH_TOOLS = [
    _fn("resolve", "Resolve a tag/branch/sha to the indexed commit sha.", {"revision": S}, ["revision"]),
    _fn("symbols", "List symbols defined at a revision, optionally only those whose qualified or short name "
                   "equals `name` (named lookups include definition text).",
        {"revision": S, "name": S, "cursor": S}, ["revision"]),
    _fn("dependencies", "Symbols that `symbol` (qualified name) calls/imports/inherits at a revision.",
        {"revision": S, "symbol": S, "hops": I, "cursor": S}, ["revision", "symbol"]),
    _fn("dependents", "Symbols that call/import/inherit `symbol` (qualified name) at a revision.",
        {"revision": S, "symbol": S, "hops": I, "cursor": S}, ["revision", "symbol"]),
    _fn("changes_between", "Files and symbols added/removed/modified/renamed between two revisions.",
        {"rev_a": S, "rev_b": S, "cursor": S}, ["rev_a", "rev_b"]),
    _fn("history", "Presence of a symbol (qualified name or module path) at each given revision "
                   "(default: every indexed tag, oldest first).",
        {"symbol": S, "revisions": {"type": "array", "items": S}}, ["symbol"]),
    _fn("investigate", "Deterministic investigation at a revision. Supported questions: "
                       "'What does <symbol> call?', 'What depends on <symbol>?', 'What changed between <a> and "
                       "<b>?', 'Is fix <sha> present?', 'When did <symbol> appear?', 'When did <symbol> "
                       "disappear?', 'Release notes', 'List symbols', 'Where is <symbol> defined?'.",
        {"revision": S, "question": S}, ["revision", "question"]),
]
SEARCH_TOOLS = [
    _fn("grep", "git grep -n -E <pattern> at a revision, optionally limited to a path or directory.",
        {"pattern": S, "revision": S, "path": S}, ["pattern", "revision"]),
    _fn("read_file", "Lines start..end (1-based, inclusive, max 200) of a file at a revision.",
        {"path": S, "revision": S, "start": I, "end": I}, ["path", "revision"]),
    _fn("git_log", "git log --oneline (max 40 entries) for an optional revision range (e.g. 'v1..v2' or a "
                   "single revision) and optional path.", {"rev_range": S, "path": S}, []),
    _fn("git_show", "git show of a commit: header, parents and changed-file stat; with `path`, that file's "
                    "diff in the commit.", {"rev": S, "path": S}, ["rev"]),
    _fn("list_tags", "All tags, oldest first.", {}, []),
]


def _cit(c):
    return None if c is None else {"path": c.path, "start_line": c.start_line, "end_line": c.end_line,
                                   "revision": c.commit}


class GraphTools:
    def __init__(self, name: str):
        from rw.repo.config import load_config
        from rw.repo.query import RepoQuery
        self.cfg = load_config(SETS[name][1])
        self.graph = SETS[name][2]
        self.q = RepoQuery(self.graph, self.cfg.name)
        self.clone = Clone(SETS[name][3])

    def _page(self, page, conv):
        gaps = [{"kind": g.kind, "detail": g.detail} for g in page.coverage.get("gaps", [])]
        return {"items": [conv(x) for x in page.items], "next_cursor": page.next_cursor,
                "total": page.coverage.get("total"), "gaps": gaps}

    def run(self, name, a):
        q = self.q
        if name == "resolve":
            sha, gap = q.resolve(a["revision"])
            return {"sha": sha, "gap": gap and {"kind": gap.kind, "detail": gap.detail}}
        if name == "symbols":
            page = q.symbols(a["revision"], a.get("name") or None, limit=50, cursor=a.get("cursor") or None)
            nm = a.get("name") or ""
            if nm and "." in nm and not page.items and not page.coverage.get("gaps"):
                # dotted partial name (e.g. Class.method): look up the short name, keep qualname suffix matches
                short = q.symbols(a["revision"], nm.rsplit(".", 1)[-1], limit=200)
                page.items = [s for s in short.items if s.qualname.endswith("." + nm)][:50]
            out = self._page(page, lambda s: {"qualname": s.qualname, "kind": s.kind, **_cit(s.citation)})
            if a.get("name"):
                for it in out["items"][:3]:
                    text = self.clone.show(it["revision"], it["path"]) or ""
                    lines = text.splitlines()[it["start_line"] - 1: min(it["end_line"], it["start_line"] + 39)]
                    it["source"] = "\n".join(f"{it['start_line'] + i}: {l}" for i, l in enumerate(lines))
            return out
        if name in ("dependencies", "dependents"):
            hops = int(a.get("hops") or 1)
            page = getattr(q, name)(a["revision"], a["symbol"], hops=max(1, min(hops, 5)), limit=50,
                                    cursor=a.get("cursor") or None)
            return self._page(page, lambda d: {"source": d.source, "target": d.target, "kind": d.kind,
                                               "provenance": d.provenance, "external": d.external, "hops": d.hops,
                                               "source_citation": _cit(d.citation),
                                               "target_citation": _cit(d.target_citation)})
        if name == "changes_between":
            page = q.changes_between(a["rev_a"], a["rev_b"], limit=50, cursor=a.get("cursor") or None)
            return self._page(page, lambda c: {"status": c.status, "path": c.path, "old_path": c.old_path,
                                               "symbols_added": c.symbols_added[:10],
                                               "symbols_removed": c.symbols_removed[:10],
                                               "symbols_modified": c.symbols_modified[:10],
                                               "citation": _cit(c.citation)})
        if name == "history":
            revs = a.get("revisions")
            if not revs:
                rows = q._q("MATCH (t:Tag)-[:POINTS_TO]->(c:Commit) RETURN t.name ORDER BY c.author_time, t.name")
                revs = [r[0] for r in rows][-200:]
            ents = q.symbol_history(a["symbol"], list(revs)[:200])
            return [{"rev": e.rev, "present": e.present, "citation": _cit(e.citation),
                     "gap": e.gap and e.gap.kind} for e in ents]
        if name == "investigate":
            from rw.repo.investigate import investigate
            return investigate(self.cfg.name, a["revision"], a["question"], graph_name=self.graph,
                               config=self.cfg).to_dict()
        raise ValueError(f"unknown tool {name}")


class SearchTools:
    def __init__(self, name: str):
        self.clone = Clone(SETS[name][3])

    @staticmethod
    def _safe(s, what):
        s = str(s or "")
        if s.startswith("-"):
            raise ValueError(f"{what} may not start with '-'")
        return s

    def run(self, name, a):
        g = self.clone
        if name == "grep":
            rev = self._safe(a["revision"], "revision")
            args = ["grep", "-n", "-I", "-E", "-e", str(a["pattern"]), rev]
            if a.get("path"):
                args += ["--", self._safe(a["path"], "path")]
            r = g.run(*args)
            return r.stdout if r.returncode in (0, 1) and r.stdout else (r.stderr.strip() or "no matches")
        if name == "read_file":
            rev, path = self._safe(a["revision"], "revision"), self._safe(a["path"], "path")
            sha = g.sha(rev)
            text = g.show(sha, path) if sha else None
            if text is None:
                return f"cannot read {path} at {rev}"
            lines = text.splitlines()
            s = max(1, int(a.get("start") or 1))
            e = min(len(lines), int(a.get("end") or s + 199), s + 199)
            return f"{path} @ {rev} ({len(lines)} lines)\n" + "\n".join(f"{i}: {lines[i - 1]}" for i in range(s, e + 1))
        if name == "git_log":
            args = ["log", "--oneline", "--decorate=short", "-n", "40"]
            if a.get("rev_range"):
                args.append(self._safe(a["rev_range"], "rev_range"))
            if a.get("path"):
                args += ["--", self._safe(a["path"], "path")]
            r = g.run(*args)
            return r.stdout or r.stderr.strip() or "no commits"
        if name == "git_show":
            rev = self._safe(a["rev"], "rev")
            if a.get("path"):
                r = g.run("show", "--format=commit %H%nparents %P%n%an %ad%n%n%s%n", rev, "--",
                          self._safe(a["path"], "path"))
            else:
                r = g.run("show", "--stat", "--format=commit %H%nparents %P%n%an %ad%n%n%B", rev)
            return r.stdout or r.stderr.strip()
        if name == "list_tags":
            r = g.run("tag", "--sort=creatordate")
            return " ".join(r.stdout.split())
        raise ValueError(f"unknown tool {name}")


# ---------------------------------------------------------------- direct context

def direct_context(name: str, q: dict, cfg_include) -> tuple[str, list]:
    clone = Clone(SETS[name][3])
    pairs = []
    for c in expected_citations(q):
        if (c["path"], c["revision"]) not in pairs:
            pairs.append((c["path"], c["revision"]))
    if not pairs:
        from rw.repo.index import _matches  # same include semantics as indexing (read-only helper)
        sha = clone.sha(q["revision"])
        r = clone.run("ls-tree", "-r", "--name-only", sha)
        for p in r.stdout.split("\n"):
            if p and (not cfg_include or _matches(p, cfg_include)) and p.endswith(".py"):
                pairs.append((p, q["revision"]))
    parts = []
    for path, rev in pairs:
        text = clone.show(clone.sha(rev), path) or ""
        numbered = "\n".join(f"{i}: {l}" for i, l in enumerate(text.splitlines(), 1))
        log = clone.run("log", "--oneline", "-n", "20", rev, "--", path).stdout
        parts.append(f"=== {path} @ {rev} ===\n{numbered}\n--- git log --oneline -n 20 {rev} -- {path} ---\n{log}")
    return "\n\n".join(parts), pairs


# ---------------------------------------------------------------- one task

def _failed_generation(err: str) -> str | None:
    """`failed_generation` of a Groq tool_use_failed 400 (the arguments when it parses as a call)."""
    try:
        body = json.loads(err.split(":", 1)[1])
        gen = body["error"].get("failed_generation")
    except (ValueError, KeyError, IndexError, AttributeError):
        return None
    if not gen:
        return None
    try:
        g = json.loads(gen)
        if isinstance(g, dict) and isinstance(g.get("arguments"), (dict, str)):
            a = g["arguments"]
            return a if isinstance(a, str) else json.dumps(a)
    except ValueError:
        pass
    return gen


def parse_final(text: str) -> tuple[str, list]:
    text = text or ""
    m = re.search(r"\{.*\}", text, re.S)
    if m:
        try:
            d = json.loads(m.group(0))
            cits = d.get("citations") or []
            return str(d.get("answer") or ""), [c for c in cits if isinstance(c, dict)]
        except json.JSONDecodeError:
            pass
    cits = []
    for mm in re.finditer(r"\{[^{}]*\"path\"[^{}]*\}", text):
        try:
            cits.append(json.loads(mm.group(0)))
        except json.JSONDecodeError:
            pass
    return text, cits


def run_task(contestant: str, name: str, q: dict, groq: Groq, tools_by_repo: dict, cfg_include) -> dict:
    user = USER_TMPL.format(repo=name, revision=q["revision"], question=q["question"],
                            compare=f"\nCompare revision: {q['compare_revision']}" if q.get("compare_revision") else "")
    calls, tool_log = [], []
    used = 0
    status = {"context_limit": False, "budget_exhausted": False, "infra_error": False}
    final_text = ""
    est_direct = None
    if contestant == "plaintext_direct":
        ctx, pairs = direct_context(name, q, cfg_include)
        messages = [{"role": "system", "content": SYSTEM},
                    {"role": "user", "content": "Source files and history:\n\n" + ctx + "\n\n" + user}]
        est_direct = math.ceil(sum(len(m["content"]) for m in messages) / DIRECT_CHARS_PER_TOKEN)
        extra = {"direct_files": pairs, "direct_prompt_chars": sum(len(m["content"]) for m in messages)}
        if est_direct + MAX_COMPLETION > TASK_BUDGET * DIRECT_SEND_SLACK:
            status["context_limit"] = True
            extra["context_limit_basis"] = "estimate (clearly over budget; not sent)"
            return _task(contestant, name, q, "", [], calls, tool_log, status, est_direct, extra)
        rec = groq.call(messages, None, None, MAX_COMPLETION, est=est_direct)
        calls.append(rec)
        if (rec.get("error") or "").startswith("HTTP 413") or (
                rec.get("prompt_tokens") and rec["prompt_tokens"] + MAX_COMPLETION > TASK_BUDGET):
            status["context_limit"] = True
            extra["context_limit_basis"] = (f"actual prompt_tokens {rec.get('prompt_tokens')} + {MAX_COMPLETION} > "
                                            f"{TASK_BUDGET}" if rec.get("prompt_tokens") else rec.get("error"))
            return _task(contestant, name, q, "", [], calls, tool_log, status, est_direct, extra)
        if rec.get("infra_error"):
            status["infra_error"] = True
        if rec.get("message"):
            final_text = rec["message"].get("content") or ""
        return _task(contestant, name, q, final_text, [], calls, tool_log, status, est_direct, extra)

    tools = GRAPH_TOOLS if contestant == "graph_tools" else SEARCH_TOOLS
    key = (contestant, name)
    if key not in tools_by_repo:
        tools_by_repo[key] = GraphTools(name) if contestant == "graph_tools" else SearchTools(name)
    impl = tools_by_repo[key]
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]
    n_tool_calls = 0
    nudges = 0
    known, known_len = None, 0  # actual prompt+completion tokens of the previous call, len(messages) then
    for turn in range(MAX_TURNS):
        if known is None:
            est = est_tokens(messages) + est_tokens(tools)
        else:
            est = known + math.ceil(sum(len(m.get("content") or "") for m in messages[known_len:])
                                    / CHARS_PER_TOKEN) + 20
        remaining = TASK_BUDGET - used
        max_tok = min(MAX_COMPLETION, remaining - est, MAX_REQ - est)
        if max_tok < MIN_COMPLETION:
            status["budget_exhausted"] = True
            break
        # forecast: would a further tool round (+300 completion, +1000 tool output, +600 to answer) fit?
        room_after = remaining - est - FORECAST_TURN_COMPLETION
        next_need = est + FORECAST_TURN_COMPLETION + FORECAST_TOOL_OUTPUT + FORECAST_ANSWER
        last = turn == MAX_TURNS - 1 or n_tool_calls >= MAX_TOOL_CALLS or room_after < next_need
        send = messages
        if last:
            # final turn: tool results flattened into plain text, no tools (gpt-oss on Groq keeps emitting
            # tool calls when the conversation still holds tool-call turns)
            evidence = "\n\n".join(f"### {t['tool']}({t['arguments']})\n{t['output']}" for t in tool_log)
            send = [messages[0], {"role": "user", "content": user + (
                "\n\nEvidence gathered with tools so far:\n\n" + evidence if evidence else "") + "\n\n" + FINAL_NUDGE}]
            est = math.ceil(sum(len(m["content"]) for m in send) / CHARS_PER_TOKEN) + 20
            max_tok = min(MAX_COMPLETION, remaining - est, MAX_REQ - est)
            if max_tok < MIN_COMPLETION:
                status["budget_exhausted"] = True
                break
        rec = groq.call(send, None if last else tools, None if last else "auto", max_tok, est=est)
        calls.append(rec)
        used += rec.get("prompt_tokens", 0) + rec.get("completion_tokens", 0)
        if rec.get("prompt_tokens"):
            known = rec["prompt_tokens"] + rec.get("completion_tokens", 0)
        if not rec.get("infra_error") and "tool_use_failed" in (rec.get("error") or ""):
            gen = _failed_generation(rec["error"])
            if gen is not None and '"answer"' in gen:
                final_text = gen  # the model emitted its JSON answer as a pseudo tool call
                break
            if not last and nudges < MAX_TOOL_NUDGES:
                nudges += 1
                messages.append({"role": "user", "content": "That tool does not exist. Available tools: " +
                                 ", ".join(t["function"]["name"] for t in tools) +
                                 ". Call one of them, or answer with ONLY the JSON object."})
                continue
            break
        if rec.get("infra_error") or not rec.get("message"):
            status["infra_error"] = bool(rec.get("infra_error"))
            break
        msg = rec["message"]
        if msg.get("content"):
            final_text = msg["content"]
        tcs = msg.get("tool_calls") or []
        if not tcs or last:
            break
        known_len = len(messages) + 1
        messages.append({"role": "assistant", "content": msg.get("content") or "",
                         "tool_calls": [{"id": t["id"], "type": "function", "function": t["function"]} for t in tcs]})
        for t in tcs:
            n_tool_calls += 1
            fname = t["function"]["name"]
            t1 = time.perf_counter()
            if n_tool_calls > MAX_TOOL_CALLS:
                out = "tool call budget exhausted; answer now"
            else:
                try:
                    args = json.loads(t["function"].get("arguments") or "{}")
                    res = impl.run(fname, args)
                    out = res if isinstance(res, str) else json.dumps(res, default=str)
                except Exception as exc:
                    out = f"tool error: {type(exc).__name__}: {exc}"
            out = clip(out)
            tool_log.append({"turn": turn, "tool": fname, "arguments": t["function"].get("arguments"),
                             "output": out, "seconds": round(time.perf_counter() - t1, 4)})
            messages.append({"role": "tool", "tool_call_id": t["id"], "content": out})
    if used > TASK_BUDGET:
        status["budget_exhausted"] = True
    return _task(contestant, name, q, final_text, [], calls, tool_log, status, None, {"tool_calls_made": n_tool_calls})


def _task(contestant, name, q, final_text, _unused, calls, tool_log, status, est_direct, extra) -> dict:
    keys = load_keys()
    clone = Clone(SETS[name][3])
    answer, raw_cits = parse_final(final_text)
    allowed = allowed_shas(clone, q)
    cits = [check_citation(clone, c, allowed, q.get("revision")) for c in raw_cits]
    if status["context_limit"] or status["infra_error"] and not final_text:
        correct, decision = False, "CONTEXT_LIMIT: scored incorrect" if status["context_limit"] else \
            "infrastructure error before an answer: scored incorrect"
        cits_scored = []
    else:
        correct, decision = answer_check(q, answer, cits, keys)
        cits_scored = cits
    recall, precision = evidence_scores(cits_scored, q, clone)
    if status["context_limit"]:
        recall = 0.0 if expected_citations(q) else None
    pt = sum(c.get("prompt_tokens", 0) for c in calls)
    ct = sum(c.get("completion_tokens", 0) for c in calls)
    wrong = [c for c in cits_scored if not c["requested_revision_match"]]
    return {"repo": name, "question_id": q["id"], "category": q["category"], "revision": q["revision"],
            "contestant": contestant, "answer": answer, "raw_final_text": final_text,
            "answer_correct": correct, "answer_decision": decision,
            "grounded_answer_correct": grounded(q, correct, recall, cits_scored) and not status["context_limit"],
            "evidence_recall": recall, "evidence_precision": precision, "citations": cits,
            "citation_validity": (sum(c["valid"] for c in cits) / len(cits)) if cits else None,
            "wrong_revision": bool(wrong), "wrong_revision_citations": len(wrong),
            "fabricated_citations": len(fabricated(cits_scored)),
            "prompt_tokens": pt, "completion_tokens": ct, "tokens": pt + ct,
            "cost_usd": round(pt / 1e6 * COST_IN + ct / 1e6 * COST_OUT, 8),
            "llm_calls": len(calls), "tool_calls": len(tool_log),
            "latency_s": round(sum(c.get("latency_s", 0.0) for c in calls) + sum(t["seconds"] for t in tool_log), 3),
            "pacing_wait_s": round(sum(c.get("pacing_wait_s", 0.0) for c in calls), 3),
            "backoff_wait_s": round(sum(c.get("backoff_wait_s", 0.0) for c in calls), 3),
            "context_limit": status["context_limit"], "budget_exhausted": status["budget_exhausted"],
            "infra_error": status["infra_error"],
            "errors": [c["error"] for c in calls if c.get("error")],
            "finish_reasons": [c.get("finish_reason") for c in calls],
            "estimated_direct_prompt_tokens": est_direct, **extra,
            "_trace": {"calls": [{k: v for k, v in c.items()} for c in calls], "tools": tool_log}}


# ---------------------------------------------------------------- aggregation + verdict

def _mean(xs):
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 4) if xs else None


def metrics(tasks):
    cits = [c for t in tasks for c in t["citations"]]
    return {"n_tasks": len(tasks),
            "answer_accuracy": _mean([float(t["answer_correct"]) for t in tasks]),
            "grounded_answer_accuracy": _mean([float(t["grounded_answer_correct"]) for t in tasks]),
            "evidence_recall": _mean([t["evidence_recall"] for t in tasks]),
            "evidence_precision": _mean([t["evidence_precision"] for t in tasks]),
            "citation_validity": round(sum(c["valid"] for c in cits) / len(cits), 4) if cits else None,
            "citations": len(cits),
            "wrong_revision": sum(t["wrong_revision"] for t in tasks),
            "tokens": _mean([t["tokens"] for t in tasks]),
            "tokens_total": sum(t["tokens"] for t in tasks),
            "tool_calls": _mean([t["tool_calls"] for t in tasks]),
            "latency_s": _mean([t["latency_s"] for t in tasks]),
            "cost_usd": _mean([t["cost_usd"] for t in tasks]),
            "cost_usd_total": round(sum(t["cost_usd"] for t in tasks), 6),
            "context_limit_failures": sum(t["context_limit"] for t in tasks),
            "budget_exhausted": sum(t["budget_exhausted"] for t in tasks),
            "infra_errors": sum(t["infra_error"] for t in tasks),
            "pacing_wait_s_total": round(sum(t["pacing_wait_s"] for t in tasks), 1)}


def aggregate(tasks):
    per_repo = {r: {c: metrics([t for t in tasks if t["repo"] == r and t["contestant"] == c]) for c in CONTESTANTS}
                for r in REPOS}
    overall = {c: metrics([t for t in tasks if t["contestant"] == c]) for c in CONTESTANTS}
    return {"per_repo": per_repo, "overall": overall}


def judge(by_c: dict) -> dict:
    """Declared PASS conditions against the stronger plaintext baseline (by grounded accuracy;
    ties broken by answer_accuracy, then evidence_recall)."""
    def strength(c):
        m = by_c[c]
        return (m["grounded_answer_accuracy"] or 0, m["answer_accuracy"] or 0, m["evidence_recall"] or 0)
    base = max(["plaintext_direct", "plaintext_search"], key=strength)
    g, b = by_c["graph_tools"], by_c[base]
    gg, bg = g["grounded_answer_accuracy"] or 0, b["grounded_answer_accuracy"] or 0
    gt, bt = g["tokens"] or 0, b["tokens"] or 0
    gr, br = g["evidence_recall"] or 0, b["evidence_recall"] or 0
    tok_within = (abs(gt - bt) <= 0.2 * bt) if bt > 0 else gt == 0
    c1 = gg >= bg + 0.15 - 1e-9 and tok_within
    c2 = (bt > 0 and gt <= 0.7 * bt + 1e-9) and gg >= bg - 0.05 - 1e-9 and gr >= br - 0.05 - 1e-9
    return {"baseline": base, "graph_grounded": gg, "baseline_grounded": bg, "graph_tokens": gt,
            "baseline_tokens": bt, "graph_recall": gr, "baseline_recall": br,
            "pass_accuracy_condition": c1, "pass_token_condition": c2,
            "tokens_within_20pct": tok_within, "verdict": "PASS" if (c1 or c2) else "FAIL"}


def verdict(runs, expected_per_run) -> tuple[str, str, dict]:
    all_tasks = [t for r in runs for t in r["tasks"]]
    detail = {"per_repeat": [], "pooled": judge(aggregate(all_tasks)["overall"]) if all_tasks else None}
    for r in runs:
        detail["per_repeat"].append(judge(aggregate(r["tasks"])["overall"]) if r["tasks"] else None)
    infra = sum(t["infra_error"] for t in all_tasks)
    total = expected_per_run * DECL["repeats"]
    detail.update({"infra_error_tasks": infra, "tasks_expected": total, "tasks_recorded": len(all_tasks)})
    missing = [r["repeat"] for r in runs if len(r["tasks"]) < expected_per_run]
    if len(runs) < DECL["repeats"] or missing:
        return "INCONCLUSIVE", f"repeat(s) missing or incomplete: {missing or 'not run'}", detail
    if infra > 0.10 * total:
        return "INCONCLUSIVE", f"{infra}/{total} tasks failed for infrastructure reasons (> 10%)", detail
    vs = [d["verdict"] for d in detail["per_repeat"]]
    if len(set(vs)) > 1:
        return "INCONCLUSIVE", f"the repeats disagree on the verdict: {vs}", detail
    p = detail["per_repeat"][0]
    why = (f"overall, both repeats {vs[0]}: graph_tools grounded {p['graph_grounded']:.3f} vs baseline "
           f"{p['baseline']} {p['baseline_grounded']:.3f} (repeat 1); tokens/task {p['graph_tokens']:.0f} vs "
           f"{p['baseline_tokens']:.0f}; accuracy condition {p['pass_accuracy_condition']}, token condition "
           f"{p['pass_token_condition']}; repeat 2: " + ", ".join(
               f"{k}={detail['per_repeat'][1][k]}" for k in ("baseline", "graph_grounded", "baseline_grounded",
                                                             "graph_tokens", "baseline_tokens")))
    return vs[0], why, detail


def indexing_cost(gt_tasks_per_repo: dict) -> dict:
    out = {"source": DECL["indexing_cost_source"], "records": [], "per_repo": {}}
    scale = sorted((ROOT / "artifacts" / "repo_scale").glob("*.json"))
    onboard = sorted((ROOT / "artifacts" / "repo_onboarding").glob("*.json"))
    evalidx = sorted((ROOT / "artifacts" / "repo_eval_index").glob("*.json"))
    for repo in REPOS:
        e = {"graph": SETS[repo][2], "tokens": 0, "llm_tokens_note": "indexing uses no LLM"}
        if repo == "requests" and scale:
            d = json.loads(scale[-1].read_text(encoding="utf-8"))
            ii = d["initial_index"]
            e.update({"evaluated_graph_record": rel(scale[-1]), "seconds": ii["seconds"],
                      "peak_rss_bytes": ii.get("peak_rss_bytes"), "peak_memory_bytes": ii.get("peak_memory_bytes"),
                      "tags": ii.get("tags"), "update_seconds": d.get("update", {}).get("seconds")
                      if isinstance(d.get("update"), dict) else None,
                      "index_size_bytes": d.get("index_size_bytes")})
            out["records"].append(rel(scale[-1]))
        mine = [p for p in evalidx if p.name.startswith(repo + "-")]
        if repo == "itsdangerous" and mine:
            d = json.loads(mine[-1].read_text(encoding="utf-8"))
            e.update({"evaluated_graph_record": rel(mine[-1]), "seconds": d["metrics"]["seconds"],
                      "peak_rss_bytes": d["metrics"].get("peak_rss_bytes"),
                      "peak_memory_bytes": d["metrics"].get("peak_memory_bytes"), "tags": d.get("tags")})
            out["records"].append(rel(mine[-1]))
        ob = [p for p in onboard if p.name.startswith(repo + "-")]
        if ob:
            d = json.loads(ob[-1].read_text(encoding="utf-8"))
            e["onboarding_record"] = rel(ob[-1])
            e["onboarding_index_seconds_3_revisions"] = (d.get("index") or {}).get("seconds")
            out["records"].append(rel(ob[-1]))
        n = gt_tasks_per_repo.get(repo, 0)
        secs = e.get("seconds")
        e["unamortised_seconds"] = secs
        e["graph_tools_tasks"] = n
        e["amortised_seconds_per_graph_task"] = round(secs / n, 3) if secs and n else None
        e["amortised_seconds_per_question"] = round(secs / max(1, n // DECL["repeats"]), 3) if secs and n else None
        out["per_repo"][repo] = e
    return out


# ---------------------------------------------------------------- main

def build_record(args, ts, started, seed, plan, runs, traces_path, failures, status, error=None) -> dict:
    all_tasks = [t for r in runs for t in r["tasks"]]
    qsets = {n: load_questions(n) for n in REPOS}
    revs = {n: set().union(*(question_revs(q) for q in qsets[n]["questions"])) for n in REPOS}
    expected = len(plan)
    v, why, vd = verdict(runs, expected) if not args.smoke else ("INCONCLUSIVE", "smoke run (plumbing only)", {})
    gtn = {r: sum(1 for t in all_tasks if t["repo"] == r and t["contestant"] == "graph_tools") for r in REPOS}
    configs = {n: {"file": rel(SETS[n][1]), "sha256": sha256_file(SETS[n][1]), "graph": SETS[n][2]} for n in REPOS}
    runner_cfg = {"model": MODEL, "temperature": TEMP, "max_completion_tokens_per_call": MAX_COMPLETION,
                  "budget": B, "chars_per_token_estimate": CHARS_PER_TOKEN, "min_completion_tokens": MIN_COMPLETION,
                  "seed": seed, "repos": configs}
    rec = {
        "schema": "repo_benefit/v1", "evidence": "E4", "status": status, "label": "smoke" if args.smoke else "full",
        "started_at": started, "finished_at": now_iso(),
        "command": " ".join(["PYTHONPATH=src", ".venv/Scripts/python.exe", "evals/repo_benefit.py", *sys.argv[1:]]),
        "llm_used": True, "scored": True,
        "threshold_file": rel(THRESHOLD), "threshold_sha256": sha256_file(THRESHOLD),
        "question_files": [{"path": f"evals/repo_questions/{SETS[n][0]}",
                            "sha256": sha256_file(ROOT / "evals" / "repo_questions" / SETS[n][0])} for n in REPOS],
        "keys_file": rel(KEYS_PATH), "keys_sha256": sha256_file(KEYS_PATH),
        "model": {"provider": DECL["model"]["provider"], "model": MODEL, "temperature": TEMP,
                  "max_completion_tokens_per_call": MAX_COMPLETION, "prompt_id": PROMPT_ID,
                  "prompt_sha256": PROMPT_SHA, "system_prompt": SYSTEM, "user_template": USER_TMPL,
                  "tool_schemas_sha256": {"graph_tools": sha256_text(json.dumps(GRAPH_TOOLS, sort_keys=True)),
                                          "plaintext_search": sha256_text(json.dumps(SEARCH_TOOLS, sort_keys=True))}},
        "manifest": {"repos": [manifest_for(n, revs[n]) for n in REPOS]},
        "coverage": {"gaps": ["plaintext_direct is CONTEXT_LIMIT when estimated prompt + completion exceeds the "
                              "7500-token task budget (no truncation)",
                              "graph index: python adapter only; Python 2 era files (requests <= 1.x models.py, "
                              "itsdangerous 0.24 itsdangerous.py) failed to parse and have no symbols "
                              "(extraction_errors in the index records)"],
                     "limits": {"max_tool_output_chars": MAX_OUT, "page_limit": 50, "history_revisions": 200,
                                "read_file_lines": 200, "git_log_entries": 40, "symbol_source_lines": 40}},
        "config": runner_cfg, "config_sha256": sha256_text(json.dumps(runner_cfg, sort_keys=True, default=str)),
        "contestants": CONTESTANTS, "repeats": DECL["repeats"], "pairing": DECL["pairing"],
        "seed": seed, "order": plan,
        "traces_path": rel(traces_path),
        "answers": [{"repeat": t["repeat"], "repo": t["repo"], "question_id": t["question_id"],
                     "contestant": t["contestant"], "answer": t["answer"], "answer_correct": t["answer_correct"]}
                    for t in all_tasks],
        "usage": {c: {"prompt_tokens": sum(t["prompt_tokens"] for t in all_tasks if t["contestant"] == c),
                      "completion_tokens": sum(t["completion_tokens"] for t in all_tasks if t["contestant"] == c),
                      "llm_calls": sum(t["llm_calls"] for t in all_tasks if t["contestant"] == c)}
                  for c in CONTESTANTS},
        "timings": {"latency_excludes_pacing": True,
                    "pacing_wait_s_total": round(sum(t["pacing_wait_s"] for t in all_tasks), 1),
                    "backoff_wait_s_total": round(sum(t["backoff_wait_s"] for t in all_tasks), 1),
                    "task_latency_s_total": round(sum(t["latency_s"] for t in all_tasks), 1)},
        "scoring": {"answer_rule": load_keys()["answer_rule"], "llm_judge": False,
                    "declared": DECL["scoring"], "primary_metric": DECL["primary_metric"],
                    "evidence": "recall/precision by citation overlap (same path, same resolved sha, intersecting "
                                "spans); CONTEXT_LIMIT and infra-error-before-answer tasks are scored incorrect "
                                "with zero evidence",
                    "wrong_revision": "tasks with any citation whose resolved sha is not the requested, compare or "
                                      "an expected-citation revision (claims in prose are not parsed)",
                    "cost": DECL["cost_model"],
                    "baseline_tiebreak": "grounded_answer_accuracy, then answer_accuracy, then evidence_recall",
                    "verdict_rule": "INCONCLUSIVE if a repeat is incomplete, > 10% infra-error tasks, or the "
                                    "per-repeat overall verdicts disagree; else the (agreeing) per-repeat verdict",
                    "decisions": [{"repeat": t["repeat"], "question_id": t["question_id"],
                                   "contestant": t["contestant"], "answer_correct": t["answer_correct"],
                                   "decision": t["answer_decision"]} for t in all_tasks]},
        "runner_decisions": __doc__.split("Implementation decisions", 1)[1],
        "runs": [{"repeat": r["repeat"], "tasks": [{k: v for k, v in t.items() if k != "_trace"} for t in r["tasks"]]}
                 for r in runs],
        "results": {**aggregate(all_tasks),
                    "per_repeat": [{"repeat": r["repeat"], **aggregate(r["tasks"])} for r in runs]},
        "indexing_cost": indexing_cost(gtn),
        "verdict": v, "verdict_reason": why, "verdict_detail": vd,
        "failures": failures,
    }
    if error:
        rec["error"] = error
    elif args.smoke:
        rec["error"] = "smoke run: plumbing check only (subset of questions/contestants), not an evaluation"
    return rec


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=20261018)
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--questions", nargs="*")
    ap.add_argument("--contestants", nargs="*")
    args = ap.parse_args()
    key = os.environ.get("GROQ_API_KEY") or next(
        (l.split("=", 1)[1].strip() for l in (ROOT / ".env").read_text().splitlines() if l.startswith("GROQ_API_KEY=")), None)
    assert key, "GROQ_API_KEY missing"
    from rw.repo.config import load_config
    ts, started = stamp(), now_iso()
    rng = random.Random(args.seed)
    qsets = {n: load_questions(n) for n in REPOS}
    contestants = args.contestants or CONTESTANTS
    plan = []
    for rep in range(1 if args.smoke else DECL["repeats"]):
        for n in REPOS:
            for q in qsets[n]["questions"]:
                if args.questions and q["id"] not in args.questions:
                    continue
                order = list(contestants)
                rng.shuffle(order)
                plan.extend({"repeat": rep, "repo": n, "question_id": q["id"], "contestant": c} for c in order)
    per_run = len(plan) // (1 if args.smoke else DECL["repeats"])
    (OUT / "attempts").mkdir(parents=True, exist_ok=True)
    (OUT / "traces").mkdir(parents=True, exist_ok=True)
    suffix = "-smoke" if args.smoke else ""
    traces_path = OUT / "traces" / f"{ts}{suffix}.json"
    ckpt = OUT / "attempts" / f"{ts}{'-smoke' if args.smoke else '-checkpoint'}.json"
    pacer = Pacer()
    groq = Groq(key, pacer)
    includes = {n: load_config(SETS[n][1]).include for n in REPOS}
    runs = [{"repeat": r, "tasks": []} for r in range(1 if args.smoke else DECL["repeats"])]
    traces, failures = [], []
    qmap = {(n, q["id"]): q for n in REPOS for q in qsets[n]["questions"]}
    tools_by_repo: dict = {}

    def save(status, error=None):
        traces_path.write_text(json.dumps(traces, indent=1, default=str), encoding="utf-8")
        rec = build_record(args, ts, started, args.seed, plan, runs, traces_path, failures, status, error)
        if status != "complete" and not error:
            rec["error"] = f"run {status}: {sum(len(r['tasks']) for r in runs)}/{len(plan)} tasks recorded"
        ckpt.write_text(json.dumps(rec, indent=1, default=str), encoding="utf-8")
        return rec

    try:
        for i, p in enumerate(plan):
            q = qmap[(p["repo"], p["question_id"])]
            if groq.consecutive_infra >= 5:
                raise RuntimeError("5 consecutive infrastructure failures (API); stopping")
            try:
                task = run_task(p["contestant"], p["repo"], q, groq, tools_by_repo, includes[p["repo"]])
            except Exception as exc:
                failures.append(f"{p}: {type(exc).__name__}: {exc}")
                raise
            task["repeat"] = p["repeat"]
            task["order_index"] = i
            traces.append({"repeat": p["repeat"], "repo": p["repo"], "question_id": p["question_id"],
                           "contestant": p["contestant"], **task.pop("_trace")})
            runs[p["repeat"]]["tasks"].append(task)
            print(f"[{i + 1}/{len(plan)}] r{p['repeat']} {p['question_id']} {p['contestant']:16s} "
                  f"ok={task['answer_correct']} rec={task['evidence_recall']} tok={task['tokens']} "
                  f"tools={task['tool_calls']} cl={task['context_limit']} be={task['budget_exhausted']} "
                  f"infra={task['infra_error']} wait={task['pacing_wait_s']:.0f}s", flush=True)
            save("running")
    except BaseException as exc:  # crash or interrupt: keep the attempt
        save("crashed", f"{type(exc).__name__}: {exc}\n{traceback.format_exc()[-2000:]}")
        print("CRASHED; attempt kept at", rel(ckpt))
        raise
    rec = save("complete")
    if args.smoke:
        print("smoke attempt:", rel(ckpt))
        return 0
    final = OUT / f"{ts}.json"
    final.write_text(json.dumps(rec, indent=1, default=str), encoding="utf-8")
    print(rel(final))
    print("VERDICT", rec["verdict"], "-", rec["verdict_reason"])
    for scope, by_c in [("overall", rec["results"]["overall"])] + list(rec["results"]["per_repo"].items()):
        for c, m in by_c.items():
            print(f"{scope:13s} {c:17s} ans={m['answer_accuracy']} grounded={m['grounded_answer_accuracy']} "
                  f"recall={m['evidence_recall']} prec={m['evidence_precision']} valid={m['citation_validity']} "
                  f"tok={m['tokens']} tools={m['tool_calls']} cl={m['context_limit_failures']} "
                  f"be={m['budget_exhausted']} infra={m['infra_errors']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
