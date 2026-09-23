"""Benchmark schema loader and catalog builder.

Parses benchmark/schema.sql into SystemLens Node, Edge, and raw catalog structures,
supporting both offline deterministic benchmarking and live PostgreSQL execution.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional

from systemlens.adapters.postgres import PostgresAdapter
from systemlens.inference.merge import compute_merge_stats, merge_edges
from systemlens.inference.naming import infer_edges_from_naming
from systemlens.models import Edge, EdgeType, Node, NodeType


def parse_sql_schema_ddl(sql_text: str) -> dict[str, Any]:
    """
    Parse PostgreSQL DDL statements into a raw catalog dictionary
    and a list of declared foreign key constraints.
    """
    tables_data: dict[str, dict[str, Any]] = {}
    declared_fks: list[dict[str, Any]] = []
    views: list[str] = []
    partitions: dict[str, str] = {}  # child -> parent

    # Normalize comments and clean sql
    lines = []
    for line in sql_text.splitlines():
        line = line.strip()
        if line.startswith("--"):
            continue
        lines.append(line)
    clean_sql = "\n".join(lines)

    # 1. Parse Views
    view_matches = re.finditer(
        r"CREATE\s+(?:OR\s+REPLACE\s+)?VIEW\s+(?:public\.)?(\w+)\s+AS",
        clean_sql,
        re.IGNORECASE,
    )
    for vm in view_matches:
        v_name = vm.group(1)
        full_name = f"public.{v_name}"
        views.append(v_name)
        tables_data[full_name] = {
            "name": v_name,
            "schema": "public",
            "type": "VIEW",
            "columns": [],
        }

    # 2. Parse Partition Tables
    part_matches = re.finditer(
        r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:public\.)?(\w+)\s+PARTITION\s+OF\s+(?:public\.)?(\w+)",
        clean_sql,
        re.IGNORECASE,
    )
    for pm in part_matches:
        child = pm.group(1)
        parent = pm.group(2)
        partitions[f"public.{child}"] = f"public.{parent}"
        tables_data[f"public.{child}"] = {
            "name": child,
            "schema": "public",
            "type": "BASE TABLE",
            "columns": [],
            "parent_partition": f"public.{parent}",
        }

    # 3. Parse Standard CREATE TABLE blocks
    table_blocks = re.finditer(
        r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:public\.)?(\w+)\s*\((.*?)\)(?:\s*PARTITION\s+BY\s+[^;]+)?;",
        clean_sql,
        re.IGNORECASE | re.DOTALL,
    )

    for tb in table_blocks:
        t_name = tb.group(1)
        body = tb.group(2)
        full_name = f"public.{t_name}"

        # If already added as partition of something, keep it
        if full_name not in tables_data:
            tables_data[full_name] = {
                "name": t_name,
                "schema": "public",
                "type": "BASE TABLE",
                "columns": [],
            }

        # Parse column definitions and table-level constraints
        col_ordinal = 1
        for raw_item in body.split(","):
            item = raw_item.strip()
            if not item:
                continue

            # Check for table-level FOREIGN KEY constraint
            # e.g., CONSTRAINT fk_name FOREIGN KEY (col) REFERENCES other_table(id)
            tbl_fk_match = re.search(
                r"(?:CONSTRAINT\s+(\w+)\s+)?FOREIGN\s+KEY\s*\(([\w\s,]+)\)\s+REFERENCES\s+(?:public\.)?(\w+)\s*\(([\w\s,]+)\)",
                item,
                re.IGNORECASE,
            )
            if tbl_fk_match:
                c_name = tbl_fk_match.group(1) or f"fk_{t_name}_{tbl_fk_match.group(3)}"
                src_cols = [c.strip() for c in tbl_fk_match.group(2).split(",")]
                tgt_table = tbl_fk_match.group(3)
                tgt_cols = [c.strip() for c in tbl_fk_match.group(4).split(",")]
                declared_fks.append({
                    "constraint_name": c_name,
                    "source_table": t_name,
                    "source_columns": src_cols,
                    "target_table": tgt_table,
                    "target_columns": tgt_cols,
                })
                continue

            # Skip PRIMARY KEY / UNIQUE / CHECK constraints
            if re.match(r"(?:CONSTRAINT\s+\w+\s+)?(?:PRIMARY\s+KEY|UNIQUE|CHECK)", item, re.IGNORECASE):
                continue

            # Column definition: name type [modifiers]
            parts = item.split()
            if len(parts) >= 2:
                col_name = parts[0].strip('"`')
                col_type = parts[1].lower()

                # Check inline REFERENCES
                # e.g. organization_id INT REFERENCES public.organizations(id)
                inline_ref = re.search(
                    r"REFERENCES\s+(?:public\.)?(\w+)\s*(?:\(([\w\s,]+)\))?",
                    item,
                    re.IGNORECASE,
                )
                if inline_ref:
                    tgt_table = inline_ref.group(1)
                    tgt_col = inline_ref.group(2) or "id"
                    declared_fks.append({
                        "constraint_name": f"fk_{t_name}_{col_name}",
                        "source_table": t_name,
                        "source_columns": [col_name],
                        "target_table": tgt_table,
                        "target_columns": [tgt_col.strip()],
                    })

                is_nullable = "NOT NULL" not in item.upper() and "PRIMARY KEY" not in item.upper()
                tables_data[full_name]["columns"].append({
                    "name": col_name,
                    "ordinal_position": col_ordinal,
                    "data_type": col_type,
                    "udt_name": col_type,
                    "is_nullable": is_nullable,
                    "default": None,
                })
                col_ordinal += 1

    return {
        "catalog": {"tables": tables_data},
        "declared_fks": declared_fks,
        "views": views,
        "partitions": partitions,
    }


def build_benchmark_db_artifacts(
    schema_sql_path: Optional[str | Path] = None,
) -> tuple[list[Node], list[Edge], dict[str, Any]]:
    """
    Build database Nodes, declared & inferred Edges, and raw catalog
    from the benchmark schema.

    Returns:
        Tuple of (nodes, merged_edges, raw_catalog)
    """
    if schema_sql_path is None:
        schema_sql_path = Path(__file__).parent / "schema.sql"
    else:
        schema_sql_path = Path(schema_sql_path)

    sql_content = schema_sql_path.read_text(encoding="utf-8")
    parsed = parse_sql_schema_ddl(sql_content)
    raw_catalog = parsed["catalog"]

    # Build DB Nodes
    nodes: list[Node] = []
    for full_name, t_meta in raw_catalog["tables"].items():
        t_name = t_meta["name"]
        schema = t_meta.get("schema", "public")

        if full_name in parsed["partitions"]:
            node_type = NodeType.PARTITION
            metadata = {
                "schema": schema,
                "table_name": t_name,
                "is_partition": True,
                "parent_table": parsed["partitions"][full_name],
                "columns": t_meta.get("columns", []),
            }
        elif t_meta.get("type") == "VIEW":
            node_type = NodeType.VIEW
            metadata = {
                "schema": schema,
                "table_name": t_name,
                "is_view": True,
                "columns": t_meta.get("columns", []),
            }
        else:
            node_type = NodeType.TABLE
            metadata = {
                "schema": schema,
                "table_name": t_name,
                "columns": t_meta.get("columns", []),
            }

        nodes.append(
            Node(
                id=f"table:{schema}.{t_name}",
                type=node_type,
                name=t_name,
                source_system="postgres",
                metadata=metadata,
            )
        )

    # Build Declared FK Edges (confidence=1.0)
    declared_edges: list[Edge] = []
    for fk in parsed["declared_fks"]:
        src_table = fk["source_table"]
        tgt_table = fk["target_table"]
        src_cols = fk["source_columns"]
        tgt_cols = fk["target_columns"]
        c_name = fk["constraint_name"]

        evidence = (
            f"FK {c_name}: "
            f"public.{src_table}({', '.join(src_cols)}) -> "
            f"public.{tgt_table}({', '.join(tgt_cols)})"
        )
        declared_edges.append(
            Edge(
                source=f"table:public.{src_table}",
                target=f"table:public.{tgt_table}",
                type=EdgeType.DECLARED_FK,
                confidence=1.0,
                evidence=evidence,
                metadata={
                    "constraint_name": c_name,
                    "source_schema": "public",
                    "source_table": src_table,
                    "source_columns": src_cols,
                    "target_schema": "public",
                    "target_table": tgt_table,
                    "target_columns": tgt_cols,
                },
            )
        )

    # Inferred Edges via Naming Conventions (c=0.55 or 0.495)
    inferred_edges = infer_edges_from_naming(raw_catalog, declared_edges=declared_edges)

    # Merge Edges (confirmation bonus on agreement)
    merged_edges = merge_edges(declared_edges, inferred_edges)

    return nodes, merged_edges, raw_catalog
