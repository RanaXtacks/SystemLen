"""PostgreSQL schema introspection adapter using information_schema."""

from __future__ import annotations

import json
from typing import Any, Optional

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    psycopg2 = None  # type: ignore

from systemlens.adapters.base import SourceAdapter
from systemlens.models import Edge, Node, NodeType

# Schemas ignored by default during introspection
SYSTEM_SCHEMAS = {"pg_catalog", "information_schema", "pg_toast"}


class PostgresAdapter(SourceAdapter):
    """Introspects a PostgreSQL database via information_schema."""

    def __init__(
        self,
        dsn: Optional[str] = None,
        connection: Optional[Any] = None,
        schemas: Optional[list[str]] = None,
        **conn_kwargs: Any,
    ) -> None:
        """
        Initialize PostgresAdapter.

        Args:
            dsn: PostgreSQL DSN/URI string (e.g. "postgresql://user:pass@host:5432/dbname").
            connection: An existing psycopg2 connection instance (useful for testing or connection pooling).
            schemas: Specific schemas to target. If None, all non-system schemas are introspected.
            conn_kwargs: Additional arguments passed to psycopg2.connect.
        """
        self.dsn = dsn
        self._connection = connection
        self.schemas = schemas
        self.conn_kwargs = conn_kwargs

    def _get_connection(self) -> Any:
        if self._connection is not None:
            return self._connection
        if psycopg2 is None:
            raise ImportError(
                "psycopg2 is required for PostgresAdapter. "
                "Install it with `pip install psycopg2-binary` or `pip install psycopg2`."
            )
        if self.dsn:
            return psycopg2.connect(self.dsn, **self.conn_kwargs)
        return psycopg2.connect(**self.conn_kwargs)

    def extract_raw_catalog(self) -> dict[str, Any]:
        """
        Extract raw catalog dump of tables and columns from information_schema.

        Returns:
            Dictionary matching raw_schema.json structure:
            {
                "tables": {
                    "schema.table_name": {
                        "name": "table_name",
                        "schema": "schema",
                        "type": "BASE TABLE" | "VIEW",
                        "columns": [
                            {
                                "name": "col_name",
                                "ordinal_position": 1,
                                "data_type": "integer",
                                "is_nullable": True,
                                "default": None
                            }
                        ]
                    }
                }
            }
        """
        conn = self._get_connection()
        close_conn = self._connection is None

        try:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor if psycopg2 else None) as cur:
                # 1. Fetch tables
                tables_query = """
                    SELECT
                        table_schema,
                        table_name,
                        table_type
                    FROM information_schema.tables
                    WHERE table_schema NOT IN %s
                """
                params: list[Any] = [tuple(SYSTEM_SCHEMAS)]
                if self.schemas:
                    tables_query += " AND table_schema = ANY(%s)"
                    params.append(self.schemas)

                tables_query += " ORDER BY table_schema, table_name;"
                cur.execute(tables_query, params)
                table_rows = cur.fetchall()

                tables_data: dict[str, dict[str, Any]] = {}
                for row in table_rows:
                    schema_name = row["table_schema"]
                    table_name = row["table_name"]
                    table_type = row["table_type"]
                    full_name = f"{schema_name}.{table_name}"

                    tables_data[full_name] = {
                        "name": table_name,
                        "schema": schema_name,
                        "type": table_type,
                        "columns": [],
                    }

                # 2. Fetch columns
                columns_query = """
                    SELECT
                        table_schema,
                        table_name,
                        column_name,
                        ordinal_position,
                        column_default,
                        is_nullable,
                        data_type,
                        udt_name
                    FROM information_schema.columns
                    WHERE table_schema NOT IN %s
                """
                col_params: list[Any] = [tuple(SYSTEM_SCHEMAS)]
                if self.schemas:
                    columns_query += " AND table_schema = ANY(%s)"
                    col_params.append(self.schemas)

                columns_query += " ORDER BY table_schema, table_name, ordinal_position;"
                cur.execute(columns_query, col_params)
                col_rows = cur.fetchall()

                for row in col_rows:
                    full_name = f"{row['table_schema']}.{row['table_name']}"
                    if full_name in tables_data:
                        tables_data[full_name]["columns"].append(
                            {
                                "name": row["column_name"],
                                "ordinal_position": row["ordinal_position"],
                                "data_type": row["data_type"],
                                "udt_name": row["udt_name"],
                                "is_nullable": (row["is_nullable"] == "YES"),
                                "default": row["column_default"],
                            }
                        )

                return {"tables": tables_data}
        finally:
            if close_conn:
                conn.close()

    def extract_nodes(self) -> list[Node]:
        """Convert extracted tables/views into graph Node objects."""
        catalog = self.extract_raw_catalog()
        nodes: list[Node] = []

        for full_name, table_info in catalog.get("tables", {}).items():
            table_type = table_info.get("type", "BASE TABLE")
            node_type = NodeType.VIEW if "VIEW" in table_type else NodeType.TABLE

            nodes.append(
                Node(
                    id=f"table:{full_name}",
                    type=node_type,
                    name=table_info["name"],
                    source_system="postgres",
                    metadata={
                        "schema": table_info["schema"],
                        "table_type": table_type,
                        "columns": table_info["columns"],
                    },
                )
            )

        return nodes

    def extract_edges(self) -> list[Edge]:
        """
        Extract declared relationships.
        (For Day 1, this returns empty list; Day 2 extends with FK constraints).
        """
        return []

    def dump_raw_schema(self, output_path: str = "raw_schema.json") -> dict[str, Any]:
        """Extract and write raw schema to JSON file."""
        catalog = self.extract_raw_catalog()
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(catalog, f, indent=2)
        return catalog
