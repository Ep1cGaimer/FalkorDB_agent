"""Aggregate independently adjudicated scores; never generates or grades answers.

Input contains public roster identities and final blind ratings, never oracle text.
All planned question/arm/repeat cells are required. Failed attempts stay in quality
denominators; unknown usage prevents cost/token advantage. Output is a numerical
gate check only, not T0 sign-off, independent scoring or acceptance validation.
"""
from __future__ import annotations

import argparse
import json
import math
import random
from collections import defaultdict
from pathlib import Path


CRITICAL = {"wrong_repository", "wrong_revision", "fabricated_citation",
            "false_absence", "unsupported_compatibility_pass"}
STATUSES = {"COMPLETE", "ERROR", "TIMEOUT", "BUDGET_EXHAUSTED", "CONTEXT_OVERFLOW"}


def number(value, name, *, maximum=None, nullable=False):
    if nullable and value is None:
        return None
    if type(value) not in {int, float} or not math.isfinite(value) or value < 0 or (
        maximum is not None and value > maximum
    ):
        raise ValueError("invalid " + name)
    return float(value)


def mean(values):
    return sum(values) / len(values) if values and all(v is not None for v in values) else None


def validate(roster, records, arms, repeats):
    if len(arms) < 2 or len(set(arms)) != len(arms) or "graph" not in arms or any(
        not isinstance(a, str) or not a for a in arms
    ) or type(repeats) is not int or repeats < 3:
        raise ValueError("graph, at least one comparator, and at least three repeats required")
    tasks = {}
    for task in roster:
        if set(task) != {"id", "repository", "stratum", "evidence_applicable", "negative"} or any(
            not isinstance(task[k], str) or not task[k] for k in ("id", "repository", "stratum")
        ) or any(type(task[k]) is not bool for k in ("evidence_applicable", "negative")) or task["id"] in tasks:
            raise ValueError("invalid or duplicate roster task")
        tasks[task["id"]] = task
    if not tasks:
        raise ValueError("empty roster")
    cells = {}
    required = {"task_id", "arm", "repeat", "status", "answer_pass", "precision", "recall",
                "material_citations_valid", "negative_handled", "critical_errors", "input_tokens",
                "output_tokens", "cost_usd", "latency_seconds", "adjudication_id"}
    for raw in records:
        if set(raw) != required:
            raise ValueError("score record fields differ from declared schema")
        row = dict(raw)
        task = tasks.get(row["task_id"])
        if task is None or row["arm"] not in arms or type(row["repeat"]) is not int or not (
            0 <= row["repeat"] < repeats
        ) or row["status"] not in STATUSES:
            raise ValueError("unknown task/arm/repeat/status")
        key = row["task_id"], row["arm"], row["repeat"]
        if key in cells:
            raise ValueError("duplicate planned cell; never select the best retry")
        for field in ("answer_pass", "material_citations_valid", "negative_handled"):
            if type(row[field]) is not bool:
                raise ValueError("strict boolean rating required")
        if not isinstance(row["critical_errors"], list) or any(
            x not in CRITICAL for x in row["critical_errors"]
        ):
            raise ValueError("invalid critical error labels")
        if row["status"] == "COMPLETE" and (
            not isinstance(row["adjudication_id"], str) or not row["adjudication_id"]
        ):
            raise ValueError("completed answers require an independent adjudication reference")
        for field in ("input_tokens", "output_tokens"):
            if row[field] is not None and (type(row[field]) is not int or row[field] < 0):
                raise ValueError("actual integer usage or explicit null required")
        row["cost_usd"] = number(row["cost_usd"], "cost", nullable=True)
        row["latency_seconds"] = number(row["latency_seconds"], "latency")
        if task["evidence_applicable"]:
            row["precision"] = number(row["precision"], "precision", maximum=1)
            row["recall"] = number(row["recall"], "recall", maximum=1)
        elif row["precision"] is not None or row["recall"] is not None:
            raise ValueError("predeclared clarification-only evidence metrics must be null")
        # Failure ratings cannot disappear or claim success, even if labels are malformed.
        if row["status"] != "COMPLETE":
            row.update(answer_pass=False, negative_handled=False)
            if task["evidence_applicable"]:
                row.update(precision=0.0, recall=0.0)
        row["answer_pass"] = row["answer_pass"] and row["material_citations_valid"] and not row["critical_errors"]
        cells[key] = row
    expected = {(t, a, r) for t in tasks for a in arms for r in range(repeats)}
    if set(cells) != expected:
        raise ValueError("missing planned cells; record failed attempts explicitly")
    return tasks, cells


