"""SystemLens Command-Line Interface."""

import argparse
import json
import os
import sys
from typing import Optional

from systemlens.adapters.postgres import PostgresAdapter
from systemlens.inference.merge import compute_merge_stats, merge_edges
from systemlens.inference.naming import infer_edges_from_naming
from systemlens.models import Edge


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

    # Subcommand: ingest-postgres
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

    # Subcommand: infer-edges
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

    return 0


if __name__ == "__main__":
    sys.exit(main())
