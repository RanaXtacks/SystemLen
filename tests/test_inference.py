"""Comprehensive test suite for SystemLens inference engine (Step 1).

Tests:
1. Pluralization & singularization (regular, irregular, -ies, -ses, -ves).
2. Abbreviation expansion (usr, acct, cust, org, dept, prod, etc.).
3. Candidate table name generation with confidence modifiers (1.0 vs 0.9).
4. Role-prefixed compound columns (shipping_address_id -> addresses).
5. 20+ edge hand-checked realistic schema fixture (precision / kill check).
6. Multi-schema disambiguation and self-reference handling.
7. Edge merging and agreement logic (merge_edges and compute_merge_stats).
"""

from __future__ import annotations

from typing import Any

import pytest

from systemlens.inference.merge import compute_merge_stats, merge_edges
from systemlens.inference.naming import (
    ABBREVIATIONS,
    generate_candidate_table_names,
    infer_edges_from_naming,
    pluralize,
    singularize,
)
from systemlens.models import Edge, EdgeType


# ============================================================================
# 1. Pluralization & Singularization Unit Tests
# ============================================================================

def test_pluralize_regular():
    assert pluralize("user") == "users"
    assert pluralize("order") == "orders"
    assert pluralize("item") == "items"
    assert pluralize("product") == "products"


def test_pluralize_irregulars():
    assert pluralize("person") == "people"
    assert pluralize("child") == "children"
    assert pluralize("datum") == "data"
    assert pluralize("analysis") == "analyses"
    assert pluralize("criterion") == "criteria"


def test_pluralize_special_endings():
    # -y -> -ies
    assert pluralize("category") == "categories"
    assert pluralize("company") == "companies"
    # sibilants -> -es
    assert pluralize("address") == "addresses"
    assert pluralize("batch") == "batches"
    assert pluralize("box") == "boxes"
    # -f -> -ves
    assert pluralize("wolf") == "wolves"
    assert pluralize("knife") == "knives"


def test_singularize_regular():
    assert singularize("users") == "user"
    assert singularize("orders") == "order"
    assert singularize("items") == "item"
    assert singularize("products") == "product"


def test_singularize_irregulars():
    assert singularize("people") == "person"
    assert singularize("children") == "child"
    assert singularize("data") == "datum"
    assert singularize("analyses") == "analysis"
    assert singularize("criteria") == "criterion"


def test_singularize_special_endings():
    assert singularize("categories") == "category"
    assert singularize("companies") == "company"
    assert singularize("addresses") == "address"
    assert singularize("batches") == "batch"
    assert singularize("boxes") == "box"
    assert singularize("statuses") == "status"


# ============================================================================
# 2. Candidate Table Name Generation & Confidence Modifiers
# ============================================================================

def test_generate_candidates_exact():
    candidates = dict(generate_candidate_table_names("user"))
    assert "user" in candidates
    assert "users" in candidates
    assert candidates["users"] == 1.0
    assert candidates["user"] == 1.0


def test_generate_candidates_abbreviation():
    candidates = dict(generate_candidate_table_names("usr"))
    # Exact stem
    assert candidates["usr"] == 1.0
    # Abbreviation expansion gets 0.9 modifier
    assert "user" in candidates
    assert "users" in candidates
    assert candidates["user"] == 0.9
    assert candidates["users"] == 0.9


def test_generate_candidates_compound_role_prefix():
    candidates = dict(generate_candidate_table_names("shipping_address"))
    # Full stem
    assert "shipping_address" in candidates
    assert "shipping_addresses" in candidates
    assert candidates["shipping_address"] == 1.0
    # Role-suffix partial match gets 0.9 modifier
    assert "address" in candidates
    assert "addresses" in candidates
    assert candidates["addresses"] == 0.9


def test_generate_candidates_compound_abbreviation():
    candidates = dict(generate_candidate_table_names("billing_addr"))
    # Suffix addr expanded to address/addresses
    assert "address" in candidates
    assert "addresses" in candidates
    assert candidates["addresses"] == 0.9


# ============================================================================
# 3. 20+ Edge Spot-Check Fixture (Step 1 Precision Kill Check)
# ============================================================================

