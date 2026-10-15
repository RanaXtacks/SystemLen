"""Confidence tiers and evidence chain presentation for SystemLens (Phase D).

Replaces bare, falsely precise floats (e.g. '[85.0%]') with calibrated
confidence tiers (High, Medium, Low) and transparent evidence chains
derived from the Phase B empirical calibration report.
"""

from __future__ import annotations

from enum import Enum
from typing import Sequence


class ConfidenceTier(str, Enum):
    """Calibrated confidence tiers for blast-radius path impacts.

    Boundaries are derived from the Phase B calibration curve:
    - HIGH:   Deterministic schema constraints (FK, structural belongs-to)
              where observed accuracy is >= 90%.
    - MEDIUM: High-signal parsed code detections (ORM call, static SQL)
              where observed accuracy is ~85-98%.
    - LOW:    Heuristic inferences (naming inference, unresolved dynamic SQL)
              or multi-hop paths with high uncertainty (< 70%).
    """

    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"


TIER_CUTOFFS_DOC = """
Tier Boundaries (derived from Phase B empirical calibration against Saleor):
- High:   Deterministic edges only (FK, structural belongs-to); observed accuracy >= 90%.
- Medium: Contains at least one high-signal code heuristic (ORM call, static SQL); observed accuracy ~85-98%.
- Low:    Contains heuristic naming inference, dynamic unresolved query, or path confidence < 70%.
""".strip()


EDGE_TYPE_DISPLAY_NAMES = {
    "declared_fk": "FK",
    "structural_belongs_to": "file membership",
    "orm_call": "ORM call",
    "static_sql_string": "static SQL",
    "inferred_naming": "naming inference",
    "dynamic_unresolved": "dynamic query",
}


def format_evidence_chain(edge_types: Sequence[str]) -> str:
    """Format a sequence of edge types into a human-readable evidence chain.

    Example:
        ['declared_fk', 'orm_call'] -> 'via FK → ORM call'
        ['orm_call'] -> 'via ORM call'
        [] -> ''
    """
    if not edge_types:
        return ""

    display_parts = [EDGE_TYPE_DISPLAY_NAMES.get(t, t.replace("_", " ")) for t in edge_types]
    return f"via {' → '.join(display_parts)}"


def classify_confidence_tier(edge_types: Sequence[str], confidence: float) -> ConfidenceTier:
    """Classify a path's confidence into High, Medium, or Low tier.

    Classification logic per 10-confidence-presentation-fix.md:
    1. Low: includes naming-inference or dynamic-unresolved edges, or confidence < 0.70.
    2. Medium: includes at least one high-signal heuristic (ORM call, parsed SQL) with no low-signal edge.
    3. High: only deterministic edges (FK, structural belongs-to) or confidence >= 0.90 with zero heuristics.

    Args:
        edge_types: List of edge type strings traversed in the path.
        confidence: Multiplicative path confidence score.

    Returns:
        ConfidenceTier (HIGH, MEDIUM, or LOW).
    """
    types_set = set(edge_types)

    # 1. Low: contains heuristic naming, unresolved dynamic SQL, or low confidence
    if "dynamic_unresolved" in types_set or "inferred_naming" in types_set or confidence < 0.70:
        return ConfidenceTier.LOW

    # 2. Medium: contains high-signal code detections
    if "orm_call" in types_set or "static_sql_string" in types_set:
        return ConfidenceTier.MEDIUM

    # 3. High: only deterministic edges (or confidence >= 0.90)
    if types_set <= {"declared_fk", "structural_belongs_to"} or confidence >= 0.90:
        return ConfidenceTier.HIGH

    # Fallback based on scalar confidence
    if confidence >= 0.90:
        return ConfidenceTier.HIGH
    elif confidence >= 0.70:
        return ConfidenceTier.MEDIUM
    return ConfidenceTier.LOW
