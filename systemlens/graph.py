"""Cross-layer graph assembly and analysis for SystemLens.

Combines database schema nodes/edges (from Step 0 & Step 1) with
code-layer Python AST nodes/edges (from Step 2) into a unified dependency graph.
Computes cross-layer metrics and Step 2 Kill Check statistics (dynamic unresolved ratio).
"""

from __future__ import annotations

from typing import Any

from systemlens.models import Edge, EdgeType, Node, NodeType


def assemble_unified_graph(
    db_nodes: list[Node] | None = None,
    db_edges: list[Edge] | None = None,
    code_nodes: list[Node] | None = None,
    code_edges: list[Edge] | None = None,
) -> dict[str, Any]:
    """
    Assemble database and code elements into a unified cross-layer graph.

    Resolves bare table references from code to qualified table nodes where possible.
    Surfaces unresolved dynamic queries as explicit nodes/edges (per tech.md honesty layer).

    Returns:
        Dict representing graph.json with 'nodes', 'edges', and 'metrics'.
    """
    db_nodes = db_nodes or []
    db_edges = db_edges or []
    code_nodes = code_nodes or []
    code_edges = code_edges or []

    # Index database table nodes for resolution
    node_registry: dict[str, Node] = {}
    table_lookup: dict[str, str] = {}  # bare_name / lower -> node_id

    for n in db_nodes:
        node_registry[n.id] = n
        if n.type in (NodeType.TABLE, NodeType.VIEW, NodeType.PARTITION):
            bare = n.name.lower()
            table_lookup.setdefault(bare, n.id)
            # Schema-qualified: public.users -> table:public.users
            clean_id_name = n.id.replace("table:", "").lower()
            table_lookup[clean_id_name] = n.id

    for n in code_nodes:
        node_registry[n.id] = n

    # Reconcile code edges to database table node IDs
    reconciled_code_edges: list[Edge] = []
    has_unresolved_dynamic = False

    for edge in code_edges:
        if edge.target == "table:unresolved":
            has_unresolved_dynamic = True
            reconciled_code_edges.append(edge)
            continue

        if edge.type in (EdgeType.STATIC_SQL_STRING, EdgeType.ORM_CALL):
            raw_target = edge.target.replace("table:", "").lower()
            if raw_target in table_lookup:
                resolved_id = table_lookup[raw_target]
                reconciled_code_edges.append(
                    Edge(
                        source=edge.source,
                        target=resolved_id,
                        type=edge.type,
                        confidence=edge.confidence,
                        evidence=edge.evidence,
                        metadata={**edge.metadata, "resolved_target": resolved_id},
                    )
                )
            else:
                # Table referenced in code is not present in extracted DB schema
                reconciled_code_edges.append(edge)
                if edge.target not in node_registry:
                    node_registry[edge.target] = Node(
                        id=edge.target,
                        type=NodeType.TABLE,
                        name=raw_target,
                        source_system="code_inferred",
                        metadata={"in_catalog": False},
                    )
        else:
            reconciled_code_edges.append(edge)

    # Ensure table:unresolved node exists if any dynamic unresolved edge is present
    if has_unresolved_dynamic and "table:unresolved" not in node_registry:
        node_registry["table:unresolved"] = Node(
            id="table:unresolved",
            type=NodeType.TABLE,
            name="<unresolved_dynamic_query>",
            source_system="python",
            metadata={
                "is_unresolved": True,
                "description": "Blind spot: dynamic query passed to execute() without static resolution",
            },
        )

    all_nodes = list(node_registry.values())
    all_edges = list(db_edges) + reconciled_code_edges

    metrics = compute_cross_layer_metrics(all_nodes, all_edges)

    return {
        "nodes": [n.to_dict() for n in all_nodes],
        "edges": [e.to_dict() for e in all_edges],
        "metrics": metrics,
    }


def compute_cross_layer_metrics(
    nodes: list[Node],
    edges: list[Edge],
) -> dict[str, Any]:
    """
    Compute comprehensive cross-layer graph metrics, including the
    Step 2 Day 14 Kill Check dynamic query ratio.
    """
    node_counts: dict[str, int] = {}
    for n in nodes:
        t = n.type.value if hasattr(n.type, "value") else str(n.type)
        node_counts[t] = node_counts.get(t, 0) + 1

    edge_counts: dict[str, int] = {}
    for e in edges:
        t = e.type.value if hasattr(e.type, "value") else str(e.type)
        edge_counts[t] = edge_counts.get(t, 0) + 1

    # Code-to-DB calls breakdown
    sql_calls = edge_counts.get(EdgeType.STATIC_SQL_STRING.value, 0)
    orm_calls = edge_counts.get(EdgeType.ORM_CALL.value, 0)
    dynamic_calls = edge_counts.get(EdgeType.DYNAMIC_UNRESOLVED.value, 0)
    total_code_db_access = sql_calls + orm_calls + dynamic_calls

    dynamic_ratio = (
        round(dynamic_calls / total_code_db_access, 4)
        if total_code_db_access > 0
        else 0.0
    )

    # Tables touched by code
    tables_touched = set()
    functions_accessing_db = set()
    for e in edges:
        if e.type in (EdgeType.STATIC_SQL_STRING, EdgeType.ORM_CALL):
            tables_touched.add(e.target)
            functions_accessing_db.add(e.source)

    return {
        "total_nodes": len(nodes),
        "total_edges": len(edges),
        "node_breakdown": node_counts,
        "edge_breakdown": edge_counts,
        "code_to_db": {
            "total_access_calls": total_code_db_access,
            "static_sql_count": sql_calls,
            "orm_call_count": orm_calls,
            "dynamic_unresolved_count": dynamic_calls,
            "dynamic_unresolved_ratio": dynamic_ratio,
            "kill_check_warning": dynamic_ratio > 0.40,
            "tables_touched_count": len(tables_touched),
            "functions_touching_db_count": len(functions_accessing_db),
        },
    }
