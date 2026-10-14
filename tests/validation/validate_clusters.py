"""Validation script for Phase C Catalog Clustering Engine.

Evaluates Louvain community detection against ground truth module boundaries
of the test schema (Saleor) to verify Modularity Q > 0.3 and Adjusted Rand Index (ARI) > 0.6.
"""

from collections import defaultdict
import json
import os
import sys
from typing import Any, Dict

from systemlens.cluster import cluster_catalog, compute_ari


def run_clustering_validation(
    catalog_path: str = "scratch/saleor_models_catalog.json",
    report_output: str = "tests/validation/clustering_report.json",
) -> Dict[str, Any]:
    """Execute clustering validation on the test schema and generate report."""
    if not os.path.exists(catalog_path):
        raise FileNotFoundError(f"Test schema catalog not found at: {catalog_path}")

    with open(catalog_path, "r", encoding="utf-8") as f:
        catalog_data = json.load(f)

    models = catalog_data.get("models", {})
    model_to_table = {k: m["table"] for k, m in models.items() if m.get("table")}
    table_to_app = {m["table"]: m["app"] for m in models.values() if m.get("table")}

    # Build unified graph for Saleor
    nodes = [{"id": f"table:{t}", "type": "table"} for t in table_to_app]
    edges = []

    # 1. Foreign keys (calibrated weight: 1.0)
    for m_name, m in models.items():
        src_table = m.get("table")
        if not src_table:
            continue
        for fk in m.get("fks", []):
            tgt_m = fk.get("target_model")
            tgt_table = None
            if tgt_m in model_to_table:
                tgt_table = model_to_table[tgt_m]
            elif tgt_m == "AUTH_USER_MODEL":
                tgt_table = "account_user"
            elif tgt_m and tgt_m.lower() in [t.split("_")[-1] for t in table_to_app]:
                candidates = [
                    t for t in table_to_app if t.endswith("_" + tgt_m.lower()) or t == tgt_m.lower()
                ]
                if candidates:
                    tgt_table = candidates[0]

            if tgt_table and tgt_table in table_to_app and tgt_table != src_table:
                edges.append(
                    {
                        "source": f"table:{src_table}",
                        "target": f"table:{tgt_table}",
                        "type": "declared_fk",
                        "confidence": 1.0,
                    }
                )

    graph_data = {"nodes": nodes, "edges": edges}

    # Run clustering
    clustering_res = cluster_catalog(
        graph_data=graph_data,
        resolution=1.0,
        seed=42,
        include_code_cooccurrence=False,
        include_naming_prefix=True,
        naming_prefix_weight=0.92,
    )

    # Build predicted labels dictionary
    pred_labels: Dict[str, int] = {}
    for cluster_idx, cluster in enumerate(clustering_res.clusters):
        for table in cluster.tables:
            pred_labels[table] = cluster_idx

    for isolated_idx, table in enumerate(clustering_res.isolated_tables, start=len(clustering_res.clusters)):
        pred_labels[table] = isolated_idx

    # Compute ARI
    ari_score = compute_ari(table_to_app, pred_labels)

    q_threshold = 0.30
    ari_threshold = 0.60

    q_passed = clustering_res.modularity_q >= q_threshold
    ari_passed = ari_score >= ari_threshold
    all_passed = q_passed and ari_passed

    report = {
        "target_schema": "Saleor",
        "total_tables": len(table_to_app),
        "total_clusters": clustering_res.total_clusters,
        "modularity_q": round(clustering_res.modularity_q, 4),
        "modularity_threshold": q_threshold,
        "modularity_passed": q_passed,
        "adjusted_rand_index": round(ari_score, 4),
        "ari_threshold": ari_threshold,
        "ari_passed": ari_passed,
        "all_gates_passed": all_passed,
        "clusters": [
            {
                "id": c.id,
                "label": c.label,
                "hub_table": c.hub_table,
                "size": c.size,
                "tables": c.tables,
            }
            for c in clustering_res.clusters
        ],
        "isolated_tables": clustering_res.isolated_tables,
    }

    if report_output:
        os.makedirs(os.path.dirname(os.path.abspath(report_output)), exist_ok=True)
        with open(report_output, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)

    return report


def print_clustering_report(report: Dict[str, Any]) -> None:
    """Print clean ASCII summary of the clustering validation."""
    print("=" * 80)
    print("SystemLens Catalog Clustering Validation Report (Phase C)")
    print("=" * 80)
    print(f"Target Schema:   {report['target_schema']}")
    print(f"Total Tables:    {report['total_tables']}")
    print(f"Detected Groups: {report['total_clusters']}")
    print("-" * 80)
    print(f"Modularity (Q):  {report['modularity_q']:.4f}  (Threshold: >= {report['modularity_threshold']})  "
          f"[{'PASS' if report['modularity_passed'] else 'FAIL'}]")
    print(f"Adjusted Rand:   {report['adjusted_rand_index']:.4f}  (Threshold: >= {report['ari_threshold']})  "
          f"[{'PASS' if report['ari_passed'] else 'FAIL'}]")
    print("-" * 80)
    print("\nDetected Catalog Modules:")
    for c in report["clusters"]:
        preview = ", ".join(c["tables"][:5])
        if len(c["tables"]) > 5:
            preview += f", ... (+{len(c['tables']) - 5} more)"
        print(f"  * {c['label']:<32} [Hub: {c['hub_table']}] ({c['size']} tables)")
        print(f"    Members: {preview}")

    if report["isolated_tables"]:
        print(f"\n  * Isolated Singletons ({len(report['isolated_tables'])} tables):")
        print(f"    {', '.join(report['isolated_tables'])}")

    print("\n" + "=" * 80)
    if report["all_gates_passed"]:
        print("VERDICT: ALL PHASE C CLUSTERING GATES PASSED! Unlocked for Phase D.")
    else:
        print("VERDICT: GATES FAILED. Review community structure or weights.")
    print("=" * 80)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    report = run_clustering_validation()
    print_clustering_report(report)
    print(f"\nDetailed report written to: {os.path.abspath('tests/validation/clustering_report.json')}")
    if not report["all_gates_passed"]:
        sys.exit(1)