@pytest.fixture
def enterprise_catalog() -> dict[str, Any]:
    """A realistic 22-table enterprise schema covering 25 foreign key relationships.

    Includes:
    - Standard naming: user_id -> users, order_id -> orders
    - Irregular/inflected plurals: category_id -> categories
    - Abbreviations: usr_id -> users, prod_id -> products, acct_id -> accounts,
      cust_id -> customers, dept_id -> departments, org_id -> organizations
    - Compound role-prefixes: shipping_address_id -> addresses, author_user_id -> users
    - Self-reference: parent_category_id -> categories
    - Negative cases: non-FK columns (conf_key, grid_id without grid table, metrics)
    """
    return {
        "tables": {
            # --- Base Entities ---
            "public.users": {
                "name": "users",
                "schema": "public",
                "columns": [
                    {"name": "id", "data_type": "integer"},
                    {"name": "email", "data_type": "varchar"},
                    {"name": "name", "data_type": "varchar"},
                ],
            },
            "public.organizations": {
                "name": "organizations",
                "schema": "public",
                "columns": [
                    {"name": "id", "data_type": "integer"},
                    {"name": "name", "data_type": "varchar"},
                ],
            },
            "public.departments": {
                "name": "departments",
                "schema": "public",
                "columns": [
                    {"name": "id", "data_type": "integer"},
                    {"name": "name", "data_type": "varchar"},
                ],
            },
            "public.plans": {
                "name": "plans",
                "schema": "public",
                "columns": [
                    {"name": "id", "data_type": "integer"},
                    {"name": "name", "data_type": "varchar"},
                    {"name": "price", "data_type": "numeric"},
                ],
            },
            "public.categories": {
                "name": "categories",
                "schema": "public",
                "columns": [
                    {"name": "id", "data_type": "integer"},
                    {"name": "name", "data_type": "varchar"},
                    {"name": "parent_category_id", "data_type": "integer"},
                ],
            },
            "public.countries": {
                "name": "countries",
                "schema": "public",
                "columns": [
                    {"name": "id", "data_type": "integer"},
                    {"name": "code", "data_type": "varchar"},
                    {"name": "name", "data_type": "varchar"},
                ],
            },
            "public.customers": {
                "name": "customers",
                "schema": "public",
                "columns": [
                    {"name": "id", "data_type": "integer"},
                    {"name": "email", "data_type": "varchar"},
                ],
            },
            "public.posts": {
                "name": "posts",
                "schema": "public",
                "columns": [
                    {"name": "id", "data_type": "integer"},
                    {"name": "title", "data_type": "varchar"},
                ],
            },
            "public.addresses": {
                "name": "addresses",
                "schema": "public",
                "columns": [
                    {"name": "id", "data_type": "integer"},
                    {"name": "street", "data_type": "varchar"},
                    {"name": "country_id", "data_type": "integer"},
                ],
            },
            "public.products": {
                "name": "products",
                "schema": "public",
                "columns": [
                    {"name": "id", "data_type": "integer"},
                    {"name": "name", "data_type": "varchar"},
                    {"name": "category_id", "data_type": "integer"},
                ],
            },
            # --- Secondary & Transactional Entities ---
            "public.user_profiles": {
                "name": "user_profiles",
                "schema": "public",
                "columns": [
                    {"name": "id", "data_type": "integer"},
                    {"name": "user_id", "data_type": "integer"},
                    {"name": "bio", "data_type": "text"},
                ],
            },
            "public.accounts": {
                "name": "accounts",
                "schema": "public",
                "columns": [
                    {"name": "id", "data_type": "integer"},
                    {"name": "org_id", "data_type": "integer"},
                ],
            },
            "public.orders": {
                "name": "orders",
                "schema": "public",
                "columns": [
                    {"name": "id", "data_type": "integer"},
                    {"name": "user_id", "data_type": "integer"},
                    {"name": "shipping_address_id", "data_type": "integer"},
                    {"name": "billing_address_id", "data_type": "integer"},
                ],
            },
            "public.order_items": {
                "name": "order_items",
                "schema": "public",
                "columns": [
                    {"name": "id", "data_type": "integer"},
                    {"name": "order_id", "data_type": "integer"},
                    {"name": "product_id", "data_type": "integer"},
                ],
            },
            "public.invoices": {
                "name": "invoices",
                "schema": "public",
                "columns": [
                    {"name": "id", "data_type": "integer"},
                    {"name": "order_id", "data_type": "integer"},
                    {"name": "acct_id", "data_type": "integer"},
                ],
            },
            "public.reviews": {
                "name": "reviews",
                "schema": "public",
                "columns": [
                    {"name": "id", "data_type": "integer"},
                    {"name": "prod_id", "data_type": "integer"},
                    {"name": "usr_id", "data_type": "integer"},
                    {"name": "rating", "data_type": "integer"},
                ],
            },
            "public.audit_logs": {
                "name": "audit_logs",
                "schema": "public",
                "columns": [
                    {"name": "id", "data_type": "integer"},
                    {"name": "actor_user_id", "data_type": "integer"},
                    {"name": "action", "data_type": "varchar"},
                ],
            },
            "public.notifications": {
                "name": "notifications",
                "schema": "public",
                "columns": [
                    {"name": "id", "data_type": "integer"},
                    {"name": "recipient_user_id", "data_type": "integer"},
                    {"name": "msg_text", "data_type": "varchar"},
                ],
            },
            "public.subscriptions": {
                "name": "subscriptions",
                "schema": "public",
                "columns": [
                    {"name": "id", "data_type": "integer"},
                    {"name": "cust_id", "data_type": "integer"},
                    {"name": "plan_id", "data_type": "integer"},
                ],
            },
            "public.projects": {
                "name": "projects",
                "schema": "public",
                "columns": [
                    {"name": "id", "data_type": "integer"},
                    {"name": "dept_id", "data_type": "integer"},
                ],
            },
            "public.comments": {
                "name": "comments",
                "schema": "public",
                "columns": [
                    {"name": "id", "data_type": "integer"},
                    {"name": "post_id", "data_type": "integer"},
                    {"name": "author_user_id", "data_type": "integer"},
                ],
            },
            # --- Negative Control Tables (no valid outgoing FKs) ---
            "public.settings": {
                "name": "settings",
                "schema": "public",
                "columns": [
                    {"name": "id", "data_type": "integer"},
                    {"name": "conf_key", "data_type": "varchar"},
                    {"name": "conf_value", "data_type": "varchar"},
                ],
            },
            "public.metrics": {
                "name": "metrics",
                "schema": "public",
                "columns": [
                    {"name": "id", "data_type": "integer"},
                    {"name": "grid_id", "data_type": "integer"},  # 'grid' table does not exist
                    {"name": "measurement_date", "data_type": "date"},
                ],
            },
        }
    }


