"""Comprehensive test suite for SystemLens Python AST static analysis adapter (Step 2).

Tests:
1. SQL table extraction with sqlparse (SELECT, JOINs, INSERT, UPDATE, DELETE, subqueries).
2. AST extraction of function and file nodes (regular, async, class methods, nested functions).
3. Structural function-to-file ownership edges (confidence 1.0).
4. Raw SQL string literal detection (confidence 0.85).
5. SQLAlchemy ORM detection (.query(Model), select(Model)) (confidence 0.80).
6. Django ORM detection (Model.objects.filter(...)) (confidence 0.80).
7. Dynamic/unresolved query fallback (confidence 0.15).
8. Unified cross-layer graph assembly & table resolution (graph.json).
9. Step 2 Kill Check: dynamic query ratio calculation and warning disclosure.
10. CLI end-to-end execution of `analyze-python`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from systemlens.adapters.python_ast import (
    PythonASTAdapter,
    extract_tables_from_sql,
)
from systemlens.cli import main
from systemlens.graph import assemble_unified_graph, compute_cross_layer_metrics
from systemlens.models import Edge, EdgeType, Node, NodeType


# ============================================================================
# 1. SQL Table Extraction Tests
# ============================================================================

def test_extract_tables_simple_select():
    tables = extract_tables_from_sql("SELECT id, name FROM users WHERE active = true")
    assert tables == ["users"]


def test_extract_tables_joins():
    sql = """
    SELECT u.id, o.total, a.city
    FROM users u
    INNER JOIN orders o ON u.id = o.user_id
    LEFT JOIN addresses a ON u.address_id = a.id
    """
    tables = extract_tables_from_sql(sql)
    assert "users" in tables
    assert "orders" in tables
    assert "addresses" in tables


def test_extract_tables_insert():
    tables = extract_tables_from_sql("INSERT INTO audit_logs (actor, action) VALUES ('admin', 'login')")
    assert tables == ["audit_logs"]


def test_extract_tables_update():
    tables = extract_tables_from_sql("UPDATE accounts SET balance = balance + 100 WHERE id = 42")
    assert tables == ["accounts"]


def test_extract_tables_delete():
    tables = extract_tables_from_sql("DELETE FROM user_sessions WHERE expires_at < NOW()")
    assert tables == ["user_sessions"]


def test_extract_tables_schema_qualified():
    tables = extract_tables_from_sql("SELECT * FROM public.products p JOIN inventory.stocks s ON p.id = s.product_id")
    assert "public.products" in tables
    assert "inventory.stocks" in tables


def test_extract_tables_subquery():
    sql = "SELECT * FROM (SELECT id, amount FROM payments) p JOIN accounts a ON p.acct_id = a.id"
    tables = extract_tables_from_sql(sql)
    assert "payments" in tables
    assert "accounts" in tables


# ============================================================================
# 2. Python AST Codebase Analysis Fixtures & Tests
# ============================================================================

@pytest.fixture
def mock_codebase(tmp_path: Path) -> Path:
    """Create a temporary Python project with raw SQL, SQLAlchemy, Django ORM, and dynamic queries."""
    src = tmp_path / "src"
    src.mkdir()

    # File 1: models.py
    models_file = src / "models.py"
    models_file.write_text(
        """
class User:
    __tablename__ = "app_users"
    id = 1

class Order:
    class Meta:
        db_table = "customer_orders"
    id = 1

class Product:
    id = 1
""",
        encoding="utf-8",
    )

    # File 2: services.py (mix of SQL, ORM, dynamic)
    services_file = src / "services.py"
    services_file.write_text(
        """
import db
from models import User, Order, Product

def get_user_dashboard(user_id):
    # Static SQL
    db.execute("SELECT * FROM app_users WHERE id = %s", (user_id,))
    # SQLAlchemy
    orders = session.query(Order).filter_by(user_id=user_id).all()
    # Dynamic unresolved query (f-string)
    db.execute(f"SELECT * FROM dynamic_{user_id}")
    return orders

async def fetch_products():
    # SQLAlchemy select
    stmt = select(Product).where(Product.in_stock == True)
    return await db.fetch_all(stmt)

class OrderService:
    def process_order(self, order_id):
        # Django ORM
        order = Order.objects.filter(id=order_id).first()
        # Dynamic query (variable)
        query_str = "SELECT * FROM " + "payments"
        db.execute(query_str)
        return order
