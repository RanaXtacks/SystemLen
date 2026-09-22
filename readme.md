# SystemLens

Cross-layer dependency tracer for legacy systems. Answers: "what code touches this table, and how sure am I?" — inside VS Code, with an explicit confidence score per result and an explicit list of what it structurally cannot see.

**Status:** Pre-validation (Steps 0–3 in progress, Step 4 test not yet run — see `plan.md`. Do not treat anything past Step 4 as committed.)

## Why this exists
Single-layer tools (DB ER diagrams, code call graphs) are commodity. Nobody traces cleanly across layers (React → API → function → table) with an honest confidence score. That's the wedge. See `prd.md` for full problem statement and non-goals.

## Docs
- `prd.md` — problem, scope, non-goals, success metric
- `plan.md` — Steps 0–4, what to build in order, kill criteria at each step
- `architecture.md` — engine/UI split, adapter interface, node/edge model
- `flow.md` — build-time and query-time pipeline diagrams (mermaid)
- `tech.md` — stack choices, confidence scoring math, blast-radius math, benchmark metrics

## V1 scope (short version)
Postgres + Python only. VS Code extension, one query: "what touches this table?" Everything else (other DBs, other languages, web dashboard, CLI, AI labels) is deferred until the Step 4 real-developer test passes. See `plan.md` deferred backlog.

## Setup (once Step 0–3 code exists)
```bash
pip install -r requirements.txt
python -m systemlens.scan --pg-url postgresql://user:pass@host/db --src ./path/to/python/backend
```
Then in VS Code: install extension from `./extension`, run command `SystemLens: What touches this?`, select a table.

## Explicit limitations (read before trusting output)
- Dynamic SQL, reflection, and cross-service calls (HTTP, queues) are not visible to static analysis — flagged in every result, not silently dropped
- Confidence scores are heuristic, not guarantees — see `tech.md` §1 for exact formula
- No NoSQL support — different data model, out of scope by design, not by oversight
