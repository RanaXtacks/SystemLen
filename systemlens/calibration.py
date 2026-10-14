"""Calibration and reliability metrics for SystemLens confidence scoring.

Provides:
1. Brier score computation: (1/N) * sum((predicted_i - actual_i)^2)
2. Calibration curve decile calculation: predicted confidence vs observed accuracy
3. Calibration gate evaluation against empirical tolerance (within roughly ±15% of the diagonal)
"""

from __future__ import annotations

import math
from typing import Any, Sequence


def compute_brier_score(
    predictions: Sequence[float],
    actuals: Sequence[bool | int],
) -> float:
    """
    Compute Brier score: mean squared error of probability predictions.

    Args:
        predictions: List of predicted confidence scores in [0.0, 1.0].
        actuals: List of ground-truth outcomes (True/1 for valid, False/0 for invalid).

    Returns:
        Brier score in [0.0, 1.0], where 0.0 is perfect calibration, and 0.25 is
        uninformative (50/50) random guessing.
    """
    if len(predictions) != len(actuals):
        raise ValueError(
            f"Length mismatch: {len(predictions)} predictions vs {len(actuals)} actuals"
        )
    if not predictions:
        return 0.0

    total_error = sum(
        (p - (1.0 if a else 0.0)) ** 2 for p, a in zip(predictions, actuals)
    )
    return round(total_error / len(predictions), 4)


def compute_calibration_curve(
    predictions: Sequence[float],
    actuals: Sequence[bool | int],
    num_buckets: int = 10,
    tolerance: float = 0.15,
    min_bucket_samples: int = 10,
) -> list[dict[str, Any]]:
    """
    Compute calibration curve across confidence deciles.

    Args:
        predictions: Predicted confidence scores in [0.0, 1.0].
        actuals: Binary ground truth labels.
        num_buckets: Number of confidence deciles/bins (default: 10).
        tolerance: Maximum allowable difference from diagonal (default: 0.15 / ±15%).
        min_bucket_samples: Minimum sample size required to evaluate tolerance (default: 10).

    Returns:
        List of bucket dicts with mean prediction, observed accuracy, count, and status.
    """
    if len(predictions) != len(actuals):
        raise ValueError("Length mismatch between predictions and actuals")

    buckets: list[list[tuple[float, int]]] = [[] for _ in range(num_buckets)]

    for p, a in zip(predictions, actuals):
        # Clip to [0.0, 1.0]
        clamped_p = max(0.0, min(1.0, float(p)))
        # Index in [0, num_buckets - 1]
        b_idx = min(int(clamped_p * num_buckets), num_buckets - 1)
        actual_val = 1 if a else 0
        buckets[b_idx].append((clamped_p, actual_val))

    results: list[dict[str, Any]] = []

    for idx, b in enumerate(buckets):
        low = idx / num_buckets
        high = (idx + 1) / num_buckets
        range_str = f"[{low:.1f}, {high:.1f})" if high < 1.0 else f"[{low:.1f}, {high:.1f}]"

        count = len(b)
        if count == 0:
            results.append({
                "bucket_index": idx,
                "range": range_str,
                "count": 0,
                "mean_predicted": None,
                "observed_accuracy": None,
                "calibration_error": None,
                "adequate_sample": False,
                "within_tolerance": True,
            })
            continue

        mean_pred = sum(p for p, _ in b) / count
        obs_acc = sum(act for _, act in b) / count
        error = abs(mean_pred - obs_acc)
        adequate = count >= min_bucket_samples
        within_tol = error <= tolerance if adequate else True

        results.append({
            "bucket_index": idx,
            "range": range_str,
            "count": count,
            "mean_predicted": round(mean_pred, 4),
            "observed_accuracy": round(obs_acc, 4),
            "calibration_error": round(error, 4),
            "adequate_sample": adequate,
            "within_tolerance": within_tol,
        })

    return results


def evaluate_calibration(
    predictions: Sequence[float],
    actuals: Sequence[bool | int],
    tolerance: float = 0.15,
    min_bucket_samples: int = 10,
) -> dict[str, Any]:
    """
    Evaluate complete calibration report including Brier score and deciles.
    """
    brier = compute_brier_score(predictions, actuals)
    curve = compute_calibration_curve(
        predictions=predictions,
        actuals=actuals,
        tolerance=tolerance,
        min_bucket_samples=min_bucket_samples,
    )

    # Check if all adequately-sampled buckets satisfy the tolerance
    evaluated_buckets = [b for b in curve if b["adequate_sample"]]
    all_passed = all(b["within_tolerance"] for b in evaluated_buckets)

    return {
        "total_samples": len(predictions),
        "brier_score": brier,
        "tolerance": tolerance,
        "min_bucket_samples": min_bucket_samples,
        "calibration_passed": all_passed,
        "deciles": curve,
    }
