"""Paired question-level statistics for T10; no model calls or automatic evidence sign-off.

Input rows are independently scored attempts. Repeated attempts remain paired inside each
question. This module cannot establish blind scoring, corpus independence or plan sign-off.
"""
from __future__ import annotations

from collections import defaultdict
import math
import random
from statistics import fmean as mean

QUALITY = ("answer_pass", "evidence_precision", "evidence_recall")
RESOURCE = ("input_tokens", "output_tokens", "query_cost_usd", "latency_s")


def _ratio(a, b):
    return a / b if b else (1.0 if not a else None)


def _interval(values):
    if any(v is None for v in values):
        return [None, None]
    values = sorted(values)

    def quantile(p):
        position = (len(values) - 1) * p
        lower = math.floor(position)
        upper = math.ceil(position)
        return values[lower] + (values[upper] - values[lower]) * (position - lower)

    return [quantile(0.025), quantile(0.975)]


def paired_bootstrap(rows: list[dict], graph_arm: str, comparator: str, *, seed: int,
                     resamples: int = 10_000) -> dict:
    """Stratified percentile intervals, resampling distinct questions, never model repeats.

    A complete pair has >=3 attempts in each arm with exactly matching repeat identifiers.
    Unsuccessful attempts must already carry their zero quality scores in the input ledger.
    Missing attempts, duplicate rows and invalid numbers are errors, not discarded data.
    """
    if resamples < 10_000:
        raise ValueError("T10 requires at least 10000 bootstrap resamples")
    grouped = defaultdict(lambda: defaultdict(dict))
    identities = {}
    for row in rows:
        if row["arm"] not in (graph_arm, comparator):
            continue
        identity = (row["repo"], row["question_id"])
        stratum = row["stratum"]
        if identity in identities and identities[identity] != stratum:
            raise ValueError("a question must have one primary stratum")
        identities[identity] = stratum
        key = (*identity, stratum)
        repeats = grouped[key][row["arm"]]
        if row["repeat"] in repeats:
            raise ValueError("duplicate paired attempt")
        for metric in QUALITY + RESOURCE:
            value = row[metric]
            if value is None and metric in QUALITY[1:] and not row["evidence_applicable"]:
                continue
            if metric in QUALITY[1:] and not row["evidence_applicable"]:
                raise ValueError("inapplicable evidence metrics must remain null")
            if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or value < 0:
                raise ValueError(f"missing or invalid measurement: {metric}")
            if metric in QUALITY and value > 1:
                raise ValueError(f"quality outside [0,1]: {metric}")
        if row["outcome"] != "PASS" and any(row[m] not in (0, None) for m in QUALITY):
            raise ValueError("unsuccessful attempts must receive zero quality credit")
        repeats[row["repeat"]] = row
    if not grouped:
        raise ValueError("no paired questions")
    questions = []
    strata = defaultdict(list)
    for key, arms in sorted(grouped.items()):
        g, b = arms.get(graph_arm, {}), arms.get(comparator, {})
        if len(g) < 3 or set(g) != set(b):
            raise ValueError("missing paired attempts or fewer than three repeats")
        if len({r["evidence_applicable"] for arm in (g, b) for r in arm.values()}) != 1:
            raise ValueError("evidence applicability must be fixed for the question")
        summary = {"repo": key[0], "question_id": key[1], "stratum": key[2], "repeats": len(g)}
        for arm, attempts in ((graph_arm, g), (comparator, b)):
            summary[arm] = {m: mean(r[m] for r in attempts.values() if r[m] is not None)
                            if any(r[m] is not None for r in attempts.values()) else None
                            for m in QUALITY + RESOURCE}
        strata[(key[0], key[2])].append(len(questions))
        questions.append(summary)

    def estimates(selected):
        averages = {}
        for arm in (graph_arm, comparator):
            averages[arm] = {m: mean(q[arm][m] for q in selected if q[arm][m] is not None)
                            if any(q[arm][m] is not None for q in selected) else None
                            for m in QUALITY + RESOURCE}
        g, b = averages[graph_arm], averages[comparator]
        effects = {m + "_difference": g[m] - b[m] if g[m] is not None and b[m] is not None else None
                   for m in QUALITY}
        effects["input_token_ratio"] = _ratio(g["input_tokens"], b["input_tokens"])
        return averages, effects

    averages, point = estimates(questions)
    samples = {metric: [] for metric in point}
    rng = random.Random(seed)
    for _ in range(resamples):
        selected = [questions[rng.choice(indices)] for indices in strata.values() for _ in indices]
        _, effect = estimates(selected)
        for metric, value in effect.items():
            samples[metric].append(value)
    return {"method": "paired stratified question bootstrap, percentile 95%",
            "seed": seed, "resamples": resamples, "n_questions": len(questions),
            "stratum_counts": [{"repo": r, "stratum": s, "questions": len(indices)}
                               for (r, s), indices in sorted(strata.items())],
            "arms": [graph_arm, comparator], "means": averages,
            "point": point, "intervals": {m: _interval(v) for m, v in samples.items()},
            "questions": questions}


def advantage_conditions(result: dict, primary_gate: str) -> dict:
    """Evaluate the frozen gate's numerical conditions; acceptance prerequisites stay separate."""
    if primary_gate not in ("A", "B"):
        raise ValueError("choose exactly one primary gate, A or B, before evaluation")
    graph, baseline = result["arms"]
    g, b = result["means"][graph], result["means"][baseline]
    point, intervals = result["point"], result["intervals"]
    no_repo_regression = True
    for repo in {q["repo"] for q in result["questions"]}:
        subset = [q for q in result["questions"] if q["repo"] == repo]
        for metric in ("answer_pass", "evidence_recall"):
            gs = [q[graph][metric] for q in subset if q[graph][metric] is not None]
            bs = [q[baseline][metric] for q in subset if q[baseline][metric] is not None]
            if gs and bs and mean(gs) < mean(bs):
                no_repo_regression = False
    if primary_gate == "A":
        passed = (point["answer_pass_difference"] >= 0.10 - 1e-12
                  and intervals["answer_pass_difference"][0] > 0
                  and g["input_tokens"] <= 1.05 * b["input_tokens"]
                  and g["query_cost_usd"] <= 1.05 * b["query_cost_usd"])
    else:
        upper = intervals["input_token_ratio"][1]
        passed = upper is not None and upper <= 0.80
        for metric in QUALITY:
            lower = intervals[metric + "_difference"][0]
            passed = passed and lower is not None and lower >= 0
    return {"primary_gate": primary_gate, "numerical_conditions_pass": bool(passed and no_repo_regression),
            "no_repository_quality_regression": no_repo_regression,
            "acceptance_validated": False,
            "required_prerequisites": ["signed frozen T0 plan", "T2 absolute quality and critical-error gates",
                                       "every applicable plaintext comparator", "independent blind scoring",
                                       "indexing cost accounting and measured break-even"]}


def break_even_queries(index_cost_usd: float, measured_query_saving_usd: float) -> int | None:
    if index_cost_usd < 0:
        raise ValueError("index cost must be nonnegative")
    return math.ceil(index_cost_usd / measured_query_saving_usd) if measured_query_saving_usd > 0 else None
