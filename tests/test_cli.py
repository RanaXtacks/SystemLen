"""Tests for SystemLens CLI."""

import json
from unittest.mock import MagicMock, patch

from systemlens.cli import main
from systemlens.models import Edge, EdgeType, Node, NodeType


def test_cli_ingest_postgres_mocked(tmp_path):
    schema_out = tmp_path / "raw_schema.json"
    nodes_out = tmp_path / "nodes.json"
    edges_out = tmp_path / "edges.json"

    mock_catalog = {
        "tables": {
            "public.users": {
                "name": "users",
                "schema": "public",
                "type": "BASE TABLE",
                "columns": [{"name": "id", "data_type": "integer"}],
            }
        }
    }
    mock_nodes = [
        Node(id="table:public.users", type=NodeType.TABLE, name="users", source_system="postgres")
    ]
    mock_edges = [
        Edge(
            source="table:public.orders",
            target="table:public.users",
            type=EdgeType.DECLARED_FK,
            confidence=1.0,
            evidence="FK fk_orders_user",
        )
    ]

    with patch("systemlens.cli.PostgresAdapter") as MockAdapter:
        adapter_instance = MockAdapter.return_value
        adapter_instance.dump_raw_schema.return_value = mock_catalog
        adapter_instance.extract_nodes.return_value = mock_nodes
        adapter_instance.extract_edges.return_value = mock_edges

        ret = main([
            "ingest-postgres",
            "--dsn", "postgresql://user:pass@localhost:5432/testdb",
            "--output", str(schema_out),
            "--nodes-output", str(nodes_out),
            "--edges-output", str(edges_out),
        ])

        assert ret == 0
        MockAdapter.assert_called_once_with(
            dsn="postgresql://user:pass@localhost:5432/testdb",
            schemas=None,
        )

        with open(nodes_out, "r", encoding="utf-8") as f:
            saved_nodes = json.load(f)
        assert len(saved_nodes) == 1
        assert saved_nodes[0]["id"] == "table:public.users"

        with open(edges_out, "r", encoding="utf-8") as f:
            saved_edges = json.load(f)
        assert len(saved_edges) == 1
        assert saved_edges[0]["type"] == "declared_fk"


def test_cli_ingest_postgres_with_inference(tmp_path):
    schema_out = tmp_path / "raw_schema.json"
    inferred_out = tmp_path / "inferred.json"
    merged_out = tmp_path / "merged.json"

    mock_catalog = {
        "tables": {
            "public.users": {
                "name": "users",
                "schema": "public",
                "columns": [{"name": "id"}],
            },
            "public.orders": {
                "name": "orders",
                "schema": "public",
                "columns": [{"name": "id"}, {"name": "user_id"}],
            },
        }
    }
    mock_declared = [
        Edge(
            source="table:public.orders",
            target="table:public.users",
            type=EdgeType.DECLARED_FK,
            confidence=1.0,
            evidence="FK constraint",
        )
    ]

    with patch("systemlens.cli.PostgresAdapter") as MockAdapter:
        adapter_instance = MockAdapter.return_value
        adapter_instance.dump_raw_schema.return_value = mock_catalog
        adapter_instance.extract_edges.return_value = mock_declared

        ret = main([
            "ingest-postgres",
            "--dsn", "postgresql://user:pass@localhost:5432/testdb",
            "--output", str(schema_out),
            "--inferred-edges-output", str(inferred_out),
            "--merged-edges-output", str(merged_out),
        ])

        assert ret == 0
        with open(inferred_out, "r", encoding="utf-8") as f:
            inferred = json.load(f)
        assert len(inferred) == 1
        assert inferred[0]["type"] == "inferred_naming"
        assert inferred[0]["source"] == "table:public.orders"
        assert inferred[0]["target"] == "table:public.users"

        with open(merged_out, "r", encoding="utf-8") as f:
            merged = json.load(f)
        assert len(merged) == 2


def test_cli_infer_edges_command(tmp_path):
    schema_file = tmp_path / "schema.json"
    declared_file = tmp_path / "declared.json"
    inferred_out = tmp_path / "inferred.json"
    merged_out = tmp_path / "merged.json"

    catalog_data = {
        "tables": {
            "public.products": {
                "name": "products",
                "schema": "public",
                "columns": [{"name": "id"}],
            },
            "public.order_items": {
                "name": "order_items",
                "schema": "public",
                "columns": [{"name": "id"}, {"name": "product_id"}],
            },
        }
    }
    with open(schema_file, "w", encoding="utf-8") as f:
        json.dump(catalog_data, f)

    declared_data = [
        {
            "source": "table:public.order_items",
            "target": "table:public.products",
            "type": "declared_fk",
            "confidence": 1.0,
            "evidence": "FK constraint",
            "metadata": {},
        }
    ]
    with open(declared_file, "w", encoding="utf-8") as f:
        json.dump(declared_data, f)

    ret = main([
        "infer-edges",
        "--schema-file", str(schema_file),
        "--declared-edges", str(declared_file),
        "--output", str(inferred_out),
        "--merged-output", str(merged_out),
        "--deduplicate",
    ])

    assert ret == 0
    with open(inferred_out, "r", encoding="utf-8") as f:
        inferred = json.load(f)
    assert len(inferred) == 1

    with open(merged_out, "r", encoding="utf-8") as f:
        merged = json.load(f)
    # With deduplicate, only 1 edge is saved, and it's the declared FK with naming_agreement marked
    assert len(merged) == 1
    assert merged[0]["type"] == "declared_fk"
    assert merged[0]["metadata"]["naming_agreement"] is True


