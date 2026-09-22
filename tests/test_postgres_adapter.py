"""Tests for Postgres schema introspection adapter."""

import json
from unittest.mock import MagicMock

from systemlens.adapters.postgres import PostgresAdapter
from systemlens.models import NodeType


class MockDictRow(dict):
    def __getitem__(self, item):
        return super().__getitem__(item)


def test_extract_raw_catalog_mocked(tmp_path):
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    # Mock tables query result
    tables_result = [
        MockDictRow({"table_schema": "public", "table_name": "users", "table_type": "BASE TABLE"}),
        MockDictRow({"table_schema": "public", "table_name": "orders", "table_type": "BASE TABLE"}),
        MockDictRow({"table_schema": "public", "table_name": "active_users", "table_type": "VIEW"}),
    ]

    # Mock columns query result
    columns_result = [
        MockDictRow({
            "table_schema": "public",
            "table_name": "users",
            "column_name": "id",
            "ordinal_position": 1,
            "column_default": "nextval('users_id_seq'::regclass)",
            "is_nullable": "NO",
            "data_type": "integer",
            "udt_name": "int4",
        }),
        MockDictRow({
            "table_schema": "public",
            "table_name": "users",
            "column_name": "email",
            "ordinal_position": 2,
            "column_default": None,
            "is_nullable": "YES",
            "data_type": "character varying",
            "udt_name": "varchar",
        }),
        MockDictRow({
            "table_schema": "public",
            "table_name": "orders",
            "column_name": "id",
            "ordinal_position": 1,
            "column_default": None,
            "is_nullable": "NO",
            "data_type": "integer",
            "udt_name": "int4",
        }),
        MockDictRow({
            "table_schema": "public",
            "table_name": "orders",
            "column_name": "user_id",
            "ordinal_position": 2,
            "column_default": None,
            "is_nullable": "YES",
            "data_type": "integer",
            "udt_name": "int4",
        }),
    ]

    mock_cursor.fetchall.side_effect = [tables_result, columns_result]

    adapter = PostgresAdapter(connection=mock_conn, schemas=["public"])
    catalog = adapter.extract_raw_catalog()

    assert "tables" in catalog
    assert len(catalog["tables"]) == 3
    assert "public.users" in catalog["tables"]
    assert "public.orders" in catalog["tables"]
    assert "public.active_users" in catalog["tables"]

    users_table = catalog["tables"]["public.users"]
    assert users_table["name"] == "users"
    assert users_table["schema"] == "public"
    assert len(users_table["columns"]) == 2
    assert users_table["columns"][0]["name"] == "id"
    assert users_table["columns"][0]["is_nullable"] is False
    assert users_table["columns"][1]["name"] == "email"
    assert users_table["columns"][1]["is_nullable"] is True

    # Test extract_nodes()
    mock_cursor.fetchall.side_effect = [tables_result, columns_result]
    nodes = adapter.extract_nodes()
    assert len(nodes) == 3

    nodes_by_id = {n.id: n for n in nodes}
    assert "table:public.users" in nodes_by_id
    assert nodes_by_id["table:public.users"].type == NodeType.TABLE
    assert nodes_by_id["table:public.users"].source_system == "postgres"
    assert nodes_by_id["table:public.active_users"].type == NodeType.VIEW

    # Test dump_raw_schema()
    mock_cursor.fetchall.side_effect = [tables_result, columns_result]
    output_file = str(tmp_path / "raw_schema.json")
    dumped = adapter.dump_raw_schema(output_file)

    with open(output_file, "r", encoding="utf-8") as f:
        loaded = json.load(f)

    assert loaded == dumped
    assert "public.users" in loaded["tables"]
