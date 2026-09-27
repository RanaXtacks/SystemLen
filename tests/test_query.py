"""Tests for SystemLens Impact Query Engine and Blast Radius Analysis (Step 3).

Tests:
1. Target resolution (bare table name, schema-qualified name, exact node ID).
2. 1-hop direct reachability (FK, static SQL, ORM).
3. 2-hop multiplicative path confidence decay: c(path) = Π c(edge_i).
4. Depth bounding (depth=1 vs depth=2).
5. Dynamic query lower confidence ranking.
6. Mandatory blind-spot disclosure invariant (never empty, surfaces dynamic SQL).
7. CLI `systemlens impact` command execution (text & JSON output).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from systemlens.cli import main
from systemlens.models import EdgeType, NodeType
from systemlens.query.impact import ImpactEngine, ImpactResult


@pytest.fixture
def sample_cross_layer_graph() -> dict:
    """A multi-hop cross-layer test graph with DB tables, foreign keys, SQL, ORM, and files."""
    return {
        "nodes": [
            # Tables
            {"id": "table:public.users", "type": "table", "name": "users", "source_system": "postgres"},
            {"id": "table:public.orders", "type": "table", "name": "orders", "source_system": "postgres"},
            {"id": "table:public.order_items", "type": "table", "name": "order_items", "source_system": "postgres"},
            {"id": "table:public.products", "type": "table", "name": "products", "source_system": "postgres"},
            {"id": "table:public.categories", "type": "table", "name": "categories", "source_system": "postgres"},
            {"id": "table:unresolved", "type": "table", "name": "<unresolved_dynamic_query>", "source_system": "python"},
            # Code functions
            {"id": "func:services.py:get_user_profile", "type": "function", "name": "get_user_profile", "source_system": "python", "metadata": {"file": "services.py", "lineno": 10}},
            {"id": "func:services.py:create_order", "type": "function", "name": "create_order", "source_system": "python", "metadata": {"file": "services.py", "lineno": 25}},
            {"id": "func:legacy.py:run_dynamic_report", "type": "function", "name": "run_dynamic_report", "source_system": "python", "metadata": {"file": "legacy.py", "lineno": 50}},
            # Files
            {"id": "file:services.py", "type": "file", "name": "services.py", "source_system": "python"},
            {"id": "file:legacy.py", "type": "file", "name": "legacy.py", "source_system": "python"},
        ],
        "edges": [
            # DB Relational edges:
            # orders -> users (declared FK, conf=1.0)
            {"source": "table:public.orders", "target": "table:public.users", "type": "declared_fk", "confidence": 1.0, "evidence": "FK"},
            # order_items -> orders (declared FK, conf=1.0)
            {"source": "table:public.order_items", "target": "table:public.orders", "type": "declared_fk", "confidence": 1.0, "evidence": "FK"},
            # products -> categories (inferred naming, conf=0.55)
            {"source": "table:public.products", "target": "table:public.categories", "type": "inferred_naming", "confidence": 0.55, "evidence": "Naming inference"},

            # Code to DB edges:
            # get_user_profile -> users (static SQL, conf=0.85)
            {"source": "func:services.py:get_user_profile", "target": "table:public.users", "type": "static_sql_string", "confidence": 0.85, "evidence": "SELECT * FROM users"},
            # create_order -> orders (ORM call, conf=0.80)
            {"source": "func:services.py:create_order", "target": "table:public.orders", "type": "orm_call", "confidence": 0.80, "evidence": "Order.objects.create()"},
            # run_dynamic_report -> table:unresolved (dynamic query, conf=0.15)
            {"source": "func:legacy.py:run_dynamic_report", "target": "table:unresolved", "type": "dynamic_unresolved", "confidence": 0.15, "evidence": "cursor.execute(sql_var)"},

            # Structural edges:
            {"source": "func:services.py:get_user_profile", "target": "file:services.py", "type": "structural_belongs_to", "confidence": 1.0, "evidence": "belongs to"},
            {"source": "func:services.py:create_order", "target": "file:services.py", "type": "structural_belongs_to", "confidence": 1.0, "evidence": "belongs to"},
            {"source": "func:legacy.py:run_dynamic_report", "target": "file:legacy.py", "type": "structural_belongs_to", "confidence": 1.0, "evidence": "belongs to"},
        ],
    }


def test_resolve_target_id(sample_cross_layer_graph):
    engine = ImpactEngine(sample_cross_layer_graph)

    # Exact ID
    assert engine.resolve_target_id("table:public.users") == "table:public.users"
    # Bare table name
    assert engine.resolve_target_id("users") == "table:public.users"
    # Function ID
    assert engine.resolve_target_id("func:services.py:create_order") == "func:services.py:create_order"
    # Non-existent
    assert engine.resolve_target_id("non_existent_table") is None


def test_blast_radius_direct_1hop(sample_cross_layer_graph):
    engine = ImpactEngine(sample_cross_layer_graph)
    result = engine.blast_radius("users", max_depth=1)

    assert result.target_id == "table:public.users"
    assert result.max_depth == 1

    # 1-hop reachable: orders (FK, 1.0) and get_user_profile (SQL, 0.85)
    impacted_ids = {n.node_id for n in result.ranked_items}
    assert "table:public.orders" in impacted_ids
    assert "func:services.py:get_user_profile" in impacted_ids
    # 2-hop nodes should NOT be in depth=1
    assert "file:services.py" not in impacted_ids
    assert "table:public.order_items" not in impacted_ids

    orders_node = next(n for n in result.ranked_items if n.node_id == "table:public.orders")
    assert orders_node.confidence == 1.0
    assert orders_node.depth == 1

    sql_node = next(n for n in result.ranked_items if n.node_id == "func:services.py:get_user_profile")
    assert sql_node.confidence == 0.85
    assert sql_node.depth == 1


def test_blast_radius_multi_hop_decay(sample_cross_layer_graph):
    """
    Test Day 15/16 requirement:
    c(path) = Π c(edge_i).
    For users:
    - Hop 1: func:get_user_profile (0.85) -> Hop 2: file:services.py (0.85 * 1.0 = 0.85)
    - Hop 1: table:orders (1.0) -> Hop 2: table:order_items (1.0 * 1.0 = 1.0)
    - Hop 1: table:orders (1.0) -> Hop 2: func:create_order (1.0 * 0.80 = 0.80)
    """
    engine = ImpactEngine(sample_cross_layer_graph)
    result = engine.blast_radius("users", max_depth=2)

    node_map = {n.node_id: n for n in result.ranked_items}

    # Verify 2-hop file reachability
    assert "file:services.py" in node_map
    services_file = node_map["file:services.py"]
    assert services_file.depth == 2
    assert services_file.confidence == 0.85

    # Verify 2-hop transitive table reachability
    assert "table:public.order_items" in node_map
    order_items_table = node_map["table:public.order_items"]
    assert order_items_table.depth == 2
    assert order_items_table.confidence == 1.0

    # Verify 2-hop transitive ORM function reachability
    assert "func:services.py:create_order" in node_map
    create_order_func = node_map["func:services.py:create_order"]
    assert create_order_func.depth == 2
    assert create_order_func.confidence == 0.80


def test_inferred_edge_multiplicative_decay(sample_cross_layer_graph):
    """
    Query blast radius of 'categories':
    - categories -> products is inferred naming (0.55)
    Path confidence to products must be 0.55.
    """
    engine = ImpactEngine(sample_cross_layer_graph)
    result = engine.blast_radius("categories", max_depth=2)

    node_map = {n.node_id: n for n in result.ranked_items}
    assert "table:public.products" in node_map
    assert node_map["table:public.products"].confidence == 0.55


def test_dynamic_unresolved_query_reachability(sample_cross_layer_graph):
    """
    Query blast radius of 'table:unresolved':
    - table:unresolved -> func:legacy.py:run_dynamic_report (conf=0.15)
    - func:legacy.py:run_dynamic_report -> file:legacy.py (conf=0.15 * 1.0 = 0.15)
    """
    engine = ImpactEngine(sample_cross_layer_graph)
    result = engine.blast_radius("table:unresolved", max_depth=2)

    node_map = {n.node_id: n for n in result.ranked_items}
    assert "func:legacy.py:run_dynamic_report" in node_map
    assert node_map["func:legacy.py:run_dynamic_report"].confidence == 0.15

    assert "file:legacy.py" in node_map
    assert node_map["file:legacy.py"].confidence == 0.15


def test_mandatory_blind_spots_disclosure_invariant(sample_cross_layer_graph):
    """
    Day 16 requirement:
    Verify it is impossible to get a query result with an empty blind_spots field,
    and verify dynamic SQL functions are explicitly disclosed.
    """
    engine = ImpactEngine(sample_cross_layer_graph)
    result = engine.blast_radius("users")

    assert len(result.blind_spots) > 0

    # Check dynamic unresolved SQL disclosure
    dynamic_bs = next((bs for bs in result.blind_spots if bs["type"] == "dynamic_unresolved_sql"), None)
    assert dynamic_bs is not None
    assert dynamic_bs["count"] == 1
    assert "func:legacy.py:run_dynamic_report" in dynamic_bs["functions"]

    # Check cross-service boundary disclosure
    cross_bs = next((bs for bs in result.blind_spots if bs["type"] == "cross_service_boundary"), None)
    assert cross_bs is not None


def test_cli_impact_command_text_and_json(sample_cross_layer_graph, tmp_path: Path, capsys):
    graph_file = tmp_path / "graph.json"
    with open(graph_file, "w", encoding="utf-8") as f:
        json.dump(sample_cross_layer_graph, f)

    # 1. Text format
    ret = main([
        "impact",
        "--target", "users",
        "--graph", str(graph_file),
        "--depth", "2",
    ])
    assert ret == 0
    captured = capsys.readouterr()
    assert "SystemLens Blast Radius Analysis" in captured.out
    assert "get_user_profile" in captured.out
    assert "Blind Spots" in captured.out

    # 2. JSON format
    ret_json = main([
        "impact",
        "--target", "users",
        "--graph", str(graph_file),
        "--json",
    ])
    assert ret_json == 0
    captured_json = capsys.readouterr()
    data = json.loads(captured_json.out)
    assert data["target"]["name"] == "users"
    assert len(data["impacted_functions"]) >= 2
    assert len(data["blind_spots"]) >= 1
