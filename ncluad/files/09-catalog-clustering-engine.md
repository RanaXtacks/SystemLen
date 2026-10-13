# Phase C — Catalog clustering engine

## Problem
This is the single biggest gap. The original product pitch was "500 tables → Auth, Payments, Students" — turning raw structure into human-meaningful groups. Nothing in the current pipeline does this. The system currently only lists dependencies; it never groups anything. Without this, SystemLens is a dependency tracer, not the product that was originally proposed.

## Goal
Take `graph.json` (already produced by the existing pipeline) and output a set of clusters — logical modules — with a measurable quality score, not an LLM guess dressed up as structure.

## Where
New module `cluster.py`, consuming `graph.json`, run as a new pipeline stage after `assemble_unified_graph()` and before `ImpactEngine` queries (clusters can enrich impact output later, but build and validate clustering independently first).

## Method
1. Build a weighted undirected graph from `graph.json`: nodes = tables (and optionally files/functions once table-level clustering is proven), edge weight = edge confidence (now calibrated, from Phase B).
2. Run **Louvain community detection** (modularity maximization) on this graph.
3. Each detected community = one catalog group. Compute:
```
Q = (1/2m) Σ_ij [A_ij - k_i k_j / 2m] δ(c_i, c_j)
```
- m = total edge weight, A_ij = edge weight between i,j, k_i = sum of i's edge weights, δ = 1 if same cluster.
- Report Q alongside every generated catalog (e.g. "Q = 0.68 across 47 tables, 6 groups").
4. **Label groups after clustering, not instead of it.** Use an LLM pass only to name each already-found cluster (e.g. "this cluster of 8 tables → call it 'Payments'"). Mislabeling a correct group is low-risk; letting an LLM decide grouping directly reintroduces the exact non-deterministic problem this phase exists to avoid.

## Validate against the same test schema used in Phase A
Compute **Adjusted Rand Index (ARI)** between found clusters and the schema's known/documented module boundaries:
```
ARI = (RI - Expected_RI) / (Max_RI - Expected_RI)
```
ARI = 1 is a perfect match, 0 is random.

## Acceptance criteria (gate to Phase D)
- Q > 0.3 on the test schema (generally accepted threshold for meaningful structure).
- ARI > 0.6 against known module boundaries, OR a person familiar with the test schema agrees with more than 80% of the groups.
- If it fails: do not patch with an LLM override. That hides a structural problem instead of fixing it — revisit edge weighting or the calibration from Phase B first.
