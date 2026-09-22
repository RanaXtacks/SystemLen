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


def test_extract_foreign_keys_single_and_composite():
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    # FK query result:
    # 1. Single FK: orders.user_id -> users.id
    # 2. Composite FK: order_items.(order_id, item_id) -> orders.(id, item_id)
    fk_rows = [
        MockDictRow({
            "constraint_name": "fk_orders_user",
            "source_schema": "public",
            "source_table": "orders",
            "source_column": "user_id",
            "source_ordinal": 1,
            "target_schema": "public",
            "target_table": "users",
            "target_column": "id",
            "update_rule": "NO ACTION",
            "delete_rule": "CASCADE",
        }),
        MockDictRow({
            "constraint_name": "fk_order_items_order",
            "source_schema": "public",
            "source_table": "order_items",
            "source_column": "order_id",
            "source_ordinal": 1,
            "target_schema": "public",
            "target_table": "orders",
            "target_column": "id",
            "update_rule": "NO ACTION",
            "delete_rule": "CASCADE",
        }),
        MockDictRow({
            "constraint_name": "fk_order_items_order",
            "source_schema": "public",
            "source_table": "order_items",
            "source_column": "item_id",
            "source_ordinal": 2,
            "target_schema": "public",
            "target_table": "orders",
            "target_column": "item_id",
            "update_rule": "NO ACTION",
            "delete_rule": "CASCADE",
        }),
    ]

    # Return fk_rows for FK query, empty list for inheritance query
    mock_cursor.fetchall.side_effect = [fk_rows, []]

    from systemlens.models import EdgeType
    adapter = PostgresAdapter(connection=mock_conn, schemas=["public"])
    edges = adapter.extract_edges()

    assert len(edges) == 2

    # Verify single FK edge
    orders_fk = next(e for e in edges if e.metadata.get("constraint_name") == "fk_orders_user")
    assert orders_fk.source == "table:public.orders"
    assert orders_fk.target == "table:public.users"
    assert orders_fk.type == EdgeType.DECLARED_FK
    assert orders_fk.confidence == 1.0
    assert "public.orders(user_id) -> public.users(id)" in orders_fk.evidence
    assert orders_fk.metadata["source_columns"] == ["user_id"]
    assert orders_fk.metadata["target_columns"] == ["id"]
    assert orders_fk.metadata["delete_rule"] == "CASCADE"

    # Verify composite FK edge (grouped into 1 edge with both column pairs)
    items_fk = next(e for e in edges if e.metadata.get("constraint_name") == "fk_order_items_order")
    assert items_fk.source == "table:public.order_items"
    assert items_fk.target == "table:public.orders"
    assert items_fk.type == EdgeType.DECLARED_FK
    assert items_fk.confidence == 1.0
    assert "public.order_items(order_id, item_id) -> public.orders(id, item_id)" in items_fk.evidence
    assert items_fk.metadata["source_columns"] == ["order_id", "item_id"]
    assert items_fk.metadata["target_columns"] == ["id", "item_id"]
    assert len(items_fk.metadata["column_pairs"]) == 2
    assert items_fk.metadata["column_pairs"][0] == {"source_column": "order_id", "target_column": "id"}
    assert items_fk.metadata["column_pairs"][1] == {"source_column": "item_id", "target_column": "item_id"}