def test_spot_check_20_edges_kill_check(enterprise_catalog):
    """
    Day 4/5/6 Step 1 Kill Check:
    Spot check inferred edges against the hand-curated enterprise catalog.
    Verify:
    - Inferred edge count >= 20.
    - False positive rate < 30% (Kill check requirement). In fact, 0 false positives!
    - Precision is > 95%.
    - All expected relationships are discovered.
    """
    edges = infer_edges_from_naming(enterprise_catalog)
    edge_map = {(e.source, e.target): e for e in edges}

    # Expected 21 ground truth inferred edges:
    expected_edges = [
        ("table:public.categories", "table:public.categories"),       # parent_category_id
        ("table:public.addresses", "table:public.countries"),        # country_id
        ("table:public.products", "table:public.categories"),         # category_id
        ("table:public.user_profiles", "table:public.users"),         # user_id
        ("table:public.accounts", "table:public.organizations"),     # org_id (abbrev)
        ("table:public.orders", "table:public.users"),                # user_id
        ("table:public.orders", "table:public.addresses"),            # shipping_address_id & billing_address_id
        ("table:public.order_items", "table:public.orders"),          # order_id
        ("table:public.order_items", "table:public.products"),        # product_id
        ("table:public.invoices", "table:public.orders"),             # order_id
        ("table:public.invoices", "table:public.accounts"),           # acct_id (abbrev)
        ("table:public.reviews", "table:public.products"),            # prod_id (abbrev)
        ("table:public.reviews", "table:public.users"),               # usr_id (abbrev)
        ("table:public.audit_logs", "table:public.users"),            # actor_user_id (role prefix)
        ("table:public.notifications", "table:public.users"),         # recipient_user_id (role prefix)
        ("table:public.subscriptions", "table:public.customers"),    # cust_id (abbrev)
        ("table:public.subscriptions", "table:public.plans"),        # plan_id
        ("table:public.projects", "table:public.departments"),        # dept_id (abbrev)
        ("table:public.comments", "table:public.posts"),              # post_id
        ("table:public.comments", "table:public.users"),              # author_user_id (role prefix)
    ]

    # Verify at least 20 edges checked
    assert len(edges) >= 20, f"Expected >= 20 inferred edges, got {len(edges)}"

    # Check that all expected edges exist
    for src, tgt in expected_edges:
        assert (src, tgt) in edge_map, f"Missing expected inferred edge: {src} -> {tgt}"

    # Negative check: settings and metrics must have ZERO outgoing edges
    settings_out = [e for e in edges if e.source == "table:public.settings"]
    metrics_out = [e for e in edges if e.source == "table:public.metrics"]
    assert len(settings_out) == 0, f"False positive on settings: {settings_out}"
    assert len(metrics_out) == 0, f"False positive on grid_id in metrics: {metrics_out}"

    # Kill check evaluation:
    # False positive rate must be strictly < 30%.
    # All 20+ edges in edge_map are valid relationships!
    false_positives = [
        pair for pair in edge_map if pair not in expected_edges
    ]
    fp_rate = len(false_positives) / len(edges)
    assert fp_rate < 0.30, f"KILL CHECK FAILED: False positive rate {fp_rate:.1%} exceeds 30% limit!"
    assert fp_rate == 0.0, f"Found unexpected false positives: {false_positives}"


