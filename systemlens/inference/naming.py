"""Naming-convention based relationship inference for schema columns.

Detects candidate relationships by matching column names like `user_id`
to table names like `users`, with pluralization handling, abbreviation
expansion, compound role-prefix matching, and confidence scoring per
tech.md formula:
    c(edge) = base_weight(inferred_naming) × modifiers
where base_weight = 0.55, and modifier:
    × 1.0 for exact/pluralized matches (user_id -> users)
    × 0.9 for partial/fuzzy/abbreviation matches (usr_id -> users, billing_address_id -> addresses)
"""

from __future__ import annotations

import re
from typing import Any

from systemlens.models import BASE_WEIGHTS, Edge, EdgeType

# Regex to detect FK-like column suffixes
FK_COLUMN_PATTERN = re.compile(r"^(.+?)_id$", re.IGNORECASE)


# --- Pluralization engine (English-centric) ---

# Irregular plurals mapping: singular -> plural
IRREGULAR_PLURALS: dict[str, str] = {
    "person": "people",
    "child": "children",
    "man": "men",
    "woman": "women",
    "mouse": "mice",
    "goose": "geese",
    "tooth": "teeth",
    "foot": "feet",
    "ox": "oxen",
    "datum": "data",
    "medium": "media",
    "criterion": "criteria",
    "phenomenon": "phenomena",
    "index": "indices",
    "matrix": "matrices",
    "vertex": "vertices",
    "appendix": "appendices",
    "analysis": "analyses",
    "basis": "bases",
    "crisis": "crises",
    "thesis": "theses",
    "axis": "axes",
}

# Build reverse map: plural -> singular
IRREGULAR_SINGULARS: dict[str, str] = {v: k for k, v in IRREGULAR_PLURALS.items()}

# Common database schema abbreviations: abbreviation -> full word
ABBREVIATIONS: dict[str, str] = {
    "usr": "user",
    "acct": "account",
    "cust": "customer",
    "org": "organization",
    "dept": "department",
    "cat": "category",
    "prod": "product",
    "addr": "address",
    "msg": "message",
    "doc": "document",
    "emp": "employee",
    "inv": "invoice",
    "txn": "transaction",
    "trans": "transaction",
    "cfg": "config",
    "conf": "configuration",
    "img": "image",
    "loc": "location",
    "ref": "reference",
    "sub": "subscription",
    "perm": "permission",
    "pkg": "package",
    "notif": "notification",
    "comm": "communication",
    "dev": "device",
    "env": "environment",
    "sess": "session",
    "repo": "repository",
}


def singularize(word: str) -> str:
    """Convert a plural English noun to its singular form (best-effort)."""
    lower = word.lower()

    # Check irregulars
    if lower in IRREGULAR_SINGULARS:
        return IRREGULAR_SINGULARS[lower]

    # Already singular (heuristic: doesn't end in 's')
    if not lower.endswith("s"):
        return lower

    # -ies -> -y (e.g., categories -> category)
    if lower.endswith("ies") and len(lower) > 3:
        return lower[:-3] + "y"

    # -ses -> -s (e.g., addresses -> address) but NOT -sses -> -ss
    if lower.endswith("ses") and not lower.endswith("sses"):
        return lower[:-2]

    # -sses -> -ss (e.g., addresses)
    if lower.endswith("sses"):
        return lower[:-2]

    # -ches, -shes, -xes, -zes -> remove -es
    if lower.endswith(("ches", "shes", "xes", "zes")):
        return lower[:-2]

    # -ves -> -f (e.g., wolves -> wolf, halves -> half)
    if lower.endswith("ves"):
        return lower[:-3] + "f"

    # -oes -> -o (e.g., heroes -> hero, potatoes -> potato)
    if lower.endswith("oes") and len(lower) > 3:
        return lower[:-2]

    # General: remove trailing 's'
    if lower.endswith("s") and not lower.endswith("ss"):
        return lower[:-1]

    return lower


