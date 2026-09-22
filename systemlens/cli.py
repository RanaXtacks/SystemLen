"""SystemLens Command-Line Interface."""

import argparse
import json
import sys
from typing import Optional

from systemlens.adapters.postgres import PostgresAdapter


def main(args: Optional[list[str]] = None) -> int:
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
        help="PostgreSQL connection DSN (e.g. postgresql://user:pass@localhost:5432/dbname)",
    )
    pg_parser.add_argument(
        "--host",
        type=str,
        default="localhost",
        help="PostgreSQL host (default: localhost)",
    )
    pg_parser.add_argument(
        "--port",
        type=int,
        default=5432,
        help="PostgreSQL port (default: 5432)",
    )
    pg_parser.add_argument(
        "--dbname",
        type=str,
        help="PostgreSQL database name",
    )
    pg_parser.add_argument(
        "--user",
        type=str,
        help="PostgreSQL user",
    )
    pg_parser.add_argument(
        "--password",
        type=str,
        help="PostgreSQL password",
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

        if parsed.nodes_output:
            nodes = adapter.extract_nodes()
            with open(parsed.nodes_output, "w", encoding="utf-8") as f:
                json.dump([n.to_dict() for n in nodes], f, indent=2)
            print(f"Extracted {len(nodes)} nodes written to {parsed.nodes_output}")

        if parsed.edges_output:
            edges = adapter.extract_edges()
            with open(parsed.edges_output, "w", encoding="utf-8") as f:
                json.dump([e.to_dict() for e in edges], f, indent=2)
            print(f"Extracted {len(edges)} edges written to {parsed.edges_output}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
