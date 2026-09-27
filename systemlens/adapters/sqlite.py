"""SQLite Schema Introspection Adapter for SystemLens.

Uses the Python standard library `sqlite3` to introspect SQLite database files.
Extracts:
1. Tables and views from `sqlite_master`.
2. Column definitions and primary keys via `PRAGMA table_info`.
3. Foreign key relationships via `PRAGMA foreign_key_list`.
4. Declared foreign key edges with confidence=1.0.
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any, Optional

from systemlens.adapters.base import SourceAdapter
from systemlens.models import Edge, EdgeType, Node, NodeType


class SQLiteAdapter(SourceAdapter):
    """
    Introspects a SQLite database file and extracts schema nodes,
    relational foreign key edges, and catalog metadata.
    """

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path).resolve()
        if not self.db_path.exists():
            raise FileNotFoundError(f"SQLite database file not found: {self.db_path}")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def dump_raw_schema(self, output_path: Optional[str | Path] = None) -> dict[str, Any]:
        """
        Introspect all tables, views, columns, and foreign keys.
        Returns a structured catalog matching SystemLens raw_schema.json format.
        """
        catalog: dict[str, Any] = {
            "source_type": "sqlite",
            "database": self.db_path.name,
            "tables": {},
        }

        with self._connect() as conn:
            cursor = conn.cursor()
            # Fetch tables and views
            cursor.execute(
                """
                SELECT type, name, sql
                FROM sqlite_master
                WHERE type IN ('table', 'view')
                  AND name NOT LIKE 'sqlite_%'
                ORDER BY name;
                """
            )
            entities = cursor.fetchall()

            for entity in entities:
                ent_type = entity["type"].upper()
                name = entity["name"]
                ddl = entity["sql"] or ""

                # Fetch columns
                # pragma table_info returns: cid, name, type, notnull, dflt_value, pk
                cursor.execute(f'PRAGMA table_info("{name}");')
                col_rows = cursor.fetchall()

                columns = []
                for col in col_rows:
                    columns.append({
                        "name": col["name"],
                        "data_type": col["type"],
                        "nullable": not bool(col["notnull"]),
                        "is_primary_key": bool(col["pk"]),
                        "default": col["dflt_value"],
                    })

                # Fetch foreign keys
                # pragma foreign_key_list returns: id, seq, table, from, to, on_update, on_delete, match
                cursor.execute(f'PRAGMA foreign_key_list("{name}");')
                fk_rows = cursor.fetchall()

                foreign_keys = []
                for fk in fk_rows:
                    foreign_keys.append({
                        "id": fk["id"],
                        "target_table": fk["table"],
                        "from_column": fk["from"],
                        "to_column": fk["to"],
                        "on_update": fk["on_update"],
                        "on_delete": fk["on_delete"],
                    })

                catalog["tables"][name] = {
                    "name": name,
                    "type": "BASE TABLE" if ent_type == "TABLE" else "VIEW",
                    "columns": columns,
                    "foreign_keys": foreign_keys,
                    "ddl": ddl,
                }

        if output_path:
            parent = os.path.dirname(os.path.abspath(output_path))
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(catalog, f, indent=2)

        return catalog

    def extract_nodes(self) -> list[Node]:
        catalog = self.dump_raw_schema()
        nodes: list[Node] = []

        for name, info in catalog["tables"].items():
            node_type = (
                NodeType.VIEW if info.get("type") == "VIEW" else NodeType.TABLE
            )
            nodes.append(
                Node(
                    id=f"table:{name}",
                    type=node_type,
                    name=name,
                    source_system="sqlite",
                    metadata=info,
                )
            )

        return nodes

    def extract_edges(self) -> list[Edge]:
        catalog = self.dump_raw_schema()
        edges: list[Edge] = []

        for name, info in catalog["tables"].items():
            source_id = f"table:{name}"
            for fk in info.get("foreign_keys", []):
                target_table = fk.get("target_table")
                if target_table:
                    target_id = f"table:{target_table}"
                    from_col = fk.get("from_column", "")
                    to_col = fk.get("to_column", "")
                    evidence = f"FK {name}.{from_col} -> {target_table}.{to_col}"
                    edges.append(
                        Edge(
                            source=source_id,
                            target=target_id,
                            type=EdgeType.DECLARED_FK,
                            confidence=1.0,
                            evidence=evidence,
                            metadata=fk,
                        )
                    )

        return edges

    def extract_raw_catalog(self) -> dict[str, Any]:
        return self.dump_raw_schema()
