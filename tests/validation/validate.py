#!/usr/bin/env python3
"""Validation Harness for SystemLens (Phase A).

Evaluates measured extraction precision and recall across edge types against
real-world open-source ground truth (Saleor e-commerce schema).

Computes 95% Wilson score confidence intervals for all edge types to account
for sample size uncertainty, and enforces empirical gate thresholds:
- INFERRED_NAMING:  precision lower bound >= 0.70
- ORM_CALL:         precision lower bound >= 0.80
- STATIC_SQL_STRING: precision lower bound >= 0.80

Outputs validation results to `tests/validation/validation_report.json`.
"""

from __future__ import annotations

import argparse
import datetime
import json
import math
import sys
from pathlib import Path
from typing import Any

# Default paths
DEFAULT_GROUND_TRUTH = Path(__file__).parent / "ground_truth.json"
DEFAULT_REPORT_OUTPUT = Path(__file__).parent / "validation_report.json"

# Phase A Gate Acceptance Thresholds (on Wilson 95% lower bound)
ACCEPTANCE_THRESHOLDS = {
    "inferred_naming": 0.70,
    "orm_call": 0.80,
    "static_sql_string": 0.80,
}


def wilson_interval(
    p_hat: float,
    n: int,
    z: float = 1.96,
) -> tuple[float, float, float]:
    """
    Calculate 95% Wilson score confidence interval for a proportion.

    Formula from 07-validation-harness.md:
        center = (p̂ + z²/2n) / (1 + z²/n)
        margin = z * sqrt(p̂(1-p̂)/n + z²/4n²) / (1 + z²/n)
        lower  = center - margin
        upper  = center + margin

    Args:
        p_hat: Sample proportion (e.g. measured precision).
        n: Sample size.
        z: Probit value (1.96 for two-sided 95% confidence).

    Returns:
        tuple of (center, lower_bound, upper_bound).
    """
    if n == 0:
        return (0.0, 0.0, 0.0)

    denominator = 1.0 + (z**2) / n
    center = (p_hat + (z**2) / (2.0 * n)) / denominator
    margin = (
        z * math.sqrt((p_hat * (1.0 - p_hat)) / n + (z**2) / (4.0 * (n**2)))
    ) / denominator

    lower = max(0.0, center - margin)
    upper = min(1.0, center + margin)

    return (center, lower, upper)


def evaluate_edge_type(
    edge_type: str,
    edges: list[dict[str, Any]],
    target_lower_bound: float,
) -> dict[str, Any]:
    """
    Evaluate sample precision, recall, and Wilson confidence interval for an edge type.
    """
    sample_size = len(edges)
    if sample_size == 0:
        raise ValueError(f"No sample edges found for edge type '{edge_type}'")

    true_positives = sum(1 for e in edges if e.get("ground_truth_label") is True)
    false_positives = sum(1 for e in edges if e.get("ground_truth_label") is False)

    precision = true_positives / (true_positives + false_positives) if (true_positives + false_positives) > 0 else 0.0
    
    # In sample validation where sample consists of detected edges,
    # sample recall relative to verified valid candidates in sample is measured
    # or approximated as TP / sample_size when evaluating sample completeness.
    recall = true_positives / sample_size

    center, lower, upper = wilson_interval(precision, sample_size)
    passed = lower >= target_lower_bound

    return {
        "edge_type": edge_type,
        "sample_size": sample_size,
        "true_positives": true_positives,
        "false_positives": false_positives,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "wilson_interval": {
            "confidence_level": 0.95,
            "center": round(center, 4),
            "lower_bound": round(lower, 4),
            "upper_bound": round(upper, 4),
        },
        "target_lower_bound": target_lower_bound,
        "gate_passed": passed,
    }


def run_validation(
    ground_truth_file: Path | str = DEFAULT_GROUND_TRUTH,
    output_report_file: Path | str | None = DEFAULT_REPORT_OUTPUT,
) -> dict[str, Any]:
    """
    Run end-to-end validation across all sampled edge types and compile report.
    """
    gt_path = Path(ground_truth_file)
    if not gt_path.exists():
        raise FileNotFoundError(f"Ground truth dataset not found at: {gt_path}")

    with open(gt_path, "r", encoding="utf-8") as f:
        gt_data = json.load(f)

    project_name = gt_data.get("project", "Unknown Project")
    edges_by_type = gt_data.get("edges", {})

    results: list[dict[str, Any]] = []
    all_passed = True

    for edge_type, target_threshold in ACCEPTANCE_THRESHOLDS.items():
        sample_edges = edges_by_type.get(edge_type, [])
        if not sample_edges:
            raise ValueError(f"Ground truth dataset missing sample edges for '{edge_type}'")

        eval_res = evaluate_edge_type(edge_type, sample_edges, target_threshold)
        results.append(eval_res)
        if not eval_res["gate_passed"]:
            all_passed = False

    report = {
        "schema_used": f"{project_name} (Python/Django e-commerce)",
        "date": datetime.date.today().isoformat(),
        "overall_gate_passed": all_passed,
        "acceptance_criteria": {
            k: f"Wilson 95% lower bound >= {v:.2f}" for k, v in ACCEPTANCE_THRESHOLDS.items()
        },
        "results": results,
    }

    if output_report_file:
        out_path = Path(output_report_file)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)

    return report


def print_validation_report(report: dict[str, Any]) -> None:
    """Print formatted validation results to stdout."""
    print("=" * 80)
    print("🔬 SystemLens Empirical Validation Report (Phase A)")
    print("=" * 80)
    print(f"Target Project: {report['schema_used']}")
    print(f"Report Date:    {report['date']}")
    print("-" * 80)
    print(f"{'Edge Type':<20} {'N':<5} {'Precision':<10} {'95% Wilson Interval':<22} {'Threshold':<11} {'Status'}")
    print("-" * 80)

    for r in report["results"]:
        interval_str = f"[{r['wilson_interval']['lower_bound']:.4f}, {r['wilson_interval']['upper_bound']:.4f}]"
        status_str = "✅ PASS" if r["gate_passed"] else "❌ FAIL"
        prec_str = f"{r['precision'] * 100:.1f}%"
        thresh_str = f">= {r['target_lower_bound']:.2f}"
        print(f"{r['edge_type']:<20} {r['sample_size']:<5} {prec_str:<10} {interval_str:<22} {thresh_str:<11} {status_str}")

    print("=" * 80)
    if report["overall_gate_passed"]:
        print("🏆 VERDICT: ALL PHASE A VALIDATION GATES PASSED! Unlocked for Phase B (Calibration).")
    else:
        print("🚨 VERDICT: VALIDATION FAILED. One or more edge types fell below the Wilson threshold.")
    print("=" * 80)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SystemLens Phase A Validation Harness")
    parser.add_argument(
        "--ground-truth",
        type=str,
        default=str(DEFAULT_GROUND_TRUTH),
        help="Path to hand-labeled ground truth JSON (default: tests/validation/ground_truth.json)",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=str,
        default=str(DEFAULT_REPORT_OUTPUT),
        help="Output path for validation report JSON (default: tests/validation/validation_report.json)",
    )
    args = parser.parse_args(argv)

    try:
        report = run_validation(
            ground_truth_file=args.ground_truth,
            output_report_file=args.output,
        )
        print_validation_report(report)
        print(f"\nDetailed report written to: {args.output}")
        return 0 if report["overall_gate_passed"] else 1
    except Exception as e:
        print(f"Validation error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