def pluralize(word: str) -> str:
    """Convert a singular English noun to its plural form (best-effort)."""
    lower = word.lower()

    # Check irregulars
    if lower in IRREGULAR_PLURALS:
        return IRREGULAR_PLURALS[lower]

    # Already ends in 's', 'x', 'z', 'ch', 'sh' -> add 'es'
    if lower.endswith(("s", "x", "z", "ch", "sh")):
        return lower + "es"

    # Ends in consonant + 'y' -> replace 'y' with 'ies'
    if lower.endswith("y") and len(lower) > 1 and lower[-2] not in "aeiou":
        return lower[:-1] + "ies"

    # Ends in 'f' -> 'ves' (e.g., wolf -> wolves)
    if lower.endswith("f"):
        return lower[:-1] + "ves"

    # Ends in 'fe' -> 'ves' (e.g., knife -> knives)
    if lower.endswith("fe"):
        return lower[:-2] + "ves"

    # General: add 's'
    return lower + "s"


def generate_candidate_table_names(stem: str) -> list[tuple[str, float]]:
    """
    Given a stem extracted from a column (e.g., 'user' from 'user_id',
    'usr' from 'usr_id', 'shipping_address' from 'shipping_address_id'),
    generate candidate table names with confidence modifiers.

    Returns:
        List of (candidate_name, confidence_modifier) tuples.
        modifier = 1.0 for exact matches, 0.9 for fuzzy/partial/abbreviation matches.
    """
    candidates: list[tuple[str, float]] = []
    lower_stem = stem.lower()

    # 1. Exact stem and basic plurals/singulars (modifier = 1.0)
    candidates.append((lower_stem, 1.0))
    plural = pluralize(lower_stem)
    if plural != lower_stem:
        candidates.append((plural, 1.0))
    singular = singularize(lower_stem)
    if singular != lower_stem:
        candidates.append((singular, 1.0))

    # Underscore variations on stem: order_item -> order_items
    if "_" in lower_stem:
        parts = lower_stem.rsplit("_", 1)
        last_plural = pluralize(parts[-1])
        last_singular = singularize(parts[-1])
        if last_plural != parts[-1]:
            candidates.append((f"{parts[0]}_{last_plural}", 1.0))
        if last_singular != parts[-1]:
            candidates.append((f"{parts[0]}_{last_singular}", 1.0))

        # 2. Role-prefixed compound columns (modifier = 0.9)
        # e.g., shipping_address -> address, addresses
        # author_user -> user, users
        suffix_stem = parts[-1]
        candidates.append((suffix_stem, 0.9))
        suffix_plural = pluralize(suffix_stem)
        if suffix_plural != suffix_stem:
            candidates.append((suffix_plural, 0.9))
        suffix_singular = singularize(suffix_stem)
        if suffix_singular != suffix_stem:
            candidates.append((suffix_singular, 0.9))

        # Suffix abbreviation check (e.g. billing_addr -> address, addresses)
        if suffix_stem in ABBREVIATIONS:
            expanded_suffix = ABBREVIATIONS[suffix_stem]
            candidates.append((expanded_suffix, 0.9))
            cand_plural = pluralize(expanded_suffix)
            if cand_plural != expanded_suffix:
                candidates.append((cand_plural, 0.9))

    # 3. Direct abbreviations (modifier = 0.9)
    # e.g., usr -> user, users; acct -> account, accounts
    if lower_stem in ABBREVIATIONS:
        expanded = ABBREVIATIONS[lower_stem]
        candidates.append((expanded, 0.9))
        cand_plural = pluralize(expanded)
        if cand_plural != expanded:
            candidates.append((cand_plural, 0.9))
        cand_singular = singularize(expanded)
        if cand_singular != expanded:
            candidates.append((cand_singular, 0.9))

    # Deduplicate while preserving best modifier
    seen: dict[str, float] = {}
    for name, mod in candidates:
        if name not in seen or mod > seen[name]:
            seen[name] = mod
    return list(seen.items())


