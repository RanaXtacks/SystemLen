"""SystemLens Command-Line Interface."""

import argparse
import json
import os
import sys
from typing import Optional

from systemlens.adapters.postgres import PostgresAdapter
from systemlens.adapters.python_ast import PythonASTAdapter
from systemlens.graph import assemble_unified_graph
from systemlens.inference.merge import compute_merge_stats, merge_edges
from systemlens.inference.naming import infer_edges_from_naming
from systemlens.models import Edge, Node, NodeType
from systemlens.query.impact import ImpactEngine


def _ensure_parent_dir(filepath: str | None) -> None:
    """Ensure that the parent directory for a target file path exists."""
    if filepath:
        parent = os.path.dirname(os.path.abspath(filepath))
        if parent:
            os.makedirs(parent, exist_ok=True)


def load_dotenv(filepath: str = ".env") -> None:
    """Load key-value pairs from a .env file into os.environ if not already set."""
    if not os.path.exists(filepath):
        return
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, val = line.split("=", 1)
                    key = key.strip()
                    val = val.strip().strip("'\"")
                    if key and key not in os.environ:
                        os.environ[key] = val
    except Exception:
        pass


def main(args: Optional[list[str]] = None) -> int:
    load_dotenv()

    parser = argparse.ArgumentParser(
        prog="systemlens",
        description="SystemLens: Cross-layer dependency tracing & blast radius analyzer",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Subcommand 1: ingest-postgres
    pg_parser = subparsers.add_parser(
        "ingest-postgres",
        help="Introspect a PostgreSQL database schema and export raw catalog or nodes",
    )
    pg_parser.add_argument(
        "--dsn",
        type=str,
        default=os.getenv("DATABASE_URL"),
        help="PostgreSQL connection DSN (default: $DATABASE_URL)",
    )
    pg_parser.add_argument(
        "--host",
        type=str,
        default=os.getenv("PGHOST", "localhost"),
        help="PostgreSQL host (default: $PGHOST or localhost)",
    )
    pg_parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("PGPORT", "5432")),
        help="PostgreSQL port (default: $PGPORT or 5432)",
    )
    pg_parser.add_argument(
        "--dbname",
        type=str,
        default=os.getenv("PGDATABASE"),
        help="PostgreSQL database name (default: $PGDATABASE)",
    )
    pg_parser.add_argument(
        "--user",
        type=str,
        default=os.getenv("PGUSER"),
        help="PostgreSQL user (default: $PGUSER)",
    )
    pg_parser.add_argument(
        "--password",
        type=str,
        default=os.getenv("PGPASSWORD"),
        help="PostgreSQL password (default: $PGPASSWORD)",
    )
    pg_parser.add_argument(
        "--schema",
        action="append",
        dest="schemas",
        help="Target schema (repeatable, e.g. --schema public --schema app)",
    )
    pg_parser.add_argument(
        "--output",
        "-o",
        type=str,
        default="raw_schema.json",
        help="Output file path for raw schema JSON (default: raw_schema.json)",
    )
    pg_parser.add_argument(
        "--edges-output",
        type=str,
        default=None,
        help="Optional output file path for extracted edges JSON",
    )
    pg_parser.add_argument(
        "--nodes-output",
        type=str,
        default=None,
        help="Optional output file path for extracted graph nodes JSON",
    )
    pg_parser.add_argument(
        "--infer-naming",
        action="store_true",
        help="Run naming convention inference after schema extraction",
    )
    pg_parser.add_argument(
        "--inferred-edges-output",
        type=str,
        default=None,
        help="Optional output file path for inferred edges JSON",
    )
    pg_parser.add_argument(
        "--merged-edges-output",
        type=str,
        default=None,
        help="Optional output file path for merged (declared + inferred) edges JSON",
    )

    # Subcommand 2: infer-edges
    infer_parser = subparsers.add_parser(
        "infer-edges",
        help="Infer candidate relational edges from column naming conventions in a raw schema file",
    )
    infer_parser.add_argument(
        "--schema-file",
        "-s",
        type=str,
        default="raw_schema.json",
        help="Input raw schema JSON file path (default: raw_schema.json)",
    )
    infer_parser.add_argument(
        "--declared-edges",
        type=str,
        default=None,
        help="Optional input path to declared edges JSON for agreement checking",
    )
    infer_parser.add_argument(
        "--output",
        "-o",
        type=str,
        default="inferred_edges.json",
        help="Output file path for inferred edges JSON (default: inferred_edges.json)",
    )
    infer_parser.add_argument(
        "--merged-output",
        type=str,
        default=None,
        help="Optional output file path for merged graph edges JSON",
    )
    infer_parser.add_argument(
        "--deduplicate",
        action="store_true",
        help="Deduplicate inferred edges that overlap with declared FKs",
    )

    # Subcommand 3: analyze-python (Step 2)
    ast_parser = subparsers.add_parser(
        "analyze-python",
        help="Statically analyze a Python codebase with AST for SQL queries, ORM calls, and dynamic queries",
    )
    ast_parser.add_argument(
        "--src-dir",
        "-s",
        type=str,
        default=".",
        help="Path to the Python source directory or file to analyze (default: current directory)",
    )
    ast_parser.add_argument(
        "--schema-file",
        type=str,
        default=None,
        help="Optional raw schema JSON file to resolve table names and link schema nodes",
    )
    ast_parser.add_argument(
        "--nodes-output",
        type=str,
        default=None,
        help="Optional output file path for extracted code nodes JSON",
    )
    ast_parser.add_argument(
        "--edges-output",
        type=str,
        default=None,
        help="Optional output file path for extracted code edges JSON",
    )
    ast_parser.add_argument(
        "--merged-graph-output",
        "-o",
        type=str,
        default="graph.json",
        help="Output file path for unified cross-layer graph JSON (default: graph.json)",
    )

    # Subcommand 4: impact (Step 3)
    impact_parser = subparsers.add_parser(
        "impact",
        help="Query the blast radius of a table or entity across the unified cross-layer graph",
    )
    impact_parser.add_argument(
        "--target",
        "-t",
        type=str,
        required=True,
        help="Name or ID of the database table or node to query (e.g. 'users', 'table:public.users')",
    )
    impact_parser.add_argument(
        "--graph",
        "-g",
        type=str,
        default="graph.json",
        help="Path to the unified graph JSON file (default: graph.json)",
    )
    impact_parser.add_argument(
        "--depth",
        "-d",
        type=int,
        default=2,
        help="Maximum reachability traversal depth (default: 2)",
    )
    impact_parser.add_argument(
        "--min-confidence",
        type=float,
        default=0.0,
        help="Minimum path confidence threshold to include (default: 0.0)",
    )
    impact_parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="Output raw JSON result to stdout",
    )
    impact_parser.add_argument(
        "--output",
        "-o",
        type=str,
        default=None,
        help="Optional output file path to write the impact query JSON result",
    )

    parsed = parser.parse_args(args)

    if parsed.command == "ingest-postgres":
        if parsed.dsn:
            adapter = PostgresAdapter(dsn=parsed.dsn, schemas=parsed.schemas)
        else:
            if not parsed.dbname or not parsed.user:
                print("Error: Either --dsn or (--dbname and --user) must be provided.", file=sys.stderr)
                return 1
            adapter = PostgresAdapter(
                host=parsed.host,
                port=parsed.port,
                dbname=parsed.dbname,
                user=parsed.user,
                password=parsed.password,
                schemas=parsed.schemas,
            )

        print("Connecting to PostgreSQL database and extracting schema...")
        catalog = adapter.dump_raw_schema(output_path=parsed.output)
        table_count = len(catalog.get("tables", {}))
        col_count = sum(len(t.get("columns", [])) for t in catalog.get("tables", {}).values())
        print(f"Extraction successful: {table_count} tables, {col_count} columns written to {parsed.output}")

        declared_edges: list[Edge] = []
        if parsed.nodes_output:
            nodes = adapter.extract_nodes()
            with open(parsed.nodes_output, "w", encoding="utf-8") as f:
                json.dump([n.to_dict() for n in nodes], f, indent=2)
            print(f"Extracted {len(nodes)} nodes written to {parsed.nodes_output}")

        if parsed.edges_output or parsed.infer_naming or parsed.merged_edges_output:
            declared_edges = adapter.extract_edges()
            if parsed.edges_output:
                with open(parsed.edges_output, "w", encoding="utf-8") as f:
                    json.dump([e.to_dict() for e in declared_edges], f, indent=2)
                print(f"Extracted {len(declared_edges)} declared edges written to {parsed.edges_output}")

        if parsed.infer_naming or parsed.inferred_edges_output or parsed.merged_edges_output:
            inferred_edges = infer_edges_from_naming(catalog)
            print(f"Inferred {len(inferred_edges)} relational edges from naming conventions.")

            if parsed.inferred_edges_output:
                with open(parsed.inferred_edges_output, "w", encoding="utf-8") as f:
                    json.dump([e.to_dict() for e in inferred_edges], f, indent=2)
                print(f"Inferred edges written to {parsed.inferred_edges_output}")

            if parsed.merged_edges_output:
                merged = merge_edges(declared_edges, inferred_edges)
                stats = compute_merge_stats(declared_edges, inferred_edges, merged)
                with open(parsed.merged_edges_output, "w", encoding="utf-8") as f:
                    json.dump([e.to_dict() for e in merged], f, indent=2)
                print(
                    f"Merged {len(merged)} edges ({stats['agreements']} agreements) "
                    f"written to {parsed.merged_edges_output}"
                )

    elif parsed.command == "infer-edges":
        if not os.path.exists(parsed.schema_file):
            print(f"Error: Schema file '{parsed.schema_file}' not found.", file=sys.stderr)
            return 1

        with open(parsed.schema_file, "r", encoding="utf-8") as f:
            catalog = json.load(f)

        inferred_edges = infer_edges_from_naming(catalog)
        with open(parsed.output, "w", encoding="utf-8") as f:
            json.dump([e.to_dict() for e in inferred_edges], f, indent=2)
        print(f"Inferred {len(inferred_edges)} relational edges written to {parsed.output}")

        if parsed.declared_edges or parsed.merged_output:
            declared_edges: list[Edge] = []
            if parsed.declared_edges and os.path.exists(parsed.declared_edges):
                with open(parsed.declared_edges, "r", encoding="utf-8") as f:
                    raw_declared = json.load(f)
                    declared_edges = [Edge.from_dict(d) for d in raw_declared]

            merged = merge_edges(declared_edges, inferred_edges, deduplicate=parsed.deduplicate)
            stats = compute_merge_stats(declared_edges, inferred_edges, merged)
            print(
                f"Merge stats: {stats['total_declared_fk']} declared FKs, "
                f"{stats['total_inferred']} inferred, {stats['agreements']} agreements "
                f"(agreement rate: {stats['agreement_rate']:.1%})"
            )

            if parsed.merged_output:
                with open(parsed.merged_output, "w", encoding="utf-8") as f:
                    json.dump([e.to_dict() for e in merged], f, indent=2)
                print(f"Merged edges written to {parsed.merged_output}")

    elif parsed.command == "analyze-python":
        known_tables: list[str] = []
        db_nodes: list[Node] = []
        db_edges: list[Edge] = []

        if parsed.schema_file and os.path.exists(parsed.schema_file):
            with open(parsed.schema_file, "r", encoding="utf-8") as f:
                catalog = json.load(f)
            for tbl_full_name, t_info in catalog.get("tables", {}).items():
                known_tables.append(tbl_full_name)
                db_nodes.append(
                    Node(
                        id=f"table:{tbl_full_name}",
                        type=NodeType.TABLE,
                        name=t_info.get("name", tbl_full_name),
                        source_system="postgres",
                        metadata=t_info,
                    )
                )

        adapter = PythonASTAdapter(root_dir=parsed.src_dir, known_tables=known_tables)
        print(f"Analyzing Python codebase at '{parsed.src_dir}'...")
        code_nodes = adapter.extract_nodes()
        code_edges = adapter.extract_edges()

        func_count = sum(1 for n in code_nodes if n.type == NodeType.FUNCTION)
        file_count = sum(1 for n in code_nodes if n.type == NodeType.FILE)
        print(f"Extracted {func_count} functions across {file_count} files.")

        if parsed.nodes_output:
            _ensure_parent_dir(parsed.nodes_output)
            with open(parsed.nodes_output, "w", encoding="utf-8") as f:
                json.dump([n.to_dict() for n in code_nodes], f, indent=2)
            print(f"Code nodes written to {parsed.nodes_output}")

        if parsed.edges_output:
            _ensure_parent_dir(parsed.edges_output)
            with open(parsed.edges_output, "w", encoding="utf-8") as f:
                json.dump([e.to_dict() for e in code_edges], f, indent=2)
            print(f"Code edges written to {parsed.edges_output}")

        unified = assemble_unified_graph(
            db_nodes=db_nodes,
            db_edges=db_edges,
            code_nodes=code_nodes,
            code_edges=code_edges,
        )
        metrics = unified["metrics"]
        print("\nCross-Layer Dependency Metrics:")
        print(f"  * Total Graph Nodes: {metrics['total_nodes']}")
        print(f"  * Total Graph Edges: {metrics['total_edges']}")
        c_db = metrics["code_to_db"]
        print(f"  * Code-to-DB Calls: {c_db['total_access_calls']}")
        print(f"    - Static SQL Literals: {c_db['static_sql_count']}")
        print(f"    - ORM Calls:           {c_db['orm_call_count']}")
        print(f"    - Dynamic Unresolved:  {c_db['dynamic_unresolved_count']} (ratio: {c_db['dynamic_unresolved_ratio']:.1%})")
        if c_db["kill_check_warning"]:
            print("  [WARNING] Dynamic unresolved ratio exceeds 40% threshold (disclosed honesty layer)!")

        _ensure_parent_dir(parsed.merged_graph_output)
        with open(parsed.merged_graph_output, "w", encoding="utf-8") as f:
            json.dump(unified, f, indent=2)
        print(f"\nUnified cross-layer graph written to {parsed.merged_graph_output}")

    elif parsed.command == "impact":
        if not os.path.exists(parsed.graph):
            print(
                f"Error: Graph file '{parsed.graph}' not found. "
                "Run 'ingest-postgres' and 'analyze-python' first.",
                file=sys.stderr,
            )
            return 1

        engine = ImpactEngine.from_graph_file(parsed.graph)
        result = engine.blast_radius(
            target=parsed.target,
            max_depth=parsed.depth,
            min_confidence=parsed.min_confidence,
        )

        if parsed.output:
            _ensure_parent_dir(parsed.output)
            with open(parsed.output, "w", encoding="utf-8") as f:
                json.dump(result.to_dict(), f, indent=2)

        if parsed.as_json:
            print(json.dumps(result.to_dict(), indent=2))
        else:
            print("=" * 65)
            print(f"SystemLens Blast Radius Analysis for [{result.target_type}] '{result.target_name}'")
            print("=" * 65)
            print(f"Resolved Target ID: {result.target_id}")
            print(f"Traversal Depth:    {result.max_depth}")
            print(f"Total Impacted:     {result.total_impacted} entities")
            print(f"  - Functions:      {len(result.impacted_functions)}")
            print(f"  - Files:          {len(result.impacted_files)}")
            print(f"  - Downstream DB:  {len(result.impacted_tables)}")
            print("-" * 65)

            if result.impacted_functions:
                print("\nImpacted Functions (Ranked by Path Confidence):")
                for fn in result.impacted_functions[:15]:
                    conf_pct = f"{fn.confidence:.1%}"
                    file_info = fn.metadata.get("file", "")
                    line_info = f":{fn.metadata.get('lineno')}" if fn.metadata.get("lineno") else ""
                    print(f"  [{conf_pct:>6}] {fn.name} ({file_info}{line_info}) [hop {fn.depth}]")

            if result.impacted_files:
                print("\nImpacted Files:")
                for fl in result.impacted_files[:10]:
                    conf_pct = f"{fl.confidence:.1%}"
                    print(f"  [{conf_pct:>6}] {fl.name} [hop {fl.depth}]")

            if result.impacted_tables:
                print("\nImpacted Downstream Tables (FKs / Views):")
                for tb in result.impacted_tables[:10]:
                    conf_pct = f"{tb.confidence:.1%}"
                    print(f"  [{conf_pct:>6}] {tb.name} [hop {tb.depth}]")

            print("\nBlind Spots (Not Visible / Unanalyzed Boundaries):")
            for bs in result.blind_spots:
                severity = bs.get("severity", "info").upper()
                msg = bs.get("message", "")
                print(f"  * [{severity}] {msg}")
            print("=" * 65)

    return 0


if __name__ == "__main__":
    sys.exit(main())
