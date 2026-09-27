"""Unit tests for SQLite schema adapter."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from systemlens.adapters.sqlite import SQLiteAdapter
from systemlens.models import EdgeType, NodeType


@pytest.fixture
def sqlite_test_db(tmp_path) -> Path:
    db_file = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_file))
    cursor = conn.cursor()
    cursor.executescript(
        """
        PRAGMA foreign_keys = ON;

        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            username TEXT NOT NULL
        );

        CREATE TABLE orders (
            id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL,
            total REAL,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        CREATE TABLE order_items (
            id INTEGER PRIMARY KEY,
            order_id INTEGER NOT NULL,
            product_name TEXT,
            FOREIGN KEY (order_id) REFERENCES orders(id)
        );

        CREATE VIEW active_users AS
        SELECT id, username FROM users;
        """
    )
    conn.commit()
    conn.close()
    return db_file


def test_sqlite_adapter_dump_raw_schema(sqlite_test_db):
    adapter = SQLiteAdapter(sqlite_test_db)
    catalog = adapter.dump_raw_schema()

    assert catalog["source_type"] == "sqlite"
    assert "users" in catalog["tables"]
    assert "orders" in catalog["tables"]
    assert "order_items" in catalog["tables"]
    assert "active_users" in catalog["tables"]

    # Check columns
    users_cols = catalog["tables"]["users"]["columns"]
    col_names = [c["name"] for c in users_cols]
    assert "id" in col_names
    assert "username" in col_names

    # Check foreign keys in orders
    orders_fks = catalog["tables"]["orders"]["foreign_keys"]
    assert len(orders_fks) == 1
    assert orders_fks[0]["target_table"] == "users"
    assert orders_fks[0]["from_column"] == "user_id"


def test_sqlite_adapter_extract_nodes(sqlite_test_db):
    adapter = SQLiteAdapter(sqlite_test_db)
    nodes = adapter.extract_nodes()

    node_map = {n.id: n for n in nodes}
    assert "table:users" in node_map
    assert node_map["table:users"].type == NodeType.TABLE
    assert "table:orders" in node_map
    assert "table:active_users" in node_map
    assert node_map["table:active_users"].type == NodeType.VIEW


def test_sqlite_adapter_extract_edges(sqlite_test_db):
    adapter = SQLiteAdapter(sqlite_test_db)
    edges = adapter.extract_edges()

    assert len(edges) == 2
    # orders -> users
    # order_items -> orders
    edge_pairs = {(e.source, e.target, e.type) for e in edges}
    assert ("table:orders", "table:users", EdgeType.DECLARED_FK) in edge_pairs
    assert ("table:order_items", "table:orders", EdgeType.DECLARED_FK) in edge_pairs
    assert all(e.confidence == 1.0 for e in edges)
