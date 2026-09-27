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
from systemlens.models import Edge, EdgeType, Node, NodeType

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

    def extract_raw_catalog(self, conn: Optional[Any] = None) -> dict[str, Any]:
        """
        Extract raw catalog dump of tables and columns from information_schema.

        Args:
            conn: Optional existing connection. If None, a connection is obtained
                  via self._get_connection().

        Returns:
            Dictionary matching raw_schema.json structure.
        """
        active_conn = conn if conn is not None else self._get_connection()
        close_conn = (conn is None and self._connection is None)

        try:
            with active_conn.cursor(cursor_factory=psycopg2.extras.DictCursor if psycopg2 else None) as cur:
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
                active_conn.close()

    def _extract_foreign_keys(self, cur: Any) -> list[Edge]:
        """
        Extract declared foreign key constraints from information_schema.

        Handles composite foreign keys by grouping column pairs by constraint.
        Returns a list of Edge objects with EdgeType.DECLARED_FK and confidence=1.0.
        """
        fk_query = """
            SELECT
                tc.constraint_name,
                tc.table_schema AS source_schema,
                tc.table_name AS source_table,
                kcu_src.column_name AS source_column,
                kcu_src.ordinal_position AS source_ordinal,
                kcu_tgt.table_schema AS target_schema,
                kcu_tgt.table_name AS target_table,
                kcu_tgt.column_name AS target_column,
                rc.update_rule,
                rc.delete_rule
            FROM information_schema.table_constraints tc
            JOIN information_schema.referential_constraints rc
                ON tc.constraint_name = rc.constraint_name
                AND tc.table_schema = rc.constraint_schema
            JOIN information_schema.key_column_usage kcu_src
                ON tc.constraint_name = kcu_src.constraint_name
                AND tc.table_schema = kcu_src.table_schema
            JOIN information_schema.key_column_usage kcu_tgt
                ON rc.unique_constraint_name = kcu_tgt.constraint_name
                AND rc.unique_constraint_schema = kcu_tgt.constraint_schema
                AND kcu_src.position_in_unique_constraint = kcu_tgt.ordinal_position
            WHERE tc.constraint_type = 'FOREIGN KEY'
              AND tc.table_schema NOT IN %s
        """
        params: list[Any] = [tuple(SYSTEM_SCHEMAS)]
        if self.schemas:
            fk_query += " AND tc.table_schema = ANY(%s)"
            params.append(self.schemas)

        fk_query += " ORDER BY tc.table_schema, tc.table_name, tc.constraint_name, kcu_src.ordinal_position;"

        try:
            cur.execute(fk_query, params)
            rows = cur.fetchall()
        except Exception:
            return []

        # Group by constraint definition
        groups: dict[tuple[str, str, str, str, str], list[Any]] = {}
        for row in rows:
            key = (
                row["source_schema"],
                row["source_table"],
                row["constraint_name"],
                row["target_schema"],
                row["target_table"],
            )
            if key not in groups:
                groups[key] = []
            groups[key].append(row)

        edges: list[Edge] = []
        for (src_schema, src_table, constraint_name, tgt_schema, tgt_table), cols in groups.items():
            cols.sort(key=lambda c: c["source_ordinal"])
            src_cols = [c["source_column"] for c in cols]
            tgt_cols = [c["target_column"] for c in cols]
            column_pairs = [
                {"source_column": c["source_column"], "target_column": c["target_column"]}
                for c in cols
            ]

            src_cols_str = ", ".join(src_cols)
            tgt_cols_str = ", ".join(tgt_cols)
            evidence = (
                f"FK {constraint_name}: "
                f"{src_schema}.{src_table}({src_cols_str}) -> "
                f"{tgt_schema}.{tgt_table}({tgt_cols_str})"
            )

            edges.append(
                Edge(
                    source=f"table:{src_schema}.{src_table}",
                    target=f"table:{tgt_schema}.{tgt_table}",
                    type=EdgeType.DECLARED_FK,
                    confidence=1.0,
                    evidence=evidence,
                    metadata={
                        "constraint_name": constraint_name,
                        "source_schema": src_schema,
                        "source_table": src_table,
                        "source_columns": src_cols,
                        "target_schema": tgt_schema,
                        "target_table": tgt_table,
                        "target_columns": tgt_cols,
                        "column_pairs": column_pairs,
                        "update_rule": cols[0]["update_rule"] if "update_rule" in cols[0] else None,
                        "delete_rule": cols[0]["delete_rule"] if "delete_rule" in cols[0] else None,
                    },
                )
            )

        return edges

    def _extract_inheritance_and_partitions(
        self, cur: Any
    ) -> tuple[dict[str, dict[str, Any]], set[str]]:
        """
        Query pg_catalog.pg_inherits and pg_class to discover table inheritance
        and partitioned tables.

        Returns:
            Tuple of:
            - inheritance_map: dict mapping child_full_name -> {parent_schema, parent_name, parent_full_name, is_partition, relationship}
            - partitioned_parents: set of parent_full_names whose relkind == 'p'
        """
        inh_query = """
            SELECT
                c_ns.nspname AS child_schema,
                c.relname AS child_name,
                c.relkind AS child_relkind,
                p_ns.nspname AS parent_schema,
                p.relname AS parent_name,
                p.relkind AS parent_relkind,
                COALESCE(c.relispartition, false) AS is_partition
            FROM pg_catalog.pg_inherits inh
            JOIN pg_catalog.pg_class c ON inh.inhrelid = c.oid
            JOIN pg_catalog.pg_namespace c_ns ON c.relnamespace = c_ns.oid
            JOIN pg_catalog.pg_class p ON inh.inhparent = p.oid
            JOIN pg_catalog.pg_namespace p_ns ON p.relnamespace = p_ns.oid
            WHERE c_ns.nspname NOT IN %s
        """
        params: list[Any] = [tuple(SYSTEM_SCHEMAS)]
        if self.schemas:
            inh_query += " AND c_ns.nspname = ANY(%s)"
            params.append(self.schemas)

        inh_map: dict[str, dict[str, Any]] = {}
        partitioned_parents: set[str] = set()

        try:
            cur.execute(inh_query, params)
            rows = cur.fetchall()
            for row in rows:
                child_full = f"{row['child_schema']}.{row['child_name']}"
                parent_full = f"{row['parent_schema']}.{row['parent_name']}"
                is_partition = bool(row.get("is_partition")) or (row.get("parent_relkind") == "p")
                rel = "partition" if is_partition else "inheritance"

                inh_map[child_full] = {
                    "child_schema": row["child_schema"],
                    "child_name": row["child_name"],
                    "child_relkind": row.get("child_relkind"),
                    "parent_schema": row["parent_schema"],
                    "parent_name": row["parent_name"],
                    "parent_full_name": parent_full,
                    "parent_relkind": row.get("parent_relkind"),
                    "is_partition": is_partition,
                    "relationship": rel,
                }

                if row.get("parent_relkind") == "p":
                    partitioned_parents.add(parent_full)
        except Exception:
            # Gracefully handle restricted catalog access or mock environments
            pass

        # Also detect partitioned parent tables that may not yet have child partitions
        parent_query = """
            SELECT
                n.nspname AS schema_name,
                c.relname AS table_name
            FROM pg_catalog.pg_class c
            JOIN pg_catalog.pg_namespace n ON c.relnamespace = n.oid
            WHERE c.relkind = 'p'
              AND n.nspname NOT IN %s
        """
        p_params: list[Any] = [tuple(SYSTEM_SCHEMAS)]
        if self.schemas:
            parent_query += " AND n.nspname = ANY(%s)"
            p_params.append(self.schemas)

        try:
            cur.execute(parent_query, p_params)
            p_rows = cur.fetchall()
            for r in p_rows:
                partitioned_parents.add(f"{r['schema_name']}.{r['table_name']}")
        except Exception:
            pass

        return inh_map, partitioned_parents

    def extract_nodes(self) -> list[Node]:
        """
        Convert extracted tables, views, and partitions into graph Node objects.

        Assigns:
        - NodeType.VIEW for views
        - NodeType.PARTITION for partition child tables
        - NodeType.TABLE for standard tables and partitioned parent tables
        """
        conn = self._get_connection()
        close_conn = self._connection is None

        try:
            catalog = self.extract_raw_catalog(conn=conn)
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor if psycopg2 else None) as cur:
                inh_map, partitioned_parents = self._extract_inheritance_and_partitions(cur)

            nodes: list[Node] = []
            for full_name, table_info in catalog.get("tables", {}).items():
                table_type = table_info.get("type", "BASE TABLE")

                # Determine node type
                inh_info = inh_map.get(full_name)
                if "VIEW" in table_type:
                    node_type = NodeType.VIEW
                elif inh_info and inh_info["is_partition"]:
                    node_type = NodeType.PARTITION
                else:
                    node_type = NodeType.TABLE

                metadata: dict[str, Any] = {
                    "schema": table_info["schema"],
                    "table_type": table_type,
                    "columns": table_info["columns"],
                }

                if inh_info:
                    metadata["parent_table"] = inh_info["parent_full_name"]
                    metadata["relationship"] = inh_info["relationship"]
                    metadata["is_partition"] = inh_info["is_partition"]

                if full_name in partitioned_parents:
                    metadata["is_partitioned"] = True

                nodes.append(
                    Node(
                        id=f"table:{full_name}",
                        type=node_type,
                        name=table_info["name"],
                        source_system="postgres",
                        metadata=metadata,
                    )
                )

            return nodes
        finally:
            if close_conn:
                conn.close()

    def extract_edges(self) -> list[Edge]:
        """
        Extract declared foreign key constraints and structural inheritance/partition edges.

        Returns:
            List of Edge objects:
            - EdgeType.DECLARED_FK (confidence=1.0)
            - EdgeType.STRUCTURAL_BELONGS_TO (confidence=1.0)
        """
        conn = self._get_connection()
        close_conn = self._connection is None

        try:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor if psycopg2 else None) as cur:
                fk_edges = self._extract_foreign_keys(cur)
                inh_map, _ = self._extract_inheritance_and_partitions(cur)

                structural_edges: list[Edge] = []
                for child_full, info in inh_map.items():
                    evidence_label = "Partition of" if info["is_partition"] else "Inherits from"
                    structural_edges.append(
                        Edge(
                            source=f"table:{child_full}",
                            target=f"table:{info['parent_full_name']}",
                            type=EdgeType.STRUCTURAL_BELONGS_TO,
                            confidence=1.0,
                            evidence=f"{evidence_label} {info['parent_full_name']}",
                            metadata={
                                "relationship": info["relationship"],
                                "parent_table": info["parent_full_name"],
                                "child_table": child_full,
                                "is_partition": info["is_partition"],
                            },
                        )
                    )

                return fk_edges + structural_edges
        finally:
            if close_conn:
                conn.close()

    def dump_raw_schema(self, output_path: str = "raw_schema.json") -> dict[str, Any]:
        """Extract and write raw schema to JSON file."""
        catalog = self.extract_raw_catalog()
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(catalog, f, indent=2)
        return catalog
