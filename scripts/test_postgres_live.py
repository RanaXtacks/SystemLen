"""Integration test and live verification script for SystemLens PostgresAdapter.

Can be run against any live PostgreSQL instance to verify schema extraction,
foreign key resolution, views, table inheritance, and partitioned tables.

Usage:
  # Against an existing database:
  uv run python scripts/test_postgres_live.py --dsn "postgresql://user:pass@localhost:5432/mydb"

  # Create a self-contained demo schema with tables, FKs, views, partitions, test it, and clean up:
  uv run python scripts/test_postgres_live.py --dsn "postgresql://user:pass@localhost:5432/mydb" --setup-demo
"""

import argparse
import json
import os
import sys
from typing import Any, Optional

try:
    import psycopg2
except ImportError:
    psycopg2 = None  # type: ignore

from systemlens.adapters.postgres import PostgresAdapter
from systemlens.models import EdgeType, NodeType

DEMO_SCHEMA_NAME = "systemlens_demo"

DEMO_DDL = f"""
CREATE SCHEMA IF NOT EXISTS {DEMO_SCHEMA_NAME};

-- 1. Base entities
CREATE TABLE IF NOT EXISTS {DEMO_SCHEMA_NAME}.users (
    id SERIAL PRIMARY KEY,
    tenant_id INT NOT NULL,
    email VARCHAR(255) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_user_tenant UNIQUE (id, tenant_id)
);

CREATE TABLE IF NOT EXISTS {DEMO_SCHEMA_NAME}.orders (
    id SERIAL PRIMARY KEY,
    user_id INT NOT NULL,
    total_amount NUMERIC(10, 2) NOT NULL,
    order_date DATE NOT NULL,
    CONSTRAINT fk_orders_user FOREIGN KEY (user_id)
        REFERENCES {DEMO_SCHEMA_NAME}.users(id) ON DELETE CASCADE
);

-- 2. Composite Foreign Key table
CREATE TABLE IF NOT EXISTS {DEMO_SCHEMA_NAME}.user_profiles (
    user_id INT NOT NULL,
    tenant_id INT NOT NULL,
    bio TEXT,
    PRIMARY KEY (user_id, tenant_id),
    CONSTRAINT fk_user_profiles_user FOREIGN KEY (user_id, tenant_id)
        REFERENCES {DEMO_SCHEMA_NAME}.users(id, tenant_id) ON DELETE CASCADE
);

-- 3. View
CREATE OR REPLACE VIEW {DEMO_SCHEMA_NAME}.active_users_view AS
    SELECT id, email, created_at
    FROM {DEMO_SCHEMA_NAME}.users;

-- 4. Partitioned table (PG 10+ declarative partitioning)
CREATE TABLE IF NOT EXISTS {DEMO_SCHEMA_NAME}.events (
    id BIGSERIAL,
    event_time TIMESTAMP NOT NULL,
    event_type VARCHAR(50) NOT NULL,
    payload JSONB,
    PRIMARY KEY (id, event_time)
) PARTITION BY RANGE (event_time);

CREATE TABLE IF NOT EXISTS {DEMO_SCHEMA_NAME}.events_2026_q1
    PARTITION OF {DEMO_SCHEMA_NAME}.events
    FOR VALUES FROM ('2026-01-01') TO ('2026-04-01');

CREATE TABLE IF NOT EXISTS {DEMO_SCHEMA_NAME}.events_2026_q2
    PARTITION OF {DEMO_SCHEMA_NAME}.events
    FOR VALUES FROM ('2026-04-01') TO ('2026-07-01');

-- 5. Traditional table inheritance
CREATE TABLE IF NOT EXISTS {DEMO_SCHEMA_NAME}.audit_log_base (
    log_id SERIAL PRIMARY KEY,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS {DEMO_SCHEMA_NAME}.audit_log_security (
    ip_address VARCHAR(45) NOT NULL,
    action VARCHAR(100) NOT NULL
) INHERITS ({DEMO_SCHEMA_NAME}.audit_log_base);
"""

DEMO_TEARDOWN = f"DROP SCHEMA IF EXISTS {DEMO_SCHEMA_NAME} CASCADE;"


def setup_demo_schema(dsn: str) -> None:
    print(f"Setting up demo schema '{DEMO_SCHEMA_NAME}'...")
    conn = psycopg2.connect(dsn)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(DEMO_DDL)
        print("Demo schema created successfully.")
    finally:
        conn.close()


def teardown_demo_schema(dsn: str) -> None:
    print(f"Tearing down demo schema '{DEMO_SCHEMA_NAME}'...")
    conn = psycopg2.connect(dsn)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(DEMO_TEARDOWN)
        print("Demo schema torn down successfully.")
    finally:
        conn.close()


