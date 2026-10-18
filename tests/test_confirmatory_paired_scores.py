"""Synthetic adjudication records only; no held-out data or model invocation."""
import copy

import pytest

from evals.confirmatory.paired_scores import effects, question_rows, report, validate


def sample():
    roster = [{"id": str(i), "repository": "r"+str(i % 2), "stratum": "s"+str(i // 2),
               "evidence_applicable": True, "negative": i == 0} for i in range(4)]
    records = []
    for task in roster:
        for arm in ("graph", "plaintext"):
            for repeat in range(3):
                records.append(dict(task_id=task["id"], arm=arm, repeat=repeat, status="COMPLETE",
                    answer_pass=True, precision=1., recall=1., material_citations_valid=True,
                    negative_handled=True, critical_errors=[], input_tokens=70 if arm=="graph" else 100,
                    output_tokens=10, cost_usd=.01, latency_seconds=2., adjudication_id="synthetic-rating"))
    return roster, records


def test_paired_question_bootstrap_and_no_acceptance_release():
    roster, records = sample()
    result = report(roster, records, ["graph", "plaintext"])
    comparison = result["comparisons"]["plaintext"]
    assert comparison["interval95"]["input_tokens_ratio"] == {
        "lower": .7, "upper": .7, "status": "MEASURED_PERCENTILE_INTERVAL"}
    assert comparison["numerical_gate_met"]
    assert not result["acceptance_validated"] and not result["basic_roster_floor_met"]
    assert result["planned_cells"] == 24 and result["distinct_questions"] == 4


def test_errors_stay_in_repeat_then_question_denominators():
    roster, records = sample()
    records[0].update(status="TIMEOUT", adjudication_id=None)
    tasks, cells = validate(roster, records, ["graph", "plaintext"], 3)
    rows = question_rows(tasks, cells, ["graph", "plaintext"], 3)
    assert rows["graph"]["0"]["answer"] == pytest.approx(2/3)
    assert rows["graph"]["0"]["precision"] == pytest.approx(2/3)
    assert not rows["graph"]["0"]["negative_all_runs_handled"]
    assert effects(list(rows["graph"].values()), list(rows["plaintext"].values()))["answer_difference"] == pytest.approx(-1/12)


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "unknown_task", "unknown_arm", "bool_usage", "nan", "missing_rating"])
def test_incomplete_or_invalid_pair_contract_is_rejected(mutation):
    roster, records = sample()
    if mutation == "missing": records.pop()
    if mutation == "duplicate": records.append(copy.deepcopy(records[0]))
    if mutation == "unknown_task": records[0]["task_id"] = "new"
    if mutation == "unknown_arm": records[0]["arm"] = "hidden"
    if mutation == "bool_usage": records[0]["input_tokens"] = True
    if mutation == "nan": records[0]["precision"] = float("nan")
    if mutation == "missing_rating": records[0]["adjudication_id"] = None
    with pytest.raises(ValueError):validate(roster, records, ["graph", "plaintext"], 3)


def test_single_critical_error_survives_repeat_averaging():
    roster, records = sample()
    records[0]["critical_errors"] = ["wrong_revision"]
    result = report(roster, records, ["graph", "plaintext"])
    assert not result["quality"]["graph"]["conditions"]["zero_critical_errors_all_runs"]
    assert not result["comparisons"]["plaintext"]["numerical_gate_met"]


def test_unknown_failed_usage_does_not_become_free_tokens():
    roster, records = sample()
    records[0].update(status="ERROR", input_tokens=None, output_tokens=None, cost_usd=None)
    result = report(roster, records, ["graph", "plaintext"])
    assert result["quality"]["graph"]["overall"]["input_tokens"] is None
    assert result["comparisons"]["plaintext"]["interval95"]["input_tokens_ratio"]["upper"] is None
    assert not result["comparisons"]["plaintext"]["numerical_gate_met"]


def test_clarification_only_metrics_require_predeclared_nulls():
    roster, records = sample()
    roster[0]["evidence_applicable"] = False
    with pytest.raises(ValueError):validate(roster, records, ["graph", "plaintext"], 3)
    for row in records:
        if row["task_id"] == "0":row.update(precision=None, recall=None)
    result = report(roster, records, ["graph", "plaintext"])
    assert result["quality"]["graph"]["evidence_applicable_questions"] == 3


def test_each_comparator_and_repository_veto_remain_separate():
    roster, records = sample()
    extra = [dict(row, arm="stronger", input_tokens=50) for row in records if row["arm"] == "plaintext"]
    result = report(roster, records+extra, ["graph", "plaintext", "stronger"])
    assert result["comparisons"]["plaintext"]["numerical_gate_met"]
    assert not result["comparisons"]["stronger"]["numerical_gate_met"]


def test_insufficient_bootstrap_or_repeats_cannot_silently_relax_contract():
    roster, records = sample()
    with pytest.raises(ValueError):report(roster, records, ["graph", "plaintext"], resamples=9999)
    with pytest.raises(ValueError):report(roster, records, ["graph", "plaintext"], repeats=2)
