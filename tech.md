# SystemLens — Tech & Math

## Stack
| Layer | Choice | Why |
|---|---|---|
| Schema ingest | `psycopg2` + `information_schema` queries | No ORM dependency, works on any Postgres, read-only |
| Python parsing | stdlib `ast` | No external parser dependency, handles real syntax including dynamic patterns you can detect (even if you can't resolve them) |
| SQL string detection | `sqlparse` (lightweight) — not `sqlglot` for V1, that's overkill for detecting "is this a SELECT/INSERT touching table X" | Keep parsing dependency-light, this isn't a SQL engine |
| Graph representation | `networkx` | Standard, has centrality/reachability built in — needed for math below, don't hand-roll |
| Clustering (deferred, not V1 critical path) | `python-louvain` | Only needed once cosmetic grouping/labels are in scope, not for the impact-query wedge |
| Storage | SQLite (via `sqlite3` stdlib) for the graph cache, JSON export for portability | No server dependency, matches "local-first" constraint in architecture.md |
| Extension | VS Code Extension API, TypeScript, single webview | Standard, no exotic UI framework needed for one input box + one list |

## Database adapter scope (why "all databases" is rejected as stated, and what's actually planned)
**V1: Postgres only.** Adapter interface (see `architecture.md`) makes MySQL/SQLite/MSSQL adapters realistically ~1–2 days each *after* V1 — they all expose a queryable schema catalog (`information_schema` or equivalent), same node/edge shape.

**Explicitly out of scope, not "later," but different-tool territory:**
- MongoDB / document stores: no fixed schema, no FK. "Extract nodes" would mean sampling documents and guessing a shape — that's a different product with different failure modes, not an adapter.
- Cassandra / wide-column: schema exists but is denormalization-first by design; "relationship" as a concept barely applies.
- Graph DBs (Neo4j etc.): ironic case — already a graph, wrapping it in this tool adds little.

If NoSQL support becomes a real requirement, it's a new PRD, not a backlog line on this one — flagging that now so it isn't quietly smuggled into V1 later.

## The math (this is the part that's actually load-bearing, not decorative)

### 1. Edge confidence score
Each edge gets a confidence `c ∈ [0,1]` from its evidence source, not from vibes:
```
c(edge) = base_weight(source_type) × modifiers

base_weight:
  declared_fk         = 1.0
  static_sql_string    = 0.85
  orm_call             = 0.8
  inferred_naming      = 0.55
  dynamic_unresolved   = 0.15   (surfaced, never hidden, never silently dropped)

modifiers (multiplicative, examples):
  × 0.9 if naming match is partial (e.g. "usr_id" vs "user_id")
  × 1.0 if match found in >1 independent evidence source (declared_fk AND naming agree)
```
This is why "deterministic where possible" from the original doc survives contact with reality: it's not claiming everything is deterministic, it's *scoring* the non-deterministic part instead of pretending it isn't there.

### 2. Impact blast radius (why this needs a graph library, not just a list)
For "what does changing table T affect," this is a **reachability** problem, not a lookup:
```
blast_radius(T, depth) = { n ∈ graph.nodes : shortest_path(T, n) ≤ depth }
```
Reported with **per-node confidence decay** — confidence compounds along a path, it doesn't stay flat:
```
c(path) = Π c(edge_i) for edge_i in path
```
So a 2-hop inferred→dynamic chain reports honestly low confidence instead of looking as solid as a 1-hop declared FK. This is the concrete fix for risk #3 (false-negative trust) from the original review: low-confidence-but-real paths still show up, ranked low, instead of being cut and disappearing.

### 3. Cluster quality (deferred feature, but scored, not eyeballed, when it ships)
If/when Louvain clustering for cosmetic grouping is added:
```
Modularity Q = (1/2m) Σ_ij [A_ij - (k_i k_j)/2m] δ(c_i, c_j)
```
Standard Louvain modularity. Report Q alongside any cluster view — a cluster diagram with no modularity score is exactly the "pretty diagram, not insight" failure flagged earlier. Q also gives an objective regression check: if a re-scan drops Q noticeably, something changed in the underlying graph, not just cosmetic reshuffling.

### 4. Why this answers "graphical only" vs "graphical + math"
A force-directed graph of a real dependency set (thousands of edges) is unreadable past a few hundred nodes — this was flagged before and still holds. The math above is what makes the **non-visual** output (ranked list, confidence, blast radius) the primary interface, with graph rendering as a secondary, filtered view (e.g. render only blast_radius(T, depth=2), not the whole graph). Numbers first, picture second — inverts the failure mode most of these tools have.

## Step 4 benchmark — concrete metrics
```
agreement_rate = matched_clusters / human_labeled_clusters
recall = true_positives_found / (true_positives_found + false_negatives_missed)
precision = true_positives_found / (true_positives_found + false_positives_flagged)
```
Recall is the metric that matters most given risk #3 — optimize for not missing real impacts over not over-flagging, since a false positive just wastes a dev's 10 seconds of review, but a false negative ships a break.
