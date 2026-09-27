# SystemLens

**Cross-layer dependency tracing & blast radius analyzer.**  
Answers: *"What code and downstream tables touch this database entity, and how sure am I?"* — directly inside VS Code and in your CI/CD pull requests, with explicit multiplicative path confidence scores and an honest disclosure of what static analysis cannot see.

---

## ⚡ What's New in V2

1. **CI/PR Automated Impact Analysis (`systemlens ci-diff`)**
   - Automatically runs on pull requests to identify modified files, map them to database tables, and post detailed blast radius comments before code is merged.
   - Includes GitHub Actions workflow (`.github/workflows/systemlens.yml`).

2. **Full VS Code Extension Suite (v0.2.0)**
   - **Activity Bar Impact Explorer:** Persistent sidebar displaying all tables, touching functions, foreign keys, blind spots, and graph metrics.
   - **CodeLens Inline Annotations:** Displays `⚡ SystemLens: Touches N table(s) (users, orders) — View Blast Radius` directly above Python and JS/TS function definitions.
   - **Gutter & Inline Decorations:** Colored icons on lines executing SQL literals (🔵), ORM calls (🟡), and dynamic queries (🔴).
   - **Interactive D3.js Force-Directed Graph:** Zoomable, draggable visual graph explorer with node-type filtering and blast radius path highlighting.

3. **Multi-Language & Multi-Database Adapters**
   - **Languages:** Python (AST + sqlparse) & JavaScript/TypeScript (Knex, Prisma, Sequelize, raw SQL template literals).
   - **Databases:** PostgreSQL (`ingest-postgres`), SQLite (`ingest-sqlite`), and MySQL / MariaDB (`ingest-mysql`).

4. **Real-Repo Validated**
   - Tested on [Saleor](https://github.com/saleor/saleor) e-commerce backend: analyzed **903 functions** across **351 files**, extracting **1,287 nodes** and **1,541 edges** with a **99.8% static ORM resolution rate** (0.2% dynamic ratio).

---

## 🚀 Quick Start

### Installation

```bash
git clone https://github.com/RanaXtacks/SystemLen.git
cd SystemLen
pip install -e .
```

### 1. Ingest Database Schema

**PostgreSQL:**
```bash
systemlens ingest-postgres --dsn "postgresql://user:pass@localhost:5432/mydb" --output raw_schema.json
```

**SQLite:**
```bash
systemlens ingest-sqlite --db path/to/app.db --output raw_schema.json
```

**MySQL:**
```bash
systemlens ingest-mysql --host localhost --database mydb --user root --output raw_schema.json
```

### 2. Analyze Codebase & Assemble Graph

**Python:**
```bash
systemlens analyze-python --src-dir ./src --schema-file raw_schema.json --merged-graph-output graph.json
```

**JavaScript / TypeScript:**
```bash
systemlens analyze-js --src-dir ./src --schema-file raw_schema.json --merged-graph-output graph.json
```

### 3. Query Blast Radius

```bash
systemlens impact --target users --graph graph.json --depth 2
```

### 4. Run CI Diff Impact Analysis

```bash
systemlens ci-diff --base origin/main --head HEAD --graph graph.json --format markdown
```

---

## 💻 VS Code Extension

Install the packaged VSIX extension from `./extension`:

```bash
code --install-extension extension/systemlens-0.2.0.vsix
```

### Features:
- **SystemLens Explorer:** Open the Activity Bar icon to explore your schema and functions.
- **What Touches This?:** Press `Ctrl+Shift+P` (or `Cmd+Shift+P`) → `SystemLens: What touches this?` or click the `$(eye) SystemLens` status bar button.
- **Dependency Graph:** Click the `$(graph) Graph` button in the status bar to open the interactive D3 visualizer.
- **CodeLens:** Click on the annotations above function definitions to view blast radius instantly.

---

## 🔬 Test Suite

Run all 84 test cases:

```bash
pytest
```

---

## ⚠️ Honesty Layer (Explicit Limitations)

- Dynamic SQL, reflections, and cross-service RPC/HTTP/queue boundaries are flagged explicitly as **Blind Spots** in every query and PR comment rather than being silently ignored.
- Confidence decay math: Multiplicative decay along the reachability path:  
  $$c(\text{path}) = \prod_{i=1}^{k} c(\text{edge}_i)$$
- No NoSQL support: relational & schema-bound entities only.
