"""Automated Benchmark Runner and Maintainer Evaluation Suite for SystemLens V1.

Implements the Day 21 verification process specified in plan.md and tech.md:
1. Ingests PostgreSQL schema and extracts Python AST dependency graph.
2. Assembles cross-layer unified graph.
3. Queries blast radius for all 8 ground-truth targets.
4. Computes Recall, Precision, Agreement Rate, and Honest Blind-Spot Disclosures.
5. Evaluates PRD Kill Check criteria.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from benchmark.loader import build_benchmark_db_artifacts
from systemlens.adapters.python_ast import PythonASTAdapter
from systemlens.graph import assemble_unified_graph
from systemlens.query.impact import ImpactEngine


def run_benchmark(
    ground_truth_path: str | Path = "benchmark/ground_truth.json",
    schema_sql_path: str | Path = "benchmark/schema.sql",
    code_dir_path: str | Path = "benchmark/app",
    output_graph_path: str | Path = "benchmark/benchmark_graph.json",
    results_output_path: str | Path = "benchmark/benchmark_results.json",
) -> dict[str, Any]:
    """Execute end-to-end benchmark evaluation against ground truth."""
    gt_file = Path(ground_truth_path)
    if not gt_file.exists():
        raise FileNotFoundError(f"Ground truth file not found: {gt_file}")

    gt_data = json.loads(gt_file.read_text(encoding="utf-8"))
    test_cases = gt_data["test_cases"]

    # 1. Build DB layer
    db_nodes, db_edges, raw_cat = build_benchmark_db_artifacts(schema_sql_path)

    # 2. Build Code layer
    py_adapter = PythonASTAdapter(Path(code_dir_path))
    code_nodes = py_adapter.extract_nodes()
    code_edges = py_adapter.extract_edges()

    # 3. Assemble Unified Graph
    graph_dict = assemble_unified_graph(
        db_nodes=db_nodes,
        db_edges=db_edges,
        code_nodes=code_nodes,
        code_edges=code_edges,
    )
    Path(output_graph_path).write_text(json.dumps(graph_dict, indent=2), encoding="utf-8")

    # 4. Instantiate Query Engine
    engine = ImpactEngine.from_graph_file(output_graph_path)

    # 5. Evaluate each test case
    target_results = []
    total_tp = 0
    total_fp = 0
    total_fn = 0
    total_tn = 0
    total_expected = 0
    total_matched = 0

    for tc in test_cases:
        target_name = tc["target_name"]
        target_id = tc["target_id"]
        gt = tc["ground_truth"]

        expected_tables = set(gt.get("expected_dependent_tables", []))
        expected_funcs = set(gt.get("expected_direct_functions", []))
        expected_files = set(gt.get("expected_direct_files", []))
        negative_controls = set(gt.get("negative_controls", []))
        expected_blind_spots = set(gt.get("expected_blind_spots", []))

        # Query blast radius at depth 2
        impact_result = engine.blast_radius(target_name, max_depth=2)

        found_table_ids = {n.node_id for n in impact_result.impacted_tables}
        found_func_ids = {n.node_id for n in impact_result.impacted_functions}
        found_file_ids = {n.node_id for n in impact_result.impacted_files}

        # Evaluate Functions (the core code-to-table wedge)
        tp_funcs = expected_funcs.intersection(found_func_ids)
        fn_funcs = expected_funcs - found_func_ids
        # False positives among negative controls:
        fp_controls = negative_controls.intersection(found_func_ids)
        tn_controls = negative_controls - found_func_ids

        # Evaluate Tables
        tp_tables = expected_tables.intersection(found_table_ids)
        fn_tables = expected_tables - found_table_ids

        # Evaluate Files
        tp_files = expected_files.intersection(found_file_ids)
        fn_files = expected_files - found_file_ids

        # Combined counts for this target
        tc_expected = len(expected_funcs) + len(expected_tables) + len(expected_files)
        tc_tp = len(tp_funcs) + len(tp_tables) + len(tp_files)
        tc_fn = len(fn_funcs) + len(fn_tables) + len(fn_files)
        tc_fp = len(fp_controls)
        tc_tn = len(tn_controls)

        tc_recall = tc_tp / (tc_tp + tc_fn) if (tc_tp + tc_fn) > 0 else 1.0
        tc_precision = tc_tp / (tc_tp + tc_fp) if (tc_tp + tc_fp) > 0 else 1.0
        tc_agreement = tc_tp / tc_expected if tc_expected > 0 else 1.0

        # Blind spots check
        disclosed_blind_spots = len(impact_result.blind_spots) > 0
        dynamic_unresolved_found = False
        for bs in impact_result.blind_spots:
            if bs.get("unresolved_count", 0) > 0:
                dynamic_unresolved_found = True

        target_results.append({
            "target": target_name,
            "target_id": target_id,
            "domain": tc.get("domain", ""),
            "expected_total": tc_expected,
            "true_positives": tc_tp,
            "false_negatives": tc_fn,
            "false_positives": tc_fp,
            "true_negatives": tc_tn,
            "recall": round(tc_recall, 4),
            "precision": round(tc_precision, 4),
            "agreement_rate": round(tc_agreement, 4),
            "missed_functions": list(fn_funcs),
            "missed_tables": list(fn_tables),
            "spurious_controls": list(fp_controls),
            "blind_spots_disclosed": disclosed_blind_spots,
            "dynamic_unresolved_captured": dynamic_unresolved_found,
            "impact_summary": {
                "functions_found": len(found_func_ids),
                "tables_found": len(found_table_ids),
                "files_found": len(found_file_ids),
                "total_impacted": impact_result.total_impacted,
            },
        })

        total_tp += tc_tp
        total_fn += tc_fn
        total_fp += tc_fp
        total_tn += tc_tn
        total_expected += tc_expected
        total_matched += tc_tp

    # Aggregate metrics
    agg_recall = total_tp / (total_tp + total_fn) if (total_tp + total_fn) > 0 else 1.0
    agg_precision = total_tp / (total_tp + total_fp) if (total_tp + total_fp) > 0 else 1.0
    agg_agreement = total_matched / total_expected if total_expected > 0 else 1.0

    # Decision Gates
    gates = {
        "gate_1_recall_above_90": agg_recall >= 0.90,
        "gate_2_precision_above_85": agg_precision >= 0.85,
        "gate_3_agreement_above_85": agg_agreement >= 0.85,
        "gate_4_zero_silent_false_negatives": total_fn == 0,
        "gate_5_blind_spots_guaranteed": all(r["blind_spots_disclosed"] for r in target_results),
    }

    all_passed = all(gates.values())
    verdict = "PASSED_VALIDATION" if all_passed else "FAILED_KILL_CHECK"

    benchmark_summary = {
        "verdict": verdict,
        "metrics": {
            "aggregate_recall": round(agg_recall, 4),
            "aggregate_precision": round(agg_precision, 4),
            "aggregate_agreement_rate": round(agg_agreement, 4),
            "total_expected": total_expected,
            "total_true_positives": total_tp,
            "total_false_negatives": total_fn,
            "total_false_positives": total_fp,
            "total_true_negatives": total_tn,
        },
        "gates": gates,
        "targets": target_results,
        "graph_metrics": graph_dict["metrics"],
    }

    Path(results_output_path).write_text(json.dumps(benchmark_summary, indent=2), encoding="utf-8")
    return benchmark_summary


def print_benchmark_report(summary: dict[str, Any]) -> None:
    """Print beautifully formatted benchmark comparison report."""
    m = summary["metrics"]
    g = summary["gates"]
    print("=" * 80)
    print("  SYSTEMLENS V1 — REAL-WORLD BENCHMARK & MAINTAINER EVALUATION REPORT")
    print("=" * 80)
    print(f"VERDICT: {summary['verdict']}")
    print("-" * 80)
    print(f"  Aggregate Recall:         {m['aggregate_recall'] * 100:.1f}%  (Target: >= 90.0%, Kill: < 80.0%)")
    print(f"  Aggregate Precision:      {m['aggregate_precision'] * 100:.1f}%  (Target: >= 85.0%)")
    print(f"  Aggregate Agreement Rate: {m['aggregate_agreement_rate'] * 100:.1f}%  (Target: >= 85.0%)")
    print(f"  Total True Positives:     {m['total_true_positives']} / {m['total_expected']}")
    print(f"  Total False Negatives:    {m['total_false_negatives']} (Silent breaks prevented)")
    print(f"  Total False Positives:    {m['total_false_positives']} (Among negative controls)")
    print("-" * 80)
    print("DECISION GATES:")
    for gate_name, passed in g.items():
        status = "[PASS]" if passed else "[FAIL]"
        print(f"  {status:7} {gate_name}")
    print("-" * 80)
    print(f"{'Target Entity':<18} | {'Domain':<22} | {'Exp':<4} | {'TP':<4} | {'Recall':<7} | {'Prec':<7} | {'Agree':<7}")
    print("-" * 80)
    for r in summary["targets"]:
        print(
            f"{r['target']:<18} | {r['domain'][:22]:<22} | "
            f"{r['expected_total']:<4} | {r['true_positives']:<4} | "
            f"{r['recall']*100:>5.1f}% | {r['precision']*100:>5.1f}% | {r['agreement_rate']*100:>5.1f}%"
        )
    print("=" * 80)


if __name__ == "__main__":
    summary = run_benchmark()
    print_benchmark_report(summary)
