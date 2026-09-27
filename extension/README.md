# SystemLens — VS Code Extension

**"What code touches this database table, and how sure am I?"**

SystemLens answers the critical impact analysis question for backend engineers working with PostgreSQL and Python. Instead of relying on manual grep, outdated ER diagrams, or tribal knowledge, SystemLens statically bridges the database schema catalog with your Python AST, computing reverse-dependency reachability with mathematical path confidence decay.

---

## Features

- **Cross-Layer Traceability**: Traces relationships across both layers:
  - Database schema: Declared foreign keys, views, table inheritance, partitions.
  - Undeclared relationships: Naming conventions (`user_id -> users`, `usr_id -> users`, `shipping_address_id -> addresses`).
  - Code layer: SQLAlchemy ORM calls, Django ORM filters, and raw SQL queries (`SELECT`, `JOIN`, `INSERT`, `UPDATE`, `DELETE`).
- **Mathematical Confidence Scoring**:
  - Every connection has an explicit confidence score $c \in [0, 1]$ based on empirical evidence:
    - Declared Foreign Key: $1.0$
    - Static SQL Literal: $0.85$
    - ORM Call: $0.80$
    - Inferred Naming Match: $0.55$ (or $0.495$ for schema abbreviations)
    - Dynamic Unresolved SQL: $0.15$
  - Multi-hop path decay: $c(\text{path}) = \prod_{e \in \text{path}} c(e_i)$.
- **Honest Blind-Spot Disclosures**:
  - Unresolved dynamic queries (e.g., f-strings, formatted strings) are **never silently dropped or hallucinated**. They are surfaced with low confidence and explicitly itemized in the **Blind Spots** disclosure panel.
- **Rich Visual Webview**:
  - Sleek dark mode interface.
  - Ranked impacted functions with file and line locations.
  - Confidence pills (`HIGH`, `MEDIUM`, `LOW`) and traversal hop badges.
  - Downstream affected database tables and files.

---

## Getting Started

### 1. Generate `graph.json` in Your Workspace
SystemLens analyzes your codebase locally. First, run the CLI scanner to ingest your PostgreSQL schema and analyze your Python source files:

```bash
# 1. Ingest PostgreSQL schema (live or DDL dump)
systemlens ingest-postgres --dsn "postgresql://user:pass@localhost:5432/dbname" --output raw_schema.json

# 2. Infer undeclared naming relationships
systemlens infer-edges --catalog raw_schema.json --output inferred_edges.json

# 3. Analyze Python source code and assemble unified graph
systemlens analyze-python --code ./src --schema raw_schema.json --inferred inferred_edges.json --output graph.json
```

### 2. Run Impact Analysis in VS Code
1. Open the Command Palette (`Ctrl+Shift+P` or `Cmd+Shift+P`).
2. Run **`SystemLens: What touches this?`**.
3. Select or type the table/entity name (e.g., `users`, `orders`, `invoices`).
4. An interactive panel opens beside your editor showing the ranked blast radius, path confidences, and visibility disclosures.

---

## Extension Settings

| Setting | Default | Description |
|---|---|---|
| `systemlens.graphPath` | `graph.json` | Path to the generated `graph.json` file relative to workspace root. |
| `systemlens.defaultDepth` | `2` | Default reachability traversal depth for blast radius queries. |

---

## Requirements

- Python 3.10+ in your environment with `systemlens` installed, or a pre-generated `graph.json` in the workspace root.
- VS Code version 1.80.0 or higher.

---

## License

MIT License.
