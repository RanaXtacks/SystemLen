# SystemLens — Architecture (V1)

## Split: Engine / UI
Engine is a standalone Python package. UI (VS Code extension) is a thin client that calls the engine's output. This split is why CLI and web can be added later without touching the engine — confirmed cheap, keep it.

```
┌─────────────────────────────────────────────┐
│                  UI Layer                    │
│   VS Code extension (webview, 1 query box)   │
│   [future: CLI, web — same engine, no logic] │
└───────────────────┬───────────────────────────┘
                     │ reads JSON graph + queries
┌───────────────────▼───────────────────────────┐
│                 Engine Layer                   │
│                                                 │
│  ┌───────────┐   ┌───────────┐   ┌──────────┐ │
│  │  Adapters  │→ │   Graph    │→ │  Query    │ │
│  │ (per source)│  │  Builder   │  │  Engine   │ │
│  └───────────┘   └───────────┘   └──────────┘ │
│        │                                       │
│  ┌─────▼──────┐                                │
│  │ Confidence  │  (per-edge score, see tech.md)│
│  │  Scorer     │                                │
│  └────────────┘                                │
└─────────────────────────────────────────────────┘
                     │
             ┌───────▼────────┐
             │  Graph storage  │
             │ (JSON / SQLite  │
             │  for V1 cache)  │
             └─────────────────┘
```

## Adapter interface (why "more DBs" is cheap later, not now)
Each adapter implements one contract:
```python
class SourceAdapter:
    def extract_nodes(self) -> list[Node]: ...
    def extract_edges(self) -> list[Edge]: ...   # each edge carries confidence + source tag
```
Postgres adapter (V1) implements this via `information_schema`. A MySQL/SQLite/MSSQL adapter is the same contract, different queries — genuinely cheap to add *after* V1, because the graph model doesn't change.

A NoSQL adapter is **not** this contract — there's no fixed schema to introspect, so "extract_nodes" has no stable definition. That's why it's a non-goal, not a backlog item: it needs a different node/edge model, not just a new adapter.

## Node & edge model (kept internal/mutable, not "frozen")
```
Node: { id, type: table|function|file, name, source_system }
Edge: { from, to, type: declared_fk|inferred_naming|static_sql|orm_call|dynamic_unresolved,
        confidence: float(0-1), evidence: str }
```
`evidence` field exists so every edge is auditable — "why does the tool think this?" always has an answer. This is the direct fix for the false-negative-trust problem: the tool never presents a bare list, always a list + reasons + explicit blind spots.

## Data flow
See `flow.md` for the step-by-step pipeline and the query-time flow.

## Where LLM fits (and doesn't, in V1)
No LLM in the V1 critical path. Structure (nodes, edges, confidence) is fully deterministic/heuristic. LLM use (cluster labeling, natural-language explain) is cosmetic and deferred — it sits *on top of* the graph, never inside the confidence/inference logic, so a bad LLM call can't silently corrupt what the tool claims to know.

## Local-first / data boundary
V1 runs entirely local: DB credentials and source code never leave the machine. No network calls in the engine. This is a stated design constraint, not an afterthought — schema and code are sensitive, and this removes the enterprise adoption blocker before it exists.