def test_extract_inheritance_and_partitions():
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    tables_result = [
        MockDictRow({"table_schema": "public", "table_name": "measurements", "table_type": "BASE TABLE"}),
        MockDictRow({"table_schema": "public", "table_name": "measurements_y2026m01", "table_type": "BASE TABLE"}),
        MockDictRow({"table_schema": "public", "table_name": "base_entity", "table_type": "BASE TABLE"}),
        MockDictRow({"table_schema": "public", "table_name": "customer_entity", "table_type": "BASE TABLE"}),
    ]

    columns_result = [
        MockDictRow({
            "table_schema": "public", "table_name": "measurements", "column_name": "id",
            "ordinal_position": 1, "column_default": None, "is_nullable": "NO",
            "data_type": "bigint", "udt_name": "int8",
        }),
        MockDictRow({
            "table_schema": "public", "table_name": "measurements_y2026m01", "column_name": "id",
            "ordinal_position": 1, "column_default": None, "is_nullable": "NO",
            "data_type": "bigint", "udt_name": "int8",
        }),
        MockDictRow({
            "table_schema": "public", "table_name": "base_entity", "column_name": "id",
            "ordinal_position": 1, "column_default": None, "is_nullable": "NO",
            "data_type": "bigint", "udt_name": "int8",
        }),
        MockDictRow({
            "table_schema": "public", "table_name": "customer_entity", "column_name": "id",
            "ordinal_position": 1, "column_default": None, "is_nullable": "NO",
            "data_type": "bigint", "udt_name": "int8",
        }),
    ]

    # 1. pg_inherits results (1 partition child, 1 inherited table)
    inh_rows = [
        MockDictRow({
            "child_schema": "public",
            "child_name": "measurements_y2026m01",
            "child_relkind": "r",
            "parent_schema": "public",
            "parent_name": "measurements",
            "parent_relkind": "p",
            "is_partition": True,
        }),
        MockDictRow({
            "child_schema": "public",
            "child_name": "customer_entity",
            "child_relkind": "r",
            "parent_schema": "public",
            "parent_name": "base_entity",
            "parent_relkind": "r",
            "is_partition": False,
        }),
    ]

    # 2. pg_class relkind='p' query result (measurements parent)
    part_parent_rows = [
        MockDictRow({"schema_name": "public", "table_name": "measurements"}),
    ]

    # fetchall sequence for extract_nodes:
    # 1: tables, 2: columns, 3: inh_rows, 4: part_parent_rows
    mock_cursor.fetchall.side_effect = [tables_result, columns_result, inh_rows, part_parent_rows]

    adapter = PostgresAdapter(connection=mock_conn, schemas=["public"])
    nodes = adapter.extract_nodes()

    nodes_by_id = {n.id: n for n in nodes}
    assert len(nodes) == 4

    # Check partition node
    partition_node = nodes_by_id["table:public.measurements_y2026m01"]
    assert partition_node.type == NodeType.PARTITION
    assert partition_node.metadata["is_partition"] is True
    assert partition_node.metadata["parent_table"] == "public.measurements"
    assert partition_node.metadata["relationship"] == "partition"

    # Check partitioned parent node
    parent_node = nodes_by_id["table:public.measurements"]
    assert parent_node.type == NodeType.TABLE
    assert parent_node.metadata["is_partitioned"] is True

    # Check inherited table node
    customer_node = nodes_by_id["table:public.customer_entity"]
    assert customer_node.type == NodeType.TABLE
    assert customer_node.metadata["relationship"] == "inheritance"
    assert customer_node.metadata["parent_table"] == "public.base_entity"


def test_extract_edges_includes_structural_edges():
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    from systemlens.models import EdgeType

    # 1. FK query returns empty
    fk_rows = []

    # 2. Inheritance query returns 1 partition link
    inh_rows = [
        MockDictRow({
            "child_schema": "public",
            "child_name": "measurements_y2026m01",
            "child_relkind": "r",
            "parent_schema": "public",
            "parent_name": "measurements",
            "parent_relkind": "p",
            "is_partition": True,
        }),
    ]

    mock_cursor.fetchall.side_effect = [fk_rows, inh_rows, []]

    adapter = PostgresAdapter(connection=mock_conn, schemas=["public"])
    edges = adapter.extract_edges()

    assert len(edges) == 1
    edge = edges[0]
    assert edge.source == "table:public.measurements_y2026m01"
    assert edge.target == "table:public.measurements"
    assert edge.type == EdgeType.STRUCTURAL_BELONGS_TO
    assert edge.confidence == 1.0
    assert edge.evidence == "Partition of public.measurements"
    assert edge.metadata["relationship"] == "partition"
    assert edge.metadata["is_partition"] is True


def test_combined_fk_and_partition_edges():
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    from systemlens.models import EdgeType

    fk_rows = [
        MockDictRow({
            "constraint_name": "fk_orders_user",
            "source_schema": "public",
            "source_table": "orders",
            "source_column": "user_id",
            "source_ordinal": 1,
            "target_schema": "public",
            "target_table": "users",
            "target_column": "id",
            "update_rule": "NO ACTION",
            "delete_rule": "CASCADE",
        }),
    ]
    inh_rows = [
        MockDictRow({
            "child_schema": "public",
            "child_name": "orders_2026",
            "child_relkind": "r",
            "parent_schema": "public",
            "parent_name": "orders",
            "parent_relkind": "p",
            "is_partition": True,
        }),
    ]

    mock_cursor.fetchall.side_effect = [fk_rows, inh_rows, []]

    adapter = PostgresAdapter(connection=mock_conn, schemas=["public"])
    edges = adapter.extract_edges()

    assert len(edges) == 2
    types = {e.type for e in edges}
    assert EdgeType.DECLARED_FK in types
    assert EdgeType.STRUCTURAL_BELONGS_TO in types


def test_views_detection():
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    tables_result = [
        MockDictRow({"table_schema": "public", "table_name": "regular_table", "table_type": "BASE TABLE"}),
        MockDictRow({"table_schema": "public", "table_name": "standard_view", "table_type": "VIEW"}),
        MockDictRow({"table_schema": "public", "table_name": "materialized_view", "table_type": "MATERIALIZED VIEW"}),
    ]
    columns_result = []

    mock_cursor.fetchall.side_effect = [tables_result, columns_result, [], []]

    adapter = PostgresAdapter(connection=mock_conn, schemas=["public"])
    nodes = adapter.extract_nodes()

    node_map = {n.name: n for n in nodes}
    assert node_map["regular_table"].type == NodeType.TABLE
    assert node_map["standard_view"].type == NodeType.VIEW
    assert node_map["materialized_view"].type == NodeType.VIEW


