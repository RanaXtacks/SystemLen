# Rule: Blast Radius Query Engine & Confidence Decay

## Context
Tracing blast radius impact across code and database dependencies requires modeling propagation direction, compounding confidence along multi-hop paths, and disclosing visibility blind spots.

## Rules
1. **Impact Propagation Direction**:
   - In the dependency graph, edges point in the direction of the reference (`orders -> users`, `func -> table`).
   - In the impact propagation graph, a change to target $T$ flows backward to everything that depends on it:
     - Reference/dependency edges: $T \to \text{dependent}$ (`users -> orders`, `table -> func`).
     - Structural containment edges: $\text{func} \to \text{file}$.
2. **Multiplicative Path Confidence Decay**:
   - Follow `tech.md`: $c(\text{path}) = \prod_{e \in \text{path}} c(e)$.
   - When multiple paths reach a node, report the maximum path confidence.
   - Rank results by confidence descending, then by hop count ascending.
3. **Mandatory Blind-Spot Invariant**:
   - Every impact query result object MUST contain a populated `blind_spots` list (never empty, never omitted).
   - If dynamic SQL calls exist, explicitly list the count and sample function names.
   - Always state unanalyzed boundaries (cross-service HTTP/RPC boundaries).
4. **VS Code Extension Architecture**:
   - The VS Code extension delegates to the CLI (`uv run systemlens impact --json`) or falls back to local `graph.json` reading.
   - Webview UI must render stat cards, ranked impacted functions with confidence badges, impacted files, impacted downstream tables, and blind spots.
