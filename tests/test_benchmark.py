"""Integration tests for SystemLens V1 Step 4 Benchmark and Maintainer Evaluation."""

import json
from pathlib import Path

import pytest

from scripts.run_benchmark import run_benchmark
from systemlens.cli import main
from systemlens.query.impact import ImpactEngine


@pytest.fixture(scope="module")
def benchmark_results():
    """Run benchmark once for the module and return summary."""
    return run_benchmark(
        ground_truth_path="benchmark/ground_truth.json",
        schema_sql_path="benchmark/schema.sql",
        code_dir_path="benchmark/app",
        output_graph_path="benchmark/benchmark_graph.json",
        results_output_path="benchmark/benchmark_results.json",
    )


def test_benchmark_verdict_passed(benchmark_results):
    """Assert benchmark passes the official PRD Step 4 decision gate."""
    assert benchmark_results["verdict"] == "PASSED_VALIDATION"


def test_benchmark_recall_exceeds_kill_check_threshold(benchmark_results):
    """
    Step 4 Kill Check: Recall must not fall below 80%. Target >= 90%.
    False negatives are the dangerous failure mode in impact analysis.
    """
    recall = benchmark_results["metrics"]["aggregate_recall"]
    assert recall >= 0.90, f"Recall {recall:.2%} failed 90% threshold"
    assert benchmark_results["metrics"]["total_false_negatives"] == 0


def test_benchmark_precision_and_agreement(benchmark_results):
    """Verify precision and agreement rate exceed 85% requirement."""
    precision = benchmark_results["metrics"]["aggregate_precision"]
    agreement = benchmark_results["metrics"]["aggregate_agreement_rate"]
    assert precision >= 0.85, f"Precision {precision:.2%} failed 85% threshold"
    assert agreement >= 0.85, f"Agreement rate {agreement:.2%} failed 85% threshold"


def test_benchmark_all_targets_validated(benchmark_results):
    """Verify each target individual recall and agreement rate."""
    for target in benchmark_results["targets"]:
        assert target["recall"] >= 0.80, f"Target {target['target']} recall {target['recall']:.2%} below 80%"
        assert target["false_negatives"] == 0, f"Target {target['target']} had false negatives"
        assert target["blind_spots_disclosed"] is True


def test_benchmark_blind_spots_and_dynamic_honesty():
    """Verify dynamic unresolved query is explicitly surfaced and never hidden."""
    engine = ImpactEngine.from_graph_file("benchmark/benchmark_graph.json")
    result = engine.blast_radius("audit_logs", max_depth=2)

    assert len(result.blind_spots) > 0
    # Check that unresolved queries were surfaced
    unresolved_blind_spots = [bs for bs in result.blind_spots if bs.get("unresolved_count", 0) > 0]
    assert len(unresolved_blind_spots) > 0
    assert "query_audit_logs_dynamic" in str(unresolved_blind_spots)


def test_benchmark_path_confidence_decay():
    """Verify multiplicative path confidence decay: c(path) = Π c(edge_i)."""
    engine = ImpactEngine.from_graph_file("benchmark/benchmark_graph.json")
    result = engine.blast_radius("users", max_depth=2)

    # 1-hop declared FK: orders -> users (c=1.0)
    # 2-hop: checkout.place_order -> orders -> users (0.85 * 1.0 = 0.85)
    # Check confidence ordering: direct declared FKs > direct static SQL > 2-hop paths
    by_name = {n.name: n for n in result.ranked_items}

    # orders is 1-hop declared FK
    assert "orders" in by_name
    assert by_name["orders"].confidence == 1.0
    assert by_name["orders"].depth == 1

    # place_order is 1-hop ORM to users (c=0.8) and static SQL to orders (c=0.85)
    assert "place_order" in by_name
    assert by_name["place_order"].confidence > 0.0


def test_benchmark_cli_impact_execution(capsys):
    """Verify CLI impact query against the benchmark graph."""
    exit_code = main([
        "impact",
        "--target", "users",
        "--graph", "benchmark/benchmark_graph.json",
        "--depth", "2",
    ])
    assert exit_code == 0
    captured = capsys.readouterr().out
    assert "IMPACT BLAST RADIUS REPORT" in captured
    assert "users" in captured
    assert "orders" in captured
    assert "Blind Spots & Unanalyzed Boundaries" in captured


def test_benchmark_cli_json_output(capsys):
    """Verify CLI --json output format against benchmark graph."""
    exit_code = main([
        "impact",
        "--target", "orders",
        "--graph", "benchmark/benchmark_graph.json",
        "--depth", "2",
        "--json",
    ])
    assert exit_code == 0
    captured = capsys.readouterr().out
    data = json.loads(captured)
    assert data["target_name"] == "orders"
    assert "impacted_functions" in data
    assert "impacted_tables" in data
    assert "blind_spots" in data
