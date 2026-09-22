# SystemLens — PRD (V1 Wedge)

## Problem
Engineers on legacy systems (500+ table DBs, undocumented services) can't answer "what breaks if I change X" without manual grep + tribal knowledge. Single-layer tools (DB ER diagrams, code call graphs) already exist and are commodity. Nobody does the **cross-layer trace** well: code → table, table → code, with a confidence score attached to each claim.

## Non-goals (V1)
- NoSQL databases (Mongo, Cassandra, etc.) — no fixed schema, no FK concept, breaks the Entity/Dependency model. Different tool, different data model. Revisit only after V1 proves out on relational.
- Multi-language codebases (V1 = Python only)
- Web dashboard, CLI (see trigger conditions in `flow.md`)
- AI-generated cluster labels (deferred — labels are cosmetic, not the wedge)
- Real-time/incremental re-scan (batch only for V1)

## Users
Backend engineer on a legacy monolith/service, doing impact analysis before a schema or refactor change. Not PMs, not architects (V1).

## Core value prop
"What code touches this table, and how sure am I?" — answered in seconds inside the editor, with an explicit confidence number per result, not a silent list that looks complete but isn't.

## Success metric (the actual test, not opinion)
Run on one real open-source codebase with messy code + real Postgres schema (e.g. Discourse, Odoo). Get ground truth from someone who knows the codebase (not the builder).
- Cluster/grouping agreement ≥ ~80% vs their mental model
- Impact-analysis recall: tool's "affected by" list misses few items a human considers true positives (false negatives are the dangerous failure mode — flag explicitly, don't hide them)

If this fails: stop, rework the confidence/inference logic. Do not proceed to more DBs, more languages, or more UI. Width does not fix a broken core.

## Scope: the 4 steps
See `plan.md`. Steps 0–4 only. Everything else lives in a deferred backlog, gated behind the Step 4 test passing.

## Risks (carried forward, not solved by wishful design)
1. Legacy schemas often lack declared FKs — relationships inferred from naming/ORM/raw SQL, not deterministic. Confidence scoring exists *because* of this, not despite it.
2. False negatives in impact analysis are worse than no tool — a dev who trusts an incomplete list ships a break. Every result must show what the tool *cannot* see.
3. Universal "Dependency" model risks flattening meaningfully different edge types (FK vs import vs HTTP call). V1 keeps the model internal/mutable, not "stable," until it's been built against a second real source.
