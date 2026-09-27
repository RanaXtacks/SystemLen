# Rule: Postgres Introspection Adapter Testing Pattern

## Context
Introspecting PostgreSQL schemas involves chained queries across `information_schema` (tables, columns, constraints) and `pg_catalog` (inheritance, partitions). When writing mock tests or running against restricted database users:

## Rules
1. **Defensive query execution**:
   - Introspection helper methods querying optional catalog tables (`pg_inherits`, `pg_partitioned_table`) must catch `(Exception, StopIteration)` to gracefully degrade without crashing when running against mock connections or restricted permissions.
2. **DictCursor simulation**:
   - Use a lightweight `MockDictRow(dict)` subclass to accurately simulate `psycopg2.extras.DictCursor` rows in unit test fixtures.
3. **Composite key grouping**:
   - Group referential constraint records by constraint name and source/target table so that composite foreign keys emit a single cohesive graph edge with all column pairs preserved in metadata rather than producing separate disconnected edges.