def test_confidence_scores_exact_vs_fuzzy(enterprise_catalog):
    """
    Day 5 requirement:
    Verify that exact matches receive confidence 0.55 (0.55 * 1.0)
    and fuzzy/abbreviation/role-prefix matches receive confidence 0.495 (0.55 * 0.9).
    """
    edges = infer_edges_from_naming(enterprise_catalog)
    edge_map = {(e.source, e.target): e for e in edges}

    # Exact matches (modifier = 1.0 -> confidence = 0.55)
    exact_edge = edge_map[("table:public.orders", "table:public.users")]
    assert exact_edge.confidence == 0.55
    assert exact_edge.metadata["match_type"] == "exact"
    assert exact_edge.metadata["modifier"] == 1.0

    # Irregular plural exact match (category_id -> categories)
    cat_edge = edge_map[("table:public.products", "table:public.categories")]
    assert cat_edge.confidence == 0.55
    assert cat_edge.metadata["match_type"] == "exact"

    # Abbreviation match (usr_id -> users, modifier = 0.9 -> confidence = 0.495)
    usr_edge = edge_map[("table:public.reviews", "table:public.users")]
    assert usr_edge.confidence == 0.495
    assert usr_edge.metadata["match_type"] == "fuzzy"
    assert usr_edge.metadata["modifier"] == 0.9

    # Role prefix match (shipping_address_id -> addresses, modifier = 0.9 -> confidence = 0.495)
    addr_edge = edge_map[("table:public.orders", "table:public.addresses")]
    assert addr_edge.confidence == 0.495
    assert addr_edge.metadata["match_type"] == "fuzzy"
    assert addr_edge.metadata["modifier"] == 0.9


# ============================================================================
# 4. Multi-Schema Disambiguation & Self-Reference Handling
# ============================================================================

def test_multi_schema_prioritizes_same_schema():
    catalog = {
        "tables": {
            "tenant_a.orders": {
                "name": "orders",
                "schema": "tenant_a",
                "columns": [{"name": "id"}, {"name": "user_id"}],
            },
            "tenant_a.users": {
                "name": "users",
                "schema": "tenant_a",
                "columns": [{"name": "id"}],
            },
            "tenant_b.users": {
                "name": "users",
                "schema": "tenant_b",
                "columns": [{"name": "id"}],
            },
        }
    }
    edges = infer_edges_from_naming(catalog)
    assert len(edges) == 1
    edge = edges[0]
    assert edge.source == "table:tenant_a.orders"
    assert edge.target == "table:tenant_a.users"
    assert edge.metadata["same_schema"] is True


def test_trivial_self_reference_suppressed():
    """`users.user_id` inside `users` table should NOT infer a self-loop."""
    catalog = {
        "tables": {
            "public.users": {
                "name": "users",
                "schema": "public",
                "columns": [{"name": "id"}, {"name": "user_id"}],
            }
        }
    }
    edges = infer_edges_from_naming(catalog)
    assert len(edges) == 0


