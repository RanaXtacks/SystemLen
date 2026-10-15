"""Unit tests for Phase D: Confidence Presentation Fix (systemlens/tiers.py)."""

from systemlens.tiers import (
    ConfidenceTier,
    classify_confidence_tier,
    format_evidence_chain,
)
from systemlens.query.impact import ImpactEngine


def test_classify_confidence_tier_high():
    # Deterministic FK only
    assert classify_confidence_tier(["declared_fk"], 1.0) == ConfidenceTier.HIGH
    # Deterministic FK + structural belongs_to
    assert (
        classify_confidence_tier(["declared_fk", "structural_belongs_to"], 1.0)
        == ConfidenceTier.HIGH
    )


def test_classify_confidence_tier_medium():
    # Direct ORM call
    assert classify_confidence_tier(["orm_call"], 0.98) == ConfidenceTier.MEDIUM
    # Direct static SQL string
    assert classify_confidence_tier(["static_sql_string"], 0.96) == ConfidenceTier.MEDIUM
    # Multi-hop FK to ORM call
    assert classify_confidence_tier(["declared_fk", "orm_call"], 0.98) == ConfidenceTier.MEDIUM


def test_classify_confidence_tier_low():
    # Naming inference is heuristic
    assert classify_confidence_tier(["inferred_naming"], 0.92) == ConfidenceTier.LOW
    # Dynamic unresolved query is uncertain
    assert classify_confidence_tier(["dynamic_unresolved"], 0.15) == ConfidenceTier.LOW
    # Multi-hop decayed below 0.70 threshold
    assert classify_confidence_tier(["orm_call"], 0.65) == ConfidenceTier.LOW


def test_format_evidence_chain():
    assert format_evidence_chain([]) == ""
    assert format_evidence_chain(["declared_fk"]) == "via FK"
    assert format_evidence_chain(["declared_fk", "orm_call"]) == "via FK → ORM call"
    assert (
        format_evidence_chain(["declared_fk", "orm_call", "structural_belongs_to"])
        == "via FK → ORM call → file membership"
    )
    assert format_evidence_chain(["static_sql_string"]) == "via static SQL"
    assert format_evidence_chain(["inferred_naming"]) == "via naming inference"


def test_impact_engine_attaches_tiers(tmp_path):
    graph_data = {
        "nodes": [
            {"id": "table:users", "type": "table", "name": "users"},
            {"id": "table:orders", "type": "table", "name": "orders"},
            {"id": "func:get_orders", "type": "function", "name": "get_orders"},
        ],
        "edges": [
            {"source": "table:orders", "target": "table:users", "type": "declared_fk", "confidence": 1.0},
            {"source": "func:get_orders", "target": "table:orders", "type": "orm_call", "confidence": 0.98},
        ],
    }
    engine = ImpactEngine(graph_data)
    result = engine.blast_radius("users")

    # Check orders (reached via declared_fk -> High)
    orders_node = next(n for n in result.impacted_tables if n.name == "orders")
    assert orders_node.tier == "High"
    assert orders_node.formatted_evidence == "via FK"
    assert orders_node.edge_types == ["declared_fk"]
    assert orders_node.confidence == 1.0

    # Check get_orders (reached via FK -> ORM call -> Medium)
    func_node = next(n for n in result.impacted_functions if n.name == "get_orders")
    assert func_node.tier == "Medium"
    assert func_node.formatted_evidence == "via FK → ORM call"
    assert func_node.edge_types == ["declared_fk", "orm_call"]
    assert func_node.confidence == 0.98

    # Check dictionary serialization preserves all fields
    d = func_node.to_dict()
    assert d["tier"] == "Medium"
    assert d["formatted_evidence"] == "via FK → ORM call"
    assert d["confidence"] == 0.98


def test_cli_impact_tier_presentation(capsys):
    from systemlens.cli import main

    ret = main(["impact", "--target", "organizations", "--graph", "benchmark/benchmark_graph.json"])
    assert ret == 0
    captured = capsys.readouterr()

    # Default output must show tiers and evidence, NOT naked percentages
    assert "[HIGH]" in captured.out or "[MEDIUM]" in captured.out
    assert "via " in captured.out


def test_cli_impact_verbose_includes_raw_confidence(capsys):
    from systemlens.cli import main

    ret = main(["impact", "--target", "organizations", "--graph", "benchmark/benchmark_graph.json", "--verbose"])
    assert ret == 0
    captured = capsys.readouterr()

    # Verbose output includes percentage inside the tier tag
    assert "%" in captured.out
    assert "via " in captured.out