def infer_edges_from_naming(
    catalog: dict[str, Any],
    declared_fk_pairs: set[tuple[str, str]] | None = None,
) -> list[Edge]:
    """
    Scan all columns in the catalog and infer FK-like relationships from
    naming conventions (e.g., 'user_id' -> 'users' table, 'usr_id' -> 'users').

    Args:
        catalog: Raw catalog dict with 'tables' key from extract_raw_catalog().
        declared_fk_pairs: Optional set of (source_node_id, target_node_id) pairs
            representing already-declared FKs, used to skip duplicate edges.

    Returns:
        List of Edge objects with type=INFERRED_NAMING and scored confidence.
    """
    if declared_fk_pairs is None:
        declared_fk_pairs = set()

    tables = catalog.get("tables", {})

    # Build lookup: bare table name (lowercased) -> list of full qualified names
    table_name_lookup: dict[str, list[str]] = {}
    for full_name, info in tables.items():
        bare_name = info["name"].lower()
        table_name_lookup.setdefault(bare_name, []).append(full_name)

    base_weight = BASE_WEIGHTS[EdgeType.INFERRED_NAMING]
    edges: list[Edge] = []

    for source_full_name, table_info in tables.items():
        source_schema = table_info.get("schema", "")
        source_bare_name = table_info.get("name", "").lower()
        source_node_id = f"table:{source_full_name}"

        for col in table_info.get("columns", []):
            col_name = col["name"]
            match = FK_COLUMN_PATTERN.match(col_name)
            if not match:
                continue

            stem = match.group(1)
            candidates = generate_candidate_table_names(stem)

            for candidate_name, modifier in candidates:
                target_full_names = table_name_lookup.get(candidate_name, [])
                if not target_full_names:
                    continue

                # Multi-schema preference: if matches exist in both the same schema
                # and other schemas, prioritize the one in the same schema
                same_schema_targets = [
                    t for t in target_full_names if tables[t].get("schema", "") == source_schema
                ]
                targets_to_evaluate = same_schema_targets if same_schema_targets else target_full_names

                for target_full_name in targets_to_evaluate:
                    # Self-reference handling:
                    # Avoid trivial self-pointing (e.g. `users.user_id` -> `users`)
                    # but allow hierarchical self-referencing (e.g. `categories.parent_category_id` -> `categories`)
                    if target_full_name == source_full_name:
                        stem_lower = stem.lower()
                        if stem_lower in (source_bare_name, singularize(source_bare_name)):
                            continue

                    target_node_id = f"table:{target_full_name}"

                    # Skip if we already have a declared FK for this pair (if caller requested)
                    if (source_node_id, target_node_id) in declared_fk_pairs:
                        continue

                    target_schema = tables[target_full_name].get("schema", "")
                    confidence = round(base_weight * modifier, 4)
                    match_type = "exact" if modifier >= 1.0 else "fuzzy"

                    evidence = (
                        f"Naming inference ({match_type}): "
                        f"{source_full_name}.{col_name} -> "
                        f"{target_full_name}"
                    )

                    edges.append(
                        Edge(
                            source=source_node_id,
                            target=target_node_id,
                            type=EdgeType.INFERRED_NAMING,
                            confidence=confidence,
                            evidence=evidence,
                            metadata={
                                "source_column": col_name,
                                "stem": stem,
                                "candidate_table": candidate_name,
                                "target_table": target_full_name,
                                "match_type": match_type,
                                "modifier": modifier,
                                "same_schema": source_schema == target_schema,
                            },
                        )
                    )

    # Deduplicate: if multiple candidates or columns point to the same target,
    # keep the one with the highest confidence
    dedup: dict[tuple[str, str], Edge] = {}
    for edge in edges:
        key = (edge.source, edge.target)
        if key not in dedup or edge.confidence > dedup[key].confidence:
            dedup[key] = edge

    return list(dedup.values())
