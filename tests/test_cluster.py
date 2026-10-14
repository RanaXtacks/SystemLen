"""Unit tests for systemlens/cluster.py catalog clustering engine."""

import json
import pytest

from systemlens.cluster import (
    CatalogClusteringResult,
    cluster_catalog,
    cluster_catalog_from_file,
    compute_ari,
    _generate_cluster_label,
)


def test_compute_ari_identical():
    labels_true = {"t1": "auth", "t2": "auth", "t3": "billing", "t4": "billing"}
    labels_pred = {"t1": 0, "t2": 0, "t3": 1, "t4": 1}
    assert compute_ari(labels_true, labels_pred) == 1.0


def test_compute_ari_discordant():
    labels_true = {"t1": "a", "t2": "a", "t3": "b", "t4": "b"}
    labels_pred = {"t1": 1, "t2": 2, "t3": 1, "t4": 2}
    # Completely mixed assignment should yield negative or zero ARI
    ari = compute_ari(labels_true, labels_pred)
    assert ari <= 0.05


def test_cluster_empty_graph():
    result = cluster_catalog({"nodes": [], "edges": []})
    assert result.total_tables == 0
    assert result.total_clusters == 0
    assert result.modularity_q == 0.0


def test_cluster_isolated_tables():
    graph_data = {
        "nodes": [
            {"id": "table:users", "type": "table"},
            {"id": "table:orders", "type": "table"},
            {"id": "table:products", "type": "table"},
        ],
        "edges": [],
    }
    result = cluster_catalog(graph_data, include_naming_prefix=False)
    assert result.total_tables == 3
    # With no edges, each table is isolated
    assert len(result.isolated_tables) == 3
    assert result.modularity_q == 0.0


def test_cluster_two_distinct_communities():
    # Community 1: Users, Accounts, Permissions
    # Community 2: Orders, Invoices, Payments
    graph_data = {
        "nodes": [
            {"id": "table:users", "type": "table"},
            {"id": "table:accounts", "type": "table"},
            {"id": "table:permissions", "type": "table"},
            {"id": "table:orders", "type": "table"},
            {"id": "table:invoices", "type": "table"},
            {"id": "table:payments", "type": "table"},
        ],
        "edges": [
            # Dense connections within Comm 1
            {"source": "table:users", "target": "table:accounts", "confidence": 1.0},
            {"source": "table:users", "target": "table:permissions", "confidence": 0.95},
            {"source": "table:accounts", "target": "table:permissions", "confidence": 0.9},
            # Dense connections within Comm 2
            {"source": "table:orders", "target": "table:invoices", "confidence": 1.0},
            {"source": "table:orders", "target": "table:payments", "confidence": 0.95},
            {"source": "table:invoices", "target": "table:payments", "confidence": 0.9},
            # Sparse cross-edge between orders and users
            {"source": "table:orders", "target": "table:users", "confidence": 0.2},
        ],
    }
    result = cluster_catalog(graph_data, resolution=1.0, seed=42, include_naming_prefix=False)
    assert result.total_tables == 6
    assert result.total_clusters == 2
    # Modularity Q must be high (> 0.3) for two well-separated communities
    assert result.modularity_q > 0.3

    # Check that members partitioned correctly
    cluster_tables = [set(c.tables) for c in result.clusters]
    assert {"users", "accounts", "permissions"} in cluster_tables
    assert {"orders", "invoices", "payments"} in cluster_tables


def test_generate_cluster_label():
    label1 = _generate_cluster_label(["order_lines", "orders", "order_discounts"], "orders")
    assert "Order" in label1

    label2 = _generate_cluster_label(["account_user", "account_profile"], "account_user")
    assert "Account" in label2

    single_label = _generate_cluster_label(["shipping"], "shipping")
    assert single_label == "Shipping Module"


def test_cluster_catalog_from_file_benchmark(tmp_path):
    benchmark_graph = {
        "nodes": [
            {"id": "table:public.users", "type": "table"},
            {"id": "table:public.user_roles", "type": "table"},
            {"id": "table:public.orders", "type": "table"},
            {"id": "table:public.order_items", "type": "table"},
        ],
        "edges": [
            {"source": "table:public.users", "target": "table:public.user_roles", "confidence": 1.0},
            {"source": "table:public.orders", "target": "table:public.order_items", "confidence": 1.0},
        ],
    }
    test_file = tmp_path / "test_graph.json"
    test_file.write_text(json.dumps(benchmark_graph), encoding="utf-8")

    result = cluster_catalog_from_file(str(test_file), seed=42)
    assert result.total_tables == 4
    assert result.total_clusters == 2
    assert result.modularity_q > 0.3
    d = result.to_dict()
    assert "modularity_q" in d
    assert "clusters" in d


def test_saleor_clustering_validation_gate():
    """Verify that Saleor test schema passes Phase C acceptance criteria (Q > 0.3 and ARI > 0.6)."""
    from tests.validation.validate_clusters import run_clustering_validation

    report = run_clustering_validation(report_output=None)
    assert report["modularity_passed"] is True
    assert report["modularity_q"] >= 0.30
    assert report["ari_passed"] is True
    assert report["adjusted_rand_index"] >= 0.60
    assert report["all_gates_passed"] is True


def test_cli_cluster_subcommand(capsys):
    """Verify that systemlens cluster command executes cleanly on benchmark graph."""
    from systemlens.cli import main

    ret = main(["cluster", "--graph", "benchmark/benchmark_graph.json"])
    assert ret == 0
    captured = capsys.readouterr()
    assert "SystemLens Catalog Clustering Engine" in captured.out
    assert "Modularity Q:" in captured.out
    assert "[CLUSTER_" in captured.out
