# SystemLens — Flow

## Build-time pipeline (run once per scan)

```mermaid
flowchart TD
    A[Postgres DB] -->|information_schema| B[Extract tables + declared FKs]
    C[Python source] -->|ast parse| D[Extract functions + SQL/ORM calls]

    B --> E[Graph Builder: table nodes + FK edges conf=1.0]
    B --> F[Infer naming-based edges conf=0.4-0.7]
    D --> G[Link functions to tables touched conf=0.3-0.9 by evidence type]

    E --> H[Unified Graph]
    F --> H
    G --> H

    H --> I[Confidence Scorer: recompute per-edge score]
    I --> J[(Graph store: JSON/SQLite)]
```

## Query-time flow (what happens when a dev asks "what touches this table?")

```mermaid
flowchart LR
    Q[Dev query: table or column name] --> R[Query Engine]
    R --> S[(Graph store)]
    S --> T[Collect all edges touching node]
    T --> U[Sort by confidence, group by evidence type]
    U --> V[Render: ranked list + confidence + evidence]
    U --> W[Explicit blind-spot note: dynamic SQL / cross-service / reflection not visible]
    V --> X[VS Code webview result]
    W --> X
```

## Why the blind-spot step is not optional
This is the direct answer to the false-negative risk: the tool never returns "5 things affected" as if that's complete. It returns "5 things affected (here's why, here's confidence), and here's what I structurally cannot see." A dev who reads the second half won't blindly ship on an incomplete list — that's the actual product safety mechanism, not a UI nicety.

## Trigger conditions for later surfaces (from plan.md backlog)
```mermaid
flowchart TD
    Core[VS Code extension — proven core] --> Check1{CI/PR use case appears?}
    Check1 -->|yes| CLI[Build CLI: thin wrapper, ~1 day]
    Check1 -->|no| Core

    Core --> Check2{Non-engineer or cross-repo demand appears?}
    Check2 -->|yes| Web[Build web dashboard]
    Check2 -->|no| Core
```
