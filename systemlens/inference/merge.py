"""Edge merging and agreement logic for combining multi-source edges.

Handles the merge step from plan.md Day 6:
- If declared_fk AND inferred_naming both point to the same (source, target),
  apply agreement bonus (x1.0 confirming per tech.md formula).
- Produce a unified graph edge list with two distinguishable edge classes.
- Support optional deduplication where declared FK takes precedence and is
  annotated with naming agreement metadata.
- Compute precision and agreement statistics for evaluation.
"""

from __future__ import annotations

from typing import Any

from systemlens.models import Edge, EdgeType


def merge_edges(
    declared_edges: list[Edge],
    inferred_edges: list[Edge],
    deduplicate: bool = False,
) -> list[Edge]:
    """
    Merge declared FK edges with inferred naming edges.

    Rules:
    - All declared edges are preserved (deterministic, base_weight=1.0).
    - When declared_fk AND inferred_naming both point to the same (source, target):
      - Both edges record the agreement in their metadata.
      - The declared edge is marked with `naming_agreement=True` and `naming_evidence`.
      - The inferred edge is marked with `declared_agreement=True` and `agreement_bonus=1.0`.
      - If deduplicate=True: the duplicate inferred edge is omitted.
      - If deduplicate=False (default): both edge classes are retained in the merged list,
        providing a unified edge set with distinguishable classes per Day 6 plan.
    - Inferred edges with no declared counterpart are kept with their original confidence.

    Args:
        declared_edges: Edges from PostgresAdapter.extract_edges()
            (e.g., DECLARED_FK, STRUCTURAL_BELONGS_TO).
        inferred_edges: Edges from infer_edges_from_naming().
        deduplicate: If True, omit inferred edges that duplicate declared FKs.
            If False (default), keep both distinguishable edge classes.

    Returns:
        Merged list of edges.
    """
    # Index declared edges by (source, target) for fast lookup
    declared_lookup: dict[tuple[str, str], Edge] = {
        (e.source, e.target): e for e in declared_edges if e.type == EdgeType.DECLARED_FK
    }

    merged: list[Edge] = list(declared_edges)

    for inf_edge in inferred_edges:
        key = (inf_edge.source, inf_edge.target)
        if key in declared_lookup:
            # Agreement: inferred naming confirms a declared FK
            decl_edge = declared_lookup[key]
            decl_edge.metadata["naming_agreement"] = True
            decl_edge.metadata["naming_evidence"] = inf_edge.evidence

            inf_edge.metadata["declared_agreement"] = True
            inf_edge.metadata["agreement_bonus"] = 1.0

            if not deduplicate:
                merged.append(inf_edge)
        else:
            # Inferred only (no declared counterpart)
            merged.append(inf_edge)

    return merged


def compute_merge_stats(
    declared_edges: list[Edge],
    inferred_edges: list[Edge],
    merged_edges: list[Edge] | None = None,
) -> dict[str, Any]:
    """
    Compute statistics about the merge result for reporting and precision assessment.

    Args:
        declared_edges: List of declared edges.
        inferred_edges: List of inferred edges.
        merged_edges: Optional list of merged edges. If None, computed via merge_edges().

    Returns:
        Dict with counts, agreements, inferred-only, declared-only, and agreement rates.
    """
    if merged_edges is None:
        merged_edges = merge_edges(declared_edges, inferred_edges)

    declared_fk_pairs = {
        (e.source, e.target) for e in declared_edges if e.type == EdgeType.DECLARED_FK
    }
    inferred_pairs = {(e.source, e.target) for e in inferred_edges}

    agreements = declared_fk_pairs & inferred_pairs
    inferred_only = inferred_pairs - declared_fk_pairs
    declared_only = declared_fk_pairs - inferred_pairs

    total_inferred = len(inferred_pairs)
    agreement_rate = len(agreements) / total_inferred if total_inferred > 0 else 0.0

    return {
        "total_declared_fk": len(declared_fk_pairs),
        "total_inferred": total_inferred,
        "total_merged": len(merged_edges),
        "agreements": len(agreements),
        "inferred_only": len(inferred_only),
        "declared_only": len(declared_only),
        "agreement_rate": round(agreement_rate, 4),
        "precision_estimate": round(agreement_rate, 4),
    }