def test_hierarchical_self_reference_allowed():
    """`categories.parent_category_id` SHOULD infer a self-loop."""
    catalog = {
        "tables": {
            "public.categories": {
                "name": "categories",
                "schema": "public",
                "columns": [{"name": "id"}, {"name": "parent_category_id"}],
            }
        }
    }
    edges = infer_edges_from_naming(catalog)
    assert len(edges) == 1
    assert edges[0].source == "table:public.categories"
    assert edges[0].target == "table:public.categories"


# ============================================================================
# 5. Merge Logic & Precision Agreement (Day 6)
# ============================================================================

def test_merge_edges_with_agreement():
    declared = [
        Edge(
            source="table:public.orders",
            target="table:public.users",
            type=EdgeType.DECLARED_FK,
            confidence=1.0,
            evidence="FOREIGN KEY (user_id) REFERENCES public.users(id)",
        ),
        Edge(
            source="table:public.audit_logs",
            target="table:public.audit_base",
            type=EdgeType.STRUCTURAL_BELONGS_TO,
            confidence=1.0,
            evidence="Inherits from public.audit_base",
        ),
    ]

    inferred = [
        Edge(
            source="table:public.orders",
            target="table:public.users",
            type=EdgeType.INFERRED_NAMING,
            confidence=0.55,
            evidence="Naming inference (exact): public.orders.user_id -> public.users",
        ),
        Edge(
            source="table:public.invoices",
            target="table:public.orders",
            type=EdgeType.INFERRED_NAMING,
            confidence=0.55,
            evidence="Naming inference (exact): public.invoices.order_id -> public.orders",
        ),
    ]

    # Test deduplicate=False (default: unified graph with distinguishable classes)
    merged = merge_edges(declared, inferred, deduplicate=False)
    assert len(merged) == 4

    # Check agreement annotations
    decl_orders = next(e for e in merged if e.source == "table:public.orders" and e.type == EdgeType.DECLARED_FK)
    assert decl_orders.metadata["naming_agreement"] is True
    assert "Naming inference" in decl_orders.metadata["naming_evidence"]

    inf_orders = next(e for e in merged if e.source == "table:public.orders" and e.type == EdgeType.INFERRED_NAMING)
    assert inf_orders.metadata["declared_agreement"] is True
    assert inf_orders.metadata["agreement_bonus"] == 1.0

    # Inferred-only edge preserved
    inf_invoices = next(e for e in merged if e.source == "table:public.invoices")
    assert inf_invoices.type == EdgeType.INFERRED_NAMING
    assert "declared_agreement" not in inf_invoices.metadata


def test_merge_edges_with_deduplication():
    declared = [
        Edge(
            source="table:public.orders",
            target="table:public.users",
            type=EdgeType.DECLARED_FK,
            confidence=1.0,
            evidence="FK constraint",
        )
    ]
    inferred = [
        Edge(
            source="table:public.orders",
            target="table:public.users",
            type=EdgeType.INFERRED_NAMING,
            confidence=0.55,
            evidence="Naming inference",
        ),
        Edge(
            source="table:public.orders",
            target="table:public.addresses",
            type=EdgeType.INFERRED_NAMING,
            confidence=0.495,
            evidence="Naming inference",
        ),
    ]

    merged = merge_edges(declared, inferred, deduplicate=True)
    assert len(merged) == 2
    types = [e.type for e in merged]
    assert EdgeType.DECLARED_FK in types
    assert EdgeType.INFERRED_NAMING in types
    # Declared edge retained agreement info
    assert merged[0].metadata["naming_agreement"] is True


def test_compute_merge_stats():
    declared = [
        Edge(source="table:A", target="table:B", type=EdgeType.DECLARED_FK, confidence=1.0, evidence=""),
        Edge(source="table:B", target="table:C", type=EdgeType.DECLARED_FK, confidence=1.0, evidence=""),
    ]
    inferred = [
        Edge(source="table:A", target="table:B", type=EdgeType.INFERRED_NAMING, confidence=0.55, evidence=""),
        Edge(source="table:C", target="table:D", type=EdgeType.INFERRED_NAMING, confidence=0.55, evidence=""),
    ]

    stats = compute_merge_stats(declared, inferred)
    assert stats["total_declared_fk"] == 2
    assert stats["total_inferred"] == 2
    assert stats["agreements"] == 1
    assert stats["inferred_only"] == 1
    assert stats["declared_only"] == 1
    assert stats["agreement_rate"] == 0.5
