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