def question_rows(tasks, cells, arms, repeats):
    by_arm = {arm: {} for arm in arms}
    for arm in arms:
        for ident, task in tasks.items():
            rows = [cells[ident, arm, r] for r in range(repeats)]
            by_arm[arm][ident] = {
                **task, "answer": mean([float(x["answer_pass"]) for x in rows]),
                "precision": mean([x["precision"] for x in rows]),
                "recall": mean([x["recall"] for x in rows]),
                "input_tokens": mean([x["input_tokens"] for x in rows]),
                "output_tokens": mean([x["output_tokens"] for x in rows]),
                "cost_usd": mean([x["cost_usd"] for x in rows]),
                "latency_seconds": mean([x["latency_seconds"] for x in rows]),
                "all_material_citations_valid": all(x["material_citations_valid"] for x in rows),
                "critical_errors": sum(len(x["critical_errors"]) for x in rows),
                "negative_all_runs_handled": all(x["negative_handled"] for x in rows) if task["negative"] else None,
                "failed_attempts": sum(x["status"] != "COMPLETE" for x in rows),
            }
    return by_arm


def metrics(rows):
    return {key: mean([r[key] for r in rows if key not in {"precision", "recall"} or r["evidence_applicable"]])
            for key in ("answer", "precision", "recall", "input_tokens", "output_tokens", "cost_usd", "latency_seconds")}


def quality(rows):
    overall = metrics(rows)
    per_repo = {name: metrics([r for r in rows if r["repository"] == name])
                for name in sorted({r["repository"] for r in rows})}
    per_stratum = {name: metrics([r for r in rows if r["stratum"] == name])
                   for name in sorted({r["stratum"] for r in rows})}
    conditions = {
        "overall_answer_90": overall["answer"] >= .90,
        "each_repository_answer_85": all(r["answer"] >= .85 for r in per_repo.values()),
        "each_stratum_answer_85": all(r["answer"] >= .85 for r in per_stratum.values()),
        "precision_95": overall["precision"] is not None and overall["precision"] >= .95,
        "recall_90": overall["recall"] is not None and overall["recall"] >= .90,
        "all_material_citations_valid": all(r["all_material_citations_valid"] for r in rows),
        "zero_critical_errors_all_runs": not any(r["critical_errors"] for r in rows),
        "all_negative_cases_handled_all_runs": all(r["negative_all_runs_handled"] for r in rows if r["negative"]),
    }
    return {"overall": overall, "per_repository": per_repo, "per_stratum": per_stratum,
            "conditions": conditions, "numerical_thresholds_met": all(conditions.values()),
            "distinct_questions": len(rows), "evidence_applicable_questions": sum(r["evidence_applicable"] for r in rows),
            "failed_attempts": sum(r["failed_attempts"] for r in rows)}


def effects(graph, base):
    gm, bm = metrics(graph), metrics(base)
    result = {}
    for key in ("answer", "precision", "recall"):
        result[key + "_difference"] = None if gm[key] is None or bm[key] is None else gm[key] - bm[key]
    for key in ("input_tokens", "cost_usd"):
        result[key + "_ratio"] = None if gm[key] is None or bm[key] is None or bm[key] <= 0 else gm[key] / bm[key]
    return result