""",
        encoding="utf-8",
    )

    return src


def test_extract_nodes(mock_codebase: Path):
    adapter = PythonASTAdapter(root_dir=mock_codebase)
    nodes = adapter.extract_nodes()
    node_ids = {n.id for n in nodes}

    # Verify file nodes
    assert "file:models.py" in node_ids
    assert "file:services.py" in node_ids

    # Verify function nodes
    assert "func:services.py:get_user_dashboard" in node_ids
    assert "func:services.py:fetch_products" in node_ids
    assert "func:services.py:process_order" in node_ids

    # Verify async flag
    fetch_node = next(n for n in nodes if n.id == "func:services.py:fetch_products")
    assert fetch_node.metadata["is_async"] is True


def test_extract_structural_edges(mock_codebase: Path):
    adapter = PythonASTAdapter(root_dir=mock_codebase)
    edges = adapter.extract_edges()
    structural = [e for e in edges if e.type == EdgeType.STRUCTURAL_BELONGS_TO]

    assert len(structural) >= 3
    # Function -> File mapping
    dash_edge = next(e for e in structural if e.source == "func:services.py:get_user_dashboard")
    assert dash_edge.target == "file:services.py"
    assert dash_edge.confidence == 1.0


def test_extract_sql_and_orm_edges(mock_codebase: Path):
    adapter = PythonASTAdapter(root_dir=mock_codebase)
    edges = adapter.extract_edges()

    # 1. Static SQL: get_user_dashboard -> table:app_users (conf=0.85)
    sql_edges = [e for e in edges if e.type == EdgeType.STATIC_SQL_STRING]
    assert len(sql_edges) >= 1
    user_sql = next(e for e in sql_edges if e.target == "table:app_users")
    assert user_sql.source == "func:services.py:get_user_dashboard"
    assert user_sql.confidence == 0.85

    # 2. SQLAlchemy ORM: get_user_dashboard -> Order (__tablename__='customer_orders', conf=0.80)
    orm_edges = [e for e in edges if e.type == EdgeType.ORM_CALL]
    assert len(orm_edges) >= 2
    order_orm = next(e for e in orm_edges if e.target == "table:customer_orders" and e.metadata.get("orm") == "sqlalchemy")
    assert order_orm.source == "func:services.py:get_user_dashboard"
    assert order_orm.confidence == 0.80

    # 3. SQLAlchemy select: fetch_products -> Product (pluralized to 'products')
    prod_orm = next(e for e in orm_edges if e.target == "table:products")
    assert prod_orm.source == "func:services.py:fetch_products"
    assert prod_orm.confidence == 0.80

    # 4. Django ORM: process_order -> Order (customer_orders)
    django_orm = next(e for e in orm_edges if e.source == "func:services.py:process_order")
    assert django_orm.target == "table:customer_orders"
    assert django_orm.metadata.get("orm") == "django"

    # 5. Dynamic Unresolved: (f-string and variable query)
    dynamic_edges = [e for e in edges if e.type == EdgeType.DYNAMIC_UNRESOLVED]
    assert len(dynamic_edges) >= 2
    for de in dynamic_edges:
        assert de.target == "table:unresolved"
        assert de.confidence == 0.15
        assert de.metadata.get("unresolved") is True


# ============================================================================
# 3. Cross-Layer Graph Assembly & Table Resolution
# ============================================================================

def test_assemble_unified_graph():
    # Database layer from Step 0/1
    db_nodes = [
        Node(id="table:public.users", type=NodeType.TABLE, name="users", source_system="postgres"),
        Node(id="table:public.orders", type=NodeType.TABLE, name="orders", source_system="postgres"),
    ]
    db_edges = [
        Edge(
            source="table:public.orders",
            target="table:public.users",
            type=EdgeType.DECLARED_FK,
            confidence=1.0,
            evidence="FK constraint",
        )
    ]

    # Code layer from Step 2
    code_nodes = [
        Node(id="file:app.py", type=NodeType.FILE, name="app.py", source_system="python"),
        Node(id="func:app.py:get_orders", type=NodeType.FUNCTION, name="get_orders", source_system="python"),
    ]
    code_edges = [
        Edge(
            source="func:app.py:get_orders",
            target="file:app.py",
            type=EdgeType.STRUCTURAL_BELONGS_TO,
            confidence=1.0,
            evidence="belongs to",
        ),
        # Points to bare "table:users" which should resolve to "table:public.users"
        Edge(
            source="func:app.py:get_orders",
            target="table:users",
            type=EdgeType.STATIC_SQL_STRING,
            confidence=0.85,
            evidence="SELECT * FROM users",
        ),
        # Dynamic query
        Edge(
            source="func:app.py:get_orders",
            target="table:unresolved",
            type=EdgeType.DYNAMIC_UNRESOLVED,
            confidence=0.15,
            evidence="Dynamic f-string",
        ),
    ]

    unified = assemble_unified_graph(
        db_nodes=db_nodes,
        db_edges=db_edges,
        code_nodes=code_nodes,
        code_edges=code_edges,
    )

    # 1. Table resolution check
    edges_list = unified["edges"]
    resolved_sql = next(e for e in edges_list if e["type"] == "static_sql_string")
    assert resolved_sql["target"] == "table:public.users"

    # 2. table:unresolved pseudo-node added
    node_ids = {n["id"] for n in unified["nodes"]}
    assert "table:unresolved" in node_ids

    # 3. Metrics computed
    metrics = unified["metrics"]
    assert metrics["total_nodes"] == 5  # 2 DB tables, 1 file, 1 func, 1 unresolved
    c_db = metrics["code_to_db"]
    assert c_db["total_access_calls"] == 2
    assert c_db["static_sql_count"] == 1
    assert c_db["dynamic_unresolved_count"] == 1
    assert c_db["dynamic_unresolved_ratio"] == 0.5
    # Warning flagged because 50% > 40%
    assert c_db["kill_check_warning"] is True


# ============================================================================
# 4. CLI Analyze-Python Command Test
# ============================================================================

def test_cli_analyze_python(mock_codebase: Path, tmp_path: Path):
    graph_out = tmp_path / "graph.json"
    nodes_out = tmp_path / "code_nodes.json"
    edges_out = tmp_path / "code_edges.json"

    ret = main([
        "analyze-python",
        "--src-dir", str(mock_codebase),
        "--nodes-output", str(nodes_out),
        "--edges-output", str(edges_out),
        "--merged-graph-output", str(graph_out),
    ])

    assert ret == 0

    with open(graph_out, "r", encoding="utf-8") as f:
        graph = json.load(f)

    assert "nodes" in graph
    assert "edges" in graph
    assert "metrics" in graph
    assert graph["metrics"]["code_to_db"]["total_access_calls"] >= 4
