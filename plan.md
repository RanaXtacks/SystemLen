# SystemLens — Build Plan (Steps 0–4, day-level)

Rule: do not start a step before the prior one produces its stated output. Do not touch anything in the deferred backlog before Step 4's test result comes back. Total: ~17-19 working days solo, ~3.5 weeks.

Each day below has one deliverable file/module and one check. If a day's check fails, fix it before starting the next day — don't carry broken foundations forward, that's how the original 6-month doc happened.

---

## Step 0 — Postgres schema ingest (Days 1–3)

**Day 1 — Connection + raw catalog dump**
- Build: `systemlens/adapters/postgres.py` — connect via `psycopg2`, query `information_schema.tables`, `information_schema.columns`
- Output file: `raw_schema.json` (tables + columns, no relationships yet)
- Check: run against 2 different real Postgres DBs (not toy schemas). If column types/nullability don't parse cleanly, fix here — don't patch downstream.

**Day 2 — Declared FK extraction**
- Build: extend `postgres.py` — query `information_schema.table_constraints` + `key_column_usage` for FKs
- Output: `Edge(type=declared_fk, confidence=1.0)` objects, merged into `raw_schema.json`
- Check: manually verify FK count against `\d+ tablename` in psql for 5 random tables. Must match exactly — this is your one fully-deterministic layer, no room for drift here.

