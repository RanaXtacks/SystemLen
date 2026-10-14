"""Tests for Phase A Validation Harness."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.validation.validate import (
    ACCEPTANCE_THRESHOLDS,
    evaluate_edge_type,
    main,
    run_validation,
    wilson_interval,
)


def test_wilson_interval_exact_boundaries():
    """Verify Wilson interval calculation against known analytical test cases."""
    # 1. Perfect precision on n=50 (e.g. 50/50): lower bound should be 0.9286
    center, lower, upper = wilson_interval(p_hat=1.0, n=50, z=1.96)
    assert round(lower, 4) == 0.9286
    assert round(upper, 4) == 1.0000

    # 2. 50% on n=100 (e.g. 50/100): symmetric around 0.50
    center, lower, upper = wilson_interval(p_hat=0.5, n=100, z=1.96)
    assert round(center, 4) == 0.5000
    assert round(lower, 4) == 0.4038
    assert round(upper, 4) == 0.5962

    # 3. Zero sample size edge case
    center, lower, upper = wilson_interval(p_hat=0.0, n=0)
    assert (center, lower, upper) == (0.0, 0.0, 0.0)


def test_evaluate_edge_type_pass_and_fail():
    """Test that evaluate_edge_type correctly evaluates gate thresholds."""
    # 50 samples with 48 true positives -> precision 0.96 -> lower bound 0.8654 >= 0.80 -> PASS
    passing_edges = [{"ground_truth_label": True}] * 48 + [{"ground_truth_label": False}] * 2
    res_pass = evaluate_edge_type("orm_call", passing_edges, target_lower_bound=0.80)
    assert res_pass["gate_passed"] is True
    assert res_pass["precision"] == 0.96
    assert res_pass["wilson_interval"]["lower_bound"] >= 0.80

    # 50 samples with 30 true positives -> precision 0.60 -> lower bound < 0.80 -> FAIL
    failing_edges = [{"ground_truth_label": True}] * 30 + [{"ground_truth_label": False}] * 20
    res_fail = evaluate_edge_type("orm_call", failing_edges, target_lower_bound=0.80)
    assert res_fail["gate_passed"] is False
    assert res_fail["wilson_interval"]["lower_bound"] < 0.80


def test_run_validation_end_to_end(tmp_path):
    """Test full validation run against ground_truth.json."""
    report_file = tmp_path / "test_report.json"
    report = run_validation(output_report_file=report_file)

    assert report["overall_gate_passed"] is True
    assert report_file.exists()

    # Verify each edge type in report
    results_by_type = {r["edge_type"]: r for r in report["results"]}

    for edge_type, threshold in ACCEPTANCE_THRESHOLDS.items():
        assert edge_type in results_by_type
        r = results_by_type[edge_type]
        assert r["sample_size"] == 50
        assert r["gate_passed"] is True
        assert r["wilson_interval"]["lower_bound"] >= threshold


def test_validation_cli_main(tmp_path):
    """Test CLI main() execution of validate.py."""
    out_file = tmp_path / "cli_report.json"
    ret = main(["--output", str(out_file)])
    assert ret == 0
    assert out_file.exists()