def test_cli_ci_diff_markdown(tmp_path):
    graph_file = tmp_path / "graph.json"
    out_md = tmp_path / "report.md"

    graph_data = {
        "nodes": [
            {"id": "table:public.users", "type": "table", "name": "users", "source_system": "postgres"},
            {"id": "func:app/auth.py:login", "type": "function", "name": "login", "source_system": "python", "metadata": {"file": "app/auth.py"}},
            {"id": "file:app/auth.py", "type": "file", "name": "app/auth.py", "source_system": "python"},
        ],
        "edges": [
            {"source": "func:app/auth.py:login", "target": "table:public.users", "type": "orm_call", "confidence": 0.8, "evidence": "ORM"},
            {"source": "func:app/auth.py:login", "target": "file:app/auth.py", "type": "structural_belongs_to", "confidence": 1.0, "evidence": "belongs to"},
        ],
    }
    with open(graph_file, "w", encoding="utf-8") as f:
        json.dump(graph_data, f)

    ret = main([
        "ci-diff",
        "--graph", str(graph_file),
        "--changed-files", "app/auth.py",
        "--format", "markdown",
        "--output", str(out_md),
    ])

    assert ret == 0
    assert out_md.exists()
    content = out_md.read_text(encoding="utf-8")
    assert "## 🔍 SystemLens Impact Analysis" in content
    assert "users" in content


def test_cli_ci_diff_json(tmp_path):
    graph_file = tmp_path / "graph.json"
    out_json = tmp_path / "report.json"

    graph_data = {
        "nodes": [
            {"id": "table:public.users", "type": "table", "name": "users", "source_system": "postgres"},
        ],
        "edges": [],
    }
    with open(graph_file, "w", encoding="utf-8") as f:
        json.dump(graph_data, f)

    ret = main([
        "ci-diff",
        "--graph", str(graph_file),
        "--changed-files", "migrations/001_users.sql",
        "--format", "json",
        "--output", str(out_json),
    ])

    assert ret == 0
    assert out_json.exists()
    with open(out_json, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["summary"]["total_affected_tables"] == 1
    assert data["affected_tables"] == ["users"]


def test_cli_ci_diff_missing_graph():
    ret = main([
        "ci-diff",
        "--graph", "nonexistent_graph_12345.json",
        "--changed-files", "app/auth.py",
    ])
    assert ret == 1


def test_cli_ci_diff_with_mocked_git(tmp_path, monkeypatch):
    graph_file = tmp_path / "graph.json"
    graph_data = {
        "nodes": [
            {"id": "table:public.users", "type": "table", "name": "users", "source_system": "postgres"},
            {"id": "func:app/auth.py:login", "type": "function", "name": "login", "source_system": "python", "metadata": {"file": "app/auth.py"}},
        ],
        "edges": [
            {"source": "func:app/auth.py:login", "target": "table:public.users", "type": "orm_call", "confidence": 0.8, "evidence": "ORM"},
        ],
    }
    with open(graph_file, "w", encoding="utf-8") as f:
        json.dump(graph_data, f)

    monkeypatch.setattr("systemlens.cli.parse_git_diff", lambda base, head: ["app/auth.py"])

    ret = main([
        "ci-diff",
        "--graph", str(graph_file),
        "--base", "origin/main",
        "--head", "HEAD",
    ])
    assert ret == 0


def test_cli_analyze_js(tmp_path):
    js_file = tmp_path / "index.js"
    js_file.write_text(
        "async function getOrders() { return await knex('orders').select('*'); }",
        encoding="utf-8",
    )
    graph_out = tmp_path / "graph.json"

    ret = main([
        "analyze-js",
        "--src-dir", str(tmp_path),
        "--merged-graph-output", str(graph_out),
    ])
    assert ret == 0
    assert graph_out.exists()
    with open(graph_out, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["metrics"]["total_nodes"] >= 2
    assert data["metrics"]["code_to_db"]["total_access_calls"] >= 1


