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
