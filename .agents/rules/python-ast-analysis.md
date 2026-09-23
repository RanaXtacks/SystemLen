# Rule: Python AST Analysis & SQL/ORM Extraction

## Context
Extracting cross-layer dependencies from Python code to databases requires traversing AST syntax trees, parsing embedded SQL with `sqlparse`, resolving ORM conventions, and classifying dynamic queries without guessing.

## Rules
1. **Confidence Scoring for Code Layer**:
   - Follow `tech.md`:
     - Raw SQL string literal: `EdgeType.STATIC_SQL_STRING` with confidence `0.85`.
     - Structured ORM call (SQLAlchemy / Django): `EdgeType.ORM_CALL` with confidence `0.80`.
     - Dynamic / unresolved query: `EdgeType.DYNAMIC_UNRESOLVED` with confidence `0.15`.
     - Structural function-to-file edge: `EdgeType.STRUCTURAL_BELONGS_TO` with confidence `1.0`.
2. **Subquery Handling in `sqlparse`**:
   - In `sqlparse`, subqueries (e.g. `FROM (SELECT ...) alias`) appear as `Identifier` nodes containing a `Parenthesis` child.
   - Always recurse inside the `Parenthesis` token to find the inner tables, and do NOT treat the subquery's alias as a database table name.
3. **ORM Model-to-Table Resolution**:
   - Pre-scan all Python files for `__tablename__ = "..."` (SQLAlchemy) and `class Meta: db_table = "..."` (Django) to build a project-wide model registry.
   - For unmapped model classes, fall back to PascalCase-to-snake_case conversion followed by English pluralization (`OrderItem` -> `order_items`).
4. **Honesty Layer (No Silent Dropping)**:
   - When `.execute()` is called with an f-string, variable, or string concatenation, do NOT attempt heuristic guessing that could introduce hallucinations.
   - Emit an `EdgeType.DYNAMIC_UNRESOLVED` edge targeting `table:unresolved` with the AST node type and line number.
   - Disclose the ratio of dynamic queries in graph summaries; flag a warning if `dynamic_ratio > 40%`.
5. **Defensive Output Directory Creation**:
   - When writing CLI output artifacts (e.g. `graph.json`, `nodes.json`), always call `os.makedirs(os.path.dirname(filepath), exist_ok=True)` before opening file streams.