def run_verification(
    adapter: PostgresAdapter,
    schema_output: str = "raw_schema.json",
    nodes_output: str = "nodes.json",
    edges_output: str = "edges.json",
) -> int:
    print("=" * 60)
    print("SystemLens PostgreSQL Introspection Verification")
    print("=" * 60)

    # 1. Raw catalog
    print("\n[1/3] Extracting raw catalog (tables & columns)...")
    catalog = adapter.dump_raw_schema(output_path=schema_output)
    tables = catalog.get("tables", {})
    table_count = len(tables)
    col_count = sum(len(t.get("columns", [])) for t in tables.values())
    print(f"  -> Found {table_count} tables/views, {col_count} total columns.")
    print(f"  -> Dumped catalog to {schema_output}")

    # 2. Nodes
    print("\n[2/3] Extracting graph nodes (with views & partitions)...")
    nodes = adapter.extract_nodes()
    node_counts: dict[str, int] = {}
    for n in nodes:
        t = n.type.value if hasattr(n.type, "value") else str(n.type)
        node_counts[t] = node_counts.get(t, 0) + 1

    print(f"  -> Extracted {len(nodes)} total nodes:")
    for n_type, count in sorted(node_counts.items()):
        print(f"     * {n_type.upper()}: {count}")

    with open(nodes_output, "w", encoding="utf-8") as f:
        json.dump([n.to_dict() for n in nodes], f, indent=2)
    print(f"  -> Dumped nodes to {nodes_output}")

    # 3. Edges
    print("\n[3/3] Extracting edges (declared FKs + structural edges)...")
    edges = adapter.extract_edges()
    edge_counts: dict[str, int] = {}
    for e in edges:
        t = e.type.value if hasattr(e.type, "value") else str(e.type)
        edge_counts[t] = edge_counts.get(t, 0) + 1

    print(f"  -> Extracted {len(edges)} total edges:")
    for e_type, count in sorted(edge_counts.items()):
        print(f"     * {e_type.upper()}: {count}")

    print("\nSample Edges:")
    for edge in edges[:10]:
        print(f"  [{edge.type.value}] {edge.source} -> {edge.target} (conf={edge.confidence})")
        print(f"      Evidence: {edge.evidence}")

    with open(edges_output, "w", encoding="utf-8") as f:
        json.dump([e.to_dict() for e in edges], f, indent=2)
    print(f"\n  -> Dumped edges to {edges_output}")

    print("\n" + "=" * 60)
    print("Verification Completed Successfully!")
    print("=" * 60)
    return 0


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


def main() -> int:
    load_dotenv()

    parser = argparse.ArgumentParser(description="Live integration test for SystemLens PostgresAdapter")
    parser.add_argument("--dsn", type=str, default=os.getenv("DATABASE_URL"), help="PostgreSQL DSN (default: $DATABASE_URL)")
    parser.add_argument("--host", type=str, default=os.getenv("PGHOST", "localhost"), help="PostgreSQL host (default: $PGHOST or localhost)")
    parser.add_argument("--port", type=int, default=int(os.getenv("PGPORT", "5432")), help="PostgreSQL port (default: $PGPORT or 5432)")
    parser.add_argument("--dbname", type=str, default=os.getenv("PGDATABASE"), help="Database name (default: $PGDATABASE)")
    parser.add_argument("--user", type=str, default=os.getenv("PGUSER"), help="Database user (default: $PGUSER)")
    parser.add_argument("--password", type=str, default=os.getenv("PGPASSWORD"), help="Database password (default: $PGPASSWORD)")
    parser.add_argument("--schema", action="append", dest="schemas", help="Target schema (repeatable)")
    parser.add_argument("--setup-demo", action="store_true", help="Set up and test against a temporary demo schema")
    parser.add_argument("--keep-demo", action="store_true", help="Do not tear down the demo schema after testing")
    parser.add_argument("--output", default="raw_schema.json", help="Output path for raw schema")
    parser.add_argument("--nodes-output", default="nodes.json", help="Output path for nodes")
    parser.add_argument("--edges-output", default="edges.json", help="Output path for edges")

    args = parser.parse_args()

    dsn = args.dsn
    if not dsn:
        if args.dbname and args.user:
            pwd = f":{args.password}" if args.password else ""
            dsn = f"postgresql://{args.user}{pwd}@{args.host}:{args.port}/{args.dbname}"
        else:
            print("Error: Provide --dsn or (--dbname and --user), or set DATABASE_URL in .env.", file=sys.stderr)
            return 1

    schemas = args.schemas
    if args.setup_demo:
        setup_demo_schema(dsn)
        schemas = [DEMO_SCHEMA_NAME]

    try:
        adapter = PostgresAdapter(dsn=dsn, schemas=schemas)
        exit_code = run_verification(
            adapter,
            schema_output=args.output,
            nodes_output=args.nodes_output,
            edges_output=args.edges_output,
        )
    finally:
        if args.setup_demo and not args.keep_demo:
            teardown_demo_schema(dsn)

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