**Day 3 — Edge cases: views, inheritance, partitions**
- Build: handle Postgres table inheritance (`pg_inherits`) and partitioned tables (don't double-count parent+partition as separate unrelated nodes)
- Output: `Node` schema finalized — `node_type: table|view|partition`
- Check (Step 0 kill check): if this breaks on a real messy DB with views/partitions, stop here and fix before Step 1. This is the "can you even read the schema" gate — everything downstream assumes this works.

---

## Step 1 — Inferred relational edges (Days 4–7)

**Day 4 — Naming-convention matcher**
- Build: `systemlens/inference/naming.py` — regex/heuristic match `*_id` columns to candidate parent tables (`user_id` → `users`)
- Output: `Edge(type=inferred_naming, confidence=0.55)` candidates, unmerged with declared edges yet
- Check: spot-check 20 inferred edges by hand. Note false positive rate now — you'll need this number for Day 6.

**Day 5 — Partial/fuzzy naming pass**
- Build: handle `usr_id`, abbreviations, pluralization mismatches — apply `× 0.9` modifier per `tech.md` formula
- Output: modifier logic added to `Edge.confidence` computation
- Check: re-run Day 4's 20-edge spot check, confirm modifier reduces confidence on the fuzzy matches specifically, not uniformly.

**Day 6 — Merge declared + inferred, precision check**
- Build: merge logic — if declared_fk AND inferred_naming both point to same edge, apply `×1.0` agreement bonus (not stacking, just confirms)
- Output: unified `graph.json` with two distinguishable edge classes
- Check (Step 1 kill check): full precision pass on inferred edges only. If >30% wrong on manual review, stop — tighten heuristic Day 7, do not proceed to Step 2 with bad inference feeding into it.

**Day 7 — Buffer / heuristic tightening**
- Use only if Day 6 check failed. Otherwise: write `tests/test_inference.py` with the 20+ hand-checked edges as a regression fixture — you'll want this later when you touch this code again.

---

## Step 2 — Python static analysis + cross-layer link (Days 8–14)

**Day 8 — AST walker skeleton**
- Build: `systemlens/adapters/python_ast.py` — walk source tree with stdlib `ast`, extract all function defs + file locations
- Output: `Node(type=function)` list, no table links yet
- Check: run on a 50+ file real repo, confirm function count is sane (spot check against `grep -c "^def "` roughly).

**Day 9 — Raw SQL string detection**
- Build: detect string literals passed to `.execute()`/`cursor.execute()` calls, parse table name via `sqlparse`
- Output: `Edge(type=static_sql_string, confidence=0.85)` from function → table
- Check: 15 manual spot checks on functions with obvious raw SQL. Must be near-100% correct — this is your highest-confidence code-layer signal.

**Day 10 — ORM call detection (SQLAlchemy pattern)**
- Build: detect `.query(Model)`, `session.query()`, model class → table name mapping
- Output: `Edge(type=orm_call, confidence=0.8)`
- Check: same 15-function spot check style, different sample. Note any ORM pattern you're NOT catching yet (e.g. raw `Model.objects.filter` if Django-style) — write it down, don't silently miss it.

**Day 11 — Dynamic/unresolved detection (the honesty layer)**
- Build: detect calls to `.execute()` with a variable (not a literal) as argument, f-strings building queries, `getattr`-style dynamic table access — flag these as `Edge(type=dynamic_unresolved, confidence=0.15)`, don't try to resolve them
- Output: every DB-touching function is now classified, even the ones you can't fully resolve
- Check: count what % of DB calls land in `dynamic_unresolved` on your test repo. Write this number down — it's a direct input to Step 4's success read.

**Day 12 — Function → table graph merge**
- Build: merge Python-layer nodes/edges into the same `graph.json` from Step 1
- Output: single unified graph, 3 node types, 5 edge types, all confidence-scored
- Check: pick 5 tables, manually trace which functions should touch them by reading code, compare to graph output.

**Day 13 — File-level rollup**
- Build: add `file` node type, `function belongs_to file` edges (structural, confidence=1.0, deterministic — this one's free)
- Output: graph now supports "what file touches this table" as well as "what function"
- Check: quick — this is low-risk, just confirm rollup counts match file count in repo.

**Day 14 — Buffer + Step 2 kill check**
- Kill check: if Day 11's dynamic_unresolved % is >40% of total DB access on your test repo, that's real and gets disclosed in every query result (per `flow.md` blind-spot step) — it does NOT mean "add more parsing tricks" in V1. Confirm this is written into Step 3's output format before moving on.

---

## Step 3 — Impact query + VS Code extension shell (Days 15–18)

**Day 15 — Query engine core**
- Build: `systemlens/query/impact.py` — given table name, traverse graph (networkx), return all connected function/file nodes with `blast_radius` + path confidence (per `tech.md` §2 formula)
- Output: CLI-testable function, returns ranked JSON (no UI yet)
- Check: run against the 5 tables you manually traced on Day 12 — results should match your manual trace, ranked with lowest confidence for the dynamic-unresolved paths.

**Day 16 — Blind-spot disclosure formatting**
- Build: attach explicit "not visible: dynamic SQL (N functions), cross-service calls (not analyzed)" note to every query result, using Day 11's counted number
- Output: query result object always has a populated `blind_spots` field, never empty/omitted
- Check: this is the actual safety mechanism from `flow.md` — verify it's literally impossible to get a result with an empty blind_spots field, even when the answer is "none that I know of."

**Day 17 — VS Code extension shell**
- Build: `extension/` — TypeScript, one command (`SystemLens: What touches this?`), one input box, webview rendering the ranked list + confidence + blind spots
- Output: installable `.vsix`, working end-to-end against your test repo
- Check: run it yourself on a table you didn't manually pre-check, see if the output looks trustworthy without you having primed the answer.

**Day 18 — Buffer + Step 3 kill check**
- Kill check: if extension doesn't work end-to-end (schema scan → graph → query → webview) on your own test repo, fix here. Nothing in Step 4 matters until this loop closes.

---

## Step 4 — The actual test (Days 19–21 + wait time)

**Day 19 — Target selection + setup**
- Pick one real open-source app with messy code + real Postgres schema (Discourse or Odoo). Run full pipeline (Steps 0–3) against it.
- Output: working graph + extension pointed at a codebase you didn't write.

**Day 20 — Find your evaluator**
- Get someone who actually knows that codebase (not you) — a maintainer, contributor, or someone who's worked in it. Pick 5-10 real tables/functions together.
- Output: a shared list of test cases, agreed before you show them any tool output (avoid biasing their answer).

**Day 21 — Run the comparison**
- For each test case: tool's answer vs. their independent answer. Compute (per `tech.md` benchmark section):
  - `agreement_rate` (clusters/grouping, if used)
  - `recall` (did the tool miss real impacts — this is the one that matters most)
  - `precision` (did the tool over-flag)
- **Decision:**
  - Recall high, few dangerous misses → validated, move to deferred backlog below, in order
  - Recall low / real misses found → stop, go back to Step 1/2 confidence logic, do NOT add scope to compensate

---

## Deferred backlog (gated behind Step 4 passing, in priority order)
1. CLI wrapper (thin, same engine) — build when CI/PR use case appears, not speculatively
2. Additional relational adapters (MySQL, SQLite, MSSQL) via adapter interface — see `architecture.md`
3. Additional language support (JS/TS backend) — only after Python path is proven, not in parallel
4. Web dashboard — only when cross-repo view or non-engineer user demand is concrete
5. AI-generated cluster labels — cosmetic layer, add once underlying graph is trusted
6. Incremental re-scan / versioning / human correction persistence — needed for real retention, not needed to pass Step 4

Explicitly NOT on this backlog: NoSQL support (see `prd.md` non-goals — different data model, different tool).