def paired_intervals(tasks, by_arm, comparator, *, resamples, seed):
    groups = defaultdict(list)
    for ident, task in tasks.items():
        groups[task["repository"], task["stratum"]].append(ident)
    strata = [sorted(ids) for _, ids in sorted(groups.items())]
    collected = defaultdict(list)
    rng = random.Random(seed)
    for _ in range(resamples):
        sample = [rng.choice(ids) for ids in strata for _ in ids]
        estimates = effects([by_arm["graph"][i] for i in sample], [by_arm[comparator][i] for i in sample])
        for key, value in estimates.items():
            collected[key].append(value)
    result = {}
    for key, values in collected.items():
        if any(x is None for x in values):
            result[key] = {"lower": None, "upper": None, "status": "INCONCLUSIVE_UNKNOWN_OR_ZERO_DENOMINATOR"}
        else:
            values.sort()
            result[key] = {"lower": values[max(0, math.ceil(.025 * resamples) - 1)],
                           "upper": values[min(resamples - 1, math.ceil(.975 * resamples) - 1)],
                           "status": "MEASURED_PERCENTILE_INTERVAL"}
    return result


def report(roster, records, arms, repeats=3, *, gate="B", resamples=10000, seed=541098):
    if gate not in {"A", "B"} or type(resamples) is not int or resamples < 10000 or type(seed) is not int:
        raise ValueError("preselected A/B gate and at least10000 resamples required")
    tasks, cells = validate(roster, records, arms, repeats)
    by_arm = question_rows(tasks, cells, arms, repeats)
    qualities = {arm: quality(list(rows.values())) for arm, rows in by_arm.items()}
    comparisons = {}
    for arm in arms:
        if arm == "graph":
            continue
        graph, base = list(by_arm["graph"].values()), list(by_arm[arm].values())
        point = effects(graph, base)
        interval = paired_intervals(tasks, by_arm, arm, resamples=resamples, seed=seed)
        veto = {}
        for repo in sorted({t["repository"] for t in tasks.values()}):
            g = metrics([r for r in graph if r["repository"] == repo])
            b = metrics([r for r in base if r["repository"] == repo])
            veto[repo] = g["answer"] >= b["answer"] and g["recall"] is not None and b["recall"] is not None and g["recall"] >= b["recall"]
        if gate == "B":
            checks = [interval["input_tokens_ratio"]["upper"] is not None and interval["input_tokens_ratio"]["upper"] <= .80]
            checks += [interval[k]["lower"] is not None and interval[k]["lower"] >= 0
                       for k in ("answer_difference", "precision_difference", "recall_difference")]
        else:
            checks = [point["answer_difference"] is not None and point["answer_difference"] >= .10,
                      interval["answer_difference"]["lower"] is not None and interval["answer_difference"]["lower"] > 0]
            checks += [point[k] is not None and point[k] <= 1.05 for k in ("input_tokens_ratio", "cost_usd_ratio")]
        comparisons[arm] = {"point": point, "interval95": interval, "repository_noninferiority": veto,
            "numerical_gate_met": all(checks) and all(veto.values()) and qualities["graph"]["numerical_thresholds_met"]}
    counts = defaultdict(int)
    for task in tasks.values():
        counts[task["stratum"]] += 1
    return {"schema": "paired-independent-score-summary/v1", "acceptance_validated": False,
        "interpretation": "Numerical aggregation of supplied adjudications only; no independent scoring, T0 signature or advantage release inferred",
        "selected_gate": gate, "resamples": resamples, "seed": seed, "repeats": repeats,
        "planned_cells": len(cells), "distinct_questions": len(tasks),
        "basic_roster_floor_met": len(tasks) >= 120 and len({t["repository"] for t in tasks.values()}) >= 2 and len(counts) == 6 and min(counts.values()) >= 20,
        "quality": qualities, "comparisons": comparisons,
        "question_means": by_arm, "break_even": "UNMEASURED; actual indexing and monetary savings required"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    data = json.loads(args.input.read_text())
    result = report(**data)
    with args.output.open("x") as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
        stream.write("\n")


if __name__ == "__main__":
    main()
