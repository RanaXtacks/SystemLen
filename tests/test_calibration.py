"""Unit tests for Phase B Weight Calibration and Reliability Module."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from systemlens.calibration import (
    compute_brier_score,
    compute_calibration_curve,
    evaluate_calibration,
)
from tests.validation.calibrate import main, run_calibration


def test_brier_score_known_cases():
    """Verify Brier score calculation on standard boundary test cases."""
    # 1. Perfect predictions (Brier = 0.0)
    assert compute_brier_score([1.0, 0.0, 1.0], [1, 0, 1]) == 0.0

    # 2. Complete inverted predictions (Brier = 1.0)
    assert compute_brier_score([1.0, 0.0], [0, 1]) == 1.0

    # 3. 50/50 guessing on binary outcomes (Brier = 0.25)
    assert compute_brier_score([0.5, 0.5, 0.5, 0.5], [1, 0, 1, 0]) == 0.25

    # 4. Empty predictions
    assert compute_brier_score([], []) == 0.0


def test_brier_score_length_mismatch():
    """Verify length mismatch raises ValueError."""
    with pytest.raises(ValueError, match="Length mismatch"):
        compute_brier_score([0.8, 0.9], [1])


def test_calibration_curve_deciles():
    """Verify decile bucketing and accuracy calculation."""
    predictions = [0.85] * 10 + [0.95] * 10
    actuals = [1] * 8 + [0] * 2 + [1] * 10  # 80% on 0.85, 100% on 0.95

    curve = compute_calibration_curve(
        predictions, actuals, num_buckets=10, min_bucket_samples=5
    )

    # Bucket 8: [0.8, 0.9)
    b8 = curve[8]
    assert b8["count"] == 10
    assert b8["mean_predicted"] == 0.85
    assert b8["observed_accuracy"] == 0.80
    assert b8["calibration_error"] == 0.05
    assert b8["within_tolerance"] is True

    # Bucket 9: [0.9, 1.0]
    b9 = curve[9]
    assert b9["count"] == 10
    assert b9["mean_predicted"] == 0.95
    assert b9["observed_accuracy"] == 1.00
    assert b9["calibration_error"] == 0.05
    assert b9["within_tolerance"] is True


def test_evaluate_calibration_passes_gate(tmp_path):
    """Verify evaluate_calibration gate check on realistic well-calibrated predictions."""
    # High confidence predictions matching actual accuracy within ±15%
    preds = [0.92] * 50
    acts = [1] * 46 + [0] * 4  # 92% observed accuracy (error = 0.0)

    result = evaluate_calibration(preds, acts, tolerance=0.15, min_bucket_samples=10)
    assert result["calibration_passed"] is True
    assert result["brier_score"] < 0.10


def test_run_calibration_end_to_end(tmp_path):
    """Test full calibration run and report generation."""
    out_report = tmp_path / "calibration_report.json"
    report = run_calibration(output_report_file=out_report)

    assert report["overall_calibration_passed"] is True
    assert out_report.exists()
    assert report["edge_level"]["brier_score"] < 0.10
    assert report["path_level"]["brier_score"] < 0.15


def test_calibrate_cli_main(tmp_path):
    """Test calibrate.py CLI entrypoint."""
    out_report = tmp_path / "cli_calibration.json"
    ret = main(["--output", str(out_report)])
    assert ret == 0
    assert out_report.exists()
